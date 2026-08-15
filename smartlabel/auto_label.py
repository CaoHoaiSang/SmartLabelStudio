from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
import importlib.util
import time

from .hardware import best_ultralytics_device
from .models import Annotation, ImageRecord, Project
from .project_store import ProjectStore


@dataclass
class AutoLabelStats:
    processed: int = 0
    detections: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    device: str = ""
    task: str = "detect"


def mask_to_geometry(mask, anchor_point: tuple[float, float] | None = None) -> dict[str, list]:
    """Convert a SAM binary mask into shared RECT/SEG/OBB geometry.

    SAM can occasionally return more than one connected component.  For a
    point prompt, prefer the component that actually contains the clicked
    point; otherwise fall back to the largest component.
    """
    import cv2
    import numpy as np

    binary = (np.asarray(mask).astype("uint8") > 0).astype("uint8") * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [contour for contour in contours if cv2.contourArea(contour) >= 9.0]
    if not contours:
        raise RuntimeError("SAM2 không tạo được vùng vật hợp lệ")

    contour = None
    if anchor_point is not None:
        anchor = (float(anchor_point[0]), float(anchor_point[1]))
        containing = [item for item in contours if cv2.pointPolygonTest(item, anchor, False) >= 0]
        if containing:
            contour = max(containing, key=cv2.contourArea)
    if contour is None:
        contour = max(contours, key=cv2.contourArea)

    epsilon = max(1.0, 0.002 * cv2.arcLength(contour, True))
    polygon = cv2.approxPolyDP(contour, epsilon, True)
    points = [[float(point[0][0]), float(point[0][1])] for point in polygon]
    if len(points) < 3:
        raise RuntimeError("Biên SAM2 có ít hơn 3 điểm")

    x, y, width, height = cv2.boundingRect(contour)
    rotated = cv2.minAreaRect(contour.astype(np.float32))
    obb = [[float(px), float(py)] for px, py in cv2.boxPoints(rotated)]
    return {
        "bbox": [float(x), float(y), float(width), float(height)],
        "points": points,
        "obb": obb,
    }


class YoloAutoLabeler:
    def __init__(self, model_path: str | Path, device: str = "auto"):
        if importlib.util.find_spec("ultralytics") is None:
            raise RuntimeError("Chưa cài ultralytics. Chạy: pip install ultralytics")
        from ultralytics import YOLO

        self.model_path = Path(model_path).resolve()
        self.device = best_ultralytics_device(device)
        self.model = YOLO(str(self.model_path))
        self.task = str(getattr(self.model, "task", "detect") or "detect")
        self.names = {int(k): str(v) for k, v in self.model.names.items()}

    def predict(self, image_path: str | Path, confidence: float = 0.25, image_size: int = 640) -> list[Annotation]:
        results = self.model.predict(
            source=str(image_path),
            conf=confidence,
            imgsz=image_size,
            device=self.device,
            verbose=False,
        )
        annotations: list[Annotation] = []
        for result in results:
            if result.obb is not None:
                corners = result.obb.xyxyxyxy.detach().cpu().numpy()
                classes = result.obb.cls.detach().cpu().numpy()
                confidences = result.obb.conf.detach().cpu().numpy()
                for points, class_id, score in zip(corners, classes, confidences):
                    points = [[float(x), float(y)] for x, y in points]
                    xs, ys = [p[0] for p in points], [p[1] for p in points]
                    ann = Annotation.create_box(
                        int(class_id),
                        [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)],
                        source="yolo", confidence=float(score), model_version=self.model_path.name,
                    )
                    ann.kind = "obb"
                    ann.obb = points
                    annotations.append(ann)
                continue
            if result.boxes is None:
                continue
            xyxy = result.boxes.xyxy.detach().cpu().numpy()
            classes = result.boxes.cls.detach().cpu().numpy()
            confidences = result.boxes.conf.detach().cpu().numpy()
            mask_polygons = list(result.masks.xy) if result.masks is not None else []
            keypoints = result.keypoints.xy.detach().cpu().numpy() if result.keypoints is not None else None
            for index, (box, class_id, score) in enumerate(zip(xyxy, classes, confidences)):
                x1, y1, x2, y2 = [float(v) for v in box]
                ann = Annotation.create_box(
                    int(class_id),
                    [x1, y1, x2 - x1, y2 - y1],
                    source="yolo",
                    confidence=float(score),
                    model_version=self.model_path.name,
                )
                if index < len(mask_polygons) and len(mask_polygons[index]) >= 3:
                    ann.kind = "polygon"
                    ann.points = [[float(x), float(y)] for x, y in mask_polygons[index]]
                if keypoints is not None and index < len(keypoints) and len(keypoints[index]) >= 2:
                    first_two = keypoints[index][:2]
                    if all(float(x) > 0 or float(y) > 0 for x, y in first_two):
                        ann.orientation = [[float(x), float(y)] for x, y in first_two]
                annotations.append(ann)
        return annotations


