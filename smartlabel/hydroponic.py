from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile

from PIL import Image

from .models import ImageRecord, Project, new_id
from .project_store import ProjectStore


SLOT_IDS = tuple(
    [f"upper_{index:02d}" for index in range(1, 6)]
    + [f"lower_{index:02d}" for index in range(1, 6)]
)
TRAIN_EXCLUDED_LABELS = {"uncertain", "not_applicable"}
MODEL_KEYS = ("plant_presence", "yellow_leaf", "wilt")
RUNTIME_TARGETS = {
    "jetson_nano_tensorrt_fp16",
    "windows_onnxruntime_cpu",
}
CROP_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

HYDRO_QA_ISSUE_MESSAGES = {
    "empty_dataset": "Dataset chưa có ảnh để kiểm tra.",
    "missing_image": "Thiếu file ảnh trong project.",
    "broken_image": "File ảnh bị hỏng hoặc không đọc được.",
    "checksum_mismatch": "Checksum ảnh không khớp với metadata.",
    "missing_capture_id": "Ảnh thiếu capture ID.",
    "invalid_asset_role": "Ảnh không có asset role là slot.",
    "plant_instance_mismatch": "Plant instance ID không khớp crop cycle và slot.",
    "missing_fullFrameRelativePath": "Thiếu liên kết tới full frame.",
    "missing_roiRelativePath": "Thiếu liên kết tới ROI cha.",
    "unsafe_lineage_path": "Đường dẫn lineage không an toàn hoặc không portable.",
    "missing_parent_asset": "Không tìm thấy full frame hoặc ROI cha.",
    "contradictory_condition_label": "Nhãn condition mâu thuẫn với plant presence.",
    "absolute_source_path": "Source path còn chứa đường dẫn tuyệt đối.",
    "absolute_metadata_path": "Metadata còn chứa đường dẫn tuyệt đối.",
    "sensitive_metadata_reference": "Metadata tham chiếu file nhạy cảm.",
    "image_not_reviewed": "Ảnh chưa được người dùng duyệt.",
    "duplicate_sha256": "Phát hiện ảnh trùng nội dung SHA-256.",
    "incomplete_capture_slots": "Capture không đủ đúng 10 slot.",
    "plant_instance_leakage": "Plant instance xuất hiện trong nhiều split.",
    "crop_cycle_holdout_missing": "Chưa có crop cycle độc lập dành riêng cho test holdout.",
}


def describe_hydro_qa_issue(issue: dict[str, Any]) -> str:
    """Return a concise Vietnamese description suitable for inline review results."""

    code = str(issue.get("code", "unknown"))
    detail = str(issue.get("message") or HYDRO_QA_ISSUE_MESSAGES.get(code, code))
    extras = []
    if issue.get("captureId"):
        extras.append(f"capture {issue['captureId']}")
    if issue.get("missing"):
        extras.append("thiếu " + ", ".join(str(value) for value in issue["missing"]))
    if issue.get("duplicates"):
        extras.append("slot trùng " + ", ".join(str(value) for value in issue["duplicates"]))
    if issue.get("related"):
        extras.append(f"trùng với {len(issue['related'])} ảnh khác")
    if issue.get("plantInstanceId"):
        extras.append(f"plant {issue['plantInstanceId']}")
    return detail + (" · " + " · ".join(extras) if extras else "")
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


def validate_crop_identity(crop_code: str, crop_display_name: str) -> tuple[str, str]:
    """Validate the portable crop identity shared by projects and model bundles."""

    normalized_code = str(crop_code or "").strip()
    normalized_name = str(crop_display_name or "").strip()
    if not CROP_CODE_PATTERN.fullmatch(normalized_code):
        raise ValueError("cropCode must use 2-64 lowercase ASCII letters, numbers or underscores")
    if not normalized_name or len(normalized_name) > 100:
        raise ValueError("cropDisplayName must contain 1-100 characters")
    return normalized_code, normalized_name


