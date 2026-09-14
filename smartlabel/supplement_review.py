"""Operator review of existing supplements; never imports parent captures."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .hydro_labels import model_attributes
from .label_schema import meaning_for
from .training_supplements import manifest_path, read_manifest, sha256, validate_manifest_samples, validate_review_labels


def review_state(row):
    if row.get("archived") is True:
        return "Đã lưu trữ"
    if row.get("reviewStatus") == "rejected":
        return "Từ chối"
    if row.get("reviewStatus") != "reviewed":
        return "Chờ duyệt"
    return "Đang dùng train" if row.get("enabled") is True else "Đã duyệt · tạm tắt"


def load_review(store, project):
    if project is None or project.metadata.get("template") != "Hydroponic Slot Condition":
        return None, None
    path = manifest_path(store, project)
    if not path.is_file():
        return None, None
    before = sha256(path)
    data = read_manifest(store, project)
    if sha256(path) != before:
        raise ValueError("Danh sách vừa thay đổi. Hãy tải lại ảnh bổ trợ.")
    ids = [r.get("id") for r in data["images"]]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Mã ảnh bổ trợ thiếu hoặc trùng; cần kiểm tra manifest.")
    return data, before


def preview_path(store, project, row):
    root = manifest_path(store, project).parent.resolve()
    path = (root / str(row.get("file", ""))).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path == manifest_path(store, project):
        raise ValueError("Không tìm thấy ảnh bổ trợ hợp lệ trong dự án.")
    if sha256(path) != row.get("sha256"):
        raise ValueError("Tệp ảnh đã thay đổi so với ảnh được ghi nhận; chưa thể duyệt.")
    return path


def save_review(store, project, assignments, row_id, decision, expected_revision,
                *, attributes=None, note="", save_draft_labels=False):
    """Atomic sidecar-only save with revision check and export validation on approval.

    An exclusive lock serializes cooperating Studio instances. A second hash
    check detects external edits made while verification is running.
    """
    if project is None or project.metadata.get("template") != "Hydroponic Slot Condition":
        raise ValueError("Duyệt ảnh bổ trợ chỉ áp dụng cho dự án Hydro.")
    if decision not in {"reviewed", "draft", "rejected", "archived"}:
        raise ValueError("Trạng thái duyệt không hợp lệ.")
    path = manifest_path(store, project)
    lock = path.with_suffix(".review.lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Một phiên SmartLabel khác đang lưu ảnh bổ trợ. Hãy thử lại sau.") from None
    temporary = None
    try:
        with handle:
            handle.write(str(os.getpid()))
        data, revision = load_review(store, project)
        if data is None or revision != expected_revision:
            raise ValueError("Danh sách đã thay đổi từ lần mở ảnh. Hãy tải lại trước khi duyệt.")
        row = next((r for r in data["images"] if r["id"] == row_id), None)
        if row is None:
            raise ValueError("Ảnh không còn trong danh sách bổ trợ.")
        previous = {key: deepcopy(row.get(key)) for key in
                    ("enabled", "archived", "reviewStatus", "attributes", "presenceMeaning", "reviewNote", "reviewedBy", "reviewedAt")}
        # Exclusion stays possible even for a damaged source. Only approval or
        # an explicit draft-save accepts form changes; other decisions keep labels.
        if attributes is not None and (decision == "reviewed" or (decision == "draft" and save_draft_labels)):
            row["attributes"] = deepcopy(attributes)
            presence = next(a for a in model_attributes(project) if a["role"] == "presence")
            if isinstance(attributes, dict) and presence["id"] in attributes:
                row["presenceMeaning"] = meaning_for(presence, attributes[presence["id"]])
            validate_review_labels(project, row)
        row.update(enabled=decision == "reviewed", archived=decision == "archived",
                   reviewStatus=row.get("reviewStatus", "draft") if decision == "archived" else decision,
                   reviewNote=note.strip() or {"reviewed": "Người dùng đã xem ảnh và xác nhận nhãn trong SmartLabel.",
                       "draft": "Chuyển về chờ duyệt trong SmartLabel.",
                       "rejected": "Người dùng loại khỏi train trong SmartLabel.",
                       "archived": "Lưu trữ khỏi danh sách làm việc và train; giữ ảnh cùng lịch sử."}[decision],
                   reviewedBy="SmartLabel operator", reviewedAt=datetime.now(timezone.utc).isoformat())
        if decision == "reviewed":
            validate_manifest_samples(store, project, model_attributes(project)[0], assignments, data)
        history = row.setdefault("reviewHistory", [])
        if not isinstance(history, list):
            raise ValueError("Lịch sử duyệt không hợp lệ; chưa lưu thay đổi.")
        history.append({"at": row["reviewedAt"], "by": row["reviewedBy"], "decision": decision, "previous": previous})
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".review-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(path) != revision:
            raise ValueError("Danh sách vừa được cập nhật bên ngoài. Hãy tải lại; thay đổi này chưa được lưu.")
        os.replace(temporary, path)
        return data, hashlib.sha256(raw).hexdigest()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
