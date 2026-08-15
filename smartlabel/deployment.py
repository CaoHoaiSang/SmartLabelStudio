from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import re
import zipfile

from .models import Project


def build_vision_bundle_manifest(
    project: Project,
    *,
    localization_model: str,
    localization_metadata: dict[str, Any],
    classifiers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the portable contract consumed by the future Radxa runtime."""
    return {
        "schema_version": 1,
        "pipeline": "detection_then_classification",
        "target": "rk3588",
        "project_id": project.id,
        "project_name": project.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "localization": {
            "model": localization_model,
            "task": localization_metadata.get("task", "detect"),
            "input_size": localization_metadata.get("imgsz", [640, 640]),
            "labels": localization_metadata.get(
                "names", {str(item.id): item.name for item in project.classes}
            ),
        },
        "classifiers": classifiers,
        "runtime_rules": {
            "load_models_once": True,
            "crop_source": "localization_bbox",
            "crop_padding_ratio": 0.05,
            "preserve_frame_id": True,
            "skip_stale_frames": True,
            "result_field": "attributes",
        },
        "result_contract": {
            "object_fields": [
                "type_id",
                "class_name",
                "confidence",
                "bbox",
                "tcp_u",
                "tcp_v",
                "width",
                "height",
                "angle",
                "attributes",
            ],
            "attribute_fields": ["value", "confidence", "model"],
            "unknown_policy": "confidence_below_threshold",
        },
        "radxa_integration": {
            "status": "not_applied",
            "note": "Xem RADXA_CLASSIFICATION_INTEGRATION.md; chưa sửa runtime Radxa.",
        },
    }


def classifier_manifest_entry(
    project: Project,
    *,
    attribute_key: str,
    model_name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    settings = project.attribute_settings.get(attribute_key, {})
    values = project.attribute_schema.get(attribute_key, [])
    return {
        "attribute_key": attribute_key,
        "attribute_title": settings.get("title", attribute_key),
        "model": model_name,
        "task": "classify",
        "input_size": metadata.get("imgsz", [224, 224]),
        "labels": metadata.get("names", {str(index): value for index, value in enumerate(values)}),
        "normalization": metadata.get(
            "normalization", {"mean": [0, 0, 0], "std": [255, 255, 255], "rgb2bgr": False}
        ),
        "input_contract": metadata.get(
            "input_contract",
            {"runtime_layout": "NHWC", "dtype": "uint8", "color": "RGB", "resize": "center_crop"},
        ),
        "confidence_threshold": 0.60,
        "unknown_below_threshold": True,
    }


def write_classifier_pt_bundle(
    project: Project,
    output: str | Path,
    models: dict[str, str | Path],
) -> Path:
    """Store several independently trained attribute classifiers in one portable file.

    This is deliberately a package, not a neural-network weight merge. Each
    attribute group keeps its own softmax label space and can later be enabled
    or disabled independently by the runtime.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    archive_names: set[str] = set()
    sources: list[tuple[Path, str]] = []
    for index, (key, raw_source) in enumerate(sorted(models.items())):
        source = Path(raw_source)
        if not source.is_file():
            raise FileNotFoundError(f"Không tìm thấy classifier của nhóm {key}: {source}")
        safe_key = re.sub(r"[^0-9A-Za-z_-]+", "_", key).strip("_") or f"attribute_{index}"
        archive_name = f"models/classifier_{safe_key}.pt"
        if archive_name.lower() in archive_names:
            archive_name = f"models/classifier_{safe_key}_{index}.pt"
        archive_names.add(archive_name.lower())
        config = project.attribute_settings.get(key, {})
        entries.append(
            {
                "attribute_key": key,
                "attribute_title": config.get("title", key),
                "model": archive_name,
                "task": "classify",
                "labels": {
                    str(label_index): value
                    for label_index, value in enumerate(project.attribute_schema.get(key, []))
                },
                "input_size": [224, 224],
            }
        )
        sources.append((source, archive_name))
    if not entries:
        raise ValueError("Chưa có classifier nào để tạo gói.")
    manifest = {
        "schema_version": 1,
        "package_type": "attribute_classifier_pt_bundle",
        "project_id": project.id,
        "project_name": project.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model_count": len(entries),
        "models": entries,
        "runtime_note": "Một gói quản lý chứa nhiều classifier độc lập; không nạp ZIP trực tiếp vào YOLO/RKNN.",
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("classification_bundle.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for source, archive_name in sources:
            archive.write(source, archive_name)
    return output
