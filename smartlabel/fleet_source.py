"""Read-only source qualification. This is not dataset admission or consent storage."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json

from PIL import Image
from .fleet_intake import FleetIntakeError, HASH, _read_json

ISSUES = {
    "source_evidence_missing": "Bộ nhận chưa cung cấp bằng chứng nguồn",
    "ownership_evidence_missing": "Thiếu thế hệ sở hữu dữ liệu",
    "invalid_source_identity": "Định danh Gateway/giàn chưa hợp lệ",
    "crop_unknown": "Chưa xác định giống cây",
    "crop_mismatch": "Giống cây khác project đang chọn",
    "diagnostic_only": "Chỉ dành cho chẩn đoán",
    "source_kind_mismatch": "Loại ảnh không khớp nguồn gửi",
    "not_plant_crop": "Ảnh toàn cảnh không phải ảnh cây/rọ",
    "invalid_crop_dates": "Ngày gieo/ngày lên NFT chưa hợp lệ",
    "invalid_slot_identity": "Thiếu hoặc sai định danh vụ/rọ/cây",
    "capture_time_unknown": "Thời gian chụp chưa xác định múi giờ",
    "image_quality_review_required": "Chất lượng ảnh cần kiểm tra lại",
    "duplicate_capture_slot": "Trùng rọ trong cùng lần chụp",
    "shared_parent_missing": "Thiếu ảnh cha đã được chọn chia sẻ",
    "parent_sharing_mismatch": "Thông tin chia sẻ ảnh cha không khớp",
    "phone_origin_not_verified": "Ảnh điện thoại chứa nguồn Hydro không được xác minh",
    "duplicate_existing_holdout": "Trùng ảnh trong tập kiểm chứng của project",
    "duplicate_existing_image": "Trùng ảnh đã có trong project",
    "duplicate_contribution_image": "Trùng ảnh trong đợt đóng góp",
    "label_review_required": "Nhãn chưa được duyệt",
    "binary_label_required": "Chưa có nhãn Có/Không rõ ràng",
    "label_semantics_invalid": "Nhãn không hợp lệ hoặc mâu thuẫn với hiện diện cây",
    "cycle_origin_ambiguous": "Vụ trùng mã với dữ liệu cũ nhưng thiếu namespace để đối chiếu",
    "existing_cycle_holdout": "Vụ/cây này đã có trong tập kiểm chứng",
}


def qualification(row):
    value = row.get("qualification")
    if value is None:  # Older receiver: allow drafts, never infer successful QA.
        return {"sourceClass": "unqualified", "issues": ["source_evidence_missing"], "trainAllowed": False}
    if (not isinstance(value, dict) or value.get("schemaVersion") != "FleetSourceQualificationV1"
            or value.get("trainAllowed") is not False or value.get("evaluationEligible") is not False
            or value.get("sourceClass") not in {"unqualified", "hydro_slot", "customer_phone"}
            or not isinstance(value.get("issues"), list) or len(value["issues"]) > 30
            or any(not isinstance(item, str) or len(item) > 80 for item in value["issues"])
            or not HASH.fullmatch(str(value.get("groupId", ""))) or row.get("groupId") != value["groupId"]
            or value.get("parentStatus") not in {"not_shared", "shared", "not_applicable"}):
        raise FleetIntakeError("Kết quả kiểm tra nguồn Fleet không hợp lệ; ảnh chưa được duyệt.")
    expected = {"hydro_slot": "hydro_camera", "customer_phone": "phone"}
    kind = value["sourceClass"]
    if kind in expected and (row.get("source") != expected[kind] or value["issues"]):
        raise FleetIntakeError("Nguồn ảnh không khớp kết quả kiểm tra.")
    if kind == "customer_phone" and value.get("splitPolicy") != "TRAIN_ONLY":
        raise FleetIntakeError("Ảnh khách điện thoại không được vào bộ kiểm chứng.")
    return value


def source_caption(row):
    value = qualification(row)
    title = {"hydro_slot": "Giàn · Hydro qua Fleet", "customer_phone": "Bổ trợ · điện thoại khách",
             "unqualified": "Nguồn cần kiểm tra"}[value["sourceClass"]]
    if value["issues"]:
        return title + " · " + "; ".join(ISSUES.get(issue, "Cần kiểm tra nguồn") for issue in value["issues"][:3])
    if value.get("parentStatus") == "not_shared":
        title += " · ảnh cha không chia sẻ"
    return title + " · chưa đưa vào dataset/train"


def dataset_preflight(session, project, store):
    """Fresh online dry run, no snapshot, file copy, split write or train permission.

    Match exact bytes AND decoded RGB against the current project. This is not
    near-duplicate detection, nor a scan of other projects or old exports.
    """
    from .dataset_manager import DatasetManager
    from .hydro_labels import model_attributes
    from .label_schema import meaning_for
    from .training_supplements import validate_review_labels

    if project.id != session.project_id or store.project_dir(project).resolve() != session.root:
        raise FleetIntakeError("Project đích đã thay đổi; không chạy kiểm tra Fleet.")
    root = session.root
    project_path = root / "project.json"
    if json.loads(project_path.read_text(encoding="utf-8")) != project.to_dict():
        raise FleetIntakeError("Project trên đĩa khác phiên đang mở; tải lại project trước khi kiểm tra.")
    project_hash = hashlib.sha256(project_path.read_bytes()).hexdigest()
    data, revision = session.refresh()
    manifest_path = root / "fleet_inbox" / data["contributionId"] / "manifest.json"
    staged = _read_json(manifest_path)
    if (staged.get("projectId") != project.id or staged.get("importId") != data["importId"]
            or staged.get("contributionId") != data["contributionId"]):
        raise FleetIntakeError("Bản kê đóng góp không khớp phiên đã xác minh.")
    contribution = staged.get("contribution", {})
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def checkpoint():
        current, current_revision = session.refresh()
        if (current_revision != revision or hashlib.sha256(json.dumps(current, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != source_hash
                or hashlib.sha256(project_path.read_bytes()).hexdigest() != project_hash):
            raise FleetIntakeError("Nhãn, nguồn hoặc project vừa thay đổi; chạy lại kiểm tra để không dùng kết quả cũ.")
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_hash:
            raise FleetIntakeError("Bản kê nguồn vừa thay đổi; chạy lại kiểm tra.")

    def pixels(file):
        with Image.open(file) as image:
            if image.width * image.height > 24000000 or image.width < 1 or image.height < 1 or getattr(image, "n_frames", 1) != 1:
                raise FleetIntakeError("Ảnh ngoài giới hạn kiểm tra.")
            image.load()
            rgb = image.convert("RGB")
            prefix = b"FleetRGBV1\0" + rgb.width.to_bytes(4, "big") + rgb.height.to_bytes(4, "big")
            return hashlib.sha256(prefix + rgb.tobytes()).hexdigest()

    def renew_if_needed():
        import time
        if session.deadline - time.monotonic() < 5:
            checkpoint()

    assignments = DatasetManager(store).ensure_split_assignment(project, persist=False)["groups"]
    known_bytes, known_pixels, existing_files, existing_groups = {}, {}, [], []
    for record in project.images:
        renew_if_needed()
        file = store.image_path(project, record)
        if not file.resolve().is_relative_to(root) or file.is_symlink() or not file.is_file():
            raise FleetIntakeError("Ảnh project hiện có bị thiếu hoặc không an toàn; kiểm tra dataset trước.")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        existing_files.append((file, digest))
        group = str(record.metadata.get("plant_instance_id") or record.capture_group or record.id)
        split = assignments.get(group, "train")
        existing_groups.append((record.metadata, split))
        known_bytes.setdefault(digest, set()).add(split)
        known_pixels.setdefault(pixels(file), set()).add(split)
    attrs = model_attributes(project)
    presence = next(a for a in attrs if a["role"] == "presence")
    counts = Counter()
    rows, seen_bytes, seen_pixels = [], set(), set()
    for row in data["images"]:
        renew_if_needed()
        q = qualification(row)
        issues = list(q["issues"])
        if row.get("source") == "hydro_camera" and contribution.get("cropCycleId"):
            for metadata, split in existing_groups:
                if metadata.get("cropCycleId") != contribution["cropCycleId"]:
                    continue
                existing_gateway = metadata.get("fleetDeviceId")
                if existing_gateway and existing_gateway != contribution.get("fleetDeviceId"):
                    continue  # Equal local IDs on a different Gateway are not the same crop cycle.
                if metadata.get("fleetSourceGroupId") == q.get("groupId"):
                    if split in {"val", "test"} and "existing_cycle_holdout" not in issues:
                        issues.append("existing_cycle_holdout")
                elif "cycle_origin_ambiguous" not in issues:
                    # Old direct Hydro imports have no verified Gateway/ownership namespace.
                    # Do not silently declare independence or rewrite their locked split.
                    issues.append("cycle_origin_ambiguous")
        file = session.preview_path(row)  # Fresh lease, custody, withdrawal marker, exact bytes.
        pixel = pixels(file)
        if row["sha256"] in known_bytes or pixel in known_pixels:
            splits = known_bytes.get(row["sha256"], set()) | known_pixels.get(pixel, set())
            issues.append("duplicate_existing_holdout" if splits & {"val", "test"} else "duplicate_existing_image")
        if row["sha256"] in seen_bytes or pixel in seen_pixels:
            issues.append("duplicate_contribution_image")
        seen_bytes.add(row["sha256"]); seen_pixels.add(pixel)
        if row.get("reviewStatus") != "reviewed":
            issues.append("label_review_required")
        try:
            labels = validate_review_labels(project, {**row, "presenceMeaning": meaning_for(presence, row.get("attributes", {}).get(presence["id"]))})
            if not labels:
                issues.append("binary_label_required")
        except ValueError:
            labels = {}; issues.append("label_semantics_invalid")
        if not issues:
            counts.update(labels.keys())
        rows.append({"assetId": row["id"], "sha256": row["sha256"], "pixelSha256": pixel,
                     "sourceClass": q["sourceClass"], "groupId": q.get("groupId"),
                     "issues": issues, "proposedSplit": "train", "attributeIds": sorted(labels)})
    checkpoint()
    # Source files may be edited without project.json changing. No cached file proof.
    if any(not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest for file, digest in existing_files):
        raise FleetIntakeError("Ảnh project đã đổi trong lúc kiểm tra; kết quả chưa có hiệu lực.")
    for row in session.data["images"]:
        session.preview_path(row)
    checkpoint()
    return {"schemaVersion": "FleetDatasetReadinessV1", "projectId": project.id,
            "contributionId": data["contributionId"], "importId": data["importId"], "reviewRevision": revision,
            "projectSha256": project_hash, "sourceManifestSha256": manifest_hash,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "sourceReady": bool(rows) and all(not row["issues"] for row in rows), "images": rows,
            "attributeCounts": dict(counts), "trainAllowed": False, "evaluationEligible": False,
            "blockers": ["managed_snapshot_and_withdrawal_gate_pending"],
            "scope": "current_project_and_selected_contribution_only"}