def apply_hydroponic_slot_template(
    project: Project,
    *,
    crop_code: str = "cai_ngot",
    crop_display_name: str = "Cải ngọt cọng xanh",
) -> Project:
    crop_code, crop_display_name = validate_crop_identity(crop_code, crop_display_name)
    project.schema_version = 2
    project.task = "classify"
    project.description = "Hydroponic fixed-slot condition classification"
    project.metadata.update({
        "template": HYDROPONIC_TEMPLATE,
        "cropCode": crop_code,
        "cropDisplayName": crop_display_name,
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
            "title": f"Có {crop_display_name} trong rọ",
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


def _validate_crop_context(value: Any, captured_at: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CaptureManifestError("manifest cropContext must be an object")
    if value.get("timezone") != "Asia/Bangkok":
        raise CaptureManifestError("manifest cropContext timezone must be Asia/Bangkok")
    if not isinstance(value.get("cropDisplayName"), str) or not value["cropDisplayName"].strip():
        raise CaptureManifestError("manifest cropContext cropDisplayName is required")
    try:
        sowing_date = date.fromisoformat(value["sowingDate"])
        nft_start_date = date.fromisoformat(value["nftStartDate"])
        local_date = date.fromisoformat(value["localDate"])
        captured_local_date = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=7))).date()
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureManifestError("manifest cropContext dates must use valid YYYY-MM-DD values") from exc
    if local_date != captured_local_date:
        raise CaptureManifestError("manifest cropContext localDate does not match capturedAt")
    if value.get("daysAfterSowing") != (local_date - sowing_date).days or value.get("daysAfterSowing", -1) < 0:
        raise CaptureManifestError("manifest cropContext daysAfterSowing is inconsistent")
    if value.get("daysAfterNft") != (local_date - nft_start_date).days:
        raise CaptureManifestError("manifest cropContext daysAfterNft is inconsistent")
    return value


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
    dataset_review = manifest.get("datasetReview")
    if dataset_review is not None:
        if not isinstance(dataset_review, dict) or dataset_review.get("status") not in {"pending", "approved", "excluded"}:
            raise CaptureManifestError("manifest datasetReview status is invalid")
        if dataset_review.get("status") == "excluded":
            raise CaptureManifestError("capture was excluded from the training dataset")
    captured_at = _validate_captured_at(manifest.get("capturedAt"))
    _validate_crop_context(manifest.get("cropContext"), captured_at)
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
    binding_views: dict[str, str] = {}
    if manifest.get("bindingId"):
        raw_views = manifest.get("views")
        if not isinstance(raw_views, list) or len(raw_views) != 2:
            raise CaptureManifestError("bound manifest requires two view mappings")
        binding_views = {
            str(view.get("viewId")): str(view.get("rackId"))
            for view in raw_views if isinstance(view, dict)
        }
        if set(binding_views) != {"upper", "lower"} or len(set(binding_views.values())) != 2:
            raise CaptureManifestError("bound manifest view mapping is invalid")
        for asset in roi_assets + slot_assets:
            if asset.get("viewId") != asset.get("rackId") or asset.get("actualRackId") != binding_views.get(asset.get("viewId")):
                raise CaptureManifestError(f"bound asset lineage mismatch: {asset.get('assetId')}")
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


