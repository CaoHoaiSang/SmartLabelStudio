"""Real, temporary image exports; no user project, model download or training."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

from PIL import Image
from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.models import ImageRecord, Annotation
from smartlabel.project_store import ProjectStore
from smartlabel.training_preparation import TrainingPreparationJob, PreparationProgress, PreparationCancelled, inspect_model


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ProjectStore(Path(temp.name) / "workspace")
        self.project = self.store.create_project("Preparation", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.datasets = DatasetManager(self.store)
        for split in ("train", "val", "test"):
            for index in range(3):
                record = ImageRecord(id=f"{split}{index}", file_name=f"{split}{index}.png",
                    width=16, height=16, capture_group=split, asset_role="slot", review_status="reviewed",
                    attributes={"plant_presence": "absent" if index == 0 else "present",
                                "yellow_leaf": "present" if index == 1 else "absent", "wilt": "absent"})
                self.project.images.append(record)
                Image.new("RGB", (16, 16), (index * 50, 80, 0)).save(self.store.image_path(self.project, record))
        self.store.save(self.project)
        self.split = self.datasets.split_assignment_path(self.project)
        self.split.write_text(json.dumps({"groups": {s: s for s in ("train", "val", "test")}}))
        self.datasets.ensure_split_assignment(self.project)
        self.request = {"task": "classify", "keys": [("plant_presence", "Cây hiện diện")],
                        "reviewed_only": True, "options": {"model": "fixture-cls.pt", "epochs": 1,
                            "image_size": 224, "batch": 1, "patience": 0, "device": "cpu",
                            "split_strategy": "locked", "validate": True}}
        self.events = []
        self.exports = self.store.project_dir(self.project) / "exports"

    def job(self, emit=None):
        return TrainingPreparationJob(self.project, self.datasets, self.request,
                                      emit or (lambda kind, value: self.events.append((kind, value))))

    def completion(self):
        complete = [value for kind, value in self.events if kind == "train_prepare_done"]
        self.assertEqual(len(complete), 1)
        return complete[0]

    def test_real_export_in_background_preserves_split_and_model(self):
        project_before = (self.store.project_dir(self.project) / "project.json").read_bytes()
        split_before = self.split.read_bytes()
        thread_ids = []
        def emit(kind, value):
            thread_ids.append(get_ident())
            self.events.append((kind, value))
        job = self.job(emit)
        job.start()
        job.thread.join(10)
        self.assertFalse(job.thread.is_alive())
        _, result, error, cancelled = self.completion()
        self.assertIsNone(error)
        self.assertFalse(cancelled)
        self.assertTrue(all(identifier != get_ident() for identifier in thread_ids))
        _, path, metadata = result["prepared"][0]
        self.assertEqual(metadata["class_counts_by_split"]["train"], {"absent": 1, "present": 2})
        self.assertTrue((path / "export.json").is_file())
        self.assertEqual(self.split.read_bytes(), split_before)
        self.assertEqual((self.store.project_dir(self.project) / "project.json").read_bytes(), project_before)

    def test_snapshot_ignores_later_in_memory_label_and_setting_edits(self):
        job = self.job()
        self.request["options"]["epochs"] = 99
        self.project.images[1].attributes["plant_presence"] = "absent"
        job._run()
        _, result, error, _ = self.completion()
        self.assertIsNone(error)
        self.assertEqual(result["options"]["epochs"], 1)
        self.assertEqual(result["prepared"][0][2]["class_counts_by_split"]["train"]["present"], 2)

    def test_cancel_during_export_removes_only_job_owned_files(self):
        old = self.exports / "older_snapshot"
        old.mkdir(parents=True)
        (old / "keep.txt").write_text("keep")
        def emit(kind, value):
            self.events.append((kind, value))
            if kind == "train_prepare_progress" and value[1].startswith("Xuất ảnh ·"):
                value[0].stop()
        self.job(emit)._run()
        _, result, error, cancelled = self.completion()
        self.assertTrue(cancelled)
        self.assertIsNone(error)
        self.assertIsNone(result)
        self.assertEqual(list(self.exports.iterdir()), [old])
        self.assertEqual((old / "keep.txt").read_text(), "keep")

    def test_later_classifier_failure_discards_entire_new_batch(self):
        self.request["keys"].append(("wilt", "Héo"))  # Single class only; must fail safely.
        self.job()._run()
        _, result, error, cancelled = self.completion()
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertFalse(cancelled)
        self.assertFalse(list(self.exports.iterdir()))

    def test_split_change_mid_export_blocks_handoff(self):
        export = self.datasets.export_classification
        def change_split(*args, **kwargs):
            path = export(*args, **kwargs)
            self.split.write_text('{"groups": {"train": "test"}}')
            return path
        with patch.object(self.datasets, "export_classification", side_effect=change_split):
            self.job()._run()
        _, result, error, _ = self.completion()
        self.assertIsNone(result)
        self.assertIn("đã đổi", str(error))
        self.assertFalse(list(self.exports.iterdir()))

    def test_model_load_error_and_precancel_do_not_export(self):
        with patch("smartlabel.training_preparation.inspect_model", side_effect=ValueError("model hỏng")), \
                patch.object(self.datasets, "export_classification") as export:
            self.job()._run()
        export.assert_not_called()
        self.assertIn("model hỏng", str(self.completion()[2]))
        self.events.clear()
        job = self.job()
        job.stop()
        with patch.object(self.datasets, "split_health") as health:
            job._run()
        health.assert_not_called()
        self.assertTrue(self.completion()[3])

    def test_cancel_during_slow_model_check_waits_then_never_exports(self):
        entered, release = Event(), Event()
        def inspect(*args, **kwargs):
            entered.set()
            release.wait(5)
            return "fixture-cls.pt"
        job = self.job()
        with patch("smartlabel.training_preparation.inspect_model", side_effect=inspect), \
                patch.object(self.datasets, "export_classification") as export:
            job.start()
            try:
                self.assertTrue(entered.wait(2))
                job.stop()
            finally:
                release.set()
                job.thread.join(5)
            export.assert_not_called()
        self.assertTrue(self.completion()[3])

    def test_model_task_check_preserves_classification_fallback_and_rejects_wrong_localization(self):
        file = self.store.project_dir(self.project) / "fixture.pt"
        file.write_bytes(b"not a model; mocked loader only")
        with patch.dict("sys.modules", {"ultralytics": SimpleNamespace(
                YOLO=lambda path: SimpleNamespace(task="detect"))}):
            self.assertEqual(inspect_model(str(file), "detect"), str(file))
            self.assertEqual(inspect_model(str(file), "classify", auto_classification=True), "yolo11n-cls.pt")
            with self.assertRaisesRegex(ValueError, "dataset cần segment"):
                inspect_model(str(file), "segment")

    def test_localization_export_supports_cancellation_too(self):
        self.project.attribute_classification_enabled = False
        self.request["task"] = "detect"
        self.request["options"]["model"] = "fixture.pt"
        for record in self.project.images:
            record.annotations.append(Annotation(id=f"ann-{record.id}", class_id=0, bbox=[1, 1, 10, 10]))
        self.job()._run()
        _, result, error, _ = self.completion()
        self.assertIsNone(error)
        self.assertEqual(result["prepared"][0][2]["exported_annotations"], 9)
        self.assertTrue((result["prepared"][0][1] / "data.yaml").is_file())

    def test_progress_is_throttled_and_cancellation_is_not_throttled(self):
        lines = []
        progress = PreparationProgress(lines.append)
        for index in range(1000):
            progress.report("fixture", index, 1000)
        progress.report("fixture", 1000, 1000)
        self.assertLess(len(lines), 10)
        self.assertIn("1000/1000", lines[-1])
        progress.cancel_event.set()
        with self.assertRaises(PreparationCancelled):
            progress.report("fixture", 999, 1000)

    def test_directory_ownership_refuses_existing_and_outside_exports(self):
        progress = PreparationProgress(lambda line: None, export_root=self.exports)
        existing = self.exports / "old"
        existing.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            progress.reserve_export(existing)
        with self.assertRaises(ValueError):
            progress.reserve_export(self.exports.parent)
        progress.discard_exports()
        self.assertTrue(existing.is_dir())
