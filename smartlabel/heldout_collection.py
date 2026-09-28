"""Local, TEST-only acquisition sidecar. Never inserts records into project.images."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import shutil
import uuid

from PIL import Image

from .benchmark_contract import canonical, digest, image_identity, inside, read_json
from .hydro_labels import model_attributes
from .label_schema import meaning_for, training_identity

COLLECTION_SCHEMA = "HydroHeldoutCollectionV1"
BENCHMARK_SCHEMA = "HydroHeldoutBenchmarkV1"
MARKER = "heldout_collection.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def root_for(store, project):
    root = store.project_dir(project) / "heldout"
    if root.resolve() != root.absolute():
        raise ValueError("Kho TEST không được là liên kết.")
    return root


def schema_identity(project):
    return [training_identity(a) for a in model_attributes(project)]


def load_collection(store, project):
    root = root_for(store, project)
    path = inside(root, MARKER)
    if not path.exists():
        return {"schemaVersion": COLLECTION_SCHEMA, "projectId": project.id,
                "cropCode": project.metadata.get("cropCode"), "attributes": schema_identity(project),
                "lots": [], "captures": [], "images": []}, None
    data = read_json(path)
    if (data.get("schemaVersion") != COLLECTION_SCHEMA or data.get("projectId") != project.id
            or data.get("cropCode") != project.metadata.get("cropCode")
            or canonical(data.get("attributes")) != canonical(schema_identity(project))):
        raise ValueError("Kho TEST không khớp project/cây trồng/schema nhãn; không ghi đè.")
    return data, digest(data)


@contextmanager
def collection_lock(root):
    """OS releases the lock after a crash; never delete another writer's lock file."""
    root.mkdir(parents=True, exist_ok=True)
    path = inside(root, ".heldout.lock")
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Một phiên khác đang ghi kho TEST; hãy thử lại.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save_collection(root, data):
    path = inside(root, MARKER)
    encoded = canonical(data)
    if len(encoded.encode("utf-8")) > 16 * 1024 * 1024:
        raise ValueError("Bản kê TEST đạt giới hạn 16 MiB; giữ nguyên dữ liệu cũ.")
    with TemporaryDirectory(prefix=".write-", dir=root) as temp:
        stage = Path(temp) / MARKER
        with stage.open("x", encoding="utf-8") as out:
            out.write(encoded); out.flush(); os.fsync(out.fileno())
        stage.replace(path)
    return digest(data)


def create_lot(store, project, name, sowing_date, count=16, *, reserved=False,
               same_sowing_batch=True, origin="Thùng xốp"):
    if reserved is not True:
        raise ValueError("Cần xác nhận toàn bộ cây của lô chưa dùng để phát triển model và chỉ dành cho TEST.")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError("Tên lô cần 1–120 ký tự.")
    if date.fromisoformat(sowing_date) > date.today():
        raise ValueError("Ngày gieo không được ở tương lai.")
    if type(count) is not int or not 1 <= count <= 1000 or type(same_sowing_batch) is not bool:
        raise ValueError("Số cây hoặc quan hệ đợt gieo không hợp lệ.")
    if not isinstance(origin, str) or not 1 <= len(origin.strip()) <= 200:
        raise ValueError("Ghi nơi nuôi cây thực tế.")
    root = root_for(store, project)
    with collection_lock(root):
        data, _ = load_collection(store, project)
        lot = {"lotId": "lot_" + uuid.uuid4().hex, "name": name.strip(), "sowingDate": sowing_date,
               "declaredPlantCount": count, "origin": origin.strip(), "reservedForTest": True,
               "sameSowingBatchAsDevelopment": same_sowing_batch, "createdAt": now(),
               "independenceBasis": "operator_attested_reserved_cohort", "plantTracking": "optional"}
        data["lots"].append(lot)
        save_collection(root, data)
    return lot["lotId"]


def preview_path(store, project, row, **_kwargs):
    path = inside(root_for(store, project), row["file"])
    if any(row.get(k) != v for k, v in image_identity(path).items()):
        raise ValueError("Ảnh TEST đã thay đổi; không mở để duyệt.")
    return path


