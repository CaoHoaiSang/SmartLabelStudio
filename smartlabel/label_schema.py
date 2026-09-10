"""LabelSchemaV1: explicit semantics, independent of geometry and display language.

Shared verbatim by SmartLabel and Hydro camera. No UI/runtime dependencies.
"""
import copy
import hashlib
import json
import re

ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
RESERVED = {"constructor", "prototype", "__proto__"}
MEANINGS = ("negative", "positive", "uncertain", "not_applicable")


def _id(value):
    return isinstance(value, str) and bool(ID.fullmatch(value)) and value not in RESERVED


def _name(value):
    return (isinstance(value, str) and 0 < len(value.strip()) <= 100
            and not any(ord(char) < 32 for char in value))


def schema_id(schema):
    body = {key: value for key, value in schema.items() if key != "schemaId"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "labels_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_label_schema(schema):
    if not isinstance(schema, dict) or set(schema) != {"schemaVersion", "schemaId", "attributes"}:
        raise ValueError("Label schema fields are invalid")
    if type(schema["schemaVersion"]) is not int or schema["schemaVersion"] != 1:
        raise ValueError("LabelSchemaV1 is required")
    attrs = schema["attributes"]
    if not isinstance(attrs, list) or not 2 <= len(attrs) <= 16:
        raise ValueError("Schema requires one presence and 1–15 conditions")
    if any(not isinstance(attr, dict) for attr in attrs):
        raise ValueError("Attribute must be an object")
    presence = [attr for attr in attrs if attr.get("role") == "presence"]
    if len(presence) != 1:
        raise ValueError("Exactly one presence attribute is required")
    ids = set()
    for attr in attrs:
        role = attr.get("role")
        fields = {"id", "displayName", "role", "values"} | ({"requires"} if role == "condition" else set())
        if set(attr) != fields or role not in {"presence", "condition"}:
            raise ValueError("Only independent binary presence/condition classifiers are supported")
        if not _id(attr["id"]) or attr["id"] in ids or not _name(attr["displayName"]):
            raise ValueError("Attribute ID/name is invalid or duplicated")
        ids.add(attr["id"])
        if role == "condition" and attr["requires"] != presence[0]["id"]:
            raise ValueError("Conditions must depend on the presence attribute")
        values = attr["values"]
        required = set(MEANINGS if role == "condition" else MEANINGS[:3])
        if not isinstance(values, list) or len(values) != len(required):
            raise ValueError("Attribute must map each required meaning exactly once")
        value_ids, meanings, names = set(), set(), set()
        for value in values:
            if not isinstance(value, dict) or set(value) != {"id", "displayName", "meaning"}:
                raise ValueError("Label fields are invalid")
            if not _id(value["id"]) or not _name(value["displayName"]):
                raise ValueError("Label ID/display name is invalid")
            if value["id"] in value_ids or value["meaning"] in meanings or value["displayName"] in names:
                raise ValueError("Duplicate label ID, meaning or display name")
            value_ids.add(value["id"])
            meanings.add(value["meaning"])
            names.add(value["displayName"])
        if meanings != required:
            raise ValueError("Missing or unsupported label meaning")
    if schema.get("schemaId") != schema_id(schema):
        raise ValueError("Label schema fingerprint mismatch")
    return copy.deepcopy(schema)


def make_label_schema(attributes):
    schema = {"schemaVersion": 1, "attributes": copy.deepcopy(attributes)}
    schema["schemaId"] = schema_id(schema)
    return validate_label_schema(schema)


def label_for(attribute, meaning):
    return next(value["id"] for value in attribute["values"] if value["meaning"] == meaning)


def meaning_for(attribute, label):
    return next((value["meaning"] for value in attribute["values"] if value["id"] == label), None)


def training_identity(attribute):
    """Display-only edits may reuse a classifier; meaning/ID changes may not."""
    return {"id": attribute["id"], "role": attribute["role"],
            "requires": attribute.get("requires"),
            "values": sorted((value["id"], value["meaning"]) for value in attribute["values"])}


def validate_model_labels(attribute, entry):
    labels = entry.get("outputLabels")
    expected = {label_for(attribute, "negative"), label_for(attribute, "positive")}
    if not isinstance(labels, list) or len(labels) != 2 or set(labels) != expected:
        raise ValueError("Model output labels do not match attribute semantics")
    for meaning in ("negative", "positive"):
        index = entry.get(meaning + "Index")
        if type(index) is not int or index not in (0, 1) or labels[index] != label_for(attribute, meaning):
            raise ValueError("Model output index does not match label meaning")
    if entry.get("attributeId") != attribute["id"]:
        raise ValueError("Model attributeId mismatch")
    return labels


def legacy_label_schema():
    names = {"plant_presence": ("Cây hiện diện", "Có cây", "Không có cây"),
             "yellow_leaf": ("Lá vàng", "Có lá vàng", "Không có lá vàng"),
             "wilt": ("Héo", "Có héo", "Không héo")}
    attributes = []
    for key, (name, positive, negative) in names.items():
        attr = {"id": key, "displayName": name,
                "role": "presence" if key == "plant_presence" else "condition",
                "values": [{"id": "absent", "displayName": negative, "meaning": "negative"},
                           {"id": "present", "displayName": positive, "meaning": "positive"},
                           {"id": "uncertain", "displayName": "Chưa chắc chắn", "meaning": "uncertain"}]}
        if attr["role"] == "condition":
            attr["requires"] = "plant_presence"
            attr["values"].append({"id": "not_applicable", "displayName": "Không áp dụng", "meaning": "not_applicable"})
        attributes.append(attr)
    return make_label_schema(attributes)

