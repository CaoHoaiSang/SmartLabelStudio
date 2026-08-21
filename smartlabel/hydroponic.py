from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re
import shutil

from PIL import Image

from .models import ImageRecord, Project, new_id
from .project_store import ProjectStore


SLOT_IDS = tuple(
    [f"upper_{index:02d}" for index in range(1, 6)]
    + [f"lower_{index:02d}" for index in range(1, 6)]
)
TRAIN_EXCLUDED_LABELS = {"uncertain", "not_applicable"}
MODEL_KEYS = ("plant_presence", "yellow_leaf", "wilt")
SENSITIVE_SUFFIXES = {".env", ".pt", ".pth", ".onnx", ".engine", ".rknn", ".ckpt"}
HYDROPONIC_TEMPLATE = "Hydroponic Slot Condition"


class CaptureManifestError(ValueError):
    pass


def is_hydroponic_project(project: Project | None) -> bool:
    return bool(project and project.metadata.get("template") == HYDROPONIC_TEMPLATE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apply_hydroponic_slot_template(project: Project) -> Project:
    project.schema_version = 2
    project.task = "classify"
    project.description = "Hydroponic fixed-slot condition classification"
    project.metadata.update({
        "template": HYDROPONIC_TEMPLATE,
        "cropCode": "cai_ngot",
        "pipeline": "fixed_slot_multilabel_v1",
        "validationStatus": "pilot_unvalidated",
    })
    project.attribute_schema = {
        "plant_presence": ["present", "absent", "uncertain"],
        "yellow_leaf": ["present", "absent", "uncertain", "not_applicable"],
        "wilt": ["present", "absent", "uncertain", "not_applicable"],
    }
    project.attribute_settings = {
        "plant_presence": {
            "title": "Cây hiện diện",
            "default": "uncertain",
            "required": True,
            "role": "classification",
            "scope": "image",
            "train_exclude": ["uncertain"],
        },
        "yellow_leaf": {
            "title": "Lá vàng",
            "default": "not_applicable",
            "required": True,
            "role": "classification",
            "scope": "image",
            "train_exclude": ["uncertain", "not_applicable"],
        },
        "wilt": {
            "title": "Héo",
            "default": "not_applicable",
            "required": True,
            "role": "classification",
            "scope": "image",
            "train_exclude": ["uncertain", "not_applicable"],
        },
    }
    project.attribute_classification_enabled = True
    return project


def _validate_captured_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CaptureManifestError("manifest capturedAt is required")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CaptureManifestError("manifest capturedAt must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CaptureManifestError("manifest capturedAt must include a timezone")
    return value.strip()


def _safe_relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise CaptureManifestError("asset relativePath is required")
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise CaptureManifestError(f"unsafe asset path: {value}")
    return path


def _asset_source(manifest_path: Path, relative: Path) -> Path:
    for parent in (manifest_path.parent, *manifest_path.parents):
        candidate = (parent / relative).resolve()
        if candidate.is_file():
            return candidate
    local_candidate = manifest_path.parent / relative.name
    if local_candidate.is_file():
        return local_candidate.resolve()
    raise CaptureManifestError(f"asset file is missing: {relative.as_posix()}")


def _rect(asset: dict[str, Any]) -> tuple[int, int, int, int]:
    raw = asset.get("rectInFullFrame")
    if not isinstance(raw, dict):
        raise CaptureManifestError(f"asset {asset.get('assetId')} has no full-frame geometry")
    try:
        values = tuple(int(raw[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureManifestError("asset geometry must contain integer x/y/width/height") from exc
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1920 or y + height > 1080:
        raise CaptureManifestError("asset geometry is outside the 1920x1080 full frame")
    return values


def validate_capture_manifest(manifest_path: str | Path) -> tuple[dict[str, Any], dict[str, Path]]:
    path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise CaptureManifestError(f"cannot read CaptureManifestV1: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise CaptureManifestError("CaptureManifestV1.schemaVersion must be 1")
    for key in ("captureId", "siteId", "deviceId", "cropCycleId", "cropCode", "cameraProfileId", "geometryProfileId"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise CaptureManifestError(f"manifest {key} is required")
    if manifest.get("qualityStatus") != "accepted":
        raise CaptureManifestError("only accepted captures can enter the labeling dataset")
    _validate_captured_at(manifest.get("capturedAt"))
    if manifest.get("trigger") not in {"manual", "scheduled"}:
        raise CaptureManifestError("manifest trigger must be manual or scheduled")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise CaptureManifestError("manifest assets must be an array")
    asset_ids = [asset.get("assetId") for asset in assets if isinstance(asset, dict)]
    if len(asset_ids) != len(assets) or any(not isinstance(item, str) or not item for item in asset_ids):
        raise CaptureManifestError("every asset requires an assetId")
    if len(set(asset_ids)) != len(asset_ids):
        raise CaptureManifestError("duplicate assetId in manifest")
    by_id = {asset["assetId"]: asset for asset in assets}
    full_assets = [asset for asset in assets if asset.get("role") == "full_frame"]
    roi_assets = [asset for asset in assets if asset.get("role") == "roi"]
    slot_assets = [asset for asset in assets if asset.get("role") == "slot"]
    if len(full_assets) != 1 or len(roi_assets) != 2 or len(slot_assets) != 10:
        raise CaptureManifestError("manifest requires exactly 1 full frame, 2 ROI and 10 slots")
    if {asset.get("slotId") for asset in slot_assets} != set(SLOT_IDS):
        raise CaptureManifestError("manifest does not contain the fixed ten unique slots")
    full_id = full_assets[0]["assetId"]
    if full_assets[0].get("width") != 1920 or full_assets[0].get("height") != 1080:
        raise CaptureManifestError("full frame must be exactly 1920x1080")
    roi_by_rack = {}
    for roi in roi_assets:
        rack_id = roi.get("rackId")
        if rack_id not in {"upper", "lower"} or rack_id in roi_by_rack:
            raise CaptureManifestError("ROI rack lineage must be upper/lower and unique")
        if roi.get("parentAssetId") != full_id:
            raise CaptureManifestError("ROI parent must be the full frame")
        _rect(roi)
        roi_by_rack[rack_id] = roi
    resolved = {}
    for asset in assets:
        relative = _safe_relative_path(asset.get("relativePath"))
        source = _asset_source(path, relative)
        digest = _sha256(source)
        expected = asset.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or digest != expected:
            raise CaptureManifestError(f"checksum mismatch: {asset['assetId']}")
        try:
            with Image.open(source) as image:
                width, height = image.size
        except OSError as exc:
            raise CaptureManifestError(f"broken image: {asset['assetId']}") from exc
        if width != int(asset.get("width", width)) or height != int(asset.get("height", height)):
            raise CaptureManifestError(f"image dimensions disagree with manifest: {asset['assetId']}")
        resolved[asset["assetId"]] = source
    for slot in slot_assets:
        rack_id = slot.get("rackId")
        if rack_id not in roi_by_rack or slot.get("parentAssetId") != roi_by_rack[rack_id]["assetId"]:
            raise CaptureManifestError(f"slot lineage mismatch: {slot.get('slotId')}")
        x, y, width, height = _rect(slot)
        roi_x, roi_y, roi_width, roi_height = _rect(roi_by_rack[rack_id])
        if x < roi_x or y < roi_y or x + width > roi_x + roi_width or y + height > roi_y + roi_height:
            raise CaptureManifestError(f"slot is outside its parent ROI: {slot.get('slotId')}")
        if slot.get("width") != width or slot.get("height") != height:
            raise CaptureManifestError(f"slot image size disagrees with geometry: {slot.get('slotId')}")
    return manifest, resolved


def import_capture_manifest(store: ProjectStore, project: Project, manifest_path: str | Path) -> tuple[int, int]:
    manifest, resolved = validate_capture_manifest(manifest_path)
    if not is_hydroponic_project(project):
        raise CaptureManifestError("project must use the Hydroponic Slot Condition template")
    expected_crop = str(project.metadata.get("cropCode", ""))
    if expected_crop and manifest["cropCode"] != expected_crop:
        raise CaptureManifestError(
            f"manifest cropCode {manifest['cropCode']} does not match project cropCode {expected_crop}"
        )
    for field in ("siteId", "deviceId"):
        configured = str(project.metadata.get(field, ""))
        if configured and manifest[field] != configured:
            raise CaptureManifestError(
                f"manifest {field} {manifest[field]} does not match project {field} {configured}"
            )
    known_asset_ids = {record.metadata.get("assetId") for record in project.images}
    slot_assets = [asset for asset in manifest["assets"] if asset.get("role") == "slot"]
    duplicate_ids = [asset["assetId"] for asset in slot_assets if asset["assetId"] in known_asset_ids]
    if duplicate_ids:
        raise CaptureManifestError(f"capture asset was already imported: {duplicate_ids[0]}")
    images_dir = store.project_dir(project) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    provenance_dir = store.project_dir(project) / "assets" / manifest["captureId"]
    if provenance_dir.exists():
        raise CaptureManifestError(f"capture provenance already exists: {manifest['captureId']}")
    created_files = []
    created_records = []
    metadata_before = json.loads(json.dumps(project.metadata))
    last_import_batch_before = project.last_import_batch
    full_asset = next(asset for asset in manifest["assets"] if asset.get("role") == "full_frame")
    roi_assets = {asset["rackId"]: asset for asset in manifest["assets"] if asset.get("role") == "roi"}
    import_batch = f"capture_{manifest['captureId']}"
    try:
        provenance_dir.mkdir(parents=True, exist_ok=False)
        parent_assets: dict[str, dict[str, str]] = {}
        for parent in (full_asset, roi_assets["upper"], roi_assets["lower"]):
            source = resolved[parent["assetId"]]
            suffix = source.suffix.lower() if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
            role_name = "full" if parent["role"] == "full_frame" else f"{parent['rackId']}_roi"
            destination = provenance_dir / f"{role_name}{suffix}"
            shutil.copy2(source, destination)
            created_files.append(destination)
            parent_assets[parent["assetId"]] = {
                "assetId": parent["assetId"],
                "role": parent["role"],
                "sha256": parent["sha256"],
                "projectRelativePath": destination.relative_to(store.project_dir(project)).as_posix(),
            }
        for asset in sorted(slot_assets, key=lambda item: SLOT_IDS.index(item["slotId"])):
            source = resolved[asset["assetId"]]
            suffix = source.suffix.lower() if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
            file_name = f"{asset['sha256'][:12]}_{asset['slotId']}{suffix}"
            destination = images_dir / file_name
            if destination.exists():
                raise CaptureManifestError(f"project image collision: {file_name}")
            shutil.copy2(source, destination)
            created_files.append(destination)
            rack_id = asset["rackId"]
            record = ImageRecord(
                id=new_id("img"),
                file_name=file_name,
                width=int(asset["width"]),
                height=int(asset["height"]),
                source_path="",
                capture_group=f"{manifest['cropCycleId']}:{asset['slotId']}",
                import_batch=import_batch,
                review_status="unlabeled",
                quality=dict(asset.get("quality", {})),
                attributes={
                    "plant_presence": "uncertain",
                    "yellow_leaf": "not_applicable",
                    "wilt": "not_applicable",
                },
                metadata={
                    "assetId": asset["assetId"],
                    "captureId": manifest["captureId"],
                    "siteId": manifest["siteId"],
                    "deviceId": manifest["deviceId"],
                    "cropCode": manifest["cropCode"],
                    "cropCycleId": manifest["cropCycleId"],
                    "slotId": asset["slotId"],
                    "rackId": rack_id,
                    "plant_instance_id": f"{manifest['cropCycleId']}:{asset['slotId']}",
                    "capturedAt": manifest.get("capturedAt"),
                    "trigger": manifest.get("trigger"),
                    "cameraProfileId": manifest["cameraProfileId"],
                    "geometryProfileId": manifest["geometryProfileId"],
                    "other_abnormal": "",
                },
                parent_asset_id=asset["parentAssetId"],
                asset_role="slot",
                lineage={
                    "fullFrameAssetId": full_asset["assetId"],
                    "roiAssetId": roi_assets[rack_id]["assetId"],
                    "rectInFullFrame": asset["rectInFullFrame"],
                    "fullFrameRelativePath": parent_assets[full_asset["assetId"]]["projectRelativePath"],
                    "roiRelativePath": parent_assets[roi_assets[rack_id]["assetId"]]["projectRelativePath"],
                    "parentAssets": {
                        "fullFrame": parent_assets[full_asset["assetId"]],
                        "roi": parent_assets[roi_assets[rack_id]["assetId"]],
                    },
                },
                sha256=asset["sha256"],
            )
            created_records.append(record)
        project.images.extend(created_records)
        project.last_import_batch = import_batch
        project.metadata.setdefault("siteId", manifest["siteId"])
        project.metadata.setdefault("deviceId", manifest["deviceId"])
        def append_unique_string(field: str, value: str) -> None:
            existing = project.metadata.get(field, [])
            safe_existing = [item for item in existing if isinstance(item, str)] if isinstance(existing, list) else []
            project.metadata[field] = sorted(set(safe_existing + [value]))

        append_unique_string("cropCycleIds", manifest["cropCycleId"])
        append_unique_string("cameraProfileIds", manifest["cameraProfileId"])
        append_unique_string("geometryProfileIds", manifest["geometryProfileId"])
        store.save(project)
    except Exception:
        for target in created_files:
            try:
                target.unlink()
            except OSError:
                pass
        for record in created_records:
            if record in project.images:
                project.images.remove(record)
        project.metadata = metadata_before
        project.last_import_batch = last_import_batch_before
        if provenance_dir.exists():
            shutil.rmtree(provenance_dir, ignore_errors=True)
        raise
    return len(created_records), 0


def hydro_dataset_qa(project: Project, store: ProjectStore, split_assignment: dict[str, Any] | None = None) -> dict[str, Any]:
    issues = []
    if not project.images:
        issues.append({
            "severity": "warning",
            "imageId": "",
            "code": "empty_dataset",
            "message": "Dataset chưa có ảnh để kiểm tra.",
        })
    distributions = {key: Counter() for key in MODEL_KEYS}
    digests = defaultdict(list)
    plant_splits = defaultdict(set)
    cycle_splits = defaultdict(set)
    capture_slots = defaultdict(list)
    assignments = dict((split_assignment or {}).get("groups", {}))
    for record in project.images:
        path = store.image_path(project, record)
        if not path.is_file():
            issues.append({"severity": "error", "imageId": record.id, "code": "missing_image"})
        else:
            try:
                with Image.open(path) as image:
                    image.verify()
            except OSError:
                issues.append({"severity": "error", "imageId": record.id, "code": "broken_image"})
            digest = _sha256(path)
            digests[digest].append(record.id)
            if record.sha256 and digest != record.sha256:
                issues.append({"severity": "error", "imageId": record.id, "code": "checksum_mismatch"})
        for key in MODEL_KEYS:
            distributions[key][record.attributes.get(key, "missing")] += 1
        capture_id = str(record.metadata.get("captureId", ""))
        slot_id = str(record.metadata.get("slotId", ""))
        if not capture_id:
            issues.append({"severity": "error", "imageId": record.id, "code": "missing_capture_id"})
        else:
            capture_slots[capture_id].append(slot_id)
        if record.asset_role != "slot":
            issues.append({"severity": "error", "imageId": record.id, "code": "invalid_asset_role"})
        expected_plant = f"{record.metadata.get('cropCycleId', '')}:{slot_id}"
        if record.metadata.get("plant_instance_id") != expected_plant:
            issues.append({"severity": "error", "imageId": record.id, "code": "plant_instance_mismatch"})
        for lineage_key in ("fullFrameRelativePath", "roiRelativePath"):
            raw_lineage_path = record.lineage.get(lineage_key)
            if not isinstance(raw_lineage_path, str) or not raw_lineage_path:
                issues.append({"severity": "error", "imageId": record.id, "code": f"missing_{lineage_key}"})
                continue
            lineage_path = Path(raw_lineage_path)
            if lineage_path.is_absolute() or ".." in lineage_path.parts:
                issues.append({"severity": "error", "imageId": record.id, "code": "unsafe_lineage_path"})
            elif not (store.project_dir(project) / lineage_path).is_file():
                issues.append({"severity": "error", "imageId": record.id, "code": "missing_parent_asset"})
        presence = record.attributes.get("plant_presence")
        if presence != "present" and any(record.attributes.get(key) != "not_applicable" for key in ("yellow_leaf", "wilt")):
            issues.append({"severity": "error", "imageId": record.id, "code": "contradictory_condition_label"})
        if record.source_path and Path(record.source_path).is_absolute():
            issues.append({"severity": "error", "imageId": record.id, "code": "absolute_source_path"})
        for value in record.metadata.values():
            if not isinstance(value, str) or not value:
                continue
            candidate = Path(value)
            if candidate.is_absolute():
                issues.append({"severity": "error", "imageId": record.id, "code": "absolute_metadata_path"})
            if candidate.name.lower() == ".env" or candidate.suffix.lower() in SENSITIVE_SUFFIXES:
                issues.append({"severity": "error", "imageId": record.id, "code": "sensitive_metadata_reference"})
        if record.review_status != "reviewed":
            issues.append({"severity": "warning", "imageId": record.id, "code": "image_not_reviewed"})
        group = str(record.metadata.get("plant_instance_id") or record.capture_group or record.id)
        split = assignments.get(group)
        if split:
            plant_splits[group].add(split)
            cycle_splits[str(record.metadata.get("cropCycleId", "unknown"))].add(split)
    for digest, image_ids in digests.items():
        if len(image_ids) > 1:
            issues.append({"severity": "error", "imageId": image_ids[0], "code": "duplicate_sha256", "related": image_ids[1:]})
    for capture_id, slot_ids in capture_slots.items():
        if len(slot_ids) != len(SLOT_IDS) or set(slot_ids) != set(SLOT_IDS):
            issues.append({
                "severity": "error",
                "imageId": "",
                "code": "incomplete_capture_slots",
                "captureId": capture_id,
                "missing": sorted(set(SLOT_IDS) - set(slot_ids)),
                "duplicates": sorted(slot for slot, count in Counter(slot_ids).items() if count > 1),
            })
    for plant_id, splits in plant_splits.items():
        if len(splits) > 1:
            issues.append({"severity": "error", "imageId": "", "code": "plant_instance_leakage", "plantInstanceId": plant_id})
    train_cycles = {cycle for cycle, splits in cycle_splits.items() if "train" in splits or "val" in splits}
    test_cycles = {cycle for cycle, splits in cycle_splits.items() if "test" in splits}
    independent_holdout = bool(test_cycles and test_cycles.isdisjoint(train_cycles) and "unknown" not in test_cycles)
    if project.images and not independent_holdout:
        issues.append({"severity": "warning", "imageId": "", "code": "crop_cycle_holdout_missing"})
    validation_status = (
        "validated_holdout"
        if independent_holdout and not any(issue["severity"] == "error" for issue in issues)
        else "pilot_unvalidated"
    )
    return {
        "schemaVersion": 1,
        "images": len(project.images),
        "issues": issues,
        "distributions": {key: dict(value) for key, value in distributions.items()},
        "independentCropCycleHoldout": independent_holdout,
        "validationStatus": validation_status,
    }


def export_jetson_onnx(model_path: str | Path, output: str | Path, input_size: int = 224, opset: int = 12) -> Path:
    source = Path(model_path).resolve()
    target = Path(output).resolve()
    if not source.is_file() or source.suffix.lower() != ".pt":
        raise FileNotFoundError("Jetson ONNX export requires an existing .pt classifier")
    from ultralytics import YOLO

    exported = Path(YOLO(str(source)).export(
        format="onnx", imgsz=input_size, batch=1, dynamic=False, half=False,
        simplify=False, opset=opset,
    )).resolve()
    if not exported.is_file():
        raise RuntimeError("Ultralytics did not create a static ONNX artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    if exported != target:
        shutil.copy2(exported, target)
    return target


def write_hydro_model_bundle(
    project: Project,
    output_dir: str | Path,
    models: dict[str, str | Path],
    thresholds: dict[str, dict[str, float]],
    *,
    dataset_version: str,
    source_commit: str,
    camera_profile_ids: list[str],
    geometry_profile_ids: list[str],
    input_size: int = 224,
) -> Path:
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"bundle output already exists: {output}")
    if set(models) != set(MODEL_KEYS) or set(thresholds) != set(MODEL_KEYS):
        raise ValueError("bundle requires independent presence/yellow/wilt models and thresholds")
    if not dataset_version or not source_commit or not camera_profile_ids or not geometry_profile_ids:
        raise ValueError("dataset/source/profile compatibility metadata is required")
    label_distribution = {}
    for key in MODEL_KEYS:
        counts = Counter(
            record.attributes.get(key)
            for record in project.images
            if record.review_status == "reviewed"
        )
        if counts["present"] < 1 or counts["absent"] < 1:
            raise ValueError(f"{key} requires reviewed present and absent samples before bundle export")
        label_distribution[key] = {"absent": counts["absent"], "present": counts["present"]}
    bundle_id = f"hydro_cai_ngot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    temporary = output.with_name(output.name + ".tmp")
    temporary.mkdir(parents=True)
    try:
        entries = {}
        for key in MODEL_KEYS:
            source = Path(models[key]).resolve()
            if not source.is_file() or source.suffix.lower() != ".onnx":
                raise FileNotFoundError(f"missing ONNX model for {key}: {source}")
            low = float(thresholds[key].get("lowThreshold", -1))
            high = float(thresholds[key].get("highThreshold", -1))
            if not 0 <= low < high <= 1:
                raise ValueError(f"invalid calibrated thresholds for {key}")
            relative = Path("models") / f"{key}.onnx"
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            entries[key] = {
                "path": relative.as_posix(),
                "sha256": _sha256(target),
                "labels": ["absent", "present"],
                "inputSize": [input_size, input_size],
                "batchSize": 1,
                "dynamic": False,
                "inputLayout": "NCHW",
                "colorOrder": "RGB",
                "normalization": {"scale": 1 / 255, "mean": [0, 0, 0], "std": [1, 1, 1]},
                "lowThreshold": low,
                "highThreshold": high,
            }
        manifest = {
            "schemaVersion": 1,
            "bundleId": bundle_id,
            "cropCode": str(project.metadata.get("cropCode") or "cai_ngot"),
            "pipeline": "fixed_slot_multilabel_v1",
            "compatibleCameraProfileIds": camera_profile_ids,
            "compatibleGeometryProfileIds": geometry_profile_ids,
            "models": entries,
            "datasetVersion": dataset_version,
            "sourceCommit": source_commit,
            "runtimeTarget": "jetson_nano_tensorrt_fp16",
            "minimumTensorRTVersion": "8.2",
            "validationStatus": project.metadata.get("validationStatus", "pilot_unvalidated"),
            "labelDistribution": label_distribution,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (temporary / "bundle.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, output)
        return output
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
