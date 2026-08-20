from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class LabelClass:
    id: int
    name: str
    color: str = "#27c2ff"
    aliases: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabelClass":
        return cls(**data)


@dataclass
class Annotation:
    id: str
    class_id: int
    kind: str = "bbox"  # legacy/preferred geometry: bbox | polygon | mask | obb
    bbox: list[float] = field(default_factory=list)  # x, y, width, height
    points: list[list[float]] = field(default_factory=list)  # SEG polygon
    obb: list[list[float]] = field(default_factory=list)  # four rotated-box corners
    orientation: list[list[float]] = field(default_factory=list)  # center + direction tip (ORI/Pose)
    confidence: float | None = None
    source: str = "manual"
    model_version: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    approved: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create_box(
        cls,
        class_id: int,
        bbox: list[float],
        *,
        source: str = "manual",
        confidence: float | None = None,
        model_version: str = "",
    ) -> "Annotation":
        return cls(
            id=new_id("ann"),
            class_id=class_id,
            bbox=[float(v) for v in bbox],
            source=source,
            confidence=confidence,
            model_version=model_version,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Annotation":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImageRecord:
    id: str
    file_name: str
    width: int
    height: int
    source_path: str = ""
    capture_group: str = ""
    import_batch: str = ""
    review_status: str = "unlabeled"  # unlabeled | draft | reviewed | rejected
    annotations: list[Annotation] = field(default_factory=list)
    quality: dict[str, float] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_asset_id: str = ""
    asset_role: str = "full_frame"  # full_frame | roi | slot
    lineage: dict[str, Any] = field(default_factory=dict)
    sha256: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageRecord":
        values = dict(data)
        values["annotations"] = [Annotation.from_dict(item) for item in data.get("annotations", [])]
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["annotations"] = [item.to_dict() for item in self.annotations]
        return data


@dataclass
class Project:
    schema_version: int
    id: str
    name: str
    task: str = "instance_segmentation"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    classes: list[LabelClass] = field(default_factory=list)
    attribute_schema: dict[str, list[str]] = field(default_factory=dict)
    # Per-group metadata.  The schema keeps the stable machine values while
    # this mapping stores the human title and labeling behaviour.
    # {key: {"title": str, "default": str, "required": bool, "role": str}}
    attribute_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    attribute_classification_enabled: bool = False
    attribute_models: dict[str, str] = field(default_factory=dict)
    attribute_model_bundle: str = ""
    active_rknn_model: str = ""
    attribute_rknn_models: dict[str, str] = field(default_factory=dict)
    images: list[ImageRecord] = field(default_factory=list)
    last_import_batch: str = ""
    active_model: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create(cls, name: str, task: str = "instance_segmentation") -> "Project":
        return cls(schema_version=2, id=new_id("project"), name=name, task=task)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        values = dict(data)
        # V1 did not have image-level attributes or asset lineage. Dataclass
        # defaults migrate those fields in memory; the next atomic save writes V2.
        if int(values.get("schema_version", 1)) not in {1, 2}:
            raise ValueError(f"Project schema không được hỗ trợ: {values.get('schema_version')}")
        values["schema_version"] = 2
        values["classes"] = [LabelClass.from_dict(item) for item in data.get("classes", [])]
        values["images"] = [ImageRecord.from_dict(item) for item in data.get("images", [])]
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["classes"] = [asdict(item) for item in self.classes]
        data["images"] = [item.to_dict() for item in self.images]
        return data

    def class_by_id(self, class_id: int) -> LabelClass | None:
        return next((item for item in self.classes if item.id == class_id), None)

    def image_by_id(self, image_id: str) -> ImageRecord | None:
        return next((item for item in self.images if item.id == image_id), None)
