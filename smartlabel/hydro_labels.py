"""Project adapter. Existing projects are read without an implicit migration."""
from .label_schema import (legacy_label_schema, validate_label_schema, make_label_schema,
                           label_for, meaning_for, training_identity)


def project_label_schema(project):
    schema = project.metadata.get("labelSchema")
    return validate_label_schema(schema) if schema is not None else legacy_label_schema()


def model_attributes(project):
    return project_label_schema(project)["attributes"]


def model_keys(project):
    return tuple(attr["id"] for attr in model_attributes(project))


def semantic_display_values(attribute):
    """Housekeeping UI text follows explicit meaning, never a free-form label name.

    Stored display names remain part of the original schema/bundle. Reading a
    legacy project must not rewrite that schema or any saved image labels.
    """
    title = attribute["displayName"].strip()
    subject = "cây" if attribute["role"] == "presence" else title[:1].lower() + title[1:]
    names = {"positive": f"Có {subject}", "negative": f"Không có {subject}",
             "uncertain": "Chưa chắc chắn", "not_applicable": "Không áp dụng"}
    return {value["id"]: names[value["meaning"]] for value in attribute["values"]}


def display_values(project, key):
    if project and project.metadata.get("template") == "Hydroponic Slot Condition":
        attr = next((a for a in model_attributes(project) if a["id"] == key), None)
        if attr:
            return semantic_display_values(attr)
    return {}


def enforce_presence(project, attributes):
    attrs = model_attributes(project)
    presence = next(a for a in attrs if a["role"] == "presence")
    if meaning_for(presence, attributes.get(presence["id"])) != "positive":
        for attr in attrs:
            if attr["role"] == "condition":
                attributes[attr["id"]] = label_for(attr, "not_applicable")


def install_label_schema(project, schema):
    """Explicit save only. Never silently rewrite any existing image label."""
    schema = validate_label_schema(schema)
    old = {a["id"]: a for a in model_attributes(project)}
    new = {a["id"]: a for a in schema["attributes"]}
    for key, attr in old.items():
        used = any(key in record.attributes for record in project.images)
        used = used or key in project.attribute_models
        if used and (key not in new or training_identity(attr) != training_identity(new[key])):
            raise ValueError("Nhãn đã được dùng: chỉ đổi tên hiển thị; tạo dự án mới để đổi mã hoặc ý nghĩa.")
    for key in old.keys() - new.keys():
        project.attribute_schema.pop(key, None)
        project.attribute_settings.pop(key, None)
    for attr in schema["attributes"]:
        key = attr["id"]
        # Preserve existing order; classifier output order comes from the artifact.
        existing = project.attribute_schema.get(key, [])
        values = [v["id"] for v in attr["values"]]
        project.attribute_schema[key] = existing if set(existing) == set(values) else values
        project.attribute_settings[key] = {
            **project.attribute_settings.get(key, {}), "title": attr["displayName"],
            "scope": "image", "role": "classification", "required": True,
            "default": "", "train_exclude": [v["id"] for v in attr["values"]
                                            if v["meaning"] in {"uncertain", "not_applicable"}],
        }
    project.metadata["labelSchema"] = schema
