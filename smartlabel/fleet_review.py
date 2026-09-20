"""Managed Fleet label sidecars. No implicit dataset admission or local-only consent."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import time
import uuid

from .fleet_intake import FleetIntakeError, HASH, UUID, _project_root, _read_json
from .hydro_labels import model_attributes
from .label_schema import meaning_for
from .training_supplements import validate_review_labels


class FleetReviewSession:
    """Short staff grant held only in RAM; a local path never grants permission."""
    def __init__(self, root, project_id, code, *, port=17864):
        self.root = _project_root(root, project_id)
        self.project_id, self.port = project_id, port
        match = re.fullmatch(r"FleetImportV1\.([A-Za-z0-9_-]{43})", code.strip())
        if not match:
            raise FleetIntakeError("Lấy mã đúng project trên Fleet rồi dán lại.")
        self._ticket = match[1]
        self.deadline = 0
        self.data = self.revision = None

    def close(self):
        self._ticket = ""
        self.deadline = 0
        self.data = None

    def refresh(self, mutation=None):
        if not self._ticket:
            raise FleetIntakeError("Phiên gán nhãn đã đóng. Lấy mã mới trên Fleet.")
        body = {"ticket": self._ticket, "projectId": self.project_id, "projectRoot": str(self.root)}
        if mutation is not None:
            body["mutation"] = mutation
        started = time.monotonic()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=45)
        try:
            connection.request("POST", "/smartlabel/review", json.dumps(body),
                               {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}", "X-Fleet-Client": "SmartLabel"})
            response = connection.getresponse()
            raw = response.read(512 * 1024 + 1)
            if response.status != 200 or len(raw) > 512 * 1024:
                raise FleetIntakeError("Chưa xác nhận quyền hoặc lưu nhãn. Bộ nhận có thể đang bận, mã hết hạn, nhãn vừa đổi hoặc ảnh đã được rút; hãy tải lại/lấy mã mới.")
            result = json.loads(raw)
            data = result.get("data", {})
            if (result.get("ok") is not True or data.get("schemaVersion") != "FleetLabelReviewV1"
                    or data.get("projectId") != self.project_id or data.get("trainAllowed") is not False
                    or not UUID.fullmatch(str(data.get("contributionId", "")))
                    or not HASH.fullmatch(str(data.get("importId", "")))
                    or not HASH.fullmatch(str(result.get("revision", "")))
                    or not isinstance(data.get("images"), list) or len(data["images"]) > 50):
                raise FleetIntakeError("Kết quả không khớp project/contract; chưa mở ảnh.")
            remaining = (datetime.fromisoformat(result["expiresAt"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
            # Maximum 30 s local display lease. Refresh cannot extend the five-minute staff grant.
            deadline = min(started + 30, time.monotonic() + remaining)
            if deadline <= time.monotonic():
                raise FleetIntakeError("Mã đã hết hạn. Lấy mã mới trên Fleet.")
            self.data, self.revision, self.deadline = data, result["revision"], deadline
            return deepcopy(data), self.revision
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
            self.deadline = 0
            if isinstance(exc, FleetIntakeError):
                raise
            raise FleetIntakeError("Không xác minh được quyền Fleet; ảnh bị khóa, nhãn cũ được giữ nguyên.") from None
        finally:
            connection.close()

    def preview_path(self, row):
        if self.data is None or self.deadline <= time.monotonic():
            raise FleetIntakeError("Cần kiểm tra lại quyền trước khi xem ảnh.")
        root = _project_root(self.root, self.project_id)
        folder = root / "fleet_inbox" / self.data["contributionId"]
        for item in (folder.parent, folder):
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise FleetIntakeError("Không mở ảnh qua liên kết.")
        if (folder / "withdrawn.json").exists():
            raise FleetIntakeError("Đợt ảnh đã được rút.")
        if _read_json(folder / "custody.json").get("importId") != self.data["importId"]:
            raise FleetIntakeError("Nguồn ảnh không khớp.")
        if not re.fullmatch(r"[a-f0-9-]{36}\.(png|jpg)", str(row.get("file", ""))) or row not in self.data["images"]:
            raise FleetIntakeError("Ảnh không thuộc đợt đã xác minh.")
        file = folder / row["file"]
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 10 * 1024 * 1024:
            raise FleetIntakeError("Tệp ảnh không hợp lệ.")
        if hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
            raise FleetIntakeError("Ảnh đã thay đổi, chưa thể gán nhãn.")
        return file

    def save(self, project, identifier, decision, revision, *, attributes, other_abnormal="", **_kwargs):
        if project.id != self.project_id or not self.data:
            raise FleetIntakeError("Project đã thay đổi.")
        if decision not in {"draft", "reviewed", "rejected"}:
            raise FleetIntakeError("Dùng Từ chối để bỏ ảnh; yêu cầu xóa đợt được quản lý trên Fleet.")
        attrs = model_attributes(project)
        known = {a["id"]: {v["id"] for v in a["values"]} for a in attrs}
        if any(key not in known or value not in known[key] for key, value in attributes.items()):
            raise FleetIntakeError("Nhãn không khớp schema project.")
        if decision == "reviewed":
            presence = next(a for a in attrs if a["role"] == "presence")
            row = {"attributes": attributes, "presenceMeaning": meaning_for(presence, attributes.get(presence["id"]))}
            if not validate_review_labels(project, row):
                raise FleetIntakeError("Cần nhãn rõ ràng trước khi duyệt; chưa chắc chắn không phải nhãn train.")
        return self.refresh({"id": identifier, "revision": revision, "operationId": str(uuid.uuid4()),
                             "attributes": attributes, "reviewStatus": decision, "otherAbnormal": other_abnormal or ""})
