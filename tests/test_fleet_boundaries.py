from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from smartlabel.dataset_manager import DatasetManager
from smartlabel.fleet_boundaries import require_legacy_project, require_legacy_training_data
from smartlabel.fleet_intake import FleetIntakeError
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore
from smartlabel.training import TrainingConfig, TrainingJob


class FleetBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "workspace")
        self.project = self.store.create_project("Existing project")
        self.root = self.store.project_dir(self.project)
        self.manager = DatasetManager(self.store)

    def test_presence_of_staging_does_not_block_unrelated_legacy_project(self):
        (self.root / "fleet_inbox").mkdir()
        require_legacy_project(self.project, self.store)
        self.assertTrue(self.manager.create_version(self.project).is_dir())
        require_legacy_training_data(self.root / "exports")

    def test_reserved_provenance_and_managed_paths_block_all_exports_before_any_write(self):
        for kind in ("metadata", "path"):
            with self.subTest(kind=kind):
                self.project.images = [ImageRecord(id="managed", file_name="../fleet_inbox/batch/photo.png" if kind == "path" else "photo.png",
                    width=64, height=64, metadata={"fleetContributionId": "id", "trainAllowed": True} if kind == "metadata" else {})]
                before = {file: file.read_bytes() for file in self.root.rglob('*') if file.is_file()}
                for export in (lambda: self.manager.create_version(self.project), lambda: self.manager.export_yolo(self.project),
                               lambda: self.manager.export_classification(self.project, "presence"), lambda: self.manager.export_coco(self.project)):
                    with self.assertRaises(FleetIntakeError): export()
                self.assertEqual(before, {file: file.read_bytes() for file in self.root.rglob('*') if file.is_file()})

    def test_direct_training_and_old_child_launcher_cannot_bypass_managed_source(self):
        path = self.root / "fleet_inbox" / "batch"
        config = TrainingConfig(model="unused.pt", data=str(path), project_dir="unused")
        lines, done = [], []
        with patch("smartlabel.training.subprocess.Popen") as process:
            TrainingJob(config, lines.append, done.append)._run()
            process.assert_not_called()
        self.assertEqual(done, [1]); self.assertTrue(any("Fleet" in line for line in lines))
        from smartlabel import train_worker
        with patch("sys.argv", ["worker", json.dumps({"data": str(path)})]):
            with self.assertRaises(FleetIntakeError): train_worker.main()

    def test_yaml_root_split_reference_junction_and_snapshot_provenance_are_checked(self):
        data = self.root / "exports" / "data.yaml"; data.parent.mkdir(exist_ok=True)
        data.write_text("path: ../fleet_inbox\ntrain: images\n")
        with self.assertRaises(FleetIntakeError): require_legacy_training_data(data)
        data.write_text("train: ../fleet_inbox/batch\n")
        with self.assertRaises(FleetIntakeError): require_legacy_training_data(data)
        data.write_text("train: images/train\nval: images/val\n")
        require_legacy_training_data(data)
        (data.parent / "export.json").write_text(json.dumps({"fleetDependencies": [], "trainAllowed": True}))
        with self.assertRaises(FleetIntakeError): require_legacy_training_data(data)

    def test_bad_manifest_blocks_training_without_deleting_or_rewriting_anything(self):
        data = self.root / "exports"; data.mkdir(exist_ok=True)
        (data / "export.json").write_text("broken")
        with self.assertRaises(FleetIntakeError): require_legacy_training_data(data)
        self.assertEqual((data / "export.json").read_text(), "broken")

    def test_unused_scalar_splits_do_not_scan_unrelated_workspace_sources(self):
        import yaml
        data = self.root / "exports" / "data.yaml"
        data.parent.mkdir(exist_ok=True)
        unrelated = Path(self.temp.name) / "another_project"
        (unrelated / "fleet_inbox").mkdir(parents=True)
        (unrelated / "holdout").mkdir()
        (unrelated / "holdout" / "benchmark.json").write_text("{}")
        before = {f: f.read_bytes() for f in unrelated.rglob('*') if f.is_file()}
        for optional in ({}, {"test": ""}, {"test": None}, {"test": []}, {"val": "", "test": ""}):
            with self.subTest(optional=optional):
                data.write_text(yaml.safe_dump({"path": ".", "train": "images/train", "val": "images/train", **optional}))
                with patch("os.getcwd", return_value=self.temp.name):
                    require_legacy_training_data(data)
        self.assertEqual(before, {f: f.read_bytes() for f in unrelated.rglob('*') if f.is_file()})

    def test_empty_optional_split_never_exempts_actual_fleet_paths_or_metadata(self):
        import yaml
        data = self.root / "exports" / "data.yaml"
        data.parent.mkdir(exist_ok=True)
        for changes in ({"train": "../fleet_inbox/images"}, {"val": ["../fleet_inbox/images"]},
                        {"path": "../fleet_inbox"}, {"fleetDependencies": []},
                        {"train": ["", "images/train"]}, {"val": [None]}):
            with self.subTest(changes=changes):
                data.write_text(yaml.safe_dump({"path": ".", "train": "images/train", "val": "images/train", "test": "", **changes}))
                with self.assertRaises(FleetIntakeError):
                    require_legacy_training_data(data)

    def test_train_all_ori_export_reaches_worker_with_unrelated_fleet_project(self):
        from io import StringIO
        from types import SimpleNamespace
        from PIL import Image
        from smartlabel.models import Annotation
        self.project = self.store.create_project("ORI fixture", classes=["part"])
        self.root = self.store.project_dir(self.project)
        source = Path(self.temp.name) / "part.png"
        Image.new("RGB", (80, 64)).save(source)
        self.store.import_images(self.project, [source])
        record = self.project.images[0]
        record.review_status = "reviewed"
        ann = Annotation.create_box(0, [20, 16, 40, 24])
        ann.orientation = [[40, 28], [55, 28]]
        record.annotations = [ann]
        exported = self.manager.export_yolo(self.project, task="ori", split_strategy="train_all")
        other = self.store.create_project("Unrelated Fleet project")
        (self.store.project_dir(other) / "fleet_inbox").mkdir()
        config = TrainingConfig(model="deltax-yolo11n-ori", data=str(exported / "data.yaml"),
                                task="ori", project_dir=str(self.root / "runs"), validate=False)
        lines, done = [], []
        child = SimpleNamespace(stdout=StringIO("TRAINING_COMPLETE\n"), pid=123, wait=lambda: 0)
        with patch("os.getcwd", return_value=str(self.store.workspace.parent)), \
             patch("smartlabel.training.best_ultralytics_device", return_value="cpu"), \
             patch("smartlabel.training.subprocess.Popen", return_value=child) as launch:
            TrainingJob(config, lines.append, done.append)._run()
        self.assertEqual(done, [0], lines)
        launch.assert_called_once()
        self.assertIn("TRAINING_COMPLETE", lines)
        metadata = json.loads((exported / "export.json").read_text())
        self.assertFalse(metadata["validation_enabled"])
        self.assertFalse(metadata["independent_test"])

    def test_split_directory_junction_and_image_list_cannot_launder_managed_paths(self):
        import os
        import subprocess
        data = self.root / "exports"; data.mkdir(exist_ok=True)
        managed = self.root / "fleet_inbox"; managed.mkdir()
        alias = data / "train"
        if os.name == "nt":
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "New-Item -ItemType Junction -Path $env:FLEET_FIXTURE_ALIAS -Target $env:FLEET_FIXTURE_TARGET | Out-Null"],
                           env={**os.environ, "FLEET_FIXTURE_ALIAS": str(alias), "FLEET_FIXTURE_TARGET": str(managed)},
                           check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            alias.symlink_to(managed, target_is_directory=True)
        try:
            with self.assertRaises(FleetIntakeError): require_legacy_training_data(data)
        finally:
            if os.name == "nt": os.rmdir(alias)
            else: alias.unlink()
        listing = data / "images.txt"; listing.write_text("../fleet_inbox/photo.png\n")
        config = data / "data.yaml"; config.write_text("train: images.txt\n")
        with self.assertRaises(FleetIntakeError): require_legacy_training_data(config)