def labels_for(project, attributes, *, final=False):
    attrs = model_attributes(project)
    if not isinstance(attributes, dict) or set(attributes) - {a["id"] for a in attrs}:
        raise ValueError("Nhãn không thuộc schema của project.")
    result = {a["id"]: meaning_for(a, attributes.get(a["id"])) for a in attrs}
    presence = next(a for a in attrs if a["role"] == "presence")
    for attr in attrs:
        value = result[attr["id"]]
        allowed = {"positive", "negative", "uncertain", "not_applicable", None}
        if final:
            allowed = ({"not_applicable"} if attr["role"] == "condition"
                       and result[presence["id"]] == "negative" else {"positive", "negative"})
        if value not in allowed or (attr["id"] in attributes and value is None):
            raise ValueError("Duyệt TEST cần nhãn Có/Không rõ ràng; không có cây thì dấu hiệu là Không áp dụng.")
    return result


def save_review(store, project, assignments, row_id, decision, expected_revision, *,
                attributes=None, save_draft_labels=False, other_abnormal=None, **_kwargs):
    if decision not in {"draft", "reviewed", "rejected"}:
        raise ValueError("Trạng thái duyệt không hợp lệ.")
    root = root_for(store, project)
    with collection_lock(root):
        data, revision = load_collection(store, project)
        if revision != expected_revision:
            raise ValueError("Kho TEST đã thay đổi; tải lại trước khi lưu nhãn.")
        row = next((r for r in data["images"] if r["id"] == row_id), None)
        if row is None:
            raise ValueError("Ảnh TEST không còn trong kho.")
        previous = {k: deepcopy(row.get(k)) for k in ("attributes", "reviewStatus", "otherAbnormal")}
        if attributes is not None and (decision == "reviewed" or save_draft_labels):
            labels_for(project, attributes, final=decision == "reviewed")
            row["attributes"] = deepcopy(attributes)
            row["otherAbnormal"] = str(other_abnormal or "")[:1000]
        if decision == "reviewed":
            labels_for(project, row["attributes"], final=True)
            preview_path(store, project, row)
        row.update(reviewStatus=decision, reviewedAt=now(), reviewedBy="SmartLabel operator")
        row.setdefault("reviewHistory", []).append({"at": row["reviewedAt"], "decision": decision,
                                                  "previous": previous})
        return data, save_collection(root, data)


