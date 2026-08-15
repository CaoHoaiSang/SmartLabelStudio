from __future__ import annotations

from dataclasses import dataclass

from .models import Project


@dataclass
class QualityIssue:
    image_id: str
    annotation_id: str
    severity: str
    message: str


def inspect_project(project: Project) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    valid_classes = {item.id for item in project.classes}
    for image in project.images:
        if image.review_status == "reviewed" and not image.annotations:
            issues.append(QualityIssue(image.id, "", "warning", "Ảnh đã duyệt nhưng không có nhãn"))
        for ann in image.annotations:
            if ann.class_id not in valid_classes:
                issues.append(QualityIssue(image.id, ann.id, "error", "Class ID không tồn tại"))
            if len(ann.bbox) != 4:
                issues.append(QualityIssue(image.id, ann.id, "error", "Bounding box không hợp lệ"))
                continue
            x, y, w, h = ann.bbox
            if w <= 1 or h <= 1:
                issues.append(QualityIssue(image.id, ann.id, "error", "Nhãn quá nhỏ hoặc rỗng"))
            if x < 0 or y < 0 or x + w > image.width + 1 or y + h > image.height + 1:
                issues.append(QualityIssue(image.id, ann.id, "error", "Nhãn nằm ngoài ảnh"))
            if ann.kind == "polygon" and len(ann.points) < 3:
                issues.append(QualityIssue(image.id, ann.id, "error", "Polygon có ít hơn ba điểm"))
            if ann.obb and len(ann.obb) != 4:
                issues.append(QualityIssue(image.id, ann.id, "error", "OBB phải có đúng bốn góc"))
            if ann.orientation and len(ann.orientation) != 2:
                issues.append(QualityIssue(image.id, ann.id, "error", "ORI phải có tâm và điểm chỉ hướng"))
            for geometry_name, points in (("SEG", ann.points), ("OBB", ann.obb), ("ORI", ann.orientation)):
                if any(px < 0 or py < 0 or px > image.width or py > image.height for px, py in points):
                    issues.append(QualityIssue(image.id, ann.id, "error", f"Điểm {geometry_name} nằm ngoài ảnh"))
            if ann.source != "manual" and ann.confidence is None:
                issues.append(QualityIssue(image.id, ann.id, "info", "Nhãn AI thiếu confidence"))
    return issues
