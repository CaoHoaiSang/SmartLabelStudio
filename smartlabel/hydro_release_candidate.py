"""Strict P2 contract reader for a future Fleet release candidate.

Phase A validates the portable document and its archive identity only. Creating
the candidate from a project remains an explicit Phase B operation.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re


SCHEMA = "HydroModelReleaseCandidateV1"
MAX_CANDIDATE_BYTES = 8 * 1024
MAX_JSON_DEPTH = 32
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
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
    if (value["schema"] != SCHEMA or value["purpose"] != "hydro-model"
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
    if not isinstance(lineage, dict) or set(lineage) != {"kind"} or lineage["kind"] != "legacy_only":
        raise ValueError("Chỉ dữ liệu legacy_only được chuẩn bị phát hành trước khi hoàn tất cổng Fleet 4b3.")
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
    archive = Path(archive)
    if not archive.is_file() or archive.is_symlink() or archive.suffix.lower() != ".zip":
        raise ValueError("Không tìm thấy ZIP gói model hoặc ZIP là liên kết.")
    destination = archive.with_name("release_candidate.json")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Ứng viên phát hành đã tồn tại; không ghi đè.")
    before = archive.stat()
    if not 0 < before.st_size <= MAX_BUNDLE_BYTES:
        raise ValueError("ZIP gói model rỗng hoặc vượt 64 MiB.")
    bundle = _bundle_from_zip(archive)
    reject_fleet_metadata(bundle)
    contract = release_object_sha256(bundle)
    status = bundle.get("validationStatus")
    acceptance = bundle.get("operationalAcceptance")
    if status == "operational_unvalidated":
        if not isinstance(acceptance, dict) or acceptance.get("bundleContractSha256") != contract:
            raise ValueError("Xác nhận vận hành không khớp contract của bundle.json trong ZIP.")
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
        "schema": SCHEMA, "purpose": "hydro-model", "bundleId": bundle.get("bundleId"),
        "bundleZipSha256": digest.hexdigest(), "bundleZipBytes": after.st_size,
        "bundleContractSha256": contract, "bundleSchemaVersion": version,
        "pipeline": bundle.get("pipeline"), "cropCode": bundle.get("cropCode"),
        "runtimeTarget": bundle.get("runtimeTarget"), "deploymentMode": bundle.get("deploymentMode"),
        "validationStatus": status, "labelSchemaSha256": label_hash,
        "evaluationEvidenceSha256": evidence_hash, "datasetVersion": bundle.get("datasetVersion"),
        "sourceCommit": bundle.get("sourceCommit"), "lineage": {"kind": "legacy_only"},
        "createdAt": bundle.get("createdAt"),
    })
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
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
        names = package.namelist()
        if names.count("bundle.json") != 1 or any(
                name.startswith("/") or ".." in Path(name).parts or name.endswith("/") for name in names):
            raise ValueError("ZIP gói model không đúng cấu trúc bundle.json.")
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
    return bundle


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
