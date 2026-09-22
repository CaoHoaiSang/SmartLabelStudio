"""Portable reviewed Hydro benchmarks, separate from project train/val/test membership."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import re
import shutil

from PIL import Image

from .fleet_boundaries import require_legacy_project, reject_fleet_metadata
from .fleet_intake import reject_generic_fleet_sources
from .hydro_labels import model_attributes
from .label_schema import meaning_for, training_identity

SCHEMA = "HydroBenchmarkV1"
MAX_IMAGES = 5000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024**3


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path, limit=16 * 1024 * 1024):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Bản kê không có hoặc vượt giới hạn dung lượng.")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Bản kê có trường trùng lặp.")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Số không hữu hạn.")))
    reject_fleet_metadata(value)
    return value


def inside(root, relative):
    root = Path(root).absolute()
    if root.resolve() != root or root.is_symlink():
        raise ValueError("Không dùng thư mục liên kết cho bộ TEST.")
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative) or ".." in relative.split("/"):
        raise ValueError("Đường dẫn ảnh trong bộ TEST không hợp lệ.")
    path = root / relative
    if path.resolve() != path or not path.resolve().is_relative_to(root):
        raise ValueError("Ảnh hoặc liên kết nằm ngoài bộ TEST.")
    reject_generic_fleet_sources([path])
    return path


def image_identity(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError("Ảnh không có hoặc vượt 10 MiB.")
    before = file_hash(path)
    with Image.open(path) as image:
        if image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1 or not 0 < image.width * image.height <= 20_000_000:
            raise ValueError("Bộ TEST chỉ nhận ảnh JPEG/PNG một khung, tối đa 20 MP.")
        rgb = image.convert("RGB")
        pixels = hashlib.sha256(f"{rgb.width}x{rgb.height}:".encode() + rgb.tobytes()).hexdigest()
    if file_hash(path) != before:
        raise ValueError("Ảnh đã đổi trong lúc kiểm tra.")
    return {"sha256": before, "pixelSha256": pixels, "bytes": path.stat().st_size}


def source_identity(record):
    meta = record.metadata
    return {key: str(meta.get(key) or "").strip() for key in
            ("fleetDeviceId", "siteId", "deviceId", "cropCycleId", "captureId", "slotId", "plant_instance_id")}


def cycle_key(source):
    return canonical([source.get(k, "") for k in ("fleetDeviceId", "siteId", "deviceId", "cropCycleId")])


def cycle_title(source):
    return f"{source.get('cropCycleId') or 'Chưa rõ vụ'} · {source.get('deviceId') or 'Chưa rõ giàn'} · {source.get('siteId') or 'Chưa rõ khu'}"


def cycle_rows(project, *, only_slots=False):
    groups = {}
    for record in project.images:
        if only_slots and record.asset_role != "slot":
            continue
        source = source_identity(record)
        key = cycle_key(source)
        row = groups.setdefault(key, {"key": key, "title": cycle_title(source), "images": 0, "reviewed": 0, "source": source, "dates": []})
        row["images"] += 1
        row["reviewed"] += record.review_status == "reviewed"
        captured = str(record.metadata.get("capturedAt") or "")[:10]
        if captured and captured not in row["dates"]:
            row["dates"].append(captured)
    for row in groups.values():
        row["dates"].sort()
        dates = row["dates"]
        row["title"] += " · " + (f"{dates[0]} → {dates[-1]}" if dates else "Chưa rõ ngày chụp")
    return sorted(groups.values(), key=lambda r: r["title"])


def export_benchmark(project, store, selected_cycles, output, *, progress=lambda *_: None, cancel=None):
    """Copy reviewed labels/images only. Never move splits or write project.json."""
    require_legacy_project(project, store)
    attributes = model_attributes(project)
    selected = [r for r in project.images if r.asset_role == "slot" and cycle_key(source_identity(r)) in selected_cycles]
    if not 1 <= len(selected) <= MAX_IMAGES:
        raise ValueError("Chọn từ 1 đến 5000 ảnh thuộc vụ cần kiểm định.")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.parent.resolve() != output.parent:
        raise ValueError("Chọn tên thư mục mới; không ghi đè bộ kiểm định.")
    presence = next(a for a in attributes if a["role"] == "presence")
    with TemporaryDirectory(prefix=".benchmark-", dir=output.parent) as temp:
        root = Path(temp) / "payload"
        (root / "images").mkdir(parents=True)
        records, size = [], 0
        for index, record in enumerate(selected, 1):
            if cancel and cancel.is_set():
                raise ValueError("Đã hủy; chưa xuất bộ TEST.")
            source = source_identity(record)
            if record.asset_role != "slot" or record.review_status != "reviewed" or not all(source[k] for k in ("siteId", "deviceId", "cropCycleId", "captureId", "slotId")):
                raise ValueError(f"{record.file_name}: cần ảnh rọ đã duyệt và nguồn giàn/vụ/rọ đầy đủ.")
            labels = {a["id"]: meaning_for(a, record.attributes.get(a["id"])) for a in attributes}
            if labels[presence["id"]] not in {"positive", "negative"}:
                raise ValueError(f"{record.file_name}: chưa xác định Có/Không có cây.")
            for attr in attributes:
                if attr["role"] == "condition" and labels[attr["id"]] not in (
                        {"positive", "negative"} if labels[presence["id"]] == "positive" else {"not_applicable"}):
                    raise ValueError(f"{record.file_name}: nhãn {attr['displayName']} chưa được duyệt dứt khoát.")
            image = store.image_path(project, record)
            if image.resolve().parent != (store.project_dir(project) / "images").resolve():
                raise ValueError("Đường dẫn ảnh nguồn nằm ngoài project.")
            identity = image_identity(image)
            if record.sha256 and record.sha256 != identity["sha256"]:
                raise ValueError("Ảnh nguồn đã thay đổi so với bản ghi được duyệt.")
            size += identity["bytes"]
            if size > MAX_TOTAL_BYTES:
                raise ValueError("Bộ TEST vượt 2 GiB.")
            relative = f"images/{identity['sha256']}{image.suffix.lower()}"
            target = root / relative
            shutil.copy2(image, target)
            if image_identity(target) != identity:
                raise ValueError("Ảnh thay đổi khi sao chép.")
            records.append({"imageId": record.id, "path": relative, **identity, "source": source,
                            "capturedAt": record.metadata.get("capturedAt"), "labels": labels, "reviewed": True})
            progress(index, len(selected), record.file_name)
        manifest = {"schemaVersion": SCHEMA, "cropCode": project.metadata.get("cropCode"),
                    "attributes": [training_identity(a) for a in attributes], "records": records,
                    "createdAt": datetime.now(timezone.utc).isoformat(), "sourceProjectId": project.id}
        (root / "benchmark.json").write_text(canonical(manifest), encoding="utf-8")
        validate_benchmark(root, project)
        if cancel and cancel.is_set():
            raise ValueError("Đã hủy; chưa xuất bộ TEST.")
        root.rename(output)
    return output


def validate_benchmark(root, project, *, cancel=None):
    root = Path(root).absolute()
    manifest = read_json(inside(root, "benchmark.json"))
    attrs = model_attributes(project)
    if manifest.get("schemaVersion") != SCHEMA or manifest.get("cropCode") != project.metadata.get("cropCode"):
        raise ValueError("Bộ TEST không đúng hợp đồng hoặc cây trồng của project.")
    if canonical(manifest.get("attributes")) != canonical([training_identity(a) for a in attrs]):
        raise ValueError("Schema/ý nghĩa nhãn của bộ TEST không khớp model.")
    rows = manifest.get("records")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_IMAGES:
        raise ValueError("Bộ TEST phải có 1–5000 ảnh.")
    hashes, pixels, identities, total = set(), set(), set(), 0
    presence = next(a for a in attrs if a["role"] == "presence")
    for row in rows:
        if cancel and cancel.is_set():
            raise ValueError("Đã hủy kiểm tra bộ TEST.")
        source = row.get("source", {})
        if row.get("reviewed") is not True or not all(isinstance(source.get(k), str) and source[k].strip() for k in ("siteId", "deviceId", "cropCycleId", "captureId", "slotId")):
            raise ValueError("Ảnh TEST cần nhãn đã duyệt và nguồn vụ/giàn/rọ.")
        identity = image_identity(inside(root, row.get("path")))
        if any(row.get(k) != v for k, v in identity.items()):
            raise ValueError("Checksum/pixel/dung lượng ảnh TEST không khớp bản kê.")
        unique = canonical([cycle_key(source), source["captureId"], source["slotId"]])
        if identity["sha256"] in hashes or identity["pixelSha256"] in pixels or unique in identities:
            raise ValueError("Ảnh hoặc nguồn rọ bị trùng trong bộ TEST.")
        hashes.add(identity["sha256"]); pixels.add(identity["pixelSha256"]); identities.add(unique)
        total += identity["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Bộ TEST vượt 2 GiB.")
        labels = row.get("labels", {})
        if set(labels) != {a["id"] for a in attrs} or labels.get(presence["id"]) not in {"positive", "negative"}:
            raise ValueError("Nhãn TEST thiếu hoặc không hợp lệ.")
        for attr in attrs:
            allowed = {"not_applicable"} if attr["role"] == "condition" and labels[presence["id"]] == "negative" else {"positive", "negative"}
            if labels[attr["id"]] not in allowed:
                raise ValueError("Nhãn TEST còn chưa chắc chắn hoặc mâu thuẫn hiện diện cây.")
    return manifest, digest(manifest)


def benchmark_root(store, project, benchmark_id=None):
    parent = store.project_dir(project) / "benchmarks"
    if parent.resolve() != parent.absolute() or parent.parent.resolve() != store.project_dir(project).absolute():
        raise ValueError("Kho bộ TEST không được là liên kết.")
    if benchmark_id is not None and not re.fullmatch(r"benchmark_[a-f0-9]{64}", benchmark_id):
        raise ValueError("Mã bộ TEST không hợp lệ.")
    return parent / benchmark_id if benchmark_id else parent


def import_benchmark(project, store, source, *, expected_digest=None, cancel=None):
    require_legacy_project(project, store)
    source = Path(source).absolute()
    manifest, fingerprint = validate_benchmark(source, project, cancel=cancel)
    if expected_digest and expected_digest != fingerprint:
        raise ValueError("Bộ TEST đã đổi sau bước xem trước; hãy chọn lại.")
    identifier = "benchmark_" + fingerprint
    parent = benchmark_root(store, project)
    parent.mkdir(exist_ok=True)
    target = benchmark_root(store, project, identifier)
    if target.exists():
        if validate_benchmark(target, project)[1] != fingerprint:
            raise ValueError("Bản nhập cũ đã thay đổi; không ghi đè.")
        return identifier
    with TemporaryDirectory(prefix=".intake-", dir=parent) as temp:
        stage = Path(temp) / "payload"
        (stage / "images").mkdir(parents=True)
        for row in manifest["records"]:
            if cancel and cancel.is_set():
                raise ValueError("Đã hủy nhập bộ TEST.")
            destination = inside(stage, row["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(inside(source, row["path"]), destination)
        (stage / "benchmark.json").write_text(canonical(manifest), encoding="utf-8")
        if validate_benchmark(stage, project, cancel=cancel)[1] != fingerprint:
            raise ValueError("Bộ TEST thay đổi khi nhập.")
        if cancel and cancel.is_set():
            raise ValueError("Đã hủy nhập bộ TEST.")
        stage.rename(target)
    return identifier


def list_benchmarks(store, project):
    parent = benchmark_root(store, project)
    return sorted(p.name for p in parent.glob("benchmark_*") if p.is_dir() and re.fullmatch(r"benchmark_[a-f0-9]{64}", p.name))
