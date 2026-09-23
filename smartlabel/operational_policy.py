"""Explicit unvalidated release permission, never a claim of model accuracy."""
from datetime import datetime, timezone
import hashlib
import json
import re

UNVALIDATED_OPERATIONAL = "operational_unvalidated"
POLICY_SCHEMA = "HydroOperationalAcceptanceV1"


def export_policy(config):
    policy = config.get("evaluationPolicy", "verified_holdout")
    if policy not in {"verified_holdout", "unvalidated_pilot"}:
        raise ValueError("Chính sách kiểm định không hợp lệ.")
    pilot = config.get("deploymentMode") == "operational" and policy == "unvalidated_pilot"
    if pilot and config.get("pilotAcknowledged") is not True:
        raise ValueError("Cần xác nhận vận hành khi chưa kiểm định độc lập; không tự bỏ qua TEST.")
    return pilot


def acceptance(checkpoint_hashes):
    return {"schemaVersion": POLICY_SCHEMA, "acknowledged": True,
            "acceptedAt": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "checkpointHashes": dict(checkpoint_hashes)}


def validate_acceptance(value, model_keys):
    if (not isinstance(value, dict) or value.get("schemaVersion") != POLICY_SCHEMA
            or value.get("acknowledged") is not True
            or not isinstance(value.get("checkpointHashes"), dict)
            or set(value["checkpointHashes"]) != set(model_keys)
            or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v)
                   for v in value["checkpointHashes"].values())):
        raise ValueError("Thiếu xác nhận vận hành chưa kiểm định gắn đúng checkpoint.")
    try:
        at = datetime.fromisoformat(value["acceptedAt"])
        if at.tzinfo is None:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("Thời điểm xác nhận vận hành không hợp lệ.") from None


def contract_hash(manifest):
    payload = {key: value for key, value in manifest.items() if key != "operationalAcceptance"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
