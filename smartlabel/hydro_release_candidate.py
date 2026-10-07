"""Strict P2 contract reader for a future Fleet release candidate.

Phase A validates the portable document and its archive identity only. Creating
the candidate from a project remains an explicit Phase B operation.
"""
from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
import hashlib
import json
import math
import os
import re
import stat


SCHEMA = "HydroModelReleaseCandidateV1"
MAX_CANDIDATE_BYTES = 8 * 1024
MAX_JSON_DEPTH = 32
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 32
MAX_BUNDLE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
LEGACY_MODEL_KEYS = {"plant_presence", "yellow_leaf", "wilt"}
RUNTIME_TARGETS = {"windows_onnxruntime_cpu", "jetson_nano_tensorrt_fp16"}
VALIDATION_STATUSES = {"pilot_unvalidated", "validated_holdout", "operational_unvalidated"}
FIELDS = {
    "schema", "purpose", "bundleId", "bundleZipSha256", "bundleZipBytes",
    "bundleContractSha256", "bundleSchemaVersion", "pipeline", "cropCode",
    "runtimeTarget", "deploymentMode", "validationStatus", "labelSchemaSha256",
    "evaluationEvidenceSha256", "datasetVersion", "sourceCommit", "lineage", "createdAt",
}
SHA256 = re.compile(r"^[a-f0-9]{64}$")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
CROP_CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Ứng viên có trường trùng lặp.")
        result[key] = value
    return result


def _text(value, maximum):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and not re.search(r"[\x00-\x1f\x7f]", value))


def _sha(value, *, nullable=False):
    return value is None and nullable or isinstance(value, str) and bool(SHA256.fullmatch(value))


def _utc(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{3})?(?:Z|\+00:00)", value):
        return False
    year, month, day = int(value[0:4]), int(value[5:7]), int(value[8:10])
    hour, minute, second = int(value[11:13]), int(value[14:16]), int(value[17:19])
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= month <= 12 and 1 <= day <= days[month - 1] and hour <= 23 and minute <= 59 and second <= 59


def validate_release_candidate(value):
    """Return an isolated candidate dict, rejecting unknown or incompatible fields."""
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("Ứng viên phát hành thiếu trường hoặc có trường không được phép.")
    if (value["schema"] not in {SCHEMA, "HydroModelReleaseCandidateV2"} or value["purpose"] != "hydro-model"
            or not isinstance(value["bundleId"], str) or not BUNDLE_ID.fullmatch(value["bundleId"])
            or type(value["bundleZipBytes"]) is not int
            or not 1 <= value["bundleZipBytes"] <= MAX_BUNDLE_BYTES
            or type(value["bundleSchemaVersion"]) is not int
            or value["bundleSchemaVersion"] not in {1, 2, 3}
            or value["pipeline"] != f"fixed_slot_multilabel_v{value['bundleSchemaVersion']}"
            or not isinstance(value["cropCode"], str) or not CROP_CODE.fullmatch(value["cropCode"])
            or not isinstance(value["runtimeTarget"], str) or value["runtimeTarget"] not in RUNTIME_TARGETS
            or not isinstance(value["deploymentMode"], str) or value["deploymentMode"] not in {"shadow", "operational"}
            or not isinstance(value["validationStatus"], str) or value["validationStatus"] not in VALIDATION_STATUSES
            or not _sha(value["bundleZipSha256"])
            or not _sha(value["bundleContractSha256"])
            or not _sha(value["labelSchemaSha256"], nullable=True)
            or not _sha(value["evaluationEvidenceSha256"], nullable=True)
            or not _text(value["datasetVersion"], 128)
            or not _text(value["sourceCommit"], 128)
            or not _utc(value["createdAt"])):
        raise ValueError("Ứng viên phát hành không đúng hợp đồng HydroModelReleaseCandidateV1.")
    lineage = value["lineage"]
    if value["schema"] == "HydroModelReleaseCandidateV2":
        from .fleet_release_lineage import validate_release_lineage
        validate_release_lineage(lineage)
        if value['bundleSchemaVersion'] != 3:
            raise ValueError('Model có nguồn Fleet cần bundle V3.')
    elif not isinstance(lineage, dict) or set(lineage) != {"kind"} or lineage["kind"] != "legacy_only":
        raise ValueError('Candidate V1 chỉ chấp nhận lineage legacy_only; nguồn Fleet cần V2.')
    if ((value["bundleSchemaVersion"] == 3) != (value["labelSchemaSha256"] is not None)
            or (value["validationStatus"] == "validated_holdout")
            != (value["evaluationEvidenceSha256"] is not None)
            or (value["deploymentMode"] == "shadow"
                and value["validationStatus"] != "pilot_unvalidated")
            or (value["deploymentMode"] == "operational"
                and value["validationStatus"] not in {"validated_holdout", "operational_unvalidated"})
            or (value["validationStatus"] == "operational_unvalidated"
                and (value["bundleSchemaVersion"] != 3 or value["deploymentMode"] != "operational"
                     or value["evaluationEvidenceSha256"] is not None))):
        raise ValueError("Trạng thái kiểm định, schema hoặc chế độ triển khai của ứng viên không khớp.")
    return {**value, "lineage": dict(lineage)}


