from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json


def quality_rating(map50_95: float, precision: float, recall: float) -> str:
    """A conservative learning-oriented rating, not an industrial acceptance rule."""
    if map50_95 >= 0.80 and precision >= 0.85 and recall >= 0.85:
        return "Rất tốt trên tập đánh giá"
    if map50_95 >= 0.65 and precision >= 0.80 and recall >= 0.80:
        return "Tốt, cần xác nhận thêm bằng ảnh hiện trường"
    if map50_95 >= 0.50 and precision >= 0.70 and recall >= 0.70:
        return "Khá, vẫn cần cải thiện trước khi sản xuất"
    return "Chưa đủ tin cậy để triển khai sản xuất"


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tolist(value: Any) -> list[float]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [_float(item) for item in value]


def evaluate_yolo_model(
    model_path: str | Path,
    data_path: str | Path,
    *,
    split: str,
    image_size: int,
    device: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """Evaluate one Ultralytics model and return JSON-safe metrics."""
    from ultralytics import YOLO

    model_path = Path(model_path).resolve()
    data_path = Path(data_path).resolve()
    if split not in {"val", "test"}:
        raise ValueError("Tập đánh giá phải là val hoặc test.")
    if not model_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy model: {model_path}")
    if not data_path.exists():
        raise FileNotFoundError(f"Không tìm thấy dataset: {data_path}")

    model = YOLO(str(model_path))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    metrics = model.val(
        data=str(data_path),
        split=split,
        imgsz=image_size,
        device=device,
        workers=0,
        verbose=False,
        plots=True,
        project=str(Path(output_root).resolve()),
        name=f"{model_path.stem}_{split}_{stamp}",
        exist_ok=True,
    )
    names = {int(key): str(value) for key, value in dict(getattr(metrics, "names", {})).items()}
    result: dict[str, Any] = {
        "model": str(model_path),
        "dataset": str(data_path),
        "task": str(getattr(model, "task", "unknown")),
        "split": split,
        "image_size": image_size,
        "save_dir": str(getattr(metrics, "save_dir", "")),
        "speed_ms": {key: _float(value) for key, value in dict(getattr(metrics, "speed", {})).items()},
        "names": names,
        "metrics": {},
        "per_class": [],
    }

    detection_metrics = None
    metric_kind = "Box"
    task = result["task"]
    metric_order = {
        "segment": (("seg", "Mask"), ("box", "Box")),
        "pose": (("pose", "Pose"), ("box", "Box")),
        "obb": (("box", "OBB"),),
    }.get(task, (("box", "Box"),))
    for attr, label in metric_order:
        candidate = getattr(metrics, attr, None)
        if candidate is not None:
            detection_metrics = candidate
            metric_kind = label
            break
    if detection_metrics is not None:
        summary = {
            "precision": _float(getattr(detection_metrics, "mp", 0)),
            "recall": _float(getattr(detection_metrics, "mr", 0)),
            "map50": _float(getattr(detection_metrics, "map50", 0)),
            "map50_95": _float(getattr(detection_metrics, "map", 0)),
        }
        result["metric_kind"] = metric_kind
        result["metrics"] = summary
        precision = _tolist(getattr(detection_metrics, "p", []))
        recall = _tolist(getattr(detection_metrics, "r", []))
        map50 = _tolist(getattr(detection_metrics, "ap50", []))
        maps = _tolist(getattr(detection_metrics, "maps", []))
        count = max(len(precision), len(recall), len(map50), len(maps), len(names))
        result["per_class"] = [
            {
                "class_id": index,
                "class_name": names.get(index, str(index)),
                "precision": precision[index] if index < len(precision) else 0.0,
                "recall": recall[index] if index < len(recall) else 0.0,
                "map50": map50[index] if index < len(map50) else 0.0,
                "map50_95": maps[index] if index < len(maps) else 0.0,
            }
            for index in range(count)
        ]
        result["rating"] = quality_rating(summary["map50_95"], summary["precision"], summary["recall"])
    elif getattr(metrics, "top1", None) is not None:
        top1 = _float(metrics.top1)
        top5 = _float(getattr(metrics, "top5", 0))
        result["metric_kind"] = "Classification"
        result["metrics"] = {"top1": top1, "top5": top5}
        result["rating"] = (
            "Tốt trên tập đánh giá" if top1 >= 0.90 else
            "Khá, cần cải thiện" if top1 >= 0.80 else
            "Chưa đủ tin cậy để triển khai sản xuất"
        )
    else:
        raise RuntimeError("Không đọc được chỉ số từ kết quả đánh giá của model này.")

    save_dir = Path(result["save_dir"])
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "evaluation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
