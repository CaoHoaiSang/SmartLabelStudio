from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
import hashlib
import json
import re
import shutil

from PIL import Image, ImageStat

from .models import ImageRecord, LabelClass, Project, new_id, utc_now


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


class ProjectStore:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()
        self.projects_dir = self.workspace / "projects"
        self.models_dir = self.workspace / "models"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[Path]:
        return sorted(self.projects_dir.glob("*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    def project_dir(self, project: Project) -> Path:
        return self.projects_dir / project.id

    def image_path(self, project: Project, record: ImageRecord) -> Path:
        return self.project_dir(project) / "images" / record.file_name

    def create_project(
        self,
        name: str,
        task: str = "instance_segmentation",
        classes: list[str] | None = None,
    ) -> Project:
        project = Project.create(name=name, task=task)
        palette = ["#21c7ff", "#74e35c", "#ffb547", "#f55d76", "#ad8cff", "#42d9c8"]
        for index, class_name in enumerate(classes or []):
            project.classes.append(LabelClass(index, class_name, palette[index % len(palette)]))
        target = self.project_dir(project)
        for folder in ("images", "versions", "exports", "runs", "cache"):
            (target / folder).mkdir(parents=True, exist_ok=True)
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        project.updated_at = utc_now()
        target = self.project_dir(project)
        target.mkdir(parents=True, exist_ok=True)
        path = target / "project.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def load(self, path_or_id: str | Path) -> Project:
        path = Path(path_or_id)
        if not path.exists():
            path = self.projects_dir / str(path_or_id) / "project.json"
        elif path.is_dir():
            path = path / "project.json"
        return Project.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def ensure_import_batches(self, project: Project, legacy_gap_seconds: int = 60) -> bool:
        """Migrate pre-batch projects using conservative import-time sessions.

        Old project files only contain ``created_at``. Consecutive records less
        than one minute apart are treated as one legacy import operation. This
        changes metadata only; image files, labels and review states are not
        touched.
        """

        def created(record: ImageRecord) -> float:
            try:
                return datetime.fromisoformat(record.created_at).timestamp()
            except (TypeError, ValueError, OSError):
                return 0.0

        ordered = sorted(enumerate(project.images), key=lambda pair: (created(pair[1]), pair[0]))
        if not ordered:
            return False
        changed = False
        current_batch = ""
        last_unbatched_time: float | None = None
        session_number = 0
        for _index, record in ordered:
            timestamp = created(record)
            if record.import_batch:
                current_batch = ""
                last_unbatched_time = None
                continue
            gap = None if last_unbatched_time is None else timestamp - last_unbatched_time
            if not current_batch or gap is None or gap < 0 or gap > legacy_gap_seconds:
                session_number += 1
                stamp = record.created_at[:19].replace(":", "").replace("-", "") or "unknown"
                current_batch = f"legacy_{stamp}_{session_number:03d}"
            record.import_batch = current_batch
            last_unbatched_time = timestamp
            changed = True

        latest_batch = ordered[-1][1].import_batch
        valid_batches = {record.import_batch for record in project.images if record.import_batch}
        if project.last_import_batch not in valid_batches or project.last_import_batch != latest_batch:
            project.last_import_batch = latest_batch
            changed = True
        if changed:
            self.save(project)
        return changed

    def import_images(
        self,
        project: Project,
        inputs: Iterable[str | Path],
        progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[int, int]:
        files: list[Path] = []
        for item in inputs:
            path = Path(item)
            if path.is_dir():
                files.extend(p for p in path.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)
            elif path.suffix.lower() in IMAGE_EXTENSIONS:
                files.append(path)
        known_hashes = {self._hash_file(self.image_path(project, image)) for image in project.images if self.image_path(project, image).exists()}
        import_batch = new_id("import")
        added = skipped = 0
        images_dir = self.project_dir(project) / "images"
        for index, source in enumerate(sorted(set(files)), start=1):
            if progress:
                progress(index, len(files), source.name)
            digest = self._hash_file(source)
            if digest in known_hashes:
                skipped += 1
                continue
            file_name = f"{digest[:10]}_{source.name}"
            destination = images_dir / file_name
            shutil.copy2(source, destination)
            with Image.open(destination) as image:
                width, height = image.size
                gray = image.convert("L").resize((256, 256))
                stat = ImageStat.Stat(gray)
                brightness = float(stat.mean[0])
                contrast = float(stat.stddev[0])
            project.images.append(
                ImageRecord(
                    id=new_id("img"),
                    file_name=file_name,
                    source_path=str(source.resolve()),
                    capture_group=self._capture_group(source),
                    import_batch=import_batch,
                    width=width,
                    height=height,
                    quality={"brightness": round(brightness, 2), "contrast": round(contrast, 2)},
                )
            )
            known_hashes.add(digest)
            added += 1
        if added:
            project.last_import_batch = import_batch
        self.save(project)
        return added, skipped

    def delete_image(self, project: Project, record: ImageRecord) -> int:
        """Delete one project image and its complete annotation record.

        Imported images are project-owned copies, so the original file named by
        ``source_path`` is deliberately never touched. Existing exports are also
        immutable snapshots and are not rewritten here.

        Returns the number of annotations removed with the image.
        """
        if record not in project.images:
            raise ValueError("Ảnh không còn tồn tại trong dự án.")

        image_path = self.image_path(project, record)
        annotation_count = len(record.annotations)
        project.images.remove(record)
        try:
            self.save(project)
        except Exception:
            project.images.append(record)
            raise

        try:
            image_path.unlink(missing_ok=True)
        except OSError as exc:
            # The metadata is already gone, but report an actionable cleanup
            # error instead of silently leaving an unreferenced project copy.
            raise OSError(f"Đã xóa dữ liệu nhãn nhưng chưa xóa được file ảnh: {image_path}") from exc
        return annotation_count

    def delete_images(self, project: Project, records: Iterable[ImageRecord]) -> tuple[int, int]:
        """Delete multiple project-owned images with a single metadata save."""
        record_ids = {record.id for record in records}
        targets = [record for record in project.images if record.id in record_ids]
        if not targets:
            return 0, 0
        annotation_count = sum(len(record.annotations) for record in targets)
        paths = [self.image_path(project, record) for record in targets]
        previous = list(project.images)
        project.images = [record for record in project.images if record.id not in record_ids]
        try:
            self.save(project)
        except Exception:
            project.images = previous
            raise
        failures = []
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures.append(str(path))
        if failures:
            raise OSError(
                f"Đã xóa dữ liệu của {len(targets)} ảnh nhưng còn {len(failures)} file không xóa được. "
                f"File đầu tiên: {failures[0]}"
            )
        return len(targets), annotation_count

    def cleanup_stale_video_cache(self, project: Project) -> tuple[int, int]:
        """Remove only interrupted ``video_extract_*`` temporary directories."""
        cache_dir = (self.project_dir(project) / "cache").resolve()
        removed_dirs = 0
        removed_files = 0
        for target in cache_dir.glob("video_extract_*"):
            resolved = target.resolve()
            if not target.is_dir() or cache_dir not in resolved.parents:
                continue
            removed_files += sum(1 for path in resolved.rglob("*") if path.is_file())
            shutil.rmtree(resolved)
            removed_dirs += 1
        return removed_dirs, removed_files

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def register_model(self, source: str | Path) -> Path:
        source = Path(source).resolve()
        digest = self._hash_file(source)[:12]
        target = self.models_dir / f"{source.stem}_{digest}{source.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source, target)
        return target

    def import_video(
        self,
        project: Project,
        video_path: str | Path,
        every_n_frames: int = 10,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[int, int]:
        import cv2

        video_path = Path(video_path).resolve()
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Không mở được video: {video_path}")
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_index = 0
        saved = 0
        temp_dir = self.project_dir(project) / "cache" / f"video_{new_id('extract')}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            extracted: list[Path] = []
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % max(1, every_n_frames) == 0:
                    path = temp_dir / f"{video_path.stem}_frame_{frame_index:08d}.jpg"
                    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    extracted.append(path)
                    saved += 1
                if progress and frame_index % 30 == 0:
                    progress(frame_index, total, video_path.name)
                frame_index += 1
            added, skipped = self.import_images(project, extracted)
            # Mark all extracted frames as one capture sequence, preventing leakage.
            extracted_names = {str(path.resolve()) for path in extracted}
            for record in project.images:
                if record.source_path in extracted_names:
                    record.capture_group = f"video_{video_path.stem}"
                    record.source_path = f"{video_path}#frame"
            self.save(project)
            return added, skipped
        finally:
            capture.release()
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _capture_group(path: Path) -> str:
        # Keep adjacent timestamped frames together so they cannot leak across
        # train/validation/test. For ordinary still images each file is its own group.
        match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2})", path.name)
        if match:
            return f"{path.parent.name}_{match.group(1)}"
        return f"{path.parent.name}_{path.stem}"