def _container_depth(text):
    depth = deepest = 0
    in_string = escape = False
    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "}]":
            depth = max(0, depth - 1)
    return deepest


def load_release_candidate(path):
    """Read a duplicate-safe UTF-8 candidate document."""
    path = Path(path)
    if (not path.is_file() or path.is_symlink()
            or not 0 < path.stat().st_size <= MAX_CANDIDATE_BYTES):
        raise ValueError("Tệp ứng viên không có, là liên kết hoặc vượt giới hạn.")
    try:
        text = path.read_text(encoding="utf-8")
        if _container_depth(text) > MAX_JSON_DEPTH:
            raise ValueError("Ứng viên phát hành không đúng hợp đồng HydroModelReleaseCandidateV1.")
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Số không hữu hạn.")),
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Không đọc được tệp ứng viên UTF-8 hợp lệ.") from None
    return validate_release_candidate(value)


def prepare_fleet_release_candidate(archive, project, store=None):
    """Write release_candidate.json beside a finished ZIP. This is an explicit action."""
    from .fleet_boundaries import reject_fleet_metadata, require_legacy_project
    require_legacy_project(project, store)
    from .fleet_boundaries import require_legacy_model
    require_legacy_model(archive, context=store.project_dir(project) if store is not None else None)
    return _prepare_checked_candidate(archive)


