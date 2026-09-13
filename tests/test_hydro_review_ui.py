from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import gc
import tkinter as tk
import unittest
from PIL import Image

from smartlabel import app as app_module, image_filters
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore
from smartlabel.ui_components import HydroBundleConfigDialog


class HydroReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        cls.temp = TemporaryDirectory()
        cls.store = ProjectStore(Path(cls.temp.name) / "workspace")
        cls.hydro = cls.store.create_project("Hydro tools", task="classify")
        apply_hydroponic_slot_template(cls.hydro)
        for index in range(5):
            record = ImageRecord(id=str(index), file_name=f"{index}.png", width=64, height=64, asset_role="slot",
                attributes={"plant_presence": "present", "yellow_leaf": "present" if index % 2 else "absent"}, review_status="draft")
            Image.new("RGB", (64, 64), "green").save(cls.store.image_path(cls.hydro, record))
            cls.hydro.images.append(record)
        cls.bottle = cls.store.create_project("Bottle", classes=["bottle", "cap"])
        cls.store.save(cls.hydro)
        cls.patches = [patch.object(app_module, "WORKSPACE", cls.store.workspace),
                       patch.object(app_module.SmartLabelApp, "_refresh_hardware"),
                       patch.object(app_module.messagebox, "showerror"), patch.object(app_module.messagebox, "showinfo")]
        for item in cls.patches:
            item.start()
        cls.app = app_module.SmartLabelApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.app.auto_label_running = self.app.evaluation_running = self.app.hydro_export_running = False
        self.app.project_views.clear()
        self.app._change_project_context(deepcopy(self.hydro))
        app_module.messagebox.showerror.reset_mock()
        app_module.messagebox.showinfo.reset_mock()
        gc.collect()

    def filter_yellow(self):
        field = next(k for k, v in self.app.label_filter_fields.items() if v == ("attribute", "yellow_leaf"))
        self.app.label_filter_field.set(field)
        self.app._label_filter_changed()
        value = next(k for k, v in self.app.label_filter_values.items() if v == "present")
        self.app.label_filter_value.set(value)
        self.app._change_image_filter()

    def test_overview_counts_hydro_attributes_and_keeps_bottle_geometry(self):
        self.app.project.images[0].review_status = "reviewed"
        self.app._refresh_project_statistics()
        hydro = self.app.project_summary.get("1.0", "end")
        self.assertIn("Giá trị thuộc tính đã duyệt: 2", hydro)
        self.assertIn("THUỘC TÍNH TRÊN ẢNH RỌ", hydro)
        self.assertNotIn("Số nhãn hình học", hydro)
        self.assertIn("Có 0 · Không 1", hydro)
        self.assertTrue(self.app.training_supplements_button.winfo_manager())
        self.app._change_project_context(deepcopy(self.bottle))
        bottle = self.app.project_summary.get("1.0", "end")
        self.assertIn("Số nhãn hình học: 0", bottle)
        self.assertNotIn("THUỘC TÍNH TRÊN ẢNH RỌ", bottle)
        self.assertFalse(self.app.training_supplements_button.winfo_manager())

    def test_filter_navigation_and_edit_reconcile_without_clearing_filter(self):
        self.filter_yellow()
        self.assertEqual([r.id for r in self.app.filtered_images], ["1", "3"])
        self.app._next_image()
        self.assertEqual(self.app.canvas.record.id, "3")
        self.app._next_image()
        self.assertEqual(self.app.canvas.record.id, "1")
        self.app._previous_image()
        self.assertEqual(self.app.canvas.record.id, "3")
        self.app._attribute_changed("yellow_leaf", "absent")
        self.assertEqual([r.id for r in self.app.filtered_images], ["1"])
        self.assertEqual(self.app.canvas.record.id, "1")
        self.assertNotEqual(self.app.label_filter_field.get(), image_filters.ALL)
        self.app._attribute_changed("yellow_leaf", "absent")
        self.assertFalse(self.app.filtered_images)
        self.assertIsNone(self.app.canvas.record)

    def test_filter_and_tool_context_survive_round_trip_without_bottle_leak(self):
        self.filter_yellow()
        hydro = self.app.project
        self.assertFalse(self.app.auto_sam_card.winfo_manager())
        self.assertEqual(self.app.model_entry.cget("state"), "disabled")
        self.assertTrue(self.app.hydro_evaluation_group.winfo_manager())
        self.app._change_project_context(self.bottle)
        self.assertEqual(self.app.label_filter_field.get(), image_filters.ALL)
        self.assertTrue(self.app.auto_sam_card.winfo_manager())
        self.assertEqual(self.app.model_entry.cget("state"), "normal")
        self.assertFalse(self.app.hydro_evaluation_group.winfo_manager())
        self.assertEqual(self.app.evaluation_model_entry.cget("state"), "normal")
        self.app._change_project_context(hydro)
        self.assertEqual([r.id for r in self.app.filtered_images], ["1", "3"])

    def test_qa_link_opens_requested_image_outside_filter_and_last_approval_clears_view(self):
        self.filter_yellow()
        self.app._open_qa_image("0")
        self.assertEqual(self.app.canvas.record.id, "0")
        self.assertEqual(self.app.label_filter_field.get(), image_filters.ALL)
        self.app.project.images = self.app.project.images[:1]
        self.app.project.images[0].attributes["wilt"] = "absent"
        self.app.image_filter.set("Bản nháp")
        self.app._change_image_filter()
        self.app._approve_image_next()
        self.assertFalse(self.app.filtered_images)
        self.assertIsNone(self.app.canvas.record)
        self.assertEqual(self.app.image_filter.get(), "Bản nháp")

    def test_dialog_defaults_locked_provenance_and_editable_thresholds(self):
        defaults = {"datasetVersion": "v1", "sourceCommit": "abc", "cameraProfileIds": ["cam"],
                    "geometryProfileIds": [], "modelTitles": {"plant_presence": "Có cây"}}
        dialog = HydroBundleConfigDialog(self.app, defaults)
        try:
            for key in ("datasetVersion", "sourceCommit", "cameraProfileIds"):
                self.assertEqual(dialog.metadata_entries[key].cget("state"), "disabled")
            self.assertEqual(dialog.metadata_entries["geometryProfileIds"].cget("state"), "normal")
            self.assertEqual(float(dialog.variables["plant_presence.lowThreshold"].get()), .3)
            self.assertEqual(float(dialog.variables["plant_presence.highThreshold"].get()), .7)
            dialog.variables["geometryProfileIds"].set("geo")
            dialog.variables["plant_presence.highThreshold"].set("0.8")
            dialog._accept()
            self.assertEqual(dialog.result["thresholds"]["plant_presence"]["highThreshold"], .8)
            self.assertEqual(dialog.result["deploymentMode"], "shadow")
        finally:
            if dialog.winfo_exists():
                dialog.destroy()

    def test_hydro_auto_worker_snapshot_ui_responsive_and_ownership_until_done(self):
        entered, release = Event(), Event()
        def worker(project, store, **options):
            self.assertIsNot(project, self.app.project)
            entered.set()
            release.wait(5)
            return {"proposals": [], "failed": [], "skipped": 5, "cancelled": options["cancel_event"].is_set()}
        with patch.object(app_module, "propose_hydro_labels", side_effect=worker), patch.object(app_module, "auto_label_project") as generic:
            self.app._start_auto_label()
            self.assertTrue(entered.wait(3))
            self.assertTrue(self.app.auto_label_running)
            callback = []
            self.app.after(0, lambda: callback.append(True))
            self.app.update()
            self.assertTrue(callback)
            self.assertFalse(self.app._can_change_project())
            self.app._start_training_for_current_mode()
            self.assertFalse(self.app.running_training_task)
            self.app._stop_auto_label()
            release.set()
            import time
            limit = time.monotonic() + 5
            while self.app.auto_label_running and time.monotonic() < limit:
                self.app.update()
                time.sleep(.01)
            self.assertFalse(self.app.auto_label_running)
            self.assertIn("Đã dừng", self.app.auto_log.get("1.0", "end"))
            generic.assert_not_called()

    def test_hydro_evaluation_dispatches_selected_attribute_and_records_report(self):
        selected = next(k for k, v in self.app.hydro_evaluation_lookup.items() if v == "yellow_leaf")
        self.app.hydro_evaluation_group.set(selected)
        metrics = dict(samples=40, accuracy=.9, precision=.8, recall=.9, f1=.85, tp=18, tn=18, fp=2, fn=2)
        result = dict(task="hydro_classify", attributeId="yellow_leaf", title="Lá vàng", split="test", metrics=metrics,
                      rating="fixture", save_dir="fixture", recommendedThresholds=None)
        with patch.object(app_module, "evaluate_hydro_attribute", return_value=result) as hydro, patch.object(app_module, "evaluate_yolo_model") as generic:
            self.app._evaluate_model()
            import time
            limit = time.monotonic() + 5
            while self.app.evaluation_running and time.monotonic() < limit:
                self.app.update()
                time.sleep(.01)
            self.assertFalse(self.app.evaluation_running)
            self.assertEqual(hydro.call_args.args[1], "yellow_leaf")
            generic.assert_not_called()
            self.assertIn("test", self.app.project.metadata["hydroEvaluations"]["yellow_leaf"])
            self.assertIn("Bỏ sót Có=2", self.app.train_log.get("1.0", "end"))

    def test_thread_start_errors_release_both_guards(self):
        with patch.object(app_module.Thread, "start", side_effect=RuntimeError("cannot start")):
            self.app._start_auto_label()
            self.assertFalse(self.app.auto_label_running)
            self.app._evaluate_model()
            self.assertFalse(self.app.evaluation_running)
        self.assertIn("cannot start", self.app.auto_log.get("1.0", "end"))

    def test_bottle_auto_and_evaluation_keep_generic_dispatch_and_captured_controls(self):
        bottle = deepcopy(self.bottle)
        bottle.images = [ImageRecord(id="b", file_name="b.png", width=20, height=20)]
        Image.new("RGB", (20, 20), "blue").save(self.store.image_path(bottle, bottle.images[0]))
        self.app._change_project_context(bottle)
        self.assertEqual(self.app.project.id, bottle.id)
        model = Path(self.temp.name) / "bottle.pt"
        model.write_bytes(b"fixture")
        self.app.model_path.set(str(model))
        stats = SimpleNamespace(processed=1, detections=0, task="detect", elapsed_seconds=.1, device="CPU")
        with patch.object(app_module, "auto_label_project", return_value=stats) as generic, patch.object(app_module, "propose_hydro_labels") as hydro:
            self.app._start_auto_label()
            import time
            limit = time.monotonic() + 5
            while self.app.auto_label_running and time.monotonic() < limit:
                self.app.update()
                time.sleep(.01)
            self.assertEqual(generic.call_args.kwargs["model_path"], str(model))
            self.assertAlmostEqual(generic.call_args.kwargs["confidence"], .25)
            hydro.assert_not_called()
        self.app.evaluation_model_path.set(str(model))
        self.app.evaluation_data_path.set(self.temp.name)
        report = dict(task="detect", split="test", metrics={"map50_95": .7, "precision": .9, "recall": .8}, save_dir="fixture")
        with patch.object(app_module, "evaluate_yolo_model", return_value=report) as generic, patch.object(app_module, "evaluate_hydro_attribute") as hydro:
            self.app._evaluate_model()
            limit = time.monotonic() + 5
            while self.app.evaluation_running and time.monotonic() < limit:
                self.app.update()
                time.sleep(.01)
            generic.assert_called_once()
            hydro.assert_not_called()
            self.assertNotIn("hydroEvaluations", self.app.project.metadata)


if __name__ == "__main__":
    unittest.main()
