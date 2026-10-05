"""Strict P2 contract reader for a future Fleet release candidate.

Phase A validates the portable document and its archive identity only. Creating
the candidate from a project remains an explicit Phase B operation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re


SCHEMA = "HydroModelReleaseCandidateV1"
MAX_CANDIDATE_BYTES = 32 * 1024
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
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


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
            or value["runtimeTarget"] not in RUNTIME_TARGETS
            or value["deploymentMode"] not in {"shadow", "operational"}
            or value["validationStatus"] not in VALIDATION_STATUSES
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
                and value["validationStatus"] not in {"validated_holdout", "operational_unvalidated"})):
        raise ValueError("Trạng thái kiểm định, schema hoặc chế độ triển khai của ứng viên không khớp.")
    return {**value, "lineage": dict(lineage)}


def load_release_candidate(path):
    """Read a duplicate-safe UTF-8 candidate document."""
    path = Path(path)
    if (not path.is_file() or path.is_symlink()
            or not 0 < path.stat().st_size <= MAX_CANDIDATE_BYTES):
        raise ValueError("Tệp ứng viên không có, là liên kết hoặc vượt giới hạn.")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Số không hữu hạn.")),
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Không đọc được tệp ứng viên UTF-8 hợp lệ.") from None
    return validate_release_candidate(value)


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
