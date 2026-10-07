"""Read-only image membership and selection rules shared by the review views."""
from .hydro_labels import display_values


ALL = "Tất cả nhãn / thuộc tính"
ANY = "Mọi giá trị"
MISSING = "Chưa gán giá trị"


def adjacent_visible_image_id(ordered_ids, visible_ids, current_id):
    """Select the next visible neighbor, then the previous; never wrap to the start."""
    try:
        position = ordered_ids.index(current_id)
    except ValueError:
        return None
    visible = set(visible_ids)
    for identifier in ordered_ids[position + 1:]:
        if identifier in visible:
            return identifier
    for identifier in reversed(ordered_ids[:position]):
        if identifier in visible:
            return identifier
    return None


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


def filter_values(project, field, records=None):
    kind, key = field
    values = {ANY: None}
    if not project or kind == "all":
        return {ANY: None}
    if any(matches_image(project, record, field=field, value="")
           for record in (project.images if records is None else records)):
        values[MISSING] = ""
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
