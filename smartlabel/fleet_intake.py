"""Fleet custody adapter. Staging is deliberately NOT a labeled dataset source."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import re
from urllib.parse import urlencode

PROJECT = re.compile(r"project_[a-zA-Z0-9_-]{1,80}\Z")
UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


class FleetIntakeError(ValueError):
    pass


def reject_generic_fleet_sources(files) -> None:
    """Do not launder managed Fleet photos through the legacy untracked importer."""
    checked = set()
    for source in files:
        for candidate in (Path(source).absolute(), Path(source).resolve()):
            for parent in (candidate, *candidate.parents):
                if parent in checked:
                    continue
                checked.add(parent)
                if parent.name.casefold() == "fleet_inbox" or (parent / ".fleet-storage-v1.json").exists():
                    raise FleetIntakeError("Ảnh thuộc kho/vùng chờ Fleet không được nhập như ảnh thường. Hãy dùng luồng Fleet có quản lý quyền và nguồn gốc.")


def fleet_inbox_url(project_id: str) -> str:
    if not PROJECT.fullmatch(project_id):
        raise FleetIntakeError("Mã project không hợp lệ.")
    return "https://hydro-fleet-thesis.vercel.app/company/contributions.html?" + urlencode({"smartLabelProject": project_id})


def _project_root(project_root: Path, project_id: str) -> Path:
    root = Path(project_root).absolute()
    if not PROJECT.fullmatch(project_id) or root.name != project_id or root.parent.name != "projects":
        raise FleetIntakeError("Hãy chọn project trong workspace SmartLabel.")
    for item in (root, *root.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise FleetIntakeError("Không nhập qua đường dẫn liên kết.")
    value = _read_json(root / "project.json", 64 * 1024 * 1024)
    if value.get("id") != project_id or value.get("metadata", {}).get("template") != "Hydroponic Slot Condition":
        raise FleetIntakeError("Chỉ nhận vào project Hydroponic Slot Condition đã lưu.")
    return root.resolve()


def _read_json(file: Path, maximum: int = 512 * 1024) -> dict:
    if file.is_symlink() or not file.is_file() or file.stat().st_size > maximum:
        raise FleetIntakeError("Tệp vùng chờ không hợp lệ.")
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FleetIntakeError("Tệp vùng chờ không hợp lệ.")
    return value


def receive(project_root: Path, project_id: str, code: str, *, port: int = 17864) -> dict:
    """Fixed loopback host, no redirects, no credentials/config copied to SmartLabel."""
    root = _project_root(project_root, project_id)
    match = re.fullmatch(r"FleetImportV1\.([A-Za-z0-9_-]{43})", code.strip())
    if not match:
        raise FleetIntakeError("Mã nhập không hợp lệ. Hãy lấy mã Nhận vào vùng chờ SmartLabel trên Fleet.")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
    try:
        connection.request("POST", "/smartlabel/import", json.dumps({"ticket": match[1], "projectId": project_id, "projectRoot": str(root)}),
                           {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}", "X-Fleet-Client": "SmartLabel"})
        response = connection.getresponse()
        payload = response.read(512 * 1024 + 1)
        if response.status == 409:
            raise FleetIntakeError("Bộ nhận đang xử lý lượt khác. Đợi một chút rồi thử lại bằng cùng mã còn hạn.")
        if response.status != 200 or len(payload) > 512 * 1024:
            raise FleetIntakeError("Chưa xác nhận nhập xong. Kiểm tra project, hạn mã, quyền nhân viên và trạng thái rút dữ liệu trên Fleet; có thể thử lại an toàn.")
        result = json.loads(payload)
        if (not isinstance(result, dict) or result.get("ok") is not True or result.get("projectId") != project_id
                or result.get("stage") != "review_pending" or result.get("trainAllowed") is not False
                or not UUID.fullmatch(str(result.get("contributionId", ""))) or not HASH.fullmatch(str(result.get("importId", "")))):
            raise FleetIntakeError("Kết quả nhập không khớp project. Không xác nhận thành công.")
        staged = next((row for row in list_staged(root, project_id) if row["importId"] == result["importId"]), None)
        if staged is None:
            raise FleetIntakeError("Ảnh chưa có bản kê hợp lệ tại project hoặc đã được rút. Kiểm tra lại trên Fleet.")
        return result
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        raise FleetIntakeError("Không xác nhận được với bộ nhận Windows. Mở bộ nhận và kiểm tra kết nối Fleet; thử lại không tạo thêm bản sao.") from None
    finally:
        connection.close()


def list_staged(project_root: Path, project_id: str) -> list[dict]:
    """Metadata only; never exposes pixels or authorizes training from stale/offline state."""
    root = _project_root(project_root, project_id)
    inbox = root / "fleet_inbox"
    if not inbox.exists():
        return []
    if inbox.is_symlink() or (hasattr(inbox, "is_junction") and inbox.is_junction()):
        raise FleetIntakeError("Vùng chờ không được là đường dẫn liên kết.")
    rows = []
    for folder in sorted(inbox.iterdir()):
        if not UUID.fullmatch(folder.name):
            continue
        if folder.is_symlink() or (hasattr(folder, "is_junction") and folder.is_junction()):
            raise FleetIntakeError("Vùng chờ có đường dẫn liên kết.")
        if not folder.is_dir() or (folder / "withdrawn.json").exists() or not (folder / "manifest.json").exists():
            continue
        value = _read_json(folder / "manifest.json")
        if (value.get("schemaVersion") != "FleetProjectImportV1" or value.get("projectId") != project_id
                or value.get("contributionId") != folder.name or value.get("trainAllowed") is not False
                or value.get("stage") != "review_pending" or not HASH.fullmatch(str(value.get("importId", "")))
                or _read_json(folder / "custody.json").get("importId") != value["importId"]):
            raise FleetIntakeError("Bản kê vùng chờ không khớp project.")
        rows.append({"contributionId": folder.name, "importId": value["importId"], "fileCount": len(value.get("files", [])),
                     "source": value.get("contribution", {}).get("source"), "stage": "review_pending"})
    return rows
