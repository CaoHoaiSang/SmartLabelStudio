"""Seed new images only; changing project defaults never relabels saved images."""
from .hydro_labels import enforce_presence, model_attributes
from .label_schema import label_for


def image_attribute_defaults(project):
    defaults = {}
    for key, values in project.attribute_schema.items():
        config = project.attribute_settings.get(key, {})
        value = config.get("default", "")
        if config.get("scope") == "image" and value and value in values:
            defaults[key] = value
    if project.metadata.get("template") == "Hydroponic Slot Condition":
        for attr in model_attributes(project):
            defaults.setdefault(attr["id"], label_for(attr,
                "uncertain" if attr["role"] == "presence" else "not_applicable"))
        enforce_presence(project, defaults)
    return defaults
