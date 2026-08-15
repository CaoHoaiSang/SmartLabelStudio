from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Iterable
import re

import cv2
import numpy as np

from .models import ImageRecord, Project
from .project_store import ProjectStore


@dataclass
class FrameFilterSettings:
    duplicate_similarity: float = 0.990
    model_confidence: float = 0.20
    negative_keep_percent: int = 10
    preview_width: int = 192
    preview_height: int = 108


@dataclass
class FrameDecision:
    image_id: str
    file_name: str
    category: str
    reason: str
    suggested_delete: bool
    similarity: float = 0.0
    detection_count: int = 0
    confidence: float = 0.0
    foreground_ratio: float = 0.0
    sharpness: float = 0.0
    brightness: float = 0.0
    source_kind: str = "imported"
    protected: bool = False
    metrics: dict[str, float] = field(default_factory=dict)


SOURCE_ALL = "all"
SOURCE_VIDEO = "video"
SOURCE_IMPORTED = "imported"


def is_video_frame(record: ImageRecord) -> bool:
    return record.source_path.endswith("#frame") or (
        record.capture_group.startswith("video_") and "_frame_" in record.file_name
    )


def video_frame_records(project: Project) -> list[ImageRecord]:
    """Return only records created by video extraction.

    Modern projects use ``source_path#frame``. The capture-group fallback keeps
    older imported projects compatible without touching normal still images.
    """
    return [record for record in project.images if is_video_frame(record)]


def imported_image_records(project: Project) -> list[ImageRecord]:
    """Return still images imported individually or from a folder."""

    return [record for record in project.images if not is_video_frame(record)]


def image_records_for_source(project: Project, source: str = SOURCE_ALL) -> list[ImageRecord]:
    if source == SOURCE_VIDEO:
        return video_frame_records(project)
    if source == SOURCE_IMPORTED:
        return imported_image_records(project)
    if source == SOURCE_ALL:
        return list(project.images)
    raise ValueError(f"Nguồn lọc không hợp lệ: {source}")


def latest_import_records(project: Project, source: str = SOURCE_ALL) -> list[ImageRecord]:
    """Return only images added by the most recent successful import call."""

    if not project.last_import_batch:
        return []
    return [
        record
        for record in image_records_for_source(project, source)
        if record.import_batch == project.last_import_batch
    ]


def image_records_for_filter(
    project: Project,
    source: str = SOURCE_ALL,
    *,
    include_existing: bool = False,
) -> list[ImageRecord]:
    """Combine source type with the user's old/new image scope."""

    if include_existing:
        return image_records_for_source(project, source)
    return latest_import_records(project, source)


def _frame_number(record: ImageRecord) -> int:
    match = re.search(r"_frame_(\d+)", record.file_name)
    return int(match.group(1)) if match else 0


