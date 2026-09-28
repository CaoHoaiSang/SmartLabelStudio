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
from .attribute_defaults import configured_image_defaults, fill_missing_image_defaults
from .training_supplements import manifest_path, read_manifest, review_attributes, sha256, validate_manifest_samples, validate_review_labels


def _replace_manifest(path, data, revision):
    """Caller holds the sidecar lock; preserve an external edit detected by CAS."""
    temporary = None
    try:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".review-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(path) != revision:
            raise ValueError("Danh sách vừa được cập nhật bên ngoài. Hãy tải lại; thay đổi này chưa được lưu.")
        os.replace(temporary, path)
        return hashlib.sha256(raw).hexdigest()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def materialize_confirmed_presence(store, project, assignments, expected_revision):
    """Explicit repair of reviewed legacy evidence; no inference from pixels/parent.

    Archived rows and explicit presence labels remain unchanged. Review status,
    enablement and other labels are preserved; each repaired row records history.
    """
    if project.metadata.get("template") != "Hydroponic Slot Condition":
        raise ValueError("Chỉ áp dụng cho dự án Hydro.")
    path = manifest_path(store, project)
    lock = path.with_suffix(".review.lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Một phiên SmartLabel khác đang lưu ảnh bổ trợ.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        data, revision = load_review(store, project)
        if data is None or revision != expected_revision:
            raise ValueError("Danh sách đã thay đổi; chưa đồng bộ hiện diện.")
        changed = []
        for row in data["images"]:
            if row.get("archived") or row.get("reviewStatus") != "reviewed":
                continue
            normalized = review_attributes(project, row)
            if normalized == row.get("attributes", {}):
                continue
            previous = deepcopy(row["attributes"])
            row["attributes"] = normalized
            validate_review_labels(project, row)
            history = row.setdefault("reviewHistory", [])
            if not isinstance(history, list):
                raise ValueError("Lịch sử duyệt không hợp lệ; chưa lưu thay đổi.")
            history.append({"at": datetime.now(timezone.utc).isoformat(), "decision": "materialize_confirmed_presence",
                            "by": "SmartLabel compatibility repair", "previousAttributes": previous,
                            "reason": "Chuyển xác nhận presenceMeaning cũ thành nhãn hiện diện theo schema."})
            changed.append(row["id"])
        if changed:
            validate_manifest_samples(store, project, model_attributes(project)[0], assignments, data)
            revision = _replace_manifest(path, data, revision)
        return data, revision, changed
    finally:
        lock.unlink(missing_ok=True)


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


def delete_supplement(store, project, row_id, expected_revision):
    """Permanently remove one supplement record and its project-owned file.

    Rejection remains the reversible way to exclude an image from training.
    This operation is deliberately destructive and uses the same sidecar lock
    and revision check as label saves. The image is first moved to a temporary
    file in the same directory so a failed manifest write can restore it.
    """
    if project is None or project.metadata.get("template") != "Hydroponic Slot Condition":
        raise ValueError("Xóa ảnh bổ trợ chỉ áp dụng cho dự án Hydro.")
    path = manifest_path(store, project)
    lock = path.with_suffix(".review.lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Một phiên SmartLabel khác đang cập nhật ảnh bổ trợ. Hãy thử lại sau.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        data, revision = load_review(store, project)
        if data is None or revision != expected_revision:
            raise ValueError("Danh sách đã thay đổi từ lần mở ảnh. Hãy tải lại trước khi xóa.")
        row = next((item for item in data["images"] if item.get("id") == row_id), None)
        if row is None:
            raise ValueError("Ảnh bổ trợ không còn trong danh sách.")

        root = path.parent.resolve()
        manifest = path.resolve()
        warning = None
        quarantine = None
        source = None

        def safe_source(item):
            try:
                candidate = (root / str(item.get("file", ""))).resolve()
                return candidate if candidate.is_relative_to(root) and candidate != manifest else None
            except (OSError, RuntimeError, ValueError):
                return None

        source = safe_source(row)
        if source is None:
            warning = "Bản ghi có đường dẫn không an toàn; SmartLabel chỉ xóa metadata và không chạm tệp bên ngoài dự án."

        remaining = [item for item in data["images"] if item is not row]
        shared = bool(source and any(safe_source(item) == source for item in remaining))
        if source and source.is_file() and not shared:
            with tempfile.NamedTemporaryFile(dir=root, prefix=".delete-", suffix=".tmp", delete=False) as stream:
                quarantine = Path(stream.name)
            quarantine.unlink(missing_ok=True)
            os.replace(source, quarantine)

        data["images"] = remaining
        try:
            new_revision = _replace_manifest(path, data, revision)
        except Exception:
            if quarantine is not None and quarantine.exists() and source is not None:
                os.replace(quarantine, source)
            raise

        if quarantine is not None:
            try:
                quarantine.unlink(missing_ok=True)
            except OSError:
                warning = f"Đã xóa bản ghi nhưng còn tệp tạm cần dọn thủ công: {quarantine.name}"
        return data, new_revision, warning
    finally:
        lock.unlink(missing_ok=True)


def form_attributes(project, row):
    """UI defaults are pending labels, never implicit training evidence."""
    return fill_missing_image_defaults(project, review_attributes(project, row),
                                       suppressed=row.get("defaultSuppressedAttributes", ()))


def materialize_missing_defaults(store, project, expected_revision):
    """Explicitly fill missing configured defaults and require another review."""
    if project is None or project.metadata.get("template") != "Hydroponic Slot Condition":
        raise ValueError("Chỉ áp dụng cho dự án Hydro.")
    path = manifest_path(store, project)
    lock = path.with_suffix(".review.lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Một phiên SmartLabel khác đang lưu ảnh bổ trợ.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        data, revision = load_review(store, project)
        if data is None or revision != expected_revision:
            raise ValueError("Danh sách đã thay đổi; chưa bổ sung mặc định.")
        changed = []
        for row in data["images"]:
            if row.get("archived") or row.get("reviewStatus") == "rejected":
                continue
            values = form_attributes(project, row)
            if values == review_attributes(project, row):
                continue
            previous = {key: deepcopy(row.get(key)) for key in
                        ("attributes", "presenceMeaning", "reviewStatus", "enabled")}
            row.update(attributes=values, reviewStatus="draft", enabled=False)
            presence = next(a for a in model_attributes(project) if a['role'] == 'presence')
            row['presenceMeaning'] = meaning_for(presence, values.get(presence['id']))
            validate_review_labels(project, row)
            history = row.setdefault("reviewHistory", [])
            if not isinstance(history, list):
                raise ValueError("Lịch sử duyệt không hợp lệ; chưa lưu thay đổi.")
            history.append({"at": datetime.now(timezone.utc).isoformat(), "decision": "fill_missing_defaults",
                            "by": "SmartLabel configured defaults", "previous": previous,
                            "reason": "Bổ sung giá trị mặc định còn thiếu; cần duyệt lại trước khi train."})
            changed.append(row['id'])
        if changed:
            revision = _replace_manifest(path, data, revision)
        return data, revision, changed
    finally:
        lock.unlink(missing_ok=True)


def preview_path(store, project, row, *, cache=None):
    root = manifest_path(store, project).parent.resolve()
    path = (root / str(row.get("file", ""))).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path == manifest_path(store, project):
        raise ValueError("Không tìm thấy ảnh bổ trợ hợp lệ trong dự án.")
    stat = path.stat()
    signature = (row.get("sha256"), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    # Only preview may cache. Approval/export still hash original files fully.
    if cache is not None and cache.get(path) == signature:
        return path
    if sha256(path) != row.get("sha256"):
        raise ValueError("Tệp ảnh đã thay đổi so với ảnh được ghi nhận; chưa thể duyệt.")
    if cache is not None:
        if len(cache) >= 150:
            cache.pop(next(iter(cache)))
        cache[path] = signature
    return path


def save_review(store, project, assignments, row_id, decision, expected_revision,
                *, attributes=None, note="", save_draft_labels=False, other_abnormal=None, pixel_cache=None):
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
                    ("enabled", "archived", "reviewStatus", "attributes", "presenceMeaning", "reviewNote", "reviewedBy", "reviewedAt", "otherAbnormal", "defaultSuppressedAttributes")}
        # Exclusion stays possible even for a damaged source. Only approval or
        # an explicit draft-save accepts form changes; other decisions keep labels.
        if attributes is not None and (decision == "reviewed" or (decision == "draft" and save_draft_labels)):
            row["attributes"] = deepcopy(attributes)
            presence = next(a for a in model_attributes(project) if a["role"] == "presence")
            row["presenceMeaning"] = meaning_for(presence, attributes.get(presence["id"])) if isinstance(attributes, dict) else None
            validate_review_labels(project, row)
            # A deliberate clear must survive reload even when a default exists.
            row["defaultSuppressedAttributes"] = sorted(
                key for key in configured_image_defaults(project) if not attributes.get(key))
            if other_abnormal is not None:
                row["otherAbnormal"] = str(other_abnormal).strip()
        row.update(enabled=decision == "reviewed", archived=decision == "archived",
                   reviewStatus=row.get("reviewStatus", "draft") if decision == "archived" else decision,
                   reviewNote=note.strip() or {"reviewed": "Người dùng đã xem ảnh và xác nhận nhãn trong SmartLabel.",
                       "draft": "Chuyển về chờ duyệt trong SmartLabel.",
                       "rejected": "Người dùng loại khỏi train trong SmartLabel.",
                       "archived": "Lưu trữ khỏi danh sách làm việc và train; giữ ảnh cùng lịch sử."}[decision],
                   reviewedBy="SmartLabel operator", reviewedAt=datetime.now(timezone.utc).isoformat())
        if decision == "reviewed":
            validate_manifest_samples(store, project, model_attributes(project)[0], assignments, data,
                                      **({"pixel_cache": pixel_cache} if pixel_cache is not None else {}))
        history = row.setdefault("reviewHistory", [])
        if not isinstance(history, list):
            raise ValueError("Lịch sử duyệt không hợp lệ; chưa lưu thay đổi.")
        history.append({"at": row["reviewedAt"], "by": row["reviewedBy"], "decision": decision, "previous": previous})
        return data, _replace_manifest(path, data, revision)
    finally:
        lock.unlink(missing_ok=True)
