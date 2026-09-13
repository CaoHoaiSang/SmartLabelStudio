"""Read-only statistics for image attributes, independent of geometry labels."""
from collections import Counter

from .hydro_labels import model_attributes
from .label_schema import meaning_for


def attribute_summary(project, assignments):
    attrs = model_attributes(project)
    presence = next(a for a in attrs if a["role"] == "presence")
    rows = []
    for attr in attrs:
        reviewed, pending = Counter(), Counter()
        splits = {s: Counter() for s in ("train", "val", "test")}
        for record in project.images:
            if record.asset_role != "slot":
                continue
            meaning = meaning_for(attr, record.attributes.get(attr["id"])) or "missing"
            counter = reviewed if record.review_status == "reviewed" else pending
            counter[meaning] += 1
            eligible = (record.review_status == "reviewed" and meaning in {"positive", "negative"}
                        and (attr["role"] == "presence" or
                             meaning_for(presence, record.attributes.get(presence["id"])) == "positive"))
            if eligible:
                group = record.metadata.get("plant_instance_id") or record.capture_group or record.id
                splits[assignments.get(group, "train")][meaning] += 1
        rows.append({"id": attr["id"], "title": attr["displayName"],
                     "reviewed": dict(reviewed), "pending": dict(pending),
                     "splits": {k: dict(v) for k, v in splits.items()}})
    return rows


def overview_lines(rows):
    reviewed = sum(sum(n for k, n in row["reviewed"].items() if k != "missing") for row in rows)
    lines = [f"Giá trị thuộc tính đã duyệt: {reviewed}", "", "THUỘC TÍNH TRÊN ẢNH RỌ"]
    for row in rows:
        c = row["reviewed"]
        lines.extend([f"  {row['title']}",
                      f"    Đã duyệt: Có {c.get('positive', 0)} · Không {c.get('negative', 0)}"
                      f" · Chưa chắc {c.get('uncertain', 0)} · Không áp dụng {c.get('not_applicable', 0)}",
                      f"    Thiếu giá trị: {c.get('missing', 0)} · Ảnh chưa duyệt/bị loại: {sum(row['pending'].values())}"])
        parts = [f"{s.upper()} {row['splits'][s].get('positive', 0)}/{row['splits'][s].get('negative', 0)}"
                 for s in ("train", "val", "test")]
        lines.append("    Đủ nhãn xuất (Có/Không): " + " · ".join(parts))
        if any(row['splits']["test"].get(m, 0) == 0 for m in ("positive", "negative")):
            lines.append("    TEST còn thiếu một lớp; chưa đánh giá đầy đủ thuộc tính này.")
    lines.append("  Số liệu theo tập khóa, chỉ tính ảnh rọ đã duyệt; chưa chắc/không áp dụng không dùng train.")
    return lines