def import_capture_manifest(
    store: ProjectStore,
    project: Project,
    manifest_path: str | Path,
    *,
    effective_crop_context: dict[str, Any] | None = None,
    crop_context_correction_ids: list[str] | None = None,
) -> tuple[int, int]:
    manifest, resolved = validate_capture_manifest(manifest_path)
    if effective_crop_context is not None:
        captured_at = _validate_captured_at(manifest.get("capturedAt"))
        _validate_crop_context(effective_crop_context, captured_at)
    correction_ids = crop_context_correction_ids or []
    if any(not isinstance(item, str) or not item.strip() for item in correction_ids) or len(set(correction_ids)) != len(correction_ids):
        raise CaptureManifestError("crop context correction IDs are invalid")
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
            capture_name_hash = hashlib.sha256(manifest["captureId"].encode("utf-8")).hexdigest()[:8]
            file_name = f"{asset['sha256'][:12]}_{capture_name_hash}_{asset['slotId']}{suffix}"
            destination = images_dir / file_name
            if destination.exists():
                raise CaptureManifestError(f"project image collision: {file_name}")
            shutil.copy2(source, destination)
            created_files.append(destination)
            rack_id = asset["rackId"]
            actual_rack_id = str(asset.get("actualRackId") or rack_id)
            position = int(asset["slotId"].split("_")[1])
            plant_instance_id = (
                f"{manifest['cropCycleId']}:{actual_rack_id}:{position}"
                if manifest.get("bindingId")
                else f"{manifest['cropCycleId']}:{asset['slotId']}"
            )
            original_crop_context = manifest.get("cropContext") if isinstance(manifest.get("cropContext"), dict) else {}
            crop_context = effective_crop_context or original_crop_context
            record = ImageRecord(
                id=new_id("img"),
                file_name=file_name,
                width=int(asset["width"]),
                height=int(asset["height"]),
                source_path="",
                capture_group=plant_instance_id,
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
                    "cropDisplayName": crop_context.get("cropDisplayName", ""),
                    "cropCycleId": manifest["cropCycleId"],
                    "slotId": asset["slotId"],
                    "viewId": asset.get("viewId", rack_id),
                    "rackId": actual_rack_id,
                    "position": position,
                    "plant_instance_id": plant_instance_id,
                    "capturedAt": manifest.get("capturedAt"),
                    "trigger": manifest.get("trigger"),
                    "scheduledFor": manifest.get("scheduledFor"),
                    "cameraProfileId": manifest["cameraProfileId"],
                    "geometryProfileId": manifest["geometryProfileId"],
                    "bindingId": manifest.get("bindingId"),
                    "bindingRevision": manifest.get("bindingRevision"),
                    "captureQualityStatus": manifest.get("qualityStatus"),
                    "datasetReviewStatus": (manifest.get("datasetReview") or {}).get("status", "legacy_unreviewed"),
                    "captureLocalDate": crop_context.get("localDate"),
                    "sowingDate": crop_context.get("sowingDate"),
                    "nftStartDate": crop_context.get("nftStartDate"),
                    "daysAfterSowing": crop_context.get("daysAfterSowing"),
                    "daysAfterNft": crop_context.get("daysAfterNft"),
                    "timezone": crop_context.get("timezone"),
                    "cropContextCorrectionIds": list(correction_ids),
                    "originalSowingDate": original_crop_context.get("sowingDate"),
                    "originalNftStartDate": original_crop_context.get("nftStartDate"),
                    "originalDaysAfterSowing": original_crop_context.get("daysAfterSowing"),
                    "originalDaysAfterNft": original_crop_context.get("daysAfterNft"),
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


DATASET_ARCHIVE_MAX_FILES = 10_000
DATASET_ARCHIVE_MAX_CAPTURES = 500
DATASET_ARCHIVE_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024
DATASET_ARCHIVE_MAX_MEMBER_BYTES = 512 * 1024 * 1024


def _safe_archive_member(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise CaptureManifestError(f"unsafe archive member: {value}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise CaptureManifestError(f"unsafe archive member: {value}")
    return "/".join(parts)


def _required_archive_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CaptureManifestError(f"dataset export {field} is required")
    return value


@contextmanager
def _validated_capture_dataset_archive(archive_path: str | Path):
    package_path = Path(archive_path).resolve()
    if package_path.suffix.lower() != ".zip" or not package_path.is_file():
        raise CaptureManifestError("Hydro dataset package must be a ZIP file")
    try:
        package = zipfile.ZipFile(package_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CaptureManifestError(f"cannot read Hydro dataset package: {exc}") from exc
    with package, tempfile.TemporaryDirectory(prefix="smartlabel_hydro_import_") as temporary:
        infos = package.infolist()
        files = [info for info in infos if not info.is_dir()]
        if not files or len(files) > DATASET_ARCHIVE_MAX_FILES:
            raise CaptureManifestError("Hydro dataset package has an invalid file count")
        if sum(info.file_size for info in files) > DATASET_ARCHIVE_MAX_UNCOMPRESSED_BYTES:
            raise CaptureManifestError("Hydro dataset package is too large after extraction")
        names: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            member_name = info.filename[:-1] if info.is_dir() and info.filename.endswith("/") else info.filename
            safe_name = _safe_archive_member(member_name)
            folded = safe_name.casefold()
            if folded in names:
                raise CaptureManifestError(f"duplicate archive member: {safe_name}")
            names[folded] = info
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or info.flag_bits & 0x1:
                raise CaptureManifestError(f"unsupported archive member: {safe_name}")
            if not info.is_dir() and info.file_size > DATASET_ARCHIVE_MAX_MEMBER_BYTES:
                raise CaptureManifestError(f"archive member is too large: {safe_name}")
        if "dataset-export.json" not in {info.filename for info in files}:
            raise CaptureManifestError("HydroDatasetExportV1 requires dataset-export.json at archive root")
        extraction_root = Path(temporary).resolve()
        for info in files:
            safe_name = _safe_archive_member(info.filename)
            destination = (extraction_root / Path(*safe_name.split("/"))).resolve()
            if extraction_root not in destination.parents:
                raise CaptureManifestError(f"unsafe archive member: {safe_name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with package.open(info) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        index_path = extraction_root / "dataset-export.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise CaptureManifestError(f"cannot read HydroDatasetExportV1: {exc}") from exc
        if not isinstance(index, dict) or index.get("kind") != "HydroDatasetExportV1" or index.get("schemaVersion") != 1:
            raise CaptureManifestError("dataset-export.json must be HydroDatasetExportV1 schemaVersion 1")
        for field in ("datasetExportId", "createdAt", "deviceId", "siteId", "cropCode"):
            _required_archive_text(index.get(field), field)
        capture_rows = index.get("captures")
        if not isinstance(capture_rows, list) or not capture_rows:
            raise CaptureManifestError("HydroDatasetExportV1 must contain at least one capture")
        if len(capture_rows) > DATASET_ARCHIVE_MAX_CAPTURES:
            raise CaptureManifestError("HydroDatasetExportV1 contains too many captures")
        if index.get("captureCount") != len(capture_rows) or index.get("slotImageCount") != len(capture_rows) * 10:
            raise CaptureManifestError("dataset export capture or slot count is inconsistent")
        capture_ids: set[str] = set()
        manifest_paths: set[str] = set()
        all_asset_ids: set[str] = set()
        all_asset_paths: set[str] = set()
        expected_files = {"dataset-export.json"}
        manifests: list[tuple[dict[str, Any], Path]] = []
        for row in capture_rows:
            if not isinstance(row, dict):
                raise CaptureManifestError("dataset export capture entry must be an object")
            capture_id = _required_archive_text(row.get("captureId"), "captures[].captureId")
            if capture_id in capture_ids:
                raise CaptureManifestError(f"duplicate captureId in dataset export: {capture_id}")
            capture_ids.add(capture_id)
            manifest_relative = _safe_archive_member(row.get("manifestPath"))
            if not manifest_relative.startswith("captures/") or not manifest_relative.endswith("/manifest.json"):
                raise CaptureManifestError(f"invalid capture manifest path: {manifest_relative}")
            if manifest_relative.casefold() in manifest_paths:
                raise CaptureManifestError(f"duplicate capture manifest path: {manifest_relative}")
            manifest_paths.add(manifest_relative.casefold())
            manifest_path = extraction_root / Path(*manifest_relative.split("/"))
            if not manifest_path.is_file():
                raise CaptureManifestError(f"capture manifest is missing: {manifest_relative}")
            expected_manifest_sha = row.get("manifestSha256")
            if not isinstance(expected_manifest_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha):
                raise CaptureManifestError(f"capture manifest checksum is invalid: {capture_id}")
            if _sha256(manifest_path) != expected_manifest_sha:
                raise CaptureManifestError(f"capture manifest checksum mismatch: {capture_id}")
            manifest, _resolved = validate_capture_manifest(manifest_path)
            dataset_review = manifest.get("datasetReview")
            if not isinstance(dataset_review, dict) or dataset_review.get("status") != "approved":
                raise CaptureManifestError(f"capture is not approved for dataset export: {capture_id}")
            for field in ("deviceId", "siteId", "cropCode"):
                if manifest.get(field) != index[field]:
                    raise CaptureManifestError(f"capture {capture_id} {field} does not match dataset export")
            for field in ("captureId", "capturedAt", "trigger", "cropCycleId"):
                if manifest.get(field) != row.get(field):
                    raise CaptureManifestError(f"capture {capture_id} {field} does not match dataset export entry")
            effective_context = row.get("effectiveCropContext")
            correction_ids = row.get("cropContextCorrectionIds")
            if effective_context is not None:
                captured_at = _validate_captured_at(manifest.get("capturedAt"))
                _validate_crop_context(effective_context, captured_at)
                if not isinstance(correction_ids, list) or not correction_ids:
                    raise CaptureManifestError(f"capture {capture_id} effective crop context requires correction IDs")
                if any(not isinstance(item, str) or not item for item in correction_ids) or len(set(correction_ids)) != len(correction_ids):
                    raise CaptureManifestError(f"capture {capture_id} crop context correction IDs are invalid")
                declared_corrections = index.get("cropCycleCorrections")
                if not isinstance(declared_corrections, list):
                    raise CaptureManifestError("dataset export cropCycleCorrections must be an array")
                known_corrections = {
                    item.get("correctionId"): item
                    for item in declared_corrections if isinstance(item, dict)
                }
                if any(item not in known_corrections for item in correction_ids):
                    raise CaptureManifestError(f"capture {capture_id} references an unknown crop context correction")
                if any(known_corrections[item].get("cropCycleId") != manifest["cropCycleId"] for item in correction_ids):
                    raise CaptureManifestError(f"capture {capture_id} references a correction from another crop cycle")
                cycle = index.get("cropCycle")
                if not isinstance(cycle, dict) or cycle.get("cropCycleId") != manifest["cropCycleId"]:
                    raise CaptureManifestError("dataset export corrected context requires its cropCycle record")
                for field in ("cropDisplayName", "sowingDate", "nftStartDate"):
                    if effective_context.get(field) != cycle.get(field):
                        raise CaptureManifestError(f"capture {capture_id} effective crop context does not match cropCycle {field}")
            elif correction_ids is not None:
                raise CaptureManifestError(f"capture {capture_id} correction IDs require effectiveCropContext")
            if row.get("slotCount") != 10:
                raise CaptureManifestError(f"capture {capture_id} slot count must be 10")
            expected_files.add(manifest_relative)
            for asset in manifest["assets"]:
                if asset["assetId"] in all_asset_ids:
                    raise CaptureManifestError(f"duplicate assetId across captures: {asset['assetId']}")
                all_asset_ids.add(asset["assetId"])
                asset_path = _safe_archive_member(asset["relativePath"])
                if asset_path.casefold() in all_asset_paths:
                    raise CaptureManifestError(f"duplicate asset path across captures: {asset_path}")
                all_asset_paths.add(asset_path.casefold())
                expected_files.add(asset_path)
            manifests.append((manifest, manifest_path))
        profile_fields = {
            "cropCycleIds": "cropCycleId",
            "cameraProfileIds": "cameraProfileId",
            "geometryProfileIds": "geometryProfileId",
        }
        for index_field, manifest_field in profile_fields.items():
            declared = index.get(index_field)
            expected = sorted({manifest[manifest_field] for manifest, _path in manifests})
            if not isinstance(declared, list) or declared != expected:
                raise CaptureManifestError(f"dataset export {index_field} is inconsistent")
        actual_files = {_safe_archive_member(info.filename) for info in files}
        if actual_files != expected_files:
            missing = sorted(expected_files - actual_files)
            unexpected = sorted(actual_files - expected_files)
            detail = f"missing={missing[:3]} unexpected={unexpected[:3]}"
            raise CaptureManifestError(f"Hydro dataset package file list is inconsistent: {detail}")
        yield index, manifests


def import_capture_dataset_archive(
    store: ProjectStore,
    project: Project,
    archive_path: str | Path,
) -> dict[str, Any]:
    if not is_hydroponic_project(project):
        raise CaptureManifestError("project must use the Hydroponic Slot Condition template")
    with _validated_capture_dataset_archive(archive_path) as (index, manifests):
        expected_crop = str(project.metadata.get("cropCode", ""))
        if expected_crop and index["cropCode"] != expected_crop:
            raise CaptureManifestError(
                f"dataset cropCode {index['cropCode']} does not match project cropCode {expected_crop}"
            )
        for field in ("siteId", "deviceId"):
            configured = str(project.metadata.get(field, ""))
            if configured and index[field] != configured:
                raise CaptureManifestError(
                    f"dataset {field} {index[field]} does not match project {field} {configured}"
                )
        records_by_capture: dict[str, list[ImageRecord]] = defaultdict(list)
        rows_by_capture = {
            row["captureId"]: row
            for row in index["captures"] if isinstance(row, dict) and isinstance(row.get("captureId"), str)
        }
        known_asset_ids = {record.metadata.get("assetId") for record in project.images}
        for record in project.images:
            capture_id = record.metadata.get("captureId")
            if isinstance(capture_id, str) and capture_id:
                records_by_capture[capture_id].append(record)
        to_import: list[Path] = []
        skipped_capture_ids: list[str] = []
        metadata_updated_capture_ids: list[str] = []
        for manifest, manifest_path in manifests:
            capture_id = manifest["captureId"]
            row = rows_by_capture[capture_id]
            existing = records_by_capture.get(capture_id, [])
            if existing:
                existing_slot_ids = {record.metadata.get("slotId") for record in existing if record.asset_role == "slot"}
                if len(existing) != 10 or existing_slot_ids != set(SLOT_IDS):
                    raise CaptureManifestError(f"project contains an incomplete imported capture: {capture_id}")
                effective_context = row.get("effectiveCropContext")
                if isinstance(effective_context, dict):
                    correction_ids = list(row.get("cropContextCorrectionIds") or [])
                    capture_metadata_changed = False
                    for record in existing:
                        metadata = record.metadata
                        before_metadata = dict(metadata)
                        metadata.setdefault("originalSowingDate", metadata.get("sowingDate"))
                        metadata.setdefault("originalNftStartDate", metadata.get("nftStartDate"))
                        metadata.setdefault("originalDaysAfterSowing", metadata.get("daysAfterSowing"))
                        metadata.setdefault("originalDaysAfterNft", metadata.get("daysAfterNft"))
                        metadata.update({
                            "cropDisplayName": effective_context.get("cropDisplayName", ""),
                            "captureLocalDate": effective_context.get("localDate"),
                            "sowingDate": effective_context.get("sowingDate"),
                            "nftStartDate": effective_context.get("nftStartDate"),
                            "daysAfterSowing": effective_context.get("daysAfterSowing"),
                            "daysAfterNft": effective_context.get("daysAfterNft"),
                            "timezone": effective_context.get("timezone"),
                            "cropContextCorrectionIds": correction_ids,
                        })
                        capture_metadata_changed = capture_metadata_changed or metadata != before_metadata
                    if capture_metadata_changed:
                        metadata_updated_capture_ids.append(capture_id)
                skipped_capture_ids.append(capture_id)
                continue
            duplicate = next(
                (asset["assetId"] for asset in manifest["assets"] if asset.get("role") == "slot" and asset["assetId"] in known_asset_ids),
                None,
            )
            if duplicate:
                raise CaptureManifestError(f"capture asset was already imported under another capture: {duplicate}")
            provenance_dir = store.project_dir(project) / "assets" / capture_id
            if provenance_dir.exists():
                raise CaptureManifestError(f"capture provenance exists without a complete import: {capture_id}")
            to_import.append(manifest_path)
        imported = 0
        slot_images = 0
        for manifest_path in to_import:
            manifest = next(item for item, path in manifests if path == manifest_path)
            row = rows_by_capture[manifest["captureId"]]
            added, _skipped = import_capture_manifest(
                store,
                project,
                manifest_path,
                effective_crop_context=row.get("effectiveCropContext"),
                crop_context_correction_ids=row.get("cropContextCorrectionIds"),
            )
            imported += 1
            slot_images += added
        if metadata_updated_capture_ids:
            store.save(project)
        return {
            "datasetExportId": index["datasetExportId"],
            "capturesImported": imported,
            "capturesSkipped": len(skipped_capture_ids),
            "slotImagesImported": slot_images,
            "skippedCaptureIds": skipped_capture_ids,
            "capturesMetadataUpdated": len(metadata_updated_capture_ids),
            "metadataUpdatedCaptureIds": metadata_updated_capture_ids,
        }


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
    reviewed_images = 0
    trainable_labels = {key: Counter() for key in MODEL_KEYS}
    validation_labels = {key: Counter() for key in MODEL_KEYS}
    excluded_labels = {key: Counter() for key in MODEL_KEYS}
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
        rack_id = str(record.metadata.get("rackId", ""))
        position = record.metadata.get("position")
        expected_plant = (
            f"{record.metadata.get('cropCycleId', '')}:{rack_id}:{position}"
            if record.metadata.get("bindingId") and rack_id and isinstance(position, int)
            else f"{record.metadata.get('cropCycleId', '')}:{slot_id}"
        )
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
        if record.review_status == "reviewed":
            reviewed_images += 1
            for key in MODEL_KEYS:
                label = record.attributes.get(key, "missing")
                if label in {"present", "absent"}:
                    trainable_labels[key][label] += 1
                    if split == "val":
                        validation_labels[key][label] += 1
                else:
                    excluded_labels[key][label] += 1
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
    model_readiness = {}
    for key in MODEL_KEYS:
        train_counts = trainable_labels[key]
        val_counts = validation_labels[key]
        model_readiness[key] = {
            "reviewedTrainable": {
                "present": train_counts["present"],
                "absent": train_counts["absent"],
            },
            "validationTrainable": {
                "present": val_counts["present"],
                "absent": val_counts["absent"],
            },
            "excludedFromTraining": dict(excluded_labels[key]),
            "workflowTrainable": train_counts["present"] > 0 and train_counts["absent"] > 0,
            "thresholdCalibrationReady": val_counts["present"] > 0 and val_counts["absent"] > 0,
        }
    has_errors = any(issue["severity"] == "error" for issue in issues)
    all_trainable = all(item["workflowTrainable"] for item in model_readiness.values())
    all_threshold_ready = all(item["thresholdCalibrationReady"] for item in model_readiness.values())
    if not project.images:
        readiness_status = "empty_dataset"
        next_actions = ["import_reviewed_capture_export"]
    elif has_errors:
        readiness_status = "dataset_qa_blocked"
        next_actions = ["resolve_dataset_errors"]
    elif reviewed_images == 0:
        readiness_status = "label_review_required"
        next_actions = ["label_and_review_slot_images"]
    elif not all_trainable:
        readiness_status = "class_pair_incomplete"
        next_actions = ["add_reviewed_present_and_absent_labels"]
    elif not all_threshold_ready:
        readiness_status = "validation_split_incomplete"
        next_actions = ["add_validation_examples_for_both_labels"]
    else:
        readiness_status = "ready_for_shadow_training"
        next_actions = (["collect_independent_crop_cycle_holdout"] if not independent_holdout else [])
    pilot_readiness = {
        "schemaVersion": 1,
        "status": readiness_status,
        "reviewedImages": reviewed_images,
        "unreviewedImages": len(project.images) - reviewed_images,
        "models": model_readiness,
        "shadowBundleReady": not has_errors and all_trainable and all_threshold_ready,
        "operationalBundleReady": (
            not has_errors and all_trainable and all_threshold_ready and validation_status == "validated_holdout"
        ),
        "nextActions": next_actions,
    }
    return {
        "schemaVersion": 1,
        "images": len(project.images),
        "issues": issues,
        "distributions": {key: dict(value) for key, value in distributions.items()},
        "independentCropCycleHoldout": independent_holdout,
        "validationStatus": validation_status,
        "pilotReadiness": pilot_readiness,
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
    runtime_target: str = "jetson_nano_tensorrt_fp16",
    deployment_mode: str = "shadow",
) -> Path:
    output = Path(output_dir).resolve()
    crop_code, _crop_display_name = validate_crop_identity(
        str(project.metadata.get("cropCode") or ""),
        str(project.metadata.get("cropDisplayName") or ""),
    )
    if output.exists():
        raise FileExistsError(f"bundle output already exists: {output}")
    if set(models) != set(MODEL_KEYS) or set(thresholds) != set(MODEL_KEYS):
        raise ValueError("bundle requires independent presence/yellow/wilt models and thresholds")
    if not dataset_version or not source_commit or not camera_profile_ids or not geometry_profile_ids:
        raise ValueError("dataset/source/profile compatibility metadata is required")
    if runtime_target not in RUNTIME_TARGETS:
        raise ValueError(f"unsupported Hydro runtime target: {runtime_target}")
    if deployment_mode not in {"shadow", "operational"}:
        raise ValueError("deployment_mode must be shadow or operational")
    validation_status = str(project.metadata.get("validationStatus", "pilot_unvalidated"))
    if runtime_target == "windows_onnxruntime_cpu" and deployment_mode != "shadow":
        raise ValueError("Windows ONNX Runtime is only allowed in shadow mode")
    if deployment_mode == "operational" and validation_status != "validated_holdout":
        raise ValueError("operational deployment requires an independent validated holdout")
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
    bundle_id = f"hydro_{crop_code}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
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
                "resizeMode": "short_side_center_crop",
                "normalization": {"scale": 1 / 255, "mean": [0, 0, 0], "std": [1, 1, 1]},
                "lowThreshold": low,
                "highThreshold": high,
            }
        manifest = {
            "schemaVersion": 1,
            "bundleId": bundle_id,
            "cropCode": crop_code,
            "pipeline": "fixed_slot_multilabel_v1",
            "compatibleCameraProfileIds": camera_profile_ids,
            "compatibleGeometryProfileIds": geometry_profile_ids,
            "models": entries,
            "datasetVersion": dataset_version,
            "sourceCommit": source_commit,
            "runtimeTarget": runtime_target,
            "deploymentMode": deployment_mode,
            "trainingPurpose": str(project.metadata.get("trainingPurpose", "pilot")),
            "validationStatus": validation_status,
            "labelDistribution": label_distribution,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if runtime_target == "jetson_nano_tensorrt_fp16":
            manifest["minimumTensorRTVersion"] = "8.2"
        (temporary / "bundle.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, output)
        archive = output.with_suffix(".zip")
        if archive.exists():
            raise FileExistsError(f"bundle ZIP already exists: {archive}")
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as package:
            for item in sorted(path for path in output.rglob("*") if path.is_file()):
                package.write(item, item.relative_to(output).as_posix())
        return output
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
