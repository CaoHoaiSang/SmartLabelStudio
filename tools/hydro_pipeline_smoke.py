from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import cv2
import numpy as np

from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydroponic import (
    MODEL_KEYS,
    apply_hydroponic_slot_template,
    export_jetson_onnx,
    hydro_dataset_qa,
    import_capture_manifest,
    validate_capture_manifest,
    write_hydro_model_bundle,
)
from smartlabel.project_store import ProjectStore


VARIANTS = (
    ("clean_a", "present", "absent", "absent"),
    ("clean_b", "present", "absent", "absent"),
    ("yellow_a", "present", "present", "absent"),
    ("yellow_b", "present", "present", "absent"),
    ("wilt_a", "present", "absent", "present"),
    ("wilt_b", "present", "absent", "present"),
    ("absent_a", "absent", "not_applicable", "not_applicable"),
    ("absent_b", "absent", "not_applicable", "not_applicable"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quality(image: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {
        "brightness": round(float(gray.mean()), 3),
        "contrast": round(float(gray.std()), 3),
        "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3),
    }


def rect(asset: dict) -> tuple[int, int, int, int]:
    value = asset["rectInFullFrame"]
    return tuple(int(value[key]) for key in ("x", "y", "width", "height"))


def transform_slot(crop: np.ndarray, variant: str, rng: np.random.Generator) -> np.ndarray:
    value = crop.copy()
    if variant.startswith("yellow"):
        hsv = cv2.cvtColor(value, cv2.COLOR_BGR2HSV)
        mask = (hsv[:, :, 0] >= 32) & (hsv[:, :, 0] <= 95) & (hsv[:, :, 1] >= 35)
        hsv[:, :, 0][mask] = np.clip(24 + rng.integers(-2, 3), 0, 179)
        hsv[:, :, 1][mask] = np.clip(hsv[:, :, 1][mask].astype(np.int16) + 35, 0, 255).astype(np.uint8)
        value = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    elif variant.startswith("wilt"):
        height, width = value.shape[:2]
        background = cv2.GaussianBlur(value, (0, 0), 25)
        compressed_height = max(2, int(round(height * 0.68)))
        compressed = cv2.resize(value, (width, compressed_height), interpolation=cv2.INTER_AREA)
        top = height - compressed_height
        background[top:, :] = cv2.GaussianBlur(compressed, (5, 5), 0)
        value = cv2.convertScaleAbs(background, alpha=0.82, beta=-8)
    elif variant.startswith("absent"):
        height, width = value.shape[:2]
        border = np.concatenate((
            value[: max(1, height // 8)].reshape(-1, 3),
            value[-max(1, height // 8):].reshape(-1, 3),
            value[:, : max(1, width // 10)].reshape(-1, 3),
            value[:, -max(1, width // 10):].reshape(-1, 3),
        ))
        fill = np.median(border, axis=0).astype(np.uint8)
        value[:] = fill
        value = cv2.GaussianBlur(value, (0, 0), 9)
    alpha = 0.97 if variant.endswith("a") else 1.03
    value = cv2.convertScaleAbs(value, alpha=alpha, beta=-2 if variant.endswith("a") else 2)
    noise = rng.normal(0, 1.2, value.shape).astype(np.int16)
    return np.clip(value.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def write_jpeg(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp" + path.suffix)
    if not cv2.imwrite(str(temporary), image, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError(f"cannot write {path}")
    temporary.replace(path)


def build_smoke_manifests(base_manifest_path: Path, output_root: Path) -> list[tuple[Path, tuple[str, str, str]]]:
    base_manifest, resolved = validate_capture_manifest(base_manifest_path)
    full_asset = next(asset for asset in base_manifest["assets"] if asset["role"] == "full_frame")
    full = cv2.imread(str(resolved[full_asset["assetId"]]))
    if full is None or full.shape[:2] != (1080, 1920):
        raise RuntimeError("base capture full frame is unreadable or not 1920x1080")
    slot_assets = [asset for asset in base_manifest["assets"] if asset["role"] == "slot"]
    captures = []
    base_time = datetime.now(timezone.utc).replace(microsecond=0)
    for variant_index, (variant, presence, yellow, wilt) in enumerate(VARIANTS):
        capture_id = f"cap_smoke_{base_time:%Y%m%dT%H%M%S}_{variant}"
        capture_dir = output_root / "captures" / base_time.strftime("%Y") / base_time.strftime("%m") / base_time.strftime("%d") / capture_id
        transformed = full.copy()
        rng = np.random.default_rng(20260821 + variant_index)
        for asset in slot_assets:
            x, y, width, height = rect(asset)
            transformed[y:y + height, x:x + width] = transform_slot(
                transformed[y:y + height, x:x + width], variant, rng,
            )
        relative_prefix = capture_dir.relative_to(output_root).as_posix()
        full_path = capture_dir / "full.jpg"
        write_jpeg(full_path, transformed)
        id_map = {asset["assetId"]: f"{capture_id}_{asset['role']}_{asset.get('slotId') or asset.get('rackId') or 'frame'}" for asset in base_manifest["assets"]}
        assets = []
        for asset in base_manifest["assets"]:
            copied = {
                key: value
                for key, value in asset.items()
                if key not in {"assetId", "parentAssetId", "relativePath", "sha256", "quality", "width", "height"}
            }
            copied["assetId"] = id_map[asset["assetId"]]
            if asset.get("parentAssetId"):
                copied["parentAssetId"] = id_map[asset["parentAssetId"]]
            if asset["role"] == "full_frame":
                target = full_path
                image = transformed
                relative = f"{relative_prefix}/full.jpg"
            elif asset["role"] == "roi":
                x, y, width, height = rect(asset)
                image = transformed[y:y + height, x:x + width]
                target = capture_dir / f"{asset['rackId']}_roi.jpg"
                relative = f"{relative_prefix}/{asset['rackId']}_roi.jpg"
                write_jpeg(target, image)
            else:
                x, y, width, height = rect(asset)
                image = transformed[y:y + height, x:x + width]
                target = capture_dir / "slots" / f"{asset['slotId']}.jpg"
                relative = f"{relative_prefix}/slots/{asset['slotId']}.jpg"
                write_jpeg(target, image)
            copied.update({
                "relativePath": relative,
                "sha256": sha256(target),
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
                "quality": quality(image),
            })
            assets.append(copied)
        captured_at = base_time + timedelta(minutes=variant_index)
        manifest = {
            key: value
            for key, value in base_manifest.items()
            if key not in {"captureId", "capturedAt", "scheduledFor", "trigger", "assets", "cropCycleId"}
        }
        manifest.update({
            "captureId": capture_id,
            "capturedAt": captured_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "trigger": "manual",
            "cropCycleId": "cai_ngot_pipeline_smoke_2026-08-21",
            "qualityStatus": "accepted",
            "assets": assets,
            "smokeFixture": {
                "schemaVersion": 1,
                "derivedFromCaptureId": base_manifest["captureId"],
                "variant": variant,
                "synthetic": True,
                "purpose": "pipeline_smoke_only",
            },
        })
        manifest_path = capture_dir / "manifest.json"
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)
        validate_capture_manifest(manifest_path)
        captures.append((manifest_path, (presence, yellow, wilt)))
    return captures


def balanced_threshold(samples: list[tuple[float, str]]) -> dict:
    negatives = [probability for probability, label in samples if label == "absent"]
    positives = [probability for probability, label in samples if label == "present"]
    if not negatives or not positives:
        raise RuntimeError("validation split requires both absent and present labels")
    values = sorted(set(probability for probability, _label in samples))
    candidates = [0.0, 1.0, *values]
    candidates.extend((left + right) / 2 for left, right in zip(values, values[1:]))
    scored = []
    for threshold in candidates:
        tnr = sum(value < threshold for value in negatives) / len(negatives)
        tpr = sum(value >= threshold for value in positives) / len(positives)
        scored.append(((tnr + tpr) / 2, -abs(threshold - 0.5), threshold))
    best_score, _tie, best = max(scored)
    maximum_negative = max(negatives)
    minimum_positive = min(positives)
    if maximum_negative < minimum_positive:
        low, high = maximum_negative, minimum_positive
    else:
        low, high = max(0.0, best - 0.05), min(1.0, best + 0.05)
    if high - low < 0.01:
        low, high = max(0.0, best - 0.02), min(1.0, best + 0.02)
    return {
        "lowThreshold": round(float(low), 6),
        "highThreshold": round(float(high), 6),
        "balancedAccuracyAtDecisionThreshold": round(float(best_score), 6),
        "decisionThreshold": round(float(best), 6),
        "validationAbsent": len(negatives),
        "validationPresent": len(positives),
        "negativeRange": [round(float(min(negatives)), 6), round(float(maximum_negative), 6)],
        "positiveRange": [round(float(minimum_positive), 6), round(float(max(positives)), 6)],
    }


def calibrate_onnx(model_path: Path, export_dir: Path) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(model_path), task="classify")
    names = {int(index): str(name) for index, name in model.names.items()}
    reverse = {name: index for index, name in names.items()}
    if set(reverse) != {"absent", "present"}:
        raise RuntimeError(f"unexpected classifier label order: {names}")
    paths = []
    labels = []
    for label in ("absent", "present"):
        for image_path in sorted((export_dir / "val" / label).glob("*")):
            if image_path.is_file():
                paths.append(str(image_path))
                labels.append(label)
    if not paths:
        raise RuntimeError("validation split is empty")
    # HydroModelBundleV1 intentionally exports a static batch-1 graph for
    # deterministic Windows/Jetson parity.  Ultralytics still groups a list
    # source using its loader batch size, even when ``batch=1`` is requested,
    # so invoke the static graph once per validation asset.
    results = [
        model.predict(path, imgsz=224, batch=1, device="cpu", verbose=False)[0]
        for path in paths
    ]
    samples = [
        (float(result.probs.data[reverse["present"]].cpu().item()), label)
        for result, label in zip(results, labels)
    ]
    report = balanced_threshold(samples)
    report["samples"] = [{"probability": round(value, 6), "label": label} for value, label in samples]
    return report


def git_commit(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown_source_commit"


def run(args: argparse.Namespace) -> dict:
    from ultralytics import YOLO

    workspace = args.workspace.resolve()
    store = ProjectStore(workspace)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project = store.create_project(f"Hydro Pipeline Smoke {stamp}", task="classify")
    apply_hydroponic_slot_template(project)
    project.description = (
        "Kiểm thử kỹ thuật SmartLabel -> train -> ONNX -> Hydro. Dữ liệu condition được biến đổi tổng hợp; "
        "không dùng để kết luận tình trạng cây thật."
    )
    project.metadata.update({
        "trainingPurpose": "pipeline_smoke_only",
        "validationStatus": "pipeline_smoke_only",
        "datasetVersion": f"pipeline-smoke-{stamp}",
        "syntheticDerived": True,
        "sourceCaptureManifest": args.manifest.name,
    })
    store.save(project)
    project_root = store.project_dir(project)
    smoke_data = project_root / "smoke_source"
    manifests = build_smoke_manifests(args.manifest.resolve(), smoke_data)
    for manifest_path, labels in manifests:
        import_capture_manifest(store, project, manifest_path)
        capture_id = json.loads(manifest_path.read_text(encoding="utf-8"))["captureId"]
        for record in project.images:
            if record.metadata.get("captureId") != capture_id:
                continue
            record.review_status = "reviewed"
            record.attributes.update({
                "plant_presence": labels[0],
                "yellow_leaf": labels[1],
                "wilt": labels[2],
            })
            record.metadata.update({
                "syntheticDerived": True,
                "trainingPurpose": "pipeline_smoke_only",
                "labelSource": "deterministic_smoke_fixture",
            })
    store.save(project)
    manager = DatasetManager(store)
    assignment = manager.ensure_split_assignment(project, force_rebalance=True, seed=42)
    qa = hydro_dataset_qa(project, store, assignment)
    errors = [issue for issue in qa["issues"] if issue["severity"] == "error"]
    if errors:
        raise RuntimeError(f"Hydro QA failed: {errors}")
    trained = {}
    onnx_models = {}
    thresholds = {}
    calibrations = {}
    exports = {}
    for key in MODEL_KEYS:
        print(f"\n===== EXPORT/TRAIN {key} =====", flush=True)
        export_dir = manager.export_classification(project, key)
        exports[key] = str(export_dir)
        run_name = f"pipeline_smoke_{key}_{stamp}"
        model = YOLO(args.base_model)
        result = model.train(
            data=str(export_dir),
            epochs=args.epochs,
            imgsz=224,
            batch=args.batch,
            patience=max(1, args.epochs),
            device="cpu",
            workers=0,
            cache=False,
            plots=False,
            project=str(project_root / "runs"),
            name=run_name,
            exist_ok=False,
            seed=42,
            deterministic=True,
            verbose=True,
        )
        best = Path(result.save_dir) / "weights" / "best.pt"
        if not best.is_file():
            raise RuntimeError(f"training did not produce {best}")
        registered = store.register_model(best)
        project.attribute_models[key] = str(registered)
        trained[key] = str(registered)
        onnx_path = project_root / "models" / f"{key}_{stamp}.onnx"
        export_jetson_onnx(registered, onnx_path, input_size=224, opset=12)
        onnx_models[key] = str(onnx_path)
        calibration = calibrate_onnx(onnx_path, export_dir)
        calibrations[key] = calibration
        thresholds[key] = {
            "lowThreshold": calibration["lowThreshold"],
            "highThreshold": calibration["highThreshold"],
        }
        store.save(project)
    project.metadata["hydroOnnxModels"] = onnx_models
    project.metadata["hydroThresholds"] = thresholds
    project.metadata["hydroRuntimeTarget"] = "windows_onnxruntime_cpu"
    project.metadata["validationStatus"] = "pipeline_smoke_only"
    source_commit = git_commit(Path(__file__).resolve().parents[1])
    bundle = write_hydro_model_bundle(
        project,
        project_root / "bundles" / f"hydro_pipeline_smoke_{stamp}",
        onnx_models,
        thresholds,
        dataset_version=project.metadata["datasetVersion"],
        source_commit=source_commit,
        camera_profile_ids=list(project.metadata.get("cameraProfileIds", [])),
        geometry_profile_ids=list(project.metadata.get("geometryProfileIds", [])),
        input_size=224,
        runtime_target="windows_onnxruntime_cpu",
        deployment_mode="shadow",
    )
    project.metadata["lastHydroBundle"] = str(bundle)
    store.save(project)
    report = {
        "schemaVersion": 1,
        "status": "completed",
        "purpose": "pipeline_smoke_only",
        "warning": "Synthetic condition variants validate plumbing only; they do not validate agronomic accuracy.",
        "projectId": project.id,
        "projectName": project.name,
        "projectPath": str(project_root),
        "images": len(project.images),
        "captures": len(manifests),
        "splitAssignment": assignment,
        "qa": qa,
        "exports": exports,
        "trainedModels": trained,
        "onnxModels": onnx_models,
        "calibration": calibrations,
        "bundle": str(bundle),
        "bundleManifestSha256": sha256(bundle / "bundle.json"),
        "sourceCommit": source_commit,
        "completedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    report_path = args.report.resolve() if args.report else project_root / "pipeline_smoke_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "projectId": project.id, "bundle": str(bundle), "report": str(report_path)}, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an honest Hydro SmartLabel -> ONNX pipeline smoke test")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--base-model", default="yolo11n-cls.pt")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch < 1:
        parser.error("epochs and batch must be positive")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
