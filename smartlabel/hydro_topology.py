"""Versioned physical topology. No inference decisions or runtime writes."""
import re

_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SLOT = re.compile(r"^[a-z][a-z0-9_-]{1,95}$")


def validate_topology(value):
    if not isinstance(value, dict) or set(value) != {"views"}:
        raise ValueError("topology requires views")
    views = value["views"]
    if not isinstance(views, list) or not 1 <= len(views) <= 8:
        raise ValueError("topology requires 1..8 views")
    seen_views, seen_racks, seen_slots = set(), set(), set()
    for view in views:
        if not isinstance(view, dict) or set(view) - {"viewId", "rackId", "slotIds", "displayName"}:
            raise ValueError("invalid topology view")
        view_id, rack_id = view.get("viewId"), view.get("rackId")
        if any(not isinstance(v, str) or not _ID.fullmatch(v) for v in (view_id, rack_id)):
            raise ValueError("invalid topology identity")
        if view_id in seen_views or rack_id in seen_racks:
            raise ValueError("duplicate topology view or rack")
        seen_views.add(view_id)
        seen_racks.add(rack_id)
        if "displayName" in view and (not isinstance(view["displayName"], str) or not view["displayName"].strip() or len(view["displayName"]) > 150):
            raise ValueError("invalid topology display name")
        ids = view.get("slotIds")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 32:
            raise ValueError("topology requires 1..32 slots per view")
        for position, slot_id in enumerate(ids, 1):
            if (not isinstance(slot_id, str) or not _SLOT.fullmatch(slot_id)
                    or slot_id != "%s_%02d" % (view_id, position) or slot_id in seen_slots):
                raise ValueError("topology slot identity/order mismatch")
            seen_slots.add(slot_id)
    if len(seen_slots) > 128:
        raise ValueError("topology exceeds 128 slots")
    return value


def topology_for(document):
    version = document.get("schemaVersion")
    if version == 2:
        return validate_topology(document.get("topology"))
    if version != 1:
        raise ValueError("unsupported topology document version")
    if document.get("topology") is not None:
        raise ValueError("V1 cannot carry a V2 topology")
    binding = document.get("cameraBinding") or {}
    mappings = document.get("views", binding.get("views", []))
    actual = {v["viewId"]: v["rackId"] for v in mappings}
    return {"views": [
        {"viewId": view_id, "rackId": actual.get(view_id, view_id),
         "slotIds": ["%s_%02d" % (view_id, i) for i in range(1, 6)]}
        for view_id in ("upper", "lower")
    ]}


def topology_slots(document):
    return [slot for view in topology_for(document)["views"] for slot in view["slotIds"]]


def topology_slot_map(document):
    return {slot: {"viewId": view["viewId"], "rackId": view["rackId"], "position": i}
            for view in topology_for(document)["views"] for i, slot in enumerate(view["slotIds"], 1)}


def topology_identity(value):
    return [(v["viewId"], v["rackId"], tuple(v["slotIds"])) for v in validate_topology(value)["views"]]
