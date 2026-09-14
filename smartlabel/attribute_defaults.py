"""Seed image attributes without overwriting existing labels or review evidence."""
from .hydro_labels import enforce_presence, model_attributes
from .label_schema import label_for, meaning_for


def configured_image_defaults(project):
    return {key: config['default'] for key, values in project.attribute_schema.items()
            if (config := project.attribute_settings.get(key, {})).get('scope') == 'image'
            and config.get('default') and config['default'] in values}


def fill_missing_image_defaults(project, attributes, *, suppressed=()):
    """Prepare missing fields without overwriting labels or treating defaults as review.

    Presence constrains only newly seeded conditions. Existing values, including
    uncertain/NA and deliberate clears, remain the operator's responsibility.
    """
    result = dict(attributes)
    added = {k: v for k, v in configured_image_defaults(project).items()
             if not result.get(k) and k not in suppressed}
    result.update(added)
    if project.metadata.get('template') == 'Hydroponic Slot Condition':
        attrs = model_attributes(project)
        presence = next(a for a in attrs if a['role'] == 'presence')
        if meaning_for(presence, result.get(presence['id'])) != 'positive':
            for attr in attrs:
                if attr['role'] != 'presence' and attr['id'] in added:
                    result[attr['id']] = label_for(attr, 'not_applicable')
    return result


def image_attribute_defaults(project):
    defaults = configured_image_defaults(project)
    if project.metadata.get("template") == "Hydroponic Slot Condition":
        for attr in model_attributes(project):
            defaults.setdefault(attr["id"], label_for(attr,
                "uncertain" if attr["role"] == "presence" else "not_applicable"))
        enforce_presence(project, defaults)
    return defaults
