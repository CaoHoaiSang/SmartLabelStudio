"""ORI dataset contract: normalized OBB corners plus a directed angle.

Angles use +X as zero and +Y (down in an image) as positive. Dataset angles
are expressed in normalized-image coordinates; the trainer transforms the
direction vector together with the OBB when restoring pixel coordinates.
"""
from __future__ import annotations

import math


def annotation_to_ori(ann, width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        raise ValueError("Kích thước ảnh ORI không hợp lệ.")
    if len(ann.obb) == 4:
        points = ann.obb
    elif not ann.obb and len(ann.bbox) == 4:
        x, y, w, h = ann.bbox
        points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    else:
        raise ValueError("ORI cần khung OBB bốn góc hoặc RECT hợp lệ.")
    try:
        points = [(float(p[0]), float(p[1])) for p in points if len(p) == 2]
    except (TypeError, ValueError, IndexError):
        raise ValueError("Tọa độ khung ORI không hợp lệ.") from None
    if len(points) != 4 or not all(math.isfinite(v) for p in points for v in p):
        raise ValueError("Tọa độ khung ORI không hợp lệ.")
    if any(x < -1e-4 or x > width + 1e-4 or y < -1e-4 or y > height + 1e-4 for x, y in points):
        raise ValueError("Khung ORI vượt biên ảnh; hãy chỉnh khung trước khi train.")
    edges = [(points[(i + 1) % 4][0] - p[0], points[(i + 1) % 4][1] - p[1]) for i, p in enumerate(points)]
    sizes = [math.hypot(*e) for e in edges]
    if min(sizes) < 1:
        raise ValueError("Khung ORI quá nhỏ hoặc có cạnh trùng nhau.")
    for i, e in enumerate(edges):
        other = edges[(i + 1) % 4]
        if abs(e[0] * other[0] + e[1] * other[1]) / (sizes[i] * sizes[(i + 1) % 4]) > 0.02:
            raise ValueError("Bốn góc ORI phải tạo thành hình chữ nhật theo thứ tự quanh khung.")
        opposite = edges[(i + 2) % 4]
        if math.hypot(e[0] + opposite[0], e[1] + opposite[1]) > max(0.5, sizes[i] * 0.01):
            raise ValueError("Khung ORI không phải hình chữ nhật.")
    if len(ann.orientation) != 2:
        raise ValueError("Nhãn thiếu hướng ORI; hãy đặt tâm và đầu hướng.")
    try:
        (ax, ay), (bx, by) = [(float(p[0]), float(p[1])) for p in ann.orientation if len(p) == 2]
    except (TypeError, ValueError, IndexError):
        raise ValueError("Hai điểm hướng ORI không hợp lệ.") from None
    if not all(math.isfinite(v) for v in (ax, ay, bx, by)):
        raise ValueError("Hai điểm hướng ORI không hữu hạn.")
    if not (0 <= ax <= width and 0 <= ay <= height and 0 <= bx <= width and 0 <= by <= height):
        raise ValueError("Hai điểm hướng ORI vượt biên ảnh.")
    cx, cy = sum(p[0] for p in points) / 4, sum(p[1] for p in points) / 4
    if math.hypot(ax - cx, ay - cy) > max(2, min(sizes) * 0.05):
        raise ValueError("Tâm mũi tên ORI lệch tâm khung; hãy đặt lại hướng.")
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1:
        raise ValueError("Tâm và đầu ORI quá gần nhau.")
    alignment = max(abs(dx * e[0] + dy * e[1]) / (length * size) for e, size in zip(edges, sizes))
    if alignment < math.cos(math.radians(3)):
        raise ValueError("ORI DeltaX cần hướng bám trục khung. Bật Bám trục và đặt lại hướng; góc tự do dùng Pose.")
    heading = (math.degrees(math.atan2(dy / height, dx / width)) + 180) % 360 - 180
    coords = " ".join(f"{x / width:.8f} {y / height:.8f}" for x, y in points)
    return f"{ann.class_id} {coords} {heading:.8f}"
