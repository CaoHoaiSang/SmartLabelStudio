from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import random
import shutil
import re

from PIL import Image, ImageDraw

from .models import Annotation, Project
from .project_store import ProjectStore
from .fleet_boundaries import require_legacy_project


class DatasetManager:
    """Creates immutable dataset snapshots and derived exports."""

    STRATEGY_LOCKED = "locked"
    STRATEGY_FINAL_KEEP_TEST = "final_keep_test"
    STRATEGY_TRAIN_ALL = "train_all"

    def __init__(self, store: ProjectStore):
        self.store = store

    def summary(self, project: Project) -> dict[str, Any]:
        statuses = Counter(image.review_status for image in project.images)
        class_counts: Counter[int] = Counter()
        sources: Counter[str] = Counter()
        for image in project.images:
            for ann in image.annotations:
                class_counts[ann.class_id] += 1
                sources[ann.source] += 1
        result = {
            "images": len(project.images),
            "annotations": sum(class_counts.values()),
            "statuses": dict(statuses),
            "classes": {item.name: class_counts[item.id] for item in project.classes},
            "sources": dict(sources),
        }
        if project.metadata.get("template") == "Hydroponic Slot Condition":
            from .hydro_statistics import attribute_summary
            result["image_attributes"] = attribute_summary(
                project, self.ensure_split_assignment(project, persist=False)["groups"])
        return result

    def split_assignment_path(self, project: Project) -> Path:
        return self.store.project_dir(project) / "split_assignment.json"

    def supplement_parent_groups(self, project: Project) -> dict:
        if project.metadata.get("template") != "Hydroponic Slot Condition":
            return {}
        from .training_supplements import read_manifest
        from .split_health import supplement_parent_groups
        return supplement_parent_groups(project, read_manifest(self.store, project))

    def split_health(self, project: Project) -> dict:
        from .split_health import split_conflicts, coverage_lines
        assignment = self.ensure_split_assignment(project, persist=False)
        parents = self.supplement_parent_groups(project)
        return {"parents": parents, "conflicts": split_conflicts(parents, assignment["groups"]),
                "coverage": coverage_lines(project, assignment["groups"])}

    def split_revision(self, project: Project) -> str:
        """Invalidate a confirmation if labels, groups or sidecar changed meanwhile."""
        from .training_supplements import manifest_path
        digest = hashlib.sha256(json.dumps(project.to_dict(), sort_keys=True).encode())
        for path in (self.split_assignment_path(project), manifest_path(self.store, project)):
            digest.update(path.read_bytes() if path.exists() else b"missing")
        return digest.hexdigest()

    def preview_rebalance(self, project: Project) -> dict:
        from .split_health import coverage_lines
        revision = self.split_revision(project)
        current = self.ensure_split_assignment(project, persist=False)["groups"]
        candidate = self.ensure_split_assignment(project, force_rebalance=True, persist=False)
        groups = self._record_groups(project.images)
        counts = {s: sum(len(groups[k]) for k, v in candidate["groups"].items() if v == s)
                  for s in ("train", "val", "test")}
        return {"revision": revision, "assignment": candidate, "counts": counts,
                "protected": len(self.supplement_parent_groups(project)),
                "moved": sum(current.get(k) != v for k, v in candidate["groups"].items()),
                "coverage": coverage_lines(project, candidate["groups"])}

    def apply_rebalance(self, project: Project, preview: dict) -> None:
        if self.split_revision(project) != preview["revision"]:
            raise ValueError("Dữ liệu đã thay đổi sau bản xem trước. Chưa phân lại; hãy mở xem trước mới.")
        # Recompute rather than trusting an altered candidate supplied by a caller.
        candidate = self.ensure_split_assignment(project, force_rebalance=True, persist=False)
        if candidate["groups"] != preview["assignment"]["groups"]:
            raise ValueError("Phương án phân tập đã thay đổi; hãy xem trước lại.")
        self._write_split_assignment(project, candidate)

    def _write_split_assignment(self, project: Project, assignment: dict) -> None:
        import os
        from tempfile import NamedTemporaryFile
        target = self.split_assignment_path(project)
        previous = target.read_bytes() if target.exists() else None
        if previous is not None:
            old = json.loads(previous)
            if all(old.get(k) == v for k, v in assignment.items() if k != "updated_at"):
                return

        def atomic_write(path, content):
            staged_name = None
            try:
                with NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as staged:
                    staged_name = staged.name
                    staged.write(content)
                    staged.flush()
                    os.fsync(staged.fileno())
                os.replace(staged_name, path)
            finally:
                if staged_name:
                    Path(staged_name).unlink(missing_ok=True)

        if previous is not None and old.get("groups") != assignment["groups"]:
            atomic_write(target.with_name("split_assignment.previous.json"), previous)
        atomic_write(target, json.dumps(assignment, ensure_ascii=False, indent=2).encode("utf-8"))

    @staticmethod
    def _record_groups(records: list) -> dict[str, list]:
        groups: dict[str, list] = defaultdict(list)
        for record in records:
            plant_instance_id = str(getattr(record, "metadata", {}).get("plant_instance_id", ""))
            groups[plant_instance_id or record.capture_group or record.id].append(record)
        return groups

    @staticmethod
    def _independent_crop_cycle_holdout(groups: dict[str, list], split_keys: dict[str, list[str]]) -> bool:
        cycles = {split: set() for split in ("train", "val", "test")}
        for split, keys in split_keys.items():
            for key in keys:
                for record in groups[key]:
                    cycle = str(getattr(record, "metadata", {}).get("cropCycleId", ""))
                    if cycle:
                        cycles[split].add(cycle)
        development = cycles["train"] | cycles["val"]
        return bool(cycles["test"] and cycles["test"].isdisjoint(development))

    def _bootstrap_from_latest_export(self, project: Project, groups: dict[str, list]) -> dict[str, str]:
        """Preserve the most recent historical split when introducing locking."""
        exports_dir = self.store.project_dir(project) / "exports"
        candidates = [path for path in exports_dir.glob("yolo_*") if (path / "export.json").is_file()]
        if not candidates:
            return {}
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        file_to_group = {record.file_name: key for key, records in groups.items() for record in records}
        votes: dict[str, Counter[str]] = defaultdict(Counter)
        for split in ("train", "val", "test"):
            folder = latest / "images" / split
            if not folder.is_dir():
                continue
            for image_path in folder.iterdir():
                group = file_to_group.get(image_path.name)
                if group:
                    votes[group][split] += 1
        return {
            key: counts.most_common(1)[0][0]
            for key, counts in votes.items()
            if counts
        }

    def ensure_split_assignment(
        self,
        project: Project,
        *,
        force_rebalance: bool = False,
        seed: int = 42,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Create/persist stable capture-group assignments.

        Existing groups never move during normal use. Newly imported groups go
        to train by default. A deliberate rebalance is the only operation that
        rewrites the locked benchmark membership.
        persist=False previews the same assignment for read-only package QA.
        """
        path = self.split_assignment_path(project)
        groups = self._record_groups(project.images)
        payload: dict[str, Any] = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError("Không đọc được phân tập đã lưu; chưa thay đổi dữ liệu. "
                                 "Cần kiểm tra/khôi phục split_assignment.json trước khi tiếp tục.") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("groups"), dict):
                raise ValueError("Phân tập đã lưu không hợp lệ; chưa thay đổi dữ liệu.")
            if any(v not in {"train", "val", "test"} for v in payload["groups"].values() if isinstance(v, str)) or any(
                    not isinstance(v, str) for v in payload["groups"].values()):
                raise ValueError("Phân tập chứa tên tập không hợp lệ; chưa thay đổi dữ liệu.")
        assignments = {
            str(key): str(value)
            for key, value in dict(payload.get("groups", {})).items()
            if value in {"train", "val", "test"}
        }
        source = "locked"
        if force_rebalance:
            balanced = self.split_capture_groups(groups, seed, train_only=self.supplement_parent_groups(project))
            assignments = {key: split for split, keys in balanced.items() for key in keys}
            source = "rebalanced"
        elif not assignments:
            assignments = self._bootstrap_from_latest_export(project, groups)
            source = "historical_export" if assignments else "initial_balance"
            if not assignments:
                balanced = self.split_capture_groups(groups, seed, train_only=self.supplement_parent_groups(project))
                assignments = {key: split for split, keys in balanced.items() for key in keys}
        new_groups = []
        for key in groups:
            if key not in assignments:
                assignments[key] = "train"
                new_groups.append(key)
        now = datetime.now().isoformat(timespec="seconds")
        result = {
            "version": 1,
            "locked": True,
            "seed": seed,
            "created_at": payload.get("created_at", now),
            "updated_at": now,
            "source": source if force_rebalance or not payload else payload.get("source", source),
            "new_group_policy": "train",
            "groups": assignments,
        }
        if persist:
            self._write_split_assignment(project, result)
        return result

    def split_summary(self, project: Project) -> dict[str, Any]:
        assignment = self.ensure_split_assignment(project, persist=False)
        groups = self._record_groups(project.images)
        counts = {split: 0 for split in ("train", "val", "test")}
        group_counts = {split: 0 for split in counts}
        for key, records in groups.items():
            split = assignment["groups"].get(key, "train")
            counts[split] += len(records)
            group_counts[split] += 1
        return {
            "counts": counts,
            "group_counts": group_counts,
            "path": "split_assignment.json",
            "source": assignment.get("source", "locked"),
            "new_group_policy": assignment.get("new_group_policy", "train"),
        }

    def split_group_rows(self, project: Project) -> list[dict[str, Any]]:
        from .benchmark_contract import source_identity, cycle_title, cycle_key
        assignment = self.ensure_split_assignment(project, persist=False)
        groups = self._record_groups(project.images)
        rows = []
        for key, records in groups.items():
            rows.append({
                "group": key,
                "split": assignment["groups"].get(key, "train"),
                "images": len(records),
                "reviewed": sum(record.review_status == "reviewed" for record in records),
                "annotations": sum(len(record.annotations) for record in records),
                "cycles": sorted({cycle_key(source_identity(record)) for record in records}),
                "sources": " | ".join(sorted({cycle_title(source_identity(record)) for record in records})),
                "dates": sorted({str(record.metadata.get("capturedAt") or "")[:10] for record in records} - {""}),
            })
            if project.metadata.get("template") == "Hydroponic Slot Condition":
                from dataclasses import replace
                from .hydro_statistics import attribute_summary
                subset = attribute_summary(replace(project, images=records), assignment["groups"])
                rows[-1]["label_counts"] = " · ".join(
                    f"{item['title']} {item['splits'][rows[-1]['split']].get('positive', 0)}/"
                    f"{item['splits'][rows[-1]['split']].get('negative', 0)}" for item in subset)
        order = {"test": 0, "val": 1, "train": 2}
        return sorted(rows, key=lambda item: (order[item["split"]], -item["images"], item["group"]))

    def set_group_split(self, project: Project, group_key: str, split: str) -> None:
        self.set_groups_split(project, [group_key], split)

    def set_groups_split(self, project: Project, group_keys: list[str], split: str, *, expected_revision=None) -> None:
        if split not in {"train", "val", "test"}:
            raise ValueError(f"Tập không hợp lệ: {split}")
        if expected_revision is not None and self.split_revision(project) != expected_revision:
            raise ValueError("Dữ liệu đã thay đổi; hãy tải lại danh sách trước khi chuyển nhóm.")
        assignment = self.ensure_split_assignment(project, persist=False)
        current_groups = self._record_groups(project.images)
        if not group_keys or any(key not in current_groups for key in group_keys):
            raise KeyError("Không tìm thấy nhóm đã chọn; chưa thay đổi phân tập.")
        if split != "train":
            from .split_health import SplitConflictError
            parents = self.supplement_parent_groups(project)
            conflicts = {key: parents[key] for key in group_keys if key in parents}
            if conflicts:
                raise SplitConflictError(conflicts)
        for key in group_keys:
            assignment["groups"][key] = split
        assignment["updated_at"] = datetime.now().isoformat(timespec="seconds")
        assignment["source"] = "manual"
        self._write_split_assignment(project, assignment)

    def _split_keys_for_strategy(
        self,
        project: Project,
        groups: dict[str, list],
        strategy: str,
    ) -> dict[str, list[str]]:
        assignment = self.ensure_split_assignment(project)
        locked = {split: [] for split in ("train", "val", "test")}
        for key in groups:
            locked[assignment["groups"].get(key, "train")].append(key)
        if strategy == self.STRATEGY_LOCKED:
            return locked
        if strategy == self.STRATEGY_FINAL_KEEP_TEST:
            return {
                "train": locked["train"] + locked["val"],
                "val": [],
                "test": locked["test"],
            }
        if strategy == self.STRATEGY_TRAIN_ALL:
            return {"train": list(groups), "val": [], "test": []}
        raise ValueError(f"Chiến lược phân tập không hợp lệ: {strategy}")

    def create_version(self, project: Project, name: str = "") -> Path:
        require_legacy_project(project, self.store)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_name = name.strip() or f"dataset_{stamp}"
        version_dir = self.store.project_dir(project) / "versions" / version_name
        if version_dir.exists():
            raise FileExistsError(f"Phiên bản đã tồn tại: {version_name}")
        version_dir.mkdir(parents=True)
        manifest = {
            "version": version_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "project": project.to_dict(),
            "summary": self.summary(project),
            "split_assignment": self.ensure_split_assignment(project),
            "image_sha256": {
                record.id: self._sha256(self.store.image_path(project, record))
                for record in project.images
                if self.store.image_path(project, record).exists()
            },
        }
        (version_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return version_dir

    @staticmethod
    def split_capture_groups(groups: dict[str, list], seed: int = 42, *, train_only=()) -> dict[str, list[str]]:
        """Split whole capture groups while balancing the number of images.

        Splitting merely by group count can be very skewed when one video group
        contains dozens of frames. This greedy allocator targets 70/15/15 by
        image count and never places one capture group in multiple splits.
        """
        keys = sorted(groups)
        random.Random(seed).shuffle(keys)
        order = {key: index for index, key in enumerate(keys)}
        keys.sort(key=lambda key: (-len(groups[key]), order[key]))
        total = sum(len(groups[key]) for key in keys)
        targets = {"train": total * 0.70, "val": total * 0.15, "test": total * 0.15}
        result: dict[str, list[str]] = {"train": [], "val": [], "test": []}
        counts = {name: 0 for name in result}
        allowed = ["train"]
        if len(keys) >= 2:
            allowed.append("val")
        if len(keys) >= 3:
            allowed.append("test")
        protected = set(train_only)
        for key in keys:
            if key in protected:
                result["train"].append(key)
                counts["train"] += len(groups[key])
        for key in keys:
            if key in protected:
                continue
            split = max(
                allowed,
                key=lambda name: (targets[name] - counts[name], targets[name], -allowed.index(name)),
            )
            result[split].append(key)
            counts[split] += len(groups[key])
        return result

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _unique_directory(parent: Path, base_name: str) -> Path:
        candidate = parent / base_name
        index = 2
        while candidate.exists():
            candidate = parent / f"{base_name}_{index}"
            index += 1
        return candidate

    def export_yolo(
        self,
        project: Project,
        *,
        segmentation: bool = False,
        task: str | None = None,
        reviewed_only: bool = True,
        seed: int = 42,
        split_strategy: str = STRATEGY_LOCKED,
    ) -> Path:
        task = task or ("segment" if segmentation else "detect")
        require_legacy_project(project, self.store)
        if task not in {"detect", "segment", "obb", "pose"}:
            raise ValueError(f"Task YOLO không hỗ trợ: {task}")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = self._unique_directory(
            self.store.project_dir(project) / "exports",
            f"yolo_{task}_{stamp}",
        )
        for split in ("train", "val", "test"):
            (export_dir / "images" / split).mkdir(parents=True, exist_ok=True)
            (export_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

        records = [i for i in project.images if not reviewed_only or i.review_status == "reviewed"]
        groups = self._record_groups(records)
        split_keys = self._split_keys_for_strategy(project, groups, split_strategy)
        exported_annotations = 0
        skipped_annotations = 0
        # Ensure tiny datasets still produce a valid training folder.
        for split, selected in split_keys.items():
            for key in selected:
                for record in groups[key]:
                    source = self.store.image_path(project, record)
                    shutil.copy2(source, export_dir / "images" / split / record.file_name)
                    label_path = export_dir / "labels" / split / f"{Path(record.file_name).stem}.txt"
                    lines = []
                    for ann in record.annotations:
                        line = self._to_yolo_task(ann, record.width, record.height, task)
                        if line:
                            lines.append(line)
                            exported_annotations += 1
                        else:
                            skipped_annotations += 1
                    label_path.write_text("\n".join(line for line in lines if line), encoding="utf-8")
        validation_enabled = split_strategy == self.STRATEGY_LOCKED and bool(split_keys["val"])
        test_enabled = split_strategy != self.STRATEGY_TRAIN_ALL and bool(split_keys["test"])
        val_path = (
            "images/val" if validation_enabled else
            "images/test" if split_strategy == self.STRATEGY_FINAL_KEEP_TEST else
            "images/train"
        )
        yaml_text = [
            "path: .",
            "train: images/train",
            f"val: {val_path}",
            f"test: {'images/test' if test_enabled else ''}",
            "names:",
        ]
        yaml_text.extend(f"  {item.id}: {item.name}" for item in project.classes)
        if task == "pose":
            yaml_text.extend(["kpt_shape: [2, 3]", "kpt_names:"])
            for item in project.classes:
                yaml_text.extend([f"  {item.id}:", "    - center", "    - direction"])
        (export_dir / "data.yaml").write_text("\n".join(yaml_text) + "\n", encoding="utf-8")
        metadata = {
            "project_id": project.id,
            "reviewed_only": reviewed_only,
            "segmentation": task == "segment",
            "task": task,
            "exported_annotations": exported_annotations,
            "skipped_annotations": skipped_annotations,
            "seed": seed,
            "split_strategy": split_strategy,
            "split_locked": True,
            "validation_enabled": validation_enabled,
            "independent_test": test_enabled,
            "split_assignment": "split_assignment.json",
            "counts": {split: sum(len(groups[k]) for k in selected) for split, selected in split_keys.items()},
        }
        (export_dir / "export.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return export_dir

    def export_classification(
        self,
        project: Project,
        attribute_key: str,
        *,
        reviewed_only: bool = True,
        seed: int = 42,
        padding_ratio: float = 0.05,
        split_strategy: str = STRATEGY_LOCKED,
    ) -> Path:
        """Export object crops for a second-stage, single-label classifier.

        Detection/SEG first finds the object.  The classifier then receives
        each crop and predicts one configured attribute group.
        """
        require_legacy_project(project, self.store)
        values = project.attribute_schema.get(attribute_key, [])
        if not values:
            raise ValueError("Nhóm thuộc tính Classification không tồn tại hoặc chưa có lựa chọn.")
        settings = project.attribute_settings.get(attribute_key, {})
        title = settings.get("title", attribute_key)
        scope = settings.get("scope", "annotation_crop")
        if scope not in {"annotation_crop", "image"}:
            raise ValueError(f"Classification scope không hỗ trợ: {scope}")
        if scope == "image" and not reviewed_only:
            raise ValueError("Image-level Classification chỉ được export từ ảnh đã Duyệt.")
        excluded_values = set(settings.get("train_exclude", [])) | {"uncertain", "not_applicable"}
        hydro_attribute = None
        if project.metadata.get("template") == "Hydroponic Slot Condition":
            from .hydro_labels import model_attributes
            from .label_schema import meaning_for
            attrs = model_attributes(project)
            hydro_attribute = next((a for a in attrs if a["id"] == attribute_key), None)
            if hydro_attribute:
                excluded_values.update(v["id"] for v in hydro_attribute["values"]
                                       if v["meaning"] in {"uncertain", "not_applicable"})
        train_values = [value for value in values if value not in excluded_values]
        if not train_values:
            raise ValueError("Nhóm Classification không còn nhãn train sau khi loại uncertain/not_applicable.")
        supplements = []
        if hydro_attribute and scope == "image":
            from .training_supplements import validated_samples
            supplements = validated_samples(self.store, project, hydro_attribute,
                                            self.ensure_split_assignment(project, persist=False)["groups"])
            if any(value not in train_values for _, value, _ in supplements):
                raise ValueError("Nhãn ảnh bổ trợ đang bị loại khỏi train; cần kiểm tra lại cấu hình thuộc tính.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = self._unique_directory(
            self.store.project_dir(project) / "exports",
            f"classify_{attribute_key}_{stamp}",
        )

        class_folders: dict[str, str] = {}
        used_folders: set[str] = set()
        for index, value in enumerate(train_values):
            safe = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .") or f"class_{index}"
            if safe.lower() in used_folders:
                safe = f"{safe}_{index}"
            used_folders.add(safe.lower())
            class_folders[value] = safe
        for split in ("train", "val", "test"):
            for folder in class_folders.values():
                (export_dir / split / folder).mkdir(parents=True, exist_ok=True)

        records = [record for record in project.images if not reviewed_only or record.review_status == "reviewed"]
        groups = self._record_groups(records)
        split_keys = self._split_keys_for_strategy(project, groups, split_strategy)

        counts: Counter[str] = Counter()
        skipped_missing = 0
        skipped_geometry = 0
        write_split_keys = {split: list(keys) for split, keys in split_keys.items()}
        synthetic_validation = split_strategy != self.STRATEGY_LOCKED
        if split_strategy == self.STRATEGY_FINAL_KEEP_TEST:
            write_split_keys["val"] = list(split_keys["test"])
        elif split_strategy == self.STRATEGY_TRAIN_ALL:
            write_split_keys["val"] = list(split_keys["train"])
        physical_crops = 0
        class_counts_by_split = {s: Counter({v: 0 for v in train_values}) for s in ("train", "val", "test")}
        for split, selected in write_split_keys.items():
            for group_key in selected:
                for record in groups[group_key]:
                    source = self.store.image_path(project, record)
                    with Image.open(source) as opened:
                        image = opened.convert("RGB")
                        if scope == "image":
                            value = record.attributes.get(attribute_key, "")
                            if hydro_attribute and hydro_attribute["role"] == "condition":
                                presence = next(a for a in attrs if a["role"] == "presence")
                                if meaning_for(presence, record.attributes.get(presence["id"])) != "positive":
                                    skipped_missing += 1
                                    continue
                            if value not in class_folders:
                                skipped_missing += 1
                                continue
                            target = export_dir / split / class_folders[value] / record.file_name
                            image.save(target, quality=95)
                            physical_crops += 1
                            if not (synthetic_validation and split == "val"):
                                counts[value] += 1
                                class_counts_by_split[split][value] += 1
                            continue
                        for ann in record.annotations:
                            value = ann.attributes.get(attribute_key, "")
                            if value not in class_folders:
                                skipped_missing += 1
                                continue
                            if len(ann.bbox) != 4:
                                skipped_geometry += 1
                                continue
                            x, y, width, height = ann.bbox
                            pad_x, pad_y = width * padding_ratio, height * padding_ratio
                            left = max(0, int(x - pad_x))
                            top = max(0, int(y - pad_y))
                            right = min(record.width, int(x + width + pad_x + 0.999))
                            bottom = min(record.height, int(y + height + pad_y + 0.999))
                            if right - left < 2 or bottom - top < 2:
                                skipped_geometry += 1
                                continue
                            crop = image.crop((left, top, right, bottom))
                            target = export_dir / split / class_folders[value] / f"{Path(record.file_name).stem}_{ann.id}.jpg"
                            crop.save(target, quality=95)
                            physical_crops += 1
                            if not (synthetic_validation and split == "val"):
                                counts[value] += 1
                                class_counts_by_split[split][value] += 1

        supplement_manifest = []
        for source, value, provenance in supplements:
            # Added after any compatibility VAL mirror: supplements are TRAIN only.
            target = export_dir / "train" / class_folders[value] / f"supplement_{provenance['sha256']}.jpg"
            with Image.open(source) as opened:
                opened.convert("RGB").save(target, quality=95)
            counts[value] += 1
            class_counts_by_split["train"][value] += 1
            physical_crops += 1
            supplement_manifest.append({**provenance, "exportedFile": target.relative_to(export_dir).as_posix()})
        exported = sum(counts.values())
        if not exported:
            raise ValueError(
                f"Không có crop nào để train nhóm “{title}”. Hãy gán thuộc tính cho nhãn"
                + (" và Duyệt ảnh." if reviewed_only else ".")
            )
        from .benchmark_contract import source_identity
        metadata = {
            "project_id": project.id,
            "task": "classify",
            "source_records": [{"fileName": r.file_name, "source": source_identity(r), "originalSha256": r.sha256}
                               for r in records] if scope == "image" else [],
            "attribute_key": attribute_key,
            "attribute_title": title,
            "classification_scope": scope,
            "excluded_labels": sorted(excluded_values),
            **({"label_attribute": hydro_attribute} if hydro_attribute else {}),
            "reviewed_only": reviewed_only,
            "padding_ratio": padding_ratio,
            "classes": class_folders,
            "counts": dict(counts),
            "class_counts_by_split": {s: dict(c) for s, c in class_counts_by_split.items()},
            "split_counts": {
                split: sum(len(groups[key]) for key in selected)
                for split, selected in split_keys.items()
            },
            "exported_crops": exported,
            "physical_crops": physical_crops,
            "training_supplements": supplement_manifest,
            "supplement_count": len(supplement_manifest),
            "skipped_missing_attribute": skipped_missing,
            "skipped_invalid_geometry": skipped_geometry,
            "seed": seed,
            "split_strategy": split_strategy,
            "split_locked": True,
            "validation_enabled": split_strategy == self.STRATEGY_LOCKED and bool(split_keys["val"]),
            "independent_test": split_strategy != self.STRATEGY_TRAIN_ALL and bool(split_keys["test"]),
            "split_assignment": "split_assignment.json",
            "validation_status": (
                "validated_holdout"
                if self._independent_crop_cycle_holdout(groups, split_keys)
                else "pilot_unvalidated"
            ),
        }
        (export_dir / "export.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return export_dir

    @classmethod
    def _to_yolo_task(cls, ann: Annotation, width: int, height: int, task: str) -> str:
        if task == "detect":
            return cls._to_yolo(ann, width, height, False)
        if task == "segment":
            return cls._to_yolo(ann, width, height, True)
        if task == "obb":
            points = ann.obb if len(ann.obb) == 4 else []
            if not points and len(ann.bbox) == 4:
                x, y, w, h = ann.bbox
                points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            if len(points) != 4:
                return ""
            values = " ".join(f"{x / width:.6f} {y / height:.6f}" for x, y in points)
            return f"{ann.class_id} {values}"
        if task == "pose":
            if len(ann.bbox) != 4 or len(ann.orientation) != 2:
                return ""
            x, y, w, h = ann.bbox
            box = f"{(x + w / 2) / width:.6f} {(y + h / 2) / height:.6f} {w / width:.6f} {h / height:.6f}"
            keypoints = " ".join(f"{px / width:.6f} {py / height:.6f} 2" for px, py in ann.orientation)
            return f"{ann.class_id} {box} {keypoints}"
        return ""

    @staticmethod
    def _to_yolo(ann: Annotation, width: int, height: int, segmentation: bool) -> str:
        if segmentation and ann.points and len(ann.points) >= 3:
            points = " ".join(f"{x / width:.6f} {y / height:.6f}" for x, y in ann.points)
            return f"{ann.class_id} {points}"
        if segmentation:
            return ""
        if len(ann.bbox) != 4:
            return ""
        x, y, w, h = ann.bbox
        return f"{ann.class_id} {(x + w / 2) / width:.6f} {(y + h / 2) / height:.6f} {w / width:.6f} {h / height:.6f}"

    def export_coco(self, project: Project, reviewed_only: bool = True) -> Path:
        require_legacy_project(project, self.store)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.store.project_dir(project) / "exports" / f"coco_{stamp}.json"
        images = []
        annotations = []
        annotation_id = 1
        for image_index, record in enumerate(project.images, start=1):
            if reviewed_only and record.review_status != "reviewed":
                continue
            images.append({"id": image_index, "file_name": record.file_name, "width": record.width, "height": record.height})
            for ann in record.annotations:
                segmentation = []
                if ann.points:
                    segmentation = [[coordinate for point in ann.points for coordinate in point]]
                area = ann.bbox[2] * ann.bbox[3] if len(ann.bbox) == 4 else 0
                annotations.append({
                    "id": annotation_id,
                    "image_id": image_index,
                    "category_id": ann.class_id,
                    "bbox": ann.bbox,
                    "area": area,
                    "segmentation": segmentation,
                    "iscrowd": 0,
                    "attributes": ann.attributes,
                    "source": ann.source,
                    "approved": ann.approved,
                })
                annotation_id += 1
        payload = {
            "info": {"description": project.name, "version": "1.0"},
            "images": images,
            "annotations": annotations,
            "categories": [{"id": item.id, "name": item.name} for item in project.classes],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