def auto_label_project(
    store: ProjectStore,
    project: Project,
    model_path: str | Path,
    *,
    confidence: float = 0.25,
    image_size: int = 640,
    device: str = "auto",
    unlabeled_only: bool = True,
    replace_predictions: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    cancel_event: Event | None = None,
) -> AutoLabelStats:
    started = time.perf_counter()
    labeler = YoloAutoLabeler(model_path, device=device)
    # Synchronize class names while preserving stable IDs used by annotations.
    known = {item.id for item in project.classes}
    from .models import LabelClass
    palette = ["#21c7ff", "#74e35c", "#ffb547", "#f55d76", "#ad8cff", "#42d9c8"]
    for class_id, name in labeler.names.items():
        if class_id not in known:
            project.classes.append(LabelClass(class_id, name, palette[class_id % len(palette)]))

    targets = [item for item in project.images if not unlabeled_only or not item.annotations]
    stats = AutoLabelStats(device="CUDA" if labeler.device != "cpu" else "CPU", task=labeler.task)
    for index, record in enumerate(targets, start=1):
        if cancel_event and cancel_event.is_set():
            break
        if progress:
            progress(index, len(targets), record.file_name)
        try:
            predictions = labeler.predict(store.image_path(project, record), confidence, image_size)
            if replace_predictions:
                record.annotations = [ann for ann in record.annotations if ann.source == "manual" or ann.approved]
            record.annotations.extend(predictions)
            if predictions and record.review_status == "unlabeled":
                record.review_status = "draft"
            stats.detections += len(predictions)
            stats.processed += 1
            if index % 10 == 0:
                store.save(project)
        except Exception:
            stats.failed += 1
    store.save(project)
    stats.elapsed_seconds = time.perf_counter() - started
    return stats