def save_capture(store, project, lot_id, payload, *, empty_slots=(), plant_ids=None, session_name="",
                 expected_revision=None):
    """Publish a previewed frame and ALL ROIs, including empty pots. No automatic labels."""
    payload = Path(payload).absolute()
    meta = read_json(inside(payload, "capture.json"))
    if meta.get("schemaVersion") != "HydroHeldoutFrameV1":
        raise ValueError("Kết quả chụp không đúng hợp đồng.")
    slots = meta.get("slots", [])
    keys = [r.get("slotId") for r in slots]
    if (len(keys) != 10 or len(set(keys)) != 10 or not set(empty_slots).issubset(keys)
            or any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", k) for k in keys)):
        raise ValueError("Phiên này cần đúng 10 ROI; vị trí rọ trống phải thuộc bố cục.")
    full_path = inside(payload, meta["fullFrame"]["path"])
    with Image.open(full_path) as opened:
        if opened.size != (1920, 1080):
            raise ValueError("Ảnh toàn giàn không đúng kích thước cấu hình.")
        full_pixels = opened.convert("RGB")
    geometry = meta.get("geometryProfile", {})
    rectangles = {s["slotId"]: s["rect"] for s in geometry.get("slots", [])}
    if (set(rectangles) != set(keys) or not meta.get("cameraProfile", {}).get("profileId")
            or not geometry.get("profileId") or meta.get("modelInvoked") is not False):
        raise ValueError("Thiếu cấu hình/nguồn thu ảnh TEST; không dùng kết quả AI làm nhãn.")
    for slot in slots:
        rect = slot["rect"]
        if rect != rectangles[slot["slotId"]] or any(type(rect.get(k)) is not int for k in ("x", "y", "width", "height")):
            raise ValueError("ROI không khớp bản cấu hình đã chụp.")
        x, y, w, h = (rect[k] for k in ("x", "y", "width", "height"))
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1920 or y+h > 1080:
            raise ValueError("ROI nằm ngoài ảnh gốc.")
        with Image.open(inside(payload, slot["path"])) as cropped:
            if cropped.size != (w, h) or cropped.convert("RGB").tobytes() != full_pixels.crop((x, y, x+w, y+h)).tobytes():
                raise ValueError("Ảnh rọ không khớp vùng cắt của ảnh gốc.")
    plant_ids = {k: str(v).strip() for k, v in (plant_ids or {}).items() if str(v).strip()}
    if (not set(plant_ids).issubset(keys) or set(plant_ids) & set(empty_slots)
            or len(set(plant_ids.values())) != len(plant_ids)
            or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", p) for p in plant_ids.values())):
        raise ValueError("Mã cây tùy chọn phải khác nhau, không gán cho rọ trống.")
    root = root_for(store, project)
    with collection_lock(root):
        data, revision = load_collection(store, project)
        lot = next((r for r in data["lots"] if r["lotId"] == lot_id), None)
        if not lot:
            raise ValueError("Không tìm thấy lô TEST của project này.")
        capture_id = meta["captureId"]
        if not re.fullmatch(r"capture_[a-f0-9]{32}", capture_id):
            raise ValueError("Mã phiên chụp không hợp lệ.")
        existing = next((r for r in data["captures"] if r["captureId"] == capture_id), None)
        selection = {"emptySlots": sorted(empty_slots), "plantIds": plant_ids, "lotId": lot_id}
        if existing:
            if existing.get("selection") != selection or existing["frameDigest"] != digest(meta):
                raise ValueError("Phiên đã lưu với nội dung khác; không ghi đè.")
            for item in [meta["fullFrame"], *slots]:
                saved = inside(root, f"captures/{capture_id}/{item['path']}")
                if any(item.get(k) != v for k, v in image_identity(saved).items()):
                    raise ValueError("Bản ảnh đã lưu bị thay đổi; không báo lưu thành công.")
            return data, revision
        if expected_revision is not None and expected_revision != revision:
            raise ValueError("Kho TEST đã thay đổi sau xem trước; tải lại trước khi lưu.")
        total_bytes = sum(r.get("storedBytes", 0) for r in data["captures"])
        added_bytes = sum(r["bytes"] for r in [meta["fullFrame"], *slots])
        if (len(data["images"]) + 10 > 5000 or total_bytes + added_bytes > 2 * 1024**3
                or shutil.disk_usage(root).free < added_bytes + 100 * 1024**2):
            raise ValueError("Kho TEST đạt giới hạn pilot (5000 ảnh rọ/2 GiB).")
        destination = inside(root, "captures/" + capture_id)
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            raise ValueError("Có phiên lưu dở cùng mã; giữ nguyên để phục hồi, hãy chụp lại.")
        known = {c["captureId"] for c in data["captures"]}
        if any(p.name not in known for p in destination.parent.iterdir()):
            raise ValueError("Kho có phiên lưu dở chưa vào bản kê; cần kiểm tra/phục hồi trước khi lưu thêm.")
        with TemporaryDirectory(prefix=".capture-", dir=root) as temp:
            stage = Path(temp) / "payload"; stage.mkdir()
            for item in [meta["fullFrame"], *slots]:
                source = inside(payload, item["path"])
                identity = image_identity(source)
                if any(item.get(k) != v for k, v in identity.items()):
                    raise ValueError("Ảnh xem trước bị thay đổi; hãy chụp lại.")
                target = inside(stage, item["path"]); target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if image_identity(target) != identity:
                    raise ValueError("Ảnh thay đổi khi sao chép.")
            (stage / "capture.json").write_text(canonical(meta), encoding="utf-8")
            stage.rename(destination)
        for slot in slots:
            with Image.open(inside(destination, slot["path"])) as image:
                width, height = image.size
            data["images"].append({"id": capture_id + "_" + slot["slotId"],
                "file": f"captures/{capture_id}/{slot['path']}", "width": width, "height": height,
                **{k: slot[k] for k in ("sha256", "pixelSha256", "bytes")},
                "source": {"kind": "heldout_capture", "lotId": lot_id, "captureId": capture_id,
                           "slotId": slot["slotId"], "plantId": plant_ids.get(slot["slotId"], "")},
                "capturedAt": meta["capturedAt"], "declaredEmpty": slot["slotId"] in empty_slots,
                "quality": slot.get("quality", {}), "qualityStatus": slot.get("qualityStatus", "unknown"),
                "reviewStatus": "unlabeled", "attributes": {}, "otherAbnormal": ""})
        data["captures"].append({"captureId": capture_id, "lotId": lot_id, "name": session_name[:120],
            "capturedAt": meta["capturedAt"], "frameDigest": digest(meta), "selection": selection,
            "cameraProfileId": meta["cameraProfile"]["profileId"], "geometryProfileId": geometry["profileId"],
            "cameraProfileSha256": digest(meta["cameraProfile"]), "geometryProfileSha256": digest(geometry),
            "storedBytes": added_bytes})
        return data, save_collection(root, data)


def export_collection(store, project, lot_id, output, *, confirmed=False, cancel=None):
    """Freeze reviewed material as a separate typed benchmark; never invent cropCycleId."""
    if confirmed is not True:
        raise ValueError("Cần xác nhận lô chỉ dành cho TEST, chưa dùng chọn checkpoint/ngưỡng.")
    output = Path(output).absolute()
    if output.exists() or output.resolve() != output:
        raise ValueError("Chọn thư mục mới, không dùng liên kết hoặc ghi đè.")
    root = root_for(store, project)
    with collection_lock(root):
        data, _ = load_collection(store, project)
        lot = next((r for r in data["lots"] if r["lotId"] == lot_id), None)
        rows = [r for r in data["images"] if r["source"]["lotId"] == lot_id]
        if not lot or not rows:
            raise ValueError("Lô chưa có ảnh.")
        if any(r["reviewStatus"] not in {"reviewed", "rejected"} for r in rows):
            raise ValueError("Duyệt hoặc từ chối từng ảnh của lô trước khi tạo bộ TEST; không bỏ qua ảnh chưa duyệt.")
        selected = [r for r in rows if r["reviewStatus"] == "reviewed"]
        if not selected:
            raise ValueError("Lô không có ảnh đã duyệt.")
        with TemporaryDirectory(prefix=".heldout-export-", dir=output.parent) as temp:
            stage = Path(temp) / "payload"; (stage / "images").mkdir(parents=True)
            records = []
            for row in selected:
                if cancel and cancel.is_set():
                    raise ValueError("Đã hủy tạo bộ TEST.")
                source = preview_path(store, project, row)
                target = stage / "images" / (row["id"] + ".png")
                shutil.copy2(source, target)
                records.append({"imageId": row["id"], "path": target.relative_to(stage).as_posix(),
                    **image_identity(target), "source": row["source"], "capturedAt": row["capturedAt"],
                    "reviewed": True, "labels": labels_for(project, row["attributes"], final=True)})
            manifest = {"schemaVersion": BENCHMARK_SCHEMA, "cropCode": data["cropCode"],
                "attributes": data["attributes"], "records": records, "cohort": lot,
                "createdAt": now(), "sourceProjectId": project.id, "evaluationUnit": "image",
                "excludedCount": len(rows) - len(selected), "totalCollectedCount": len(rows),
                "acquisitions": [c for c in data["captures"] if c["lotId"] == lot_id]}
            (stage / "benchmark.json").write_text(canonical(manifest), encoding="utf-8")
            from .benchmark_contract import validate_benchmark
            validate_benchmark(stage, project, cancel=cancel)
            if cancel and cancel.is_set():
                raise ValueError("Đã hủy tạo bộ TEST.")
            stage.rename(output)
    return output
