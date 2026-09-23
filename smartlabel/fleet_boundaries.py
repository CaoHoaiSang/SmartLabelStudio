"""Fail closed for Fleet material in legacy dataset/train entry points.

This is containment while managed snapshot/withdrawal support is incomplete,
not a replacement for that future online gate. Unrelated legacy data stays local.
"""
import json
import os
from pathlib import Path

from .fleet_intake import FleetIntakeError, reject_generic_fleet_sources

MESSAGE = ("Dữ liệu Fleet chưa được dùng qua luồng dataset/train cũ. Cần snapshot có quản lý "
           "và kiểm tra quyền rút dữ liệu; không chép ảnh hoặc đổi cờ để bỏ qua bước này.")
MARKERS = {"fleetContributionId", "fleetContribution", "fleetDependencies", "fleetLineage", "fleetDataset", "fleetSourceGroupId"}


def reject_benchmark_sources(paths):
    for path in paths:
        resolved = Path(path).resolve()
        for parent in (resolved, *resolved.parents):
            if parent.is_dir() and any((parent / name).exists() for name in ("benchmark.json", "heldout_collection.json", "heldout_frame.json")):
                raise ValueError("Bộ TEST ngoài chỉ dành cho đánh giá, không được nhập vào TRAIN/VAL.")


def reject_fleet_metadata(value):
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if not isinstance(item, (dict, list)) or id(item) in seen:
            continue
        seen.add(id(item))
        if len(seen) > 200000:
            raise FleetIntakeError("Bản kê dataset vượt giới hạn kiểm tra.")
        if isinstance(item, dict):
            if (MARKERS.intersection(item) or str(item.get("schemaVersion", "")).startswith("Fleet")
                    or item.get("source") in ("fleet", "fleet_contribution")):
                raise FleetIntakeError(MESSAGE)
            pending.extend(item.values())
        else:
            pending.extend(item)


def require_legacy_project(project, store=None):
    reject_fleet_metadata(project.metadata)
    files = []
    for record in project.images:
        reject_fleet_metadata(record.metadata)
        reject_fleet_metadata(record.lineage)
        files.append(store.image_path(project, record) if store is not None else Path(record.file_name))
        if record.source_path and "://" not in record.source_path:
            files.append(Path(record.source_path))
    reject_generic_fleet_sources(files)
    reject_benchmark_sources(files)


def _metadata(folder):
    if (folder / "fleet_lineage.json").exists():
        raise FleetIntakeError(MESSAGE)
    for name in ("export.json", "manifest.json"):
        file = folder / name
        if not file.exists():
            continue
        if not file.is_file() or file.is_symlink() or file.stat().st_size > 64 * 1024 * 1024:
            raise FleetIntakeError("Không xác minh được bản kê dataset.")
        try:
            reject_fleet_metadata(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            if isinstance(error, FleetIntakeError):
                raise
            raise FleetIntakeError("Bản kê dataset không đọc được; chưa mở train.") from None


def _dataset_paths(target):
    """Walk path names only; do not follow directory links into another dataset."""
    yield target
    if target.is_dir():
        for root, folders, files in os.walk(target, followlinks=False):
            for name in folders + files:
                yield Path(root) / name
    elif target.is_file() and target.suffix.lower() == ".txt":
        if target.stat().st_size > 4 * 1024 * 1024:
            raise FleetIntakeError("Danh sách ảnh dataset vượt giới hạn kiểm tra.")
        lines = target.read_text(encoding="utf-8").splitlines()
        if len(lines) > 50000:
            raise FleetIntakeError("Danh sách ảnh dataset vượt giới hạn kiểm tra.")
        for line in lines:
            if line.strip():
                yield target.parent / line.strip()
                yield Path(line.strip()).absolute()


def require_legacy_training_data(data):
    if not data:
        return  # Existing validation is responsible for missing generic training inputs.
    file = Path(data)
    reject_generic_fleet_sources(_dataset_paths(file))
    reject_benchmark_sources(_dataset_paths(file))
    if not file.exists():
        return
    folder = file if file.is_dir() else file.parent
    _metadata(folder)
    if file.is_file() and file.suffix.lower() in {".yaml", ".yml"}:
        if file.stat().st_size > 1024 * 1024:
            raise FleetIntakeError("Cấu hình dataset vượt giới hạn kiểm tra.")
        import yaml  # Already used by SmartLabel/Ultralytics; never execute YAML constructors.
        try:
            value = yaml.safe_load(file.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            raise FleetIntakeError("Không đọc được cấu hình dataset để kiểm tra nguồn.") from None
        reject_fleet_metadata(value)
        if not isinstance(value, dict):
            raise FleetIntakeError("Cấu hình dataset không hợp lệ.")
        base = value.get("path", ".")
        if not isinstance(base, str):
            raise FleetIntakeError("Đường dẫn dataset không hợp lệ.")
        # Validate both the YAML-relative and working-directory interpretations;
        # Ultralytics resolves dataset roots according to its own configuration.
        roots = {folder / base, Path(base).absolute()}
        for root in roots:
            reject_generic_fleet_sources([root]); _metadata(root)
            for key in ("train", "val", "test"):
                entries = value.get(key, [])
                entries = entries if isinstance(entries, list) else [entries]
                for entry in entries:
                    if entry is None:
                        continue
                    if not isinstance(entry, str):
                        raise FleetIntakeError("Danh sách ảnh dataset không hợp lệ.")
                    reject_generic_fleet_sources(_dataset_paths(root / entry))
                    reject_benchmark_sources(_dataset_paths(root / entry))
