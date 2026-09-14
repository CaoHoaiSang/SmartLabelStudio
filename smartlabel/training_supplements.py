"""Explicit, local, training-only Hydro supplements; never fabricated captures.

The sidecar is independent of project.json so an open labeling session cannot
overwrite it. Export validates every enabled record before making a snapshot.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image

from .hydro_labels import model_attributes
from .label_schema import meaning_for, training_identity


def manifest_path(store, project):
    return store.project_dir(project) / "training_supplements" / "manifest.json"


def read_manifest(store, project):
    path = manifest_path(store, project)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schemaVersion") != 1 or data.get("projectId") != project.id
            or not isinstance(data.get("images"), list) or any(not isinstance(r, dict) for r in data["images"])):
        raise ValueError("Manifest ảnh bổ trợ không đúng phiên bản hoặc dự án.")
    return data


def summary_lines(store, project):
    try:
        data = read_manifest(store, project)
        if data is None:
            return []
        active = [r for r in data["images"] if r.get("enabled") is True]
        counts = Counter(r.get("kind", "unknown") for r in active)
        return ["", f"ẢNH BỔ TRỢ TRAIN: {len(active)} đang bật"
                f" · Tổng hợp {counts['synthetic']} · Nguồn ngoài {counts['external']}",
                "  Tách khỏi ảnh giàn và thống kê TEST; kiểm tra nguồn, nhãn và tệp khi xuất train.",
                "  Xem và duyệt tại GÁN NHÃN → Ảnh bổ trợ."]
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return ["", f"Ảnh bổ trợ cần kiểm tra: {exc}"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pixel_hash(path):
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        return hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()


def validated_samples(store, project, attribute, assignments):
    if project.metadata.get("template") != "Hydroponic Slot Condition":
        return []
    data = read_manifest(store, project)
    return validate_manifest_samples(store, project, attribute, assignments, data)


def validate_manifest_samples(store, project, attribute, assignments, data):
    """Validate a candidate sidecar without writing it, using the export contract."""
    if project.metadata.get("template") != "Hydroponic Slot Condition":
        return []
    if data is None:
        return []
    if not any(row.get("enabled") is True for row in data["images"]):
        return []
    attributes = {a["id"]: a for a in model_attributes(project)}
    identities = {k: training_identity(a) for k, a in attributes.items()}
    # JSON round-trip normalizes tuples in the contract identity.
    if data.get("labelIdentities") != json.loads(json.dumps(identities)):
        raise ValueError("Ý nghĩa nhãn ảnh bổ trợ khác dự án; cần duyệt lại manifest.")
    presence = next(a for a in attributes.values() if a["role"] == "presence")
    records = {r.id: r for r in project.images}
    root = manifest_path(store, project).parent.resolve()
    seen_ids, seen_hashes = set(), set()
    source_pixels = None
    result = []
    for row in data["images"]:
        if row.get("enabled") is not True:
            continue
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
            raise ValueError("Mã ảnh bổ trợ thiếu hoặc trùng.")
        seen_ids.add(identifier)
        if row.get("split") != "train" or row.get("reviewStatus") != "reviewed" or not row.get("reviewNote"):
            raise ValueError(f"{identifier}: ảnh bổ trợ phải được duyệt và chỉ vào TRAIN.")
        if row.get("kind") not in {"synthetic", "external"} or not row.get("provenance"):
            raise ValueError(f"{identifier}: thiếu nguồn ảnh bổ trợ.")
        if not row.get("cropCode") or row.get("cropCode") != project.metadata.get("cropCode"):
            raise ValueError(f"{identifier}: giống cây không khớp dự án.")
        values = row.get("attributes", {})
        if not isinstance(values, dict) or not values or any(k not in attributes or meaning_for(attributes[k], v) not in {"positive", "negative"}
                             for k, v in values.items()):
            raise ValueError(f"{identifier}: nhãn bổ trợ không hợp lệ.")
        if any(attributes[k]["role"] == "condition" for k in values) and row.get("presenceMeaning") != "positive":
            raise ValueError(f"{identifier}: phải xác nhận có cây trước khi gán tình trạng.")
        if presence["id"] in values and meaning_for(presence, values[presence["id"]]) != row.get("presenceMeaning"):
            raise ValueError(f"{identifier}: hiện diện mâu thuẫn.")
        source = (root / str(row.get("file", ""))).resolve()
        if not source.is_relative_to(root) or not source.is_file() or source == manifest_path(store, project):
            raise ValueError(f"{identifier}: đường dẫn ảnh không hợp lệ.")
        digest = sha256(source)
        if digest != row.get("sha256") or digest in seen_hashes:
            raise ValueError(f"{identifier}: ảnh thay đổi hoặc bị trùng.")
        seen_hashes.add(digest)
        if source_pixels is None:
            source_pixels = {pixel_hash(store.image_path(project, r)) for r in project.images}
        pixels = pixel_hash(source)
        if pixels in source_pixels:
            raise ValueError(f"{identifier}: ảnh trùng nội dung với dự án/ảnh bổ trợ.")
        source_pixels.add(pixels)
        provenance = row["provenance"]
        if not isinstance(provenance, dict):
            raise ValueError(f"{identifier}: nguồn ảnh phải là bản ghi thông tin.")
        if row["kind"] == "synthetic":
            parent = records.get(provenance.get("parentImageId"))
            if parent is None:
                raise ValueError(f"{identifier}: thiếu ảnh gốc trong dự án.")
            group = parent.metadata.get("plant_instance_id") or parent.capture_group or parent.id
            if assignments.get(group, "train") != "train":
                raise ValueError(f"{identifier}: ảnh gốc đã ở VAL/TEST; tắt biến thể trước khi xuất.")
            if (parent.review_status != "reviewed" or
                    sha256(store.image_path(project, parent)) != provenance.get("parentSha256") or
                    not provenance.get("method") or not provenance.get("prompt")):
                raise ValueError(f"{identifier}: ảnh gốc/nguồn tổng hợp chưa xác minh.")
        elif not all(provenance.get(k) for k in ("url", "author", "license", "licenseUrl", "retrievedAt")):
            raise ValueError(f"{identifier}: thiếu giấy phép hoặc thông tin trích nguồn.")
        if attribute["id"] in values:
            result.append((source, values[attribute["id"]], dict(row)))
    return result