def _load_preview(path: Path, settings: FrameFilterSettings) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Không đọc được ảnh: {path}")
    image = cv2.resize(image, (settings.preview_width, settings.preview_height), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(image, (3, 3), 0)


def _similarity(first: np.ndarray, second: np.ndarray) -> float:
    return max(0.0, 1.0 - float(np.mean(cv2.absdiff(first, second))) / 255.0)


def _detection_metrics(result, width: int, height: int, threshold: float) -> dict[str, float]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return {"accepted": 0.0, "weak": 0.0, "confidence": 0.0, "coverage": 0.0, "edge": 0.0}
    confidences = boxes.conf.detach().cpu().numpy()
    coords = boxes.xyxy.detach().cpu().numpy()
    accepted = confidences >= threshold
    weak = (confidences >= 0.05) & ~accepted
    accepted_coords = coords[accepted]
    coverage = 0.0
    edge = 0.0
    if len(accepted_coords):
        areas = np.maximum(0.0, accepted_coords[:, 2] - accepted_coords[:, 0]) * np.maximum(0.0, accepted_coords[:, 3] - accepted_coords[:, 1])
        coverage = min(1.0, float(areas.sum()) / max(width * height, 1))
        margin_x = max(width * 0.015, 2.0)
        margin_y = max(height * 0.015, 2.0)
        edge = float(np.any(
            (accepted_coords[:, 0] <= margin_x)
            | (accepted_coords[:, 1] <= margin_y)
            | (accepted_coords[:, 2] >= width - margin_x)
            | (accepted_coords[:, 3] >= height - margin_y)
        ))
    return {
        "accepted": float(accepted.sum()),
        "weak": float(weak.sum()),
        "confidence": float(confidences[accepted].max()) if accepted.any() else 0.0,
        "coverage": coverage,
        "edge": edge,
    }


def _run_yolo(
    paths: list[Path],
    model_path: str | Path,
    settings: FrameFilterSettings,
    progress: Callable[[int, int, str], None] | None,
    cancel_event: Event | None,
) -> dict[str, dict[str, float]]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    metrics: dict[str, dict[str, float]] = {}
    chunk_size = 24
    total = len(paths)
    for start in range(0, total, chunk_size):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Đã dừng phân tích frame.")
        chunk = paths[start : start + chunk_size]
        results = model.predict(
            [str(path) for path in chunk],
            device="cpu",
            imgsz=640,
            conf=0.05,
            verbose=False,
        )
        for offset, (path, result) in enumerate(zip(chunk, results), start=1):
            shape = getattr(result, "orig_shape", None) or (1, 1)
            height, width = int(shape[0]), int(shape[1])
            metrics[str(path)] = _detection_metrics(result, width, height, settings.model_confidence)
            if progress:
                progress(start + offset, total, "AI đang kiểm tra chai")
    return metrics


def _is_protected(record: ImageRecord) -> bool:
    return bool(record.annotations) or record.review_status == "reviewed"


def _duplicate_clusters(
    records: list[ImageRecord],
    previews: dict[str, np.ndarray],
    threshold: float,
    *,
    consecutive: bool,
) -> list[list[ImageRecord]]:
    """Group near-identical images without merging a slowly changing sequence."""

    if consecutive:
        clusters: list[list[ImageRecord]] = []
        cluster: list[ImageRecord] = []
        representative = None
        for record in records:
            preview = previews[record.id]
            if representative is None or _similarity(representative, preview) >= threshold:
                cluster.append(record)
                if representative is None:
                    representative = preview
            else:
                clusters.append(cluster)
                cluster = [record]
                representative = preview
        if cluster:
            clusters.append(cluster)
        return clusters

    # Still images are not guaranteed to be adjacent in filename order. Match
    # each image against cluster representatives so duplicates can be found
    # across multiple imported folders while keeping the operation reviewable.
    clusters = []
    representatives: list[np.ndarray] = []
    for record in records:
        preview = previews[record.id]
        matched = None
        for index, representative in enumerate(representatives):
            if _similarity(representative, preview) >= threshold:
                matched = index
                break
        if matched is None:
            clusters.append([record])
            representatives.append(preview)
        else:
            clusters[matched].append(record)
    return clusters


def analyze_smart_images(
    project: Project,
    store: ProjectStore,
    settings: FrameFilterSettings | None = None,
    *,
    model_path: str | Path | None = None,
    records: Iterable[ImageRecord] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    cancel_event: Event | None = None,
) -> list[FrameDecision]:
    """Analyze video frames and imported stills, then propose keep/delete.

    The active YOLO model is used only as an assistant. Weak detections are
    always kept for manual review. No project data is mutated by this function.
    """
    settings = settings or FrameFilterSettings()
    candidates = list(records) if records is not None else image_records_for_source(project)
    candidates.sort(
        key=lambda item: (
            0 if is_video_frame(item) else 1,
            item.capture_group,
            _frame_number(item) if is_video_frame(item) else 0,
            item.file_name,
        )
    )
    if not candidates:
        return []

    previews: dict[str, np.ndarray] = {}
    paths: dict[str, Path] = {}
    video_groups: dict[str, list[ImageRecord]] = {}
    imported_records: list[ImageRecord] = []
    total = len(candidates)
    for index, record in enumerate(candidates, start=1):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Đã dừng phân tích frame.")
        path = store.image_path(project, record)
        paths[record.id] = path
        previews[record.id] = _load_preview(path, settings)
        if is_video_frame(record):
            video_groups.setdefault(record.capture_group or "video", []).append(record)
        else:
            imported_records.append(record)
        if progress and (index == total or index % 10 == 0):
            progress(index, total, "Đang đo độ nét và độ giống")

    yolo_metrics: dict[str, dict[str, float]] = {}
    usable_model = Path(model_path).exists() if model_path else False
    if usable_model:
        yolo_metrics = _run_yolo(
            [paths[record.id] for record in candidates],
            str(model_path),
            settings,
            progress,
            cancel_event,
        )

    video_backgrounds: dict[str, np.ndarray] = {}
    for group_name, group_records in video_groups.items():
        sample_count = min(48, len(group_records))
        sample_indices = np.linspace(0, len(group_records) - 1, sample_count, dtype=int)
        video_backgrounds[group_name] = np.median(
            np.stack([previews[group_records[index].id] for index in sample_indices]),
            axis=0,
        ).astype(np.uint8)

    base: dict[str, FrameDecision] = {}
    for record in candidates:
        preview = previews[record.id]
        source_kind = SOURCE_VIDEO if is_video_frame(record) else SOURCE_IMPORTED
        background = video_backgrounds.get(record.capture_group or "video") if source_kind == SOURCE_VIDEO else None
        if background is not None:
            difference = cv2.absdiff(preview, background)
            foreground = float(np.count_nonzero(difference > 18)) / max(difference.size, 1)
        else:
            foreground = 0.0
        sharpness = float(cv2.Laplacian(preview, cv2.CV_64F).var())
        brightness = float(preview.mean())
        detected = yolo_metrics.get(str(paths[record.id]), {})
        accepted = int(detected.get("accepted", 0))
        weak = int(detected.get("weak", 0))
        confidence = float(detected.get("confidence", 0.0))
        quality_issue = ""
        severe_quality = False
        if brightness < 12:
            quality_issue = "Ảnh quá tối"
            severe_quality = True
        elif brightness > 245:
            quality_issue = "Ảnh quá sáng"
            severe_quality = True
        elif sharpness < 3:
            quality_issue = "Ảnh rất mờ hoặc quá ít chi tiết"

        if usable_model and accepted:
            category = "positive"
            reason = f"AI thấy {accepted} vật · tin cậy {confidence:.2f}"
            suggested_delete = False
        elif usable_model and weak:
            category = "uncertain"
            reason = f"AI chỉ thấy {weak} dự đoán yếu · cần kiểm tra"
            suggested_delete = False
        elif usable_model:
            category = "quality" if quality_issue else "empty"
            reason = quality_issue or "AI không thấy vật · ứng viên ảnh nền/ảnh vật chưa vào đủ"
            suggested_delete = True
        elif source_kind == SOURCE_VIDEO and foreground < 0.010:
            category = "empty"
            reason = "OpenCV thấy rất ít thay đổi so với nền video · cần kiểm tra"
            suggested_delete = True
        elif quality_issue:
            category = "quality"
            reason = f"{quality_issue} · chưa có model để xác nhận vật"
            suggested_delete = severe_quality
        else:
            category = "positive"
            reason = (
                "OpenCV thấy vật/chuyển động; chưa có model để xác nhận Class"
                if source_kind == SOURCE_VIDEO
                else "Ảnh nhập đạt kiểm tra cơ bản; cần model để xác định ảnh có vật hay ảnh nền"
            )
            suggested_delete = False
        if quality_issue and accepted:
            reason += f" · cảnh báo: {quality_issue.lower()}"
        base[record.id] = FrameDecision(
            image_id=record.id,
            file_name=record.file_name,
            category=category,
            reason=reason,
            suggested_delete=suggested_delete,
            detection_count=accepted,
            confidence=confidence,
            foreground_ratio=foreground,
            sharpness=sharpness,
            brightness=brightness,
            source_kind=source_kind,
            protected=_is_protected(record),
            metrics={
                "coverage": float(detected.get("coverage", 0.0)),
                "edge": float(detected.get("edge", 0.0)),
            },
        )

    duplicate_sets = [
        (group_records, True) for group_records in video_groups.values()
    ]
    if imported_records:
        duplicate_sets.append((imported_records, False))
    for group_records, consecutive in duplicate_sets:
        clusters = _duplicate_clusters(
            group_records,
            previews,
            settings.duplicate_similarity,
            consecutive=consecutive,
        )
        for members in clusters:
            if len(members) < 2:
                continue
            def quality(record: ImageRecord) -> float:
                decision = base[record.id]
                coverage = decision.metrics.get("coverage", 0.0)
                edge_penalty = decision.metrics.get("edge", 0.0)
                return (
                    (100.0 if decision.protected else 0.0)
                    + decision.detection_count * 4.0
                    + decision.confidence * 2.0
                    + coverage * 3.0
                    + min(decision.sharpness / 800.0, 1.0)
                    - edge_penalty * 0.75
                )
            keeper = max(members, key=quality)
            reference = previews[keeper.id]
            for record in members:
                if record.id == keeper.id:
                    continue
                decision = base[record.id]
                decision.category = "duplicate"
                decision.similarity = _similarity(reference, previews[record.id])
                noun = "frame" if consecutive else "ảnh"
                decision.reason = f"Gần trùng {noun} tốt hơn · giống {decision.similarity * 100:.1f}%"
                decision.suggested_delete = True

    # Keep a small, evenly distributed set of true negative frames. Empty
    # records that are already duplicates remain deletion candidates.
    negative_groups = list(video_groups.values())
    if imported_records:
        negative_groups.append(imported_records)
    for group_records in negative_groups:
        empty = [base[record.id] for record in group_records if base[record.id].category == "empty"]
        keep_count = round(len(empty) * max(0, min(settings.negative_keep_percent, 100)) / 100)
        keep_count = min(len(empty), max(1 if empty and settings.negative_keep_percent else 0, keep_count))
        keep_indices = set(np.linspace(0, len(empty) - 1, keep_count, dtype=int).tolist()) if keep_count else set()
        for index, decision in enumerate(empty):
            if index in keep_indices:
                decision.category = "negative_keep"
                decision.reason = "Giữ làm ảnh nền âm để giảm nhận nhầm băng tải"
            else:
                decision.suggested_delete = True

    # Never auto-delete work the user already invested in. It remains possible
    # to explicitly double-click that row to XÓA and confirm the bulk action.
    for record in candidates:
        decision = base[record.id]
        if decision.protected and decision.suggested_delete:
            decision.suggested_delete = False
            decision.reason += " · đang bảo vệ vì ảnh đã có nhãn/đã duyệt"

    return [base[record.id] for record in candidates]


def analyze_video_frames(
    project: Project,
    store: ProjectStore,
    settings: FrameFilterSettings | None = None,
    **kwargs,
) -> list[FrameDecision]:
    """Backward-compatible video-only entry point used by older code/tests."""

    kwargs.setdefault("records", video_frame_records(project))
    return analyze_smart_images(project, store, settings, **kwargs)
