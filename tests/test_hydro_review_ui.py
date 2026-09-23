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
        self.app.image_filter.set('Tất cả')
        self.app.label_filter_field.set(image_filters.ALL)
        self.app.label_filter_value.set(image_filters.ANY)
        self.app._change_image_filter()
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

    def test_test_tools_stay_together_in_dataset_and_hide_for_other_projects(self):
        import customtkinter as ctk
        tools = self.app.heldout_tools
        self.assertTrue(tools.winfo_manager())
        actions = next(w for w in tools.winfo_children() if isinstance(w, ctk.CTkFrame)
                       and len([b for b in w.winfo_children() if isinstance(b, ctk.CTkButton)]) == 2)
        buttons = [w for w in actions.winfo_children() if isinstance(w, ctk.CTkButton)]
        self.assertEqual([b.cget("text") for b in buttons], ["1. Thu thập ảnh TEST", "2. Bộ TEST ngoài"])
        self.assertEqual([int(b.grid_info()["row"]) for b in buttons], [0, 0])
        self.app._change_project_context(deepcopy(self.bottle))
        self.assertFalse(tools.winfo_manager())
        self.app._change_project_context(deepcopy(self.hydro))
        self.assertEqual(tools.master.pack_slaves().index(tools) + 1,
                         tools.master.pack_slaves().index(self.app.dataset_statistics_card))

    def test_overview_counts_hydro_attributes_and_keeps_bottle_geometry(self):
        self.app.project.images[0].review_status = "reviewed"
        self.app._refresh_project_statistics()
        hydro = self.app.project_summary.get("1.0", "end")
        self.assertIn("Giá trị thuộc tính đã duyệt: 2", hydro)
        self.assertIn("THUỘC TÍNH TRÊN ẢNH RỌ", hydro)
        self.assertNotIn("Số nhãn hình học", hydro)
        self.assertIn("Có 0 · Không 1", hydro)
        self.assertFalse(hasattr(self.app, "training_supplements_button"))
        self.assertGreaterEqual(int(self.app.image_list_title_label.cget("font")[1]), 14)
        labels = []
        def collect(widget):
            for child in widget.winfo_children():
                try:
                    text = child.cget("text")
                except (AttributeError, ValueError, tk.TclError):
                    text = ""
                if text:
                    labels.append((text, child))
                collect(child)
        collect(self.app.project_overview)
        texts = [text for text, _ in labels]
        self.assertLess(texts.index("THUỘC TÍNH TRÊN ẢNH RỌ"), texts.index("ẢNH BỔ TRỢ · CHỈ TRAIN"))
        supplement_title = next(widget for text, widget in labels if text == "ẢNH BỔ TRỢ · CHỈ TRAIN")
        self.assertEqual(supplement_title.master.cget("fg_color"), "#132b31")
        self.app._change_project_context(deepcopy(self.bottle))
        bottle = self.app.project_summary.get("1.0", "end")
        self.assertIn("Số nhãn hình học: 0", bottle)
        self.assertNotIn("THUỘC TÍNH TRÊN ẢNH RỌ", bottle)
        self.assertFalse(hasattr(self.app, "training_supplements_button"))

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
        self.assertEqual(self.app.canvas.record.id, "3")
        self.assertEqual(self.app.canvas.record.attributes['yellow_leaf'], 'absent')
        self.assertIn('không còn thuộc bộ lọc', self.app.label_save_status.cget('text'))
        self.assertEqual(self.app.image_list.curselection(), ())
        self.assertNotEqual(self.app.label_filter_field.get(), image_filters.ALL)
        self.app._next_image()
        self.assertEqual(self.app.canvas.record.id, "1")
        self.app._attribute_changed("yellow_leaf", "absent")
        self.assertFalse(self.app.filtered_images)
        self.assertEqual(self.app.canvas.record.id, "1")
        self.app._next_image()
        self.assertIsNone(self.app.canvas.record)

    def test_capture_dropdown_persists_in_reviewed_filter_and_stays_on_edited_image(self):
        app = self.app
        for row in app.project.images:
            row.review_status = 'reviewed'
        app.image_filter.set('Đã duyệt')
        app._change_image_filter()
        edited = app.canvas.record
        menu = app.attribute_widgets['yellow_leaf']
        caption = next(k for k, v in app.attribute_display_to_value['yellow_leaf'].items() if v == 'present')
        menu._dropdown_callback(caption)
        self.assertIs(app.canvas.record, edited)
        self.assertEqual(menu.get(), caption)
        self.assertEqual(edited.review_status, 'draft')
        saved = self.store.load(app.project.id).image_by_id(edited.id)
        self.assertEqual(saved.attributes['yellow_leaf'], 'present')
        self.assertIn('yellow_leaf', saved.metadata['hydroManualAttributes'])
        self.assertEqual(app.image_position_label.cget('text'), '1 / 5')
        app._next_image()
        self.assertEqual(app.canvas.record.id, '1')

    def test_capture_save_failure_keeps_previous_labels_and_explains_retry(self):
        app = self.app
        previous = deepcopy(app.canvas.record.to_dict())
        with patch.object(app.store, 'save', side_effect=OSError('disk unavailable')):
            app._attribute_changed('yellow_leaf', 'present')
        self.assertEqual(app.canvas.record.to_dict(), previous)
        self.assertIn('Chưa lưu được nhãn', app.label_save_status.cget('text'))

    def test_edit_defers_hidden_statistics_until_overview_is_opened(self):
        app = self.app
        app.deiconify()
        app.tabs.set('GÁN NHÃN')
        app.update()
        with patch.object(app, '_refresh_project_statistics', wraps=app._refresh_project_statistics) as refresh:
            app._attribute_changed('yellow_leaf', 'present')
            refresh.assert_not_called()
            self.assertTrue(app.project_statistics_dirty)
            app.tabs.set('DỰ ÁN')
            app.update()
            refresh.assert_called_once()
            self.assertFalse(app.project_statistics_dirty)
        app.withdraw()

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

    def test_review_open_explains_aggregate_and_stale_rows(self):
        self.app._begin_review_results("QA", "fixture")
        self.app._append_review_result("[CẢNH BÁO] Toàn dataset", "")
        self.app.review_list.selection_set(0)
        self.app._open_issue()
        app_module.messagebox.showinfo.assert_called_once()

        app_module.messagebox.showinfo.reset_mock()
        self.app._begin_review_results("QA", "fixture")
        self.app._append_review_result("[LỖI] stale.jpg", "missing-image-id")
        self.app.review_list.selection_set(0)
        self.app._open_issue()
        app_module.messagebox.showerror.assert_called_once()

    def test_unvalidated_project_defaults_bundle_to_shadow(self):
        self.app.project.metadata.pop("hydroDeploymentMode", None)
        self.app.project.metadata["validationStatus"] = "pilot_unvalidated"
        captured = {}

        def capture_defaults(_parent, defaults):
            captured.update(defaults)
            return None

        with patch.object(app_module, "ask_hydro_bundle_config", side_effect=capture_defaults), \
                patch.object(self.app, "_hydro_classifier_paths", return_value={}):
            self.app._export_hydro_bundle()
        self.assertEqual(captured["deploymentMode"], "shadow")

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
            self.assertEqual(dialog.result["deploymentMode"], "operational")
        finally:
            if dialog.winfo_exists():
                dialog.destroy()

    def test_overview_and_dataset_expand_scroll_to_bottom_and_back_for_both_tasks(self):
        import time
        from smartlabel.models import Annotation
        self.app.deiconify()
        self.app.geometry('1180x720')
        try:
            for tab, panel in (('DỰ ÁN', self.app.project_overview), ('DATASET', self.app.dataset_overview)):
                self.app.tabs.set(tab)
                self.app.update()
                time.sleep(.15)
                if not panel.details_visible:
                    panel.toggle_details()
                self.app.update()
                canvas = panel._parent_canvas
                self.assertGreater(canvas.bbox('all')[3], canvas.winfo_height())
                canvas.yview_moveto(0)
                panel.event_generate('<MouseWheel>', delta=-120)
                self.app.update()
                self.assertGreater(canvas.yview()[0], 0, 'mouse wheel must scroll expanded content')
                panel._scrollbar._command('moveto', 1)
                self.app.update()
                self.assertAlmostEqual(canvas.yview()[1], 1, places=3)
                panel._scrollbar._command('moveto', 0)
                self.app.update()
                self.assertAlmostEqual(canvas.yview()[0], 0, places=3)
                panel.toggle_details()
                self.app.update()
                self.assertTrue(canvas.cget('scrollregion'))
            bottle = deepcopy(self.bottle)
            bottle.attribute_schema = {'condition': ['good', 'bad']}
            bottle.attribute_settings = {'condition': {'title': 'Tình trạng chai', 'scope': 'annotation_crop'}}
            record = ImageRecord(id='b', file_name='b.png', width=20, height=20)
            record.annotations = [Annotation(id='a', class_id=0, attributes={'condition': 'bad'})]
            bottle.images = [record]
            Image.new('RGB', (20, 20), 'blue').save(self.store.image_path(bottle, record))
            self.app._change_project_context(bottle)
            for panel in (self.app.project_overview, self.app.dataset_overview):
                text = '\n'.join(w.cget('text') for w in panel.wrapped_labels)
                self.assertIn('1 nhãn vật thể', text)
                self.assertIn('Tình trạng chai · trên vật thể', text)
                self.assertIn('bad   ·   1', text)
                self.assertNotIn('ẢNH BỔ TRỢ', text)
            self.app.project = None
            self.app._refresh_everything()
            self.assertFalse(self.app.dataset_overview._parent_frame.winfo_manager())
        finally:
            self.app.withdraw()

    def test_auto_label_shows_each_actual_checkpoint_and_refreshes_after_registration(self):
        checkpoint = Path(self.temp.name) / 'yellow-current.pt'
        checkpoint.write_bytes(b'UI fixture')
        self.app.project.attribute_models['yellow_leaf'] = str(checkpoint)
        self.app.project.attribute_models['wilt'] = str(Path(self.temp.name) / 'missing.pt')
        before = deepcopy(self.app.project.to_dict())
        self.app._refresh_active_model_status()
        self.assertIn('yellow-current.pt', self.app.auto_classifier_rows['yellow_leaf'].cget('text'))
        self.assertIn('Thiếu tệp PT', self.app.auto_classifier_rows['wilt'].cget('text'))
        self.assertIn('Chưa có model', self.app.auto_classifier_rows['plant_presence'].cget('text'))
        self.assertFalse(self.app.model_entry.winfo_manager())
        self.assertFalse(self.app.auto_choose_button.winfo_manager())
        self.assertEqual(before, self.app.project.to_dict())
        self.app.running_classification_key = 'wilt'
        with patch.object(self.app, '_latest_best_pt', return_value=checkpoint), patch.object(self.app.store, 'register_model', return_value=checkpoint):
            self.app._activate_latest_classification_model()
        self.assertIn('yellow-current.pt', self.app.auto_classifier_rows['wilt'].cget('text'))
        self.app._change_project_context(self.bottle)
        self.assertEqual(self.app.auto_classifier_rows, {})
        self.assertFalse(self.app.auto_classifier_panel._parent_frame.winfo_manager())
        self.assertTrue(self.app.model_entry.winfo_manager())
        self.assertTrue(self.app.auto_choose_button.winfo_manager())

    def test_bundle_runtime_and_usage_mode_are_independent(self):
        from smartlabel.ui_components import HYDRO_RUNTIME_LABELS, HYDRO_DEPLOYMENT_LABELS
        defaults = {'datasetVersion': 'v1', 'sourceCommit': 'abc', 'cameraProfileIds': ['cam'],
                    'geometryProfileIds': ['geo'], 'modelTitles': {'plant_presence': 'Có cây'}}
        for runtime in HYDRO_RUNTIME_LABELS:
            for mode in HYDRO_DEPLOYMENT_LABELS:
                dialog = HydroBundleConfigDialog(self.app, defaults)
                dialog.runtime_label.set(runtime)
                dialog.deployment_label.set(mode)
                dialog._accept()
                self.assertEqual(dialog.result['runtimeTarget'], HYDRO_RUNTIME_LABELS[runtime])
                self.assertEqual(dialog.result['deploymentMode'], HYDRO_DEPLOYMENT_LABELS[mode])

    def test_bundle_actions_remain_visible_at_minimum_window_size(self):
        import time
        self.app.deiconify()
        self.app.update()
        dialog = HydroBundleConfigDialog(self.app, {})
        try:
            dialog.geometry('650x650')
            for _ in range(3):
                dialog.update()
                time.sleep(.1)
            button = dialog.continue_button
            self.assertTrue(button.winfo_ismapped())
            bottom = button.winfo_rooty() + button.winfo_height() - dialog.winfo_rooty()
            self.assertLessEqual(bottom, dialog.winfo_height())
            self.assertGreaterEqual(button.winfo_height(), 28)
        finally:
            dialog.destroy()
            self.app.withdraw()

    def test_split_change_refreshes_both_statistics_panels(self):
        record = self.app.project.images[0]
        record.review_status = 'reviewed'
        self.app.project.images = [record]
        path = self.app.datasets.split_assignment_path(self.app.project)
        import json
        group = record.metadata.get('plant_instance_id') or record.capture_group or record.id
        path.write_text(json.dumps({'groups': {group: 'test'}}), encoding='utf-8')
        self.app._split_assignment_changed()
        for panel in (self.app.project_overview, self.app.dataset_overview):
            first_split = panel.split_frames[0]
            test_positive = next(w for w in first_split.winfo_children()
                                 if int(w.grid_info()['row']) == 1 and int(w.grid_info()['column']) == 3)
            self.assertEqual(test_positive.cget('text'), '1')

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
