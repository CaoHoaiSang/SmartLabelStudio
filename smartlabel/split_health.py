"""Cheap, read-only split diagnostics. Never change labels or supplement consent."""
from collections import defaultdict


class SplitConflictError(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        count = sum(len(ids) for ids in conflicts.values())
        lines = [f"{count} ảnh bổ trợ TRAIN có ảnh gốc thuộc {len(conflicts)} nhóm xung đột với VAL/TEST.",
                 "Ảnh gốc và biến thể không được nằm ở hai tập: model có thể học trước ảnh dùng để đánh giá."]
        lines += [f"• {key}: {len(ids)} ảnh bổ trợ" for key, ids in list(conflicts.items())[:8]]
        if len(conflicts) > 8:
            lines.append(f"… và {len(conflicts) - 8} nhóm khác.")
        lines += ["", "Cách xử lý: Dataset → Xem / chuyển nhóm → Chỉ nhóm xung đột → Đưa nhóm xung đột về TRAIN.",
                  "Nếu muốn giữ ảnh gốc ở VAL/TEST: vào GÁN NHÃN → Bổ trợ, tắt dùng train các biến thể liên quan.",
                  "Không cần xóa ảnh, làm lại nhãn hoặc phân lại toàn bộ. Sau khi sửa, bấm Train lại.",
                  "Đổi tập không làm TEST mới trở thành độc lập với model đã học ảnh đó trước đây."]
        super().__init__("\n".join(lines))


def supplement_parent_groups(project, data):
    """Protect all enabled synthetic rows; bad provenance fails closed."""
    groups = defaultdict(list)
    if project.metadata.get("template") != "Hydroponic Slot Condition" or data is None:
        return {}
    records = {r.id: r for r in project.images}
    for row in data["images"]:
        if row.get("enabled") is not True or row.get("kind") != "synthetic":
            continue
        provenance = row.get("provenance")
        parent = records.get(provenance.get("parentImageId")) if isinstance(provenance, dict) else None
        if parent is None:
            raise ValueError(f"Ảnh bổ trợ {row.get('id')}: thiếu ảnh gốc. "
                             "Vào GÁN NHÃN → Bổ trợ, kiểm tra nguồn hoặc tắt dùng train trước khi phân tập.")
        group = parent.metadata.get("plant_instance_id") or parent.capture_group or parent.id
        groups[group].append(row.get("id"))
    return dict(groups)


def split_conflicts(parents, assignments):
    return {group: ids for group, ids in parents.items() if assignments.get(group, "train") != "train"}


def require_compatible_supplements(project, data, assignments):
    conflicts = split_conflicts(supplement_parent_groups(project, data), assignments)
    if conflicts:
        raise SplitConflictError(conflicts)


def coverage_lines(project, assignments):
    """Eligible reviewed Hydro labels, not raw image counts or accuracy claims."""
    if project.metadata.get("template") != "Hydroponic Slot Condition":
        return []
    from .hydro_statistics import attribute_summary
    lines = ["Ảnh giàn đủ nhãn xuất — Có/Không (chưa cộng ảnh bổ trợ TRAIN):"]
    for row in attribute_summary(project, assignments):
        parts = [f"{s.upper()} {row['splits'][s].get('positive', 0)}/{row['splits'][s].get('negative', 0)}"
                 for s in ("train", "val", "test")]
        lines.append(f"{row['title']}: " + " · ".join(parts))
        missing = [s.upper() for s in ("train", "val", "test")
                   if any(row['splits'][s].get(m, 0) == 0 for m in ("positive", "negative"))]
        if missing:
            lines.append("  Thiếu Có hoặc Không ở " + ", ".join(missing)
                         + ": chọn nhóm có nhãn đã duyệt phù hợp hoặc bổ sung ảnh thật; không tự gán nhãn.")
    lines.append("70/15/15 là mục tiêu số ảnh, không bảo đảm đủ từng nhãn. TEST thiếu lớp không tự chặn train.")
    return lines


def classification_training_problem(metadata):
    """Check actual exported TRAIN, never pooled TRAIN+VAL+TEST counts."""
    counts = metadata.get("class_counts_by_split")
    if counts is None:  # Legacy snapshots retain their previous compatibility path.
        return "" if sum(bool(n) for n in metadata.get("counts", {}).values()) >= 2 else "Cần ít nhất hai nhãn có ảnh để train."
    title = metadata.get("attribute_title", metadata.get("attribute_key", "Classifier"))
    train = counts.get("train", {})
    meanings = {v["id"]: {"positive": "Có", "negative": "Không"}.get(v.get("meaning"), v["id"])
                for v in metadata.get("label_attribute", {}).get("values", [])}
    if sum(bool(n) for n in train.values()) < 2:
        return (f"{title}: TRAIN chưa đủ hai lớp có ảnh (" + ", ".join(f"{meanings.get(k, k)}: {v}" for k, v in train.items())
                + "). Ảnh nằm ở VAL/TEST không bù cho lớp thiếu trong TRAIN. "
                "Vào Dataset → Xem / chuyển nhóm để xem số Có/Không; chuyển cả nhóm có nhãn còn thiếu "
                "về TRAIN hoặc bổ sung và duyệt ảnh đúng nhãn. Không cần xóa ảnh hay chia lại ngẫu nhiên.")
    if metadata.get("split_strategy", "locked") == "locked" and not sum(counts.get("val", {}).values()):
        return (f"{title}: VAL không có ảnh đủ nhãn xuất. Vào Dataset → Xem / chuyển nhóm, "
                "chọn nhóm có ảnh đã duyệt cho VAL; hoặc chọn chiến lược Final không chạy validation "
                "nếu đó là chủ đích của bạn. Không tự dùng TEST thay VAL.")
    return ""
