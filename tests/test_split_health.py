from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore
from smartlabel.split_health import SplitConflictError, classification_training_problem
from smartlabel.training_supplements import manifest_path


class SplitHealthTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ProjectStore(Path(temp.name) / "workspace")
        self.project = self.store.create_project("Split fixture", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.manager = DatasetManager(self.store)
        for i in range(10):
            for j in range(2):
                self.project.images.append(ImageRecord(id=f"{i}_{j}", file_name=f"{i}_{j}.png", width=32, height=32,
                    asset_role="slot", review_status="reviewed", capture_group=f"g{i}",
                    attributes={"plant_presence": "present" if j else "absent",
                                "yellow_leaf": "present" if i % 2 else "absent", "wilt": "absent"}))
        self.assignment = {f"g{i}": "train" if i < 7 else "val" if i < 9 else "test" for i in range(10)}
        self.split = self.manager.split_assignment_path(self.project)
        self.split.write_text(json.dumps({"groups": self.assignment}), encoding="utf-8")
        self.sidecar = manifest_path(self.store, self.project)
        self.sidecar.parent.mkdir()
        self.manifest = {"schemaVersion": 1, "projectId": self.project.id, "images": [
            {"id": "variant", "enabled": True, "kind": "synthetic", "provenance": {"parentImageId": "7_1"}}]}
        self.save_manifest()

    def save_manifest(self):
        self.sidecar.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_diagnosis_identifies_all_conflicts_without_writes(self):
        before = self.split.read_bytes(), self.sidecar.read_bytes(), self.project.to_dict()
        health = self.manager.split_health(self.project)
        self.assertEqual(health["conflicts"], {"g7": ["variant"]})
        self.assertIn("Có/Không", "\n".join(health["coverage"]))
        self.assertEqual(before, (self.split.read_bytes(), self.sidecar.read_bytes(), self.project.to_dict()))

    def test_rebalance_preview_pins_parent_and_preserves_whole_groups(self):
        before = self.split.read_bytes()
        preview = self.manager.preview_rebalance(self.project)
        self.assertEqual(before, self.split.read_bytes())
        self.assertEqual(preview["assignment"]["groups"]["g7"], "train")
        self.assertEqual(sum(preview["counts"].values()), 20)
        self.assertEqual(set(preview["assignment"]["groups"]), set(self.assignment))
        self.manager.apply_rebalance(self.project, preview)
        self.assertEqual(self.manager.split_health(self.project)["conflicts"], {})
        self.assertEqual(before, self.split.with_name("split_assignment.previous.json").read_bytes())

    def test_manual_move_into_holdout_is_blocked_before_write(self):
        self.manager.set_groups_split(self.project, ["g7"], "train")
        before = self.split.read_bytes()
        for target in ("val", "test"):
            with self.assertRaisesRegex(SplitConflictError, "1 ảnh bổ trợ"):
                self.manager.set_groups_split(self.project, ["g7", "g1"], target)
            self.assertEqual(before, self.split.read_bytes())

    def test_repair_only_moves_conflicting_group_no_labels_or_supplement_changes(self):
        before = deepcopy(self.project.to_dict()), self.sidecar.read_bytes()
        self.manager.set_groups_split(self.project, ["g7"], "train", expected_revision=self.manager.split_revision(self.project))
        expected = {**self.assignment, "g7": "train"}
        self.assertEqual(self.manager.ensure_split_assignment(self.project, persist=False)["groups"], expected)
        self.assertEqual(before, (self.project.to_dict(), self.sidecar.read_bytes()))

    def test_preview_rejects_stale_split_label_or_sidecar(self):
        for change in ("split", "label", "sidecar"):
            with self.subTest(change=change):
                preview = self.manager.preview_rebalance(self.project)
                if change == "split":
                    self.manager.set_groups_split(self.project, ["g1"], "val")
                elif change == "label":
                    self.project.images[0].attributes["plant_presence"] = "uncertain"
                else:
                    self.manifest["images"][0]["enabled"] = False
                    self.save_manifest()
                before = self.split.read_bytes()
                with self.assertRaisesRegex(ValueError, "thay đổi"):
                    self.manager.apply_rebalance(self.project, preview)
                self.assertEqual(before, self.split.read_bytes())

    def test_manual_move_rejects_stale_confirmation(self):
        revision = self.manager.split_revision(self.project)
        self.manifest["images"][0]["enabled"] = False
        self.save_manifest()
        before = self.split.read_bytes()
        with self.assertRaisesRegex(ValueError, "thay đổi"):
            self.manager.set_groups_split(self.project, ["g7"], "train", expected_revision=revision)
        self.assertEqual(before, self.split.read_bytes())

    def test_disabled_and_external_supplements_do_not_pin_groups(self):
        for update in ({"enabled": False}, {"enabled": True, "kind": "external"}):
            self.manifest["images"][0].update(update)
            self.save_manifest()
            self.assertEqual(self.manager.supplement_parent_groups(self.project), {})

    def test_missing_parent_and_corrupt_sidecar_block_rebalance_without_writing(self):
        before = self.split.read_bytes()
        self.manifest["images"][0]["provenance"] = {}
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "thiếu ảnh gốc"):
            self.manager.ensure_split_assignment(self.project, force_rebalance=True)
        self.sidecar.write_text("{")
        with self.assertRaises(ValueError):
            self.manager.ensure_split_assignment(self.project, force_rebalance=True)
        self.assertEqual(before, self.split.read_bytes())

    def test_corrupt_assignment_is_not_silently_replaced(self):
        for content in ("{", "[]", '{"groups":[]}', '{"groups":{"g0":"typo"}}', '{"groups":{"g0":null}}'):
            self.split.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.manager.ensure_split_assignment(self.project, force_rebalance=True)
            self.assertEqual(content, self.split.read_text())

    def test_atomic_failure_preserves_original_and_cleans_staged_files(self):
        before = self.split.read_bytes()
        with patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.manager.set_groups_split(self.project, ["g7"], "train")
        self.assertEqual(before, self.split.read_bytes())
        self.assertFalse(list(self.split.parent.glob("tmp*")))

    def test_all_groups_pinned_reports_no_holdout_instead_of_leaking(self):
        self.manifest["images"] = [{"id": str(i), "enabled": True, "kind": "synthetic",
                                    "provenance": {"parentImageId": f"{i}_1"}} for i in range(10)]
        self.save_manifest()
        preview = self.manager.preview_rebalance(self.project)
        self.assertEqual(preview["counts"], {"train": 20, "val": 0, "test": 0})
        self.assertIn("Thiếu Có hoặc Không", "\n".join(preview["coverage"]))

    def test_existing_group_import_keeps_val_new_group_goes_train(self):
        self.project.images.extend([ImageRecord(id="old", file_name="old.png", width=32, height=32, capture_group="g8"),
                                    ImageRecord(id="new", file_name="new.png", width=32, height=32, capture_group="new")])
        result = self.manager.ensure_split_assignment(self.project)["groups"]
        self.assertEqual(result["g8"], "val")
        self.assertEqual(result["new"], "train")
        self.assertEqual({k: result[k] for k in self.assignment}, self.assignment)

    def test_generic_localization_ignores_hydro_sidecar(self):
        self.project.metadata.clear()
        self.sidecar.write_text("{")
        self.assertEqual(self.manager.supplement_parent_groups(self.project), {})
        self.manager.preview_rebalance(self.project)

    def test_noop_persistence_and_summary_do_not_rewrite_file(self):
        self.manager.ensure_split_assignment(self.project)
        before = self.split.read_bytes(), self.split.stat().st_mtime_ns
        self.manager.ensure_split_assignment(self.project)
        self.manager.split_summary(self.project)
        self.assertEqual(before, (self.split.read_bytes(), self.split.stat().st_mtime_ns))

    def test_coverage_excludes_pending_and_explicitly_excluded_labels(self):
        self.project.attribute_settings["yellow_leaf"]["train_exclude"] = ["present"]
        lines = self.manager.split_health(self.project)["coverage"]
        self.assertTrue(any("Lá vàng: TRAIN 0/" in line for line in lines))

    def test_training_readiness_uses_actual_train_classes_not_pooled_counts(self):
        meta = {"counts": {"present": 10, "absent": 10}, "class_counts_by_split": {
            "train": {"present": 0, "absent": 10}, "val": {"present": 10}, "test": {}}, "split_strategy": "locked"}
        self.assertIn("TRAIN chưa đủ", classification_training_problem(meta))
        meta["class_counts_by_split"]["train"]["present"] = 2
        self.assertEqual(classification_training_problem(meta), "")  # TEST optional, VAL one class warns separately.
        meta["class_counts_by_split"]["val"] = {}
        self.assertIn("VAL không có", classification_training_problem(meta))
        meta["split_strategy"] = "train_all"
        self.assertEqual(classification_training_problem(meta), "")


if __name__ == "__main__":
    unittest.main()