def _prepare_checked_candidate(archive, lineage=None):
    from .fleet_boundaries import reject_fleet_metadata
    archive = Path(archive)
    if not archive.is_file() or archive.is_symlink() or archive.suffix.lower() != ".zip":
        raise ValueError("Không tìm thấy ZIP gói model hoặc ZIP là liên kết.")
    destination = archive.with_name(archive.stem + ".release_candidate.json")
    if destination.is_symlink() or (destination.exists() and lineage is None):
        raise ValueError("Ứng viên phát hành đã tồn tại; không ghi đè.")
    before = archive.stat()
    if not 0 < before.st_size <= MAX_BUNDLE_BYTES:
        raise ValueError("ZIP gói model rỗng hoặc vượt 64 MiB.")
    bundle = _bundle_from_zip(archive)
    if lineage is None:
        reject_fleet_metadata(bundle)
        if 'fleetLineage' in bundle:
            raise ValueError('Gói Fleet phải đi qua luồng phát hành có quản lý.')
    else:
        from .fleet_release_lineage import validate_release_lineage
        lineage = validate_release_lineage(lineage)
        if bundle.get('fleetLineage') != lineage:
            raise ValueError('Thông tin nguồn đã đổi; chưa tạo candidate.')
    contract = release_object_sha256(bundle)
    status = bundle.get("validationStatus")
    acceptance = bundle.get("operationalAcceptance")
    if status == "operational_unvalidated":
        if not isinstance(acceptance, dict) or acceptance.get("bundleContractSha256") != contract:
            raise ValueError("Xác nhận vận hành không khớp contract của bundle.json trong ZIP.")
        from datetime import datetime
        from .operational_policy import validate_acceptance
        validate_acceptance(acceptance, bundle["models"])
        # Match the deployed Hydro/Nano acceptance contract, including Python 3.6 time parsing.
        stamp = acceptance.get("acceptedAt", "")
        try:
            if not stamp.endswith("+00:00"):
                raise ValueError()
            datetime.strptime(stamp[:-6], "%Y-%m-%dT%H:%M:%S.%f")
        except (TypeError, ValueError):
            raise ValueError("Thời điểm xác nhận vận hành không tương thích Hydro.") from None
        if ("evaluationEvidence" in bundle or
                any(token in str(bundle.get("trainingPurpose", "")) for token in ("smoke", "fixture"))):
            raise ValueError("Gói vận hành chưa kiểm định không được dùng bằng chứng hoặc model smoke/fixture.")
    elif acceptance is not None:
        raise ValueError("Xác nhận vận hành chưa kiểm định không khớp trạng thái gói.")
    version = bundle.get("schemaVersion")
    label_schema = bundle.get("labelSchema")
    evidence = bundle.get("evaluationEvidence")
    if version == 3:
        if not isinstance(label_schema, dict):
            raise ValueError("Gói V3 thiếu schema nhãn trong bundle.json.")
        label_hash = release_object_sha256(label_schema)
    elif label_schema is None:
        label_hash = None
    else:
        raise ValueError("Schema nhãn chỉ được có trong gói Hydro V3.")
    if status == "validated_holdout":
        if not isinstance(evidence, dict):
            raise ValueError("Gói đã kiểm định thiếu evaluationEvidence trong bundle.json.")
        evidence_hash = release_object_sha256(evidence)
    elif evidence is None:
        evidence_hash = None
    else:
        raise ValueError("Bằng chứng kiểm định không khớp trạng thái gói.")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = archive.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("ZIP gói model đã đổi trong lúc kiểm tra.")
    candidate = validate_release_candidate({
        "schema": "HydroModelReleaseCandidateV2" if lineage is not None else SCHEMA, "purpose": "hydro-model", "bundleId": bundle.get("bundleId"),
        "bundleZipSha256": digest.hexdigest(), "bundleZipBytes": after.st_size,
        "bundleContractSha256": contract, "bundleSchemaVersion": version,
        "pipeline": bundle.get("pipeline"), "cropCode": bundle.get("cropCode"),
        "runtimeTarget": bundle.get("runtimeTarget"), "deploymentMode": bundle.get("deploymentMode"),
        "validationStatus": status, "labelSchemaSha256": label_hash,
        "evaluationEvidenceSha256": evidence_hash, "datasetVersion": bundle.get("datasetVersion"),
        "sourceCommit": bundle.get("sourceCommit"), "lineage": lineage if lineage is not None else {"kind": "legacy_only"},
        "createdAt": bundle.get("createdAt"),
    })
    if lineage is not None and destination.exists():
        if load_release_candidate(destination) != candidate:
            raise ValueError('Candidate đã có nhưng không khớp gói; không ghi đè.')
        return verify_candidate_archive(candidate, archive)
    from uuid import uuid4
    temporary = destination.with_name(destination.name + "." + str(uuid4()) + ".tmp")
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
            handle.flush(); os.fsync(handle.fileno())
        # Atomic no-clobber publication on the same filesystem (Windows/Linux).
        # A concurrent candidate writer must never be silently replaced.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    try:
        return verify_candidate_archive(load_release_candidate(destination), archive)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _bundle_from_zip(archive):
    import zipfile
    try:
        package = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        raise ValueError("ZIP gói model không đọc được.") from None
    with package:
        entries = package.infolist()
        if len(entries) > MAX_BUNDLE_ENTRIES:
            raise ValueError("ZIP gói model có quá 32 tệp.")
        if sum(entry.file_size for entry in entries) > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise ValueError("ZIP gói model vượt 1 GiB sau giải nén.")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("ZIP gói model có tên tệp trùng lặp.")
        for entry in entries:
            relative = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (entry.is_dir() or entry.filename.startswith(("/", "\\"))
                    or "\\" in entry.filename or ":" in entry.filename
                    or not entry.filename or "." in relative.parts or ".." in relative.parts
                    or stat.S_ISLNK(mode)):
                raise ValueError("ZIP gói model có đường dẫn hoặc liên kết không an toàn.")
        if names.count("bundle.json") != 1:
            raise ValueError("ZIP gói model phải có đúng một bundle.json.")
        info = package.getinfo("bundle.json")
        if info.file_size > MAX_CANDIDATE_BYTES:
            raise ValueError("bundle.json vượt giới hạn.")
        try:
            bundle = json.loads(package.read("bundle.json").decode("utf-8"), object_pairs_hook=_pairs,
                                 parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Số không hữu hạn.")))
        except (UnicodeError, json.JSONDecodeError, ValueError):
            raise ValueError("bundle.json trong ZIP không phải JSON hợp lệ.") from None
        if not isinstance(bundle, dict):
            raise ValueError("bundle.json trong ZIP không phải object.")
        _validate_bundle_archive(package, bundle, set(names))
    return bundle


def _validate_bundle_archive(package, bundle, names):
    if 'fleetLineage' in bundle:
        from .fleet_release_lineage import validate_release_lineage
        validate_release_lineage(bundle['fleetLineage'])
        if bundle.get('schemaVersion') != 3:
            raise ValueError('Gói Fleet cần bundle V3.')
    models = bundle.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("bundle.json thiếu danh sách model.")
    version = bundle.get("schemaVersion")
    for key in ("compatibleCameraProfileIds", "compatibleGeometryProfileIds"):
        profiles = bundle.get(key)
        if (not isinstance(profiles, list) or not profiles
                or any(not isinstance(value, str) or not value for value in profiles)):
            raise ValueError(f"{key} phải có ít nhất một profile hợp lệ để Hydro nhập gói.")
    if version == 3:
        from .label_schema import validate_label_schema, validate_model_labels
        try:
            schema = validate_label_schema(bundle.get("labelSchema"))
        except ValueError as exc:
            raise ValueError("labelSchema trong bundle.json không hợp lệ.") from exc
        attributes = {attribute["id"]: attribute for attribute in schema["attributes"]}
        expected_models = set(attributes)
        if type(bundle.get("geometrySchemaVersion")) is not int or bundle["geometrySchemaVersion"] not in (1, 2):
            raise ValueError("Gói V3 cần geometrySchemaVersion 1 hoặc 2.")
    elif version in (1, 2):
        expected_models = LEGACY_MODEL_KEYS
    else:
        raise ValueError("Phiên bản bundle không hợp lệ.")
    if set(models) != expected_models:
        raise ValueError("Tập model không khớp labelSchema hoặc ba model legacy.")
    model_paths = set()
    for model_id, model in models.items():
        if not isinstance(model, dict):
            raise ValueError("Khai báo model trong bundle.json không hợp lệ.")
        relative = model.get("path")
        if (not isinstance(relative, str) or not relative
                or PurePosixPath(relative).is_absolute() or "\\" in relative or ":" in relative
                or "." in PurePosixPath(relative).parts or ".." in PurePosixPath(relative).parts):
            raise ValueError("Đường dẫn model trong bundle.json không an toàn.")
        if relative in model_paths:
            raise ValueError("Hai model không được dùng chung một tệp.")
        model_paths.add(relative)
        if relative not in names:
            raise ValueError("ZIP thiếu tệp model đã khai báo.")
        expected_hash = model.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash):
            raise ValueError("SHA-256 model trong bundle.json không hợp lệ.")
        digest = hashlib.sha256()
        with package.open(relative) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected_hash:
            raise ValueError("SHA-256 model trong ZIP không khớp bundle.json.")
        low, high = model.get("lowThreshold"), model.get("highThreshold")
        if (type(low) not in (int, float) or type(high) not in (int, float)
                or not 0 <= low < high <= 1):
            raise ValueError("Ngưỡng model phải thỏa 0 ≤ low < high ≤ 1.")
        if version == 3:
            validate_model_labels(attributes[model_id], model)
            if model.get("labels") != model["outputLabels"]:
                raise ValueError("labels và outputLabels của model không khớp.")
        elif model.get("labels") != ["absent", "present"]:
            raise ValueError("Model legacy cần đúng hai nhãn absent/present.")
        if model.get("batchSize") != 1 or model.get("dynamic") is not False:
            raise ValueError("Model phải dùng batch tĩnh bằng 1.")
        if (model.get("inputLayout", "NCHW") not in {"NCHW", "NHWC"}
                or model.get("colorOrder") not in {"RGB", "BGR"}
                or model.get("resizeMode") != "short_side_center_crop"):
            raise ValueError("Thông tin tiền xử lý ảnh của model không tương thích Hydro.")
        size = model.get("inputSize")
        if (not isinstance(size, list) or len(size) != 2
                or any(type(value) is not int or not 1 <= value <= 4096 for value in size)):
            raise ValueError("inputSize cần hai kích thước nguyên từ 1 đến 4096.")
        if version == 3:
            norm = model.get("normalization")
            if not isinstance(norm, dict):
                raise ValueError("Model V3 cần normalization tường minh.")
            def finite(value):
                return type(value) in (int, float) and math.isfinite(value)
            scale, mean, std = (norm.get(key) for key in ("scale", "mean", "std"))
            if (not finite(scale) or scale <= 0
                    or not isinstance(mean, list) or len(mean) != 3 or not all(finite(v) for v in mean)
                    or not isinstance(std, list) or len(std) != 3 or not all(finite(v) and v > 0 for v in std)):
                raise ValueError("normalization cần scale hữu hạn dương và ba kênh mean/std hợp lệ.")
    if names != {"bundle.json", *model_paths}:
        raise ValueError("ZIP chỉ được chứa bundle.json và đúng các tệp model đã khai báo.")
    if (bundle.get("runtimeTarget") == "jetson_nano_tensorrt_fp16"
            and (not isinstance(bundle.get("minimumTensorRTVersion"), str)
                 or not bundle["minimumTensorRTVersion"].strip())):
        raise ValueError("Gói Jetson thiếu minimumTensorRTVersion.")


def release_object_sha256(value):
    """Hash one object with the exporter contract_hash. Do not reimplement the dumps."""
    from .operational_policy import contract_hash
    if not isinstance(value, dict):
        raise ValueError("Đối tượng cần băm phải là object JSON.")
    return contract_hash(value)


def verify_candidate_archive(candidate, archive):
    """Re-hash the archive and detect replacement during the read."""
    candidate = validate_release_candidate(candidate)
    archive = Path(archive)
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("Không tìm thấy ZIP gói model hoặc ZIP là liên kết.")
    before = archive.stat()
    if not 0 < before.st_size <= MAX_BUNDLE_BYTES:
        raise ValueError("ZIP gói model rỗng hoặc vượt 64 MiB.")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = archive.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("ZIP gói model đã đổi trong lúc kiểm tra.")
    if after.st_size != candidate["bundleZipBytes"]:
        raise ValueError("Dung lượng ZIP không khớp ứng viên phát hành.")
    if digest.hexdigest() != candidate["bundleZipSha256"]:
        raise ValueError("SHA-256 ZIP không khớp ứng viên phát hành.")
    return candidate