class Sam2Adapter:
    """Optional prompt-to-mask adapter; SAM2 is loaded only when requested."""

    @staticmethod
    def available_configs() -> list[str]:
        if importlib.util.find_spec("sam2") is None:
            return []
        try:
            import sam2
            root = Path(sam2.__file__).resolve().parent
            config_root = root / "configs"
            # The installed package initializes Hydra directly at sam2/configs,
            # therefore config_name must be relative to that directory.
            return [path.relative_to(config_root).as_posix() for path in sorted(config_root.rglob("*.yaml"))]
        except Exception:
            return []

    @classmethod
    def suggest_config(cls) -> str:
        configs = cls.available_configs()
        for preferred in (
            "sam2.1/sam2.1_hiera_s.yaml",
            "sam2_hiera_s.yaml",
            "sam2.1/sam2.1_hiera_t.yaml",
            "sam2_hiera_t.yaml",
        ):
            if preferred in configs:
                return preferred
        return configs[0] if configs else ""

    @classmethod
    def resolve_config(cls, requested: str, checkpoint: str | Path) -> str:
        configs = cls.available_configs()
        normalized = requested.replace("\\", "/").strip()
        if normalized.startswith("configs/"):
            normalized = normalized[len("configs/"):]
        checkpoint_name = Path(checkpoint).name.lower()
        if "sam2.1" in checkpoint_name and not any("sam2.1" in item for item in configs):
            raise RuntimeError(
                "Checkpoint là SAM2.1 nhưng package hiện tại chỉ có config SAM2 đời đầu. "
                "Hãy cập nhật package SAM2 chính thức của Meta hoặc chọn checkpoint SAM2 tương ứng."
            )
        if normalized in configs:
            return normalized
        size_aliases = {
            "hiera_s": ("hiera_s.yaml",),
            "hiera_t": ("hiera_t.yaml",),
            "hiera_l": ("hiera_l.yaml",),
            "hiera_b+": ("hiera_b+.yaml", "hiera_bplus.yaml"),
        }
        for token, endings in size_aliases.items():
            if token in normalized or token in checkpoint_name:
                match = next((item for item in configs if item.endswith(endings)), None)
                if match:
                    return match
        if len(configs) == 1:
            return configs[0]
        available = ", ".join(configs) or "không có"
        raise RuntimeError(f"Không tìm thấy config SAM2 “{requested}”. Config hiện có: {available}")

    def __init__(self, checkpoint: str | Path, config: str, device: str = "auto"):
        if importlib.util.find_spec("sam2") is None:
            raise RuntimeError(
                "Chưa cài SAM2. Trên Windows nên dùng WSL/CUDA theo hướng dẫn Meta; "
                "có thể tiếp tục dùng box/polygon mà không cần SAM2."
            )
        checkpoint_value = str(checkpoint).strip()
        checkpoint_path = Path(checkpoint_value).expanduser() if checkpoint_value else None
        if checkpoint_path is None or not checkpoint_path.is_file() or checkpoint_path.suffix.lower() not in {".pt", ".pth"}:
            raise RuntimeError(
                "Checkpoint SAM2 chưa hợp lệ. Hãy chọn đúng một file .pt/.pth, không chọn thư mục hoặc để trống."
            )
        import torch
        import numpy as np
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        resolved_config = self.resolve_config(config, checkpoint)
        actual_device = "cuda" if device == "auto" and torch.cuda.is_available() else device
        if actual_device == "auto":
            actual_device = "cpu"
        self.np = np
        self.device = actual_device
        self.config = resolved_config
        try:
            try:
                model = build_sam2(resolved_config, str(checkpoint_path), device=actual_device)
            except Exception as first_exc:
                # Some official/source checkouts initialize Hydra one level higher.
                # Retry with the documented configs/ prefix only for missing-config errors.
                if "Cannot find primary config" not in str(first_exc):
                    raise
                model = build_sam2(f"configs/{resolved_config}", str(checkpoint_path), device=actual_device)
            self.predictor = SAM2ImagePredictor(model)
        except Exception as exc:
            message = str(exc)
            if "Missing key" in message or "Unexpected key" in message or "size mismatch" in message:
                raise RuntimeError(
                    f"Checkpoint không tương thích với config {resolved_config}. "
                    "Hãy chọn đúng cặp checkpoint/config (SAM2 hoặc SAM2.1)."
                ) from exc
            raise RuntimeError(f"Không nạp được SAM2 với config {resolved_config}: {message}") from exc
        self.image_key = ""

    def set_image(self, rgb_image, image_key: str = "") -> None:
        if image_key != self.image_key:
            self.predictor.set_image(rgb_image)
            self.image_key = image_key

    def mask_from_box(self, box_xyxy: list[float]):
        masks, scores, _ = self.predictor.predict(
            point_coords=None,
            point_labels=None,
            box=self.np.asarray(box_xyxy, dtype=self.np.float32),
            multimask_output=True,
        )
        index = int(scores.argmax())
        return masks[index], float(scores[index])

    def mask_from_prompts(self, box_xyxy: list[float], points: list[list[float]], labels: list[int]):
        masks, scores, _ = self.predictor.predict(
            point_coords=self.np.asarray(points, dtype=self.np.float32) if points else None,
            point_labels=self.np.asarray(labels, dtype=self.np.int32) if labels else None,
            box=self.np.asarray(box_xyxy, dtype=self.np.float32),
            multimask_output=True,
        )
        index = int(scores.argmax())
        return masks[index], float(scores[index])

    def mask_from_points(self, points: list[list[float]], labels: list[int]):
        """Create a mask from positive/negative points without an initial box."""
        if not points or len(points) != len(labels):
            raise ValueError("Cần ít nhất một điểm SAM và số nhãn điểm phải khớp")
        masks, scores, _ = self.predictor.predict(
            point_coords=self.np.asarray(points, dtype=self.np.float32),
            point_labels=self.np.asarray(labels, dtype=self.np.int32),
            box=None,
            multimask_output=True,
        )
        index = int(scores.argmax())
        return masks[index], float(scores[index])
