"""Read-only image membership rules shared by the browser and inline edits."""
from .hydro_labels import display_values


ALL = "Tất cả nhãn / thuộc tính"
ANY = "Mọi giá trị"
MISSING = "Chưa gán giá trị"


def filter_fields(project):
    fields = {ALL: ("all", "")}
    if not project:
        return fields
    if project.classes and project.metadata.get("template") != "Hydroponic Slot Condition":
        fields["Nhãn vật thể (Class)"] = ("class", "")
    for key in project.attribute_schema:
        title = project.attribute_settings.get(key, {}).get("title", key)
        fields[f"{title} · {key}"] = ("attribute", key)
    return fields


def filter_values(project, field):
    kind, key = field
    values = {ANY: None, MISSING: ""}
    if not project or kind == "all":
        return {ANY: None}
    if kind == "class":
        values.update({f"{item.name} · #{item.id}": item.id for item in project.classes})
    else:
        captions = display_values(project, key)
        values.update({f"{captions.get(value, value)} · [{value}]": value
                       for value in project.attribute_schema.get(key, [])})
    return values


def matches_image(project, record, status=None, field=("all", ""), value=None):
    if status and record.review_status != status:
        return False
    kind, key = field
    if kind == "all" or value is None:
        return True
    if kind == "class":
        return not record.annotations if value == "" else any(a.class_id == value for a in record.annotations)
    scope = project.attribute_settings.get(key, {}).get("scope", "annotation_crop")
    if scope == "image":
        return record.attributes.get(key, "") == value
    return (not record.annotations or any(not a.attributes.get(key) for a in record.annotations)) if value == "" else any(
        a.attributes.get(key) == value for a in record.annotations)
