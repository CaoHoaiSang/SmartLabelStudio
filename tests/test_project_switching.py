"""Real Tk regression tests; use xvfb-run on Linux, no user workspace/models."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
import unittest

from PIL import Image

from smartlabel import app as app_module
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore
from smartlabel.ui_layout import pack_before


class ProjectSwitchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display required (CI: xvfb-run): {exc}")
        cls.temp = TemporaryDirectory()
        cls.workspace = Path(cls.temp.name) / "workspace"
        cls.store = ProjectStore(cls.workspace)
        cls.bottle = cls.store.create_project("Bottle", classes=["bottle", "cap"])
        cls.hydro = cls.store.create_project("Hydro", task="classify")
        apply_hydroponic_slot_template(cls.hydro)
        cls.empty = cls.store.create_project("Empty Hydro", task="classify")
        apply_hydroponic_slot_template(cls.empty)
        for project, count in ((cls.bottle, 55), (cls.hydro, 7)):
            for i in range(count):
                name = f"image_{i}.png"
                Image.new("RGB", (64, 48), "green" if project == cls.hydro else "blue").save(
                    cls.store.project_dir(project) / "images" / name
                )
                project.images.append(ImageRecord(id=f"{project.id}_{i}", file_name=name, width=64, height=48))
        for project in (cls.bottle, cls.hydro, cls.empty):
            cls.store.save(project)
        cls.patches = [patch.object(app_module, "WORKSPACE", cls.workspace),
                       patch.object(app_module.SmartLabelApp, "_refresh_hardware"),
                       patch.object(app_module.messagebox, "showerror"),
                       patch.object(app_module.messagebox, "showinfo")]
        for item in cls.patches:
            item.start()
        cls.app = app_module.SmartLabelApp()
        cls.app.withdraw()

    def setUp(self):
        self.app.project_views.clear()
        self.app.image_filter.set("Tất cả")
        self.app._change_image_filter()
        app_module.messagebox.showerror.reset_mock()
        app_module.messagebox.showinfo.reset_mock()

    def tearDown(self):
        # Make swallowed GUI exceptions test failures instead of hanging CI.
        app_module.messagebox.showerror.assert_not_called()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()  # deliberately don't call _on_close (which saves projects)
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def switch(self, project):
        self.app._refresh_project_menu()
        label = next(label for label, path in self.app.project_lookup.items()
                     if path.parent.name == project.id)
        self.app._switch_project(label)

    def test_01_round_trip_refreshes_real_app_and_button_order(self):
        for _ in range(3):
            self.switch(self.bottle)
            self.assertEqual(len(self.app.filtered_images), 55)
            self.assertFalse(self.app.hydro_import_button.winfo_manager())
            self.switch(self.hydro)
            self.assertEqual(len(self.app.filtered_images), 7)
            self.assertEqual(self.app.canvas.project.id, self.hydro.id)
            self.assertEqual(set(self.app.attribute_widgets), {"plant_presence", "yellow_leaf", "wilt"})
            children = self.app.import_folder_button.master.pack_slaves()
            self.assertLess(children.index(self.app.hydro_archive_import_button), children.index(self.app.hydro_import_button))
            self.assertLess(children.index(self.app.hydro_import_button), children.index(self.app.import_folder_button))
            self.assertIn("Classification toàn ảnh", self.app.project_summary.get("1.0", "end"))

    def test_02_empty_project_clears_canvas_and_class(self):
        self.switch(self.bottle)
        self.app.canvas.active_class_id = 1
        self.switch(self.empty)
        self.assertIsNone(self.app.canvas.record)
        self.assertIsNone(self.app.canvas.image)
        self.assertIsNone(self.app.canvas.active_class_id)
        self.assertEqual(self.app.current_index, -1)
        self.assertFalse(self.app.canvas.history)

    def test_label_details_follow_project_workflow_without_losing_review_controls(self):
        for _ in range(2):
            self.switch(self.hydro)
            self.assertFalse(self.app.class_quick_frame.winfo_manager())
            self.assertFalse(self.app.annotation_info.winfo_manager())
            self.assertFalse(self.app.approve_switch.winfo_manager())
            self.assertEqual(self.app.approve_image_button.winfo_manager(), "pack")
            self.assertEqual(self.app.unapprove_image_button.winfo_manager(), "pack")
            self.assertEqual(self.app.attribute_panel.winfo_manager(), "pack")
            labels = [child.cget("text") for child in self.app.attribute_panel.winfo_children()
                      if isinstance(child, app_module.ctk.CTkLabel)]
            self.assertFalse(any("Ảnh slot" in label or "hai giai đoạn" in label for label in labels))
            # Repacking attributes while the box panel is hidden must stay above review.
            self.app.attribute_panel.pack_forget()
            self.app._apply_attribute_panel_visibility()
            children = self.app.review_actions.master.pack_slaves()
            self.assertLess(children.index(self.app.attribute_panel), children.index(self.app.hydro_metadata_frame))
            self.assertLess(children.index(self.app.hydro_metadata_frame), children.index(self.app.review_actions))
            self.switch(self.bottle)
            self.assertEqual(self.app.class_quick_frame.winfo_manager(), "pack")
            self.assertEqual(self.app.annotation_info.winfo_manager(), "pack")
            self.assertEqual(self.app.approve_switch.winfo_manager(), "pack")
            self.assertEqual(len(self.app.class_buttons), 2)
            children = self.app.review_actions.master.pack_slaves()
            self.assertLess(children.index(self.app.annotation_info), children.index(self.app.approve_switch))
            self.assertLess(children.index(self.app.approve_switch), children.index(self.app.review_actions))

    def test_03_model_and_dataset_paths_do_not_leak(self):
        self.switch(self.bottle)
        for variable in (self.app.model_path, self.app.deploy_model_path,
                         self.app.evaluation_model_path, self.app.evaluation_data_path):
            variable.set("old-project-model.pt")
        self.app.train_data_entry.insert(0, "old-project-data.yaml")
        self.app.train_model_entry.delete(0, tk.END)
        self.app.train_model_entry.insert(0, "old-project-checkpoint.pt")
        self.switch(self.hydro)
        for variable in (self.app.model_path, self.app.deploy_model_path,
                         self.app.evaluation_model_path, self.app.evaluation_data_path):
            self.assertEqual(variable.get(), "")
        self.assertEqual(self.app.train_data_entry.get(), "")
        self.assertEqual(self.app.train_model_entry.get(), "yolo11n-cls.pt")

    def test_04_remembers_page_and_image_only_for_that_project(self):
        self.switch(self.bottle)
        self.app._change_image_page(1)
        selected = self.app.canvas.record.id
        self.switch(self.hydro)
        self.assertEqual(self.app.image_page, 0)
        self.assertEqual(self.app.current_index, 0)
        self.switch(self.bottle)
        self.assertEqual(self.app.image_page, 1)
        self.assertEqual(self.app.canvas.record.id, selected)

    def test_05_empty_filter_is_kept_per_project_without_old_canvas(self):
        self.switch(self.bottle)
        self.app.image_filter.set("Đã duyệt")
        self.app._change_image_filter()
        self.assertFalse(self.app.filtered_images)
        self.assertIsNone(self.app.canvas.record)
        self.switch(self.hydro)
        self.assertEqual(self.app.image_filter.get(), "Tất cả")
        self.assertEqual(len(self.app.filtered_images), 7)
        self.switch(self.bottle)
        self.assertEqual(self.app.image_filter.get(), "Đã duyệt")
        self.assertIsNone(self.app.canvas.record)

    def test_06_same_kind_projects_and_same_selection_are_safe(self):
        self.switch(self.hydro)
        self.switch(self.empty)
        self.assertFalse(self.app.filtered_images)
        self.switch(self.hydro)
        original = self.app.project
        self.app.project.name = "Unsaved in-memory name"
        self.switch(self.hydro)
        self.assertIs(self.app.project, original)
        self.assertEqual(self.app.project.name, "Unsaved in-memory name")

    def test_07_busy_jobs_cannot_switch_or_create_even_before_done_event(self):
        self.switch(self.bottle)
        original = self.app.project
        for flag in ("import_in_progress", "auto_label_running", "evaluation_running",
                     "running_training_task", "batch_training_active", "running_rknn_task", "rknn_batch_active",
                     "hydro_export_running"):
            before = getattr(self.app, flag)
            try:
                setattr(self.app, flag, "classify" if flag.startswith("running_") else True)
                self.switch(self.hydro)
                self.assertIs(self.app.project, original)
                with patch.object(app_module, "ask_new_project") as dialog:
                    self.app._new_project()
                    dialog.assert_not_called()
            finally:
                setattr(self.app, flag, before)

    def test_08_invalid_project_load_restores_menu_without_writing(self):
        self.switch(self.bottle)
        original = self.app.project
        before = (self.store.project_dir(self.bottle) / "project.json").read_bytes()
        path = self.workspace / "projects" / "invalid" / "project.json"
        self.app.project_lookup["Broken"] = path
        with self.assertLogs(app_module.logger, level="ERROR"):
            self.app._switch_project("Broken")
        self.assertIs(self.app.project, original)
        self.assertIn("Bottle", self.app.project_menu.get())
        self.assertEqual(before, (self.store.project_dir(self.bottle) / "project.json").read_bytes())
        app_module.messagebox.showerror.assert_called_once()
        app_module.messagebox.showerror.reset_mock()

    def test_09_layout_error_is_logged_and_data_still_refreshes(self):
        self.switch(self.bottle)
        with patch.object(self.app, "_apply_project_context_visibility", side_effect=tk.TclError("test layout")):
            with self.assertLogs(app_module.logger, level="ERROR"):
                self.switch(self.hydro)
        self.assertEqual(self.app.canvas.project.id, self.hydro.id)
        self.assertEqual(len(self.app.filtered_images), 7)
        self.app._apply_project_context_visibility()

    def test_10_required_refresh_failure_returns_to_previous_context(self):
        self.switch(self.bottle)
        original = self.app._refresh_project_statistics
        def fail_for_hydro():
            if self.app.project.id == self.hydro.id:
                raise RuntimeError("fixture: required refresh failure")
            original()
        with patch.object(self.app, "_refresh_project_statistics", side_effect=fail_for_hydro):
            with self.assertLogs(app_module.logger, level="ERROR"):
                self.switch(self.hydro)
        self.assertEqual(self.app.project.id, self.bottle.id)
        self.assertEqual(self.app.canvas.project.id, self.bottle.id)
        app_module.messagebox.showerror.assert_called_once()
        app_module.messagebox.showerror.reset_mock()

    def test_11_hidden_anchor_falls_back_without_tcl_error(self):
        frame = tk.Frame(self.app)
        a, b, c = [tk.Button(frame) for _ in range(3)]
        c.pack()
        with self.assertLogs("smartlabel.ui_layout", level="WARNING"):
            pack_before(a, b)
        self.assertEqual(a.winfo_manager(), "pack")
        frame.destroy()

    def test_12_classless_project_cannot_create_box_or_polygon(self):
        self.switch(self.hydro)
        canvas = self.app.canvas
        self.assertIsNone(canvas.active_class_id)
        canvas.set_mode("box")
        canvas.drag_start = (1, 1)
        x, y = canvas.to_canvas(20, 20)
        canvas._release(SimpleNamespace(x=x, y=y))
        canvas.set_mode("polygon")
        canvas.polygon_points = [[1, 1], [20, 1], [20, 20]]
        canvas._double_click(None)
        self.assertEqual(canvas.record.annotations, [])

    def test_13_switch_invalidates_sam_requests_and_annotation_edit_state(self):
        self.switch(self.bottle)
        old_version = self.app.sam_click_request_version
        self.app.sam_request_versions["old-ann"] = 9
        self.app.canvas.edit_state = {"id": "old-ann"}
        self.app.canvas.drag_start = (1, 1)
        self.switch(self.hydro)
        self.assertGreater(self.app.sam_click_request_version, old_version)
        self.assertEqual(self.app.sam_request_versions, {})
        self.assertIsNone(self.app.canvas.edit_state)
        self.assertIsNone(self.app.canvas.drag_start)

    def test_14_new_project_uses_the_same_clean_context(self):
        self.switch(self.bottle)
        with patch.object(app_module, "ask_new_project", return_value=("New empty", "blank", {})):
            self.app._new_project()
        self.assertEqual(self.app.project.name, "New empty")
        self.assertIsNone(self.app.canvas.record)
        self.assertIsNone(self.app.canvas.active_class_id)
        self.assertEqual(self.app.image_filter.get(), "Tất cả")

    def test_15_standard_attribute_mode_round_trip_keeps_export_controls(self):
        standard = self.store.create_project("Attributes", classes=["item"])
        standard.attribute_schema = {"condition": ["present", "absent"]}
        standard.attribute_classification_enabled = True
        self.store.save(standard)
        for _ in range(3):
            self.switch(self.bottle)
            self.switch(standard)
            self.assertTrue(self.app.batch_rknn_export_button.winfo_manager())
            self.assertFalse(self.app.hydro_bundle_export_button.winfo_manager())
            self.switch(self.hydro)
            self.assertTrue(self.app.hydro_bundle_export_button.winfo_manager())
            self.assertFalse(self.app.batch_rknn_export_button.winfo_manager())
            self.assertFalse(hasattr(self.app, "hydro_onnx_export_button"))
            self.assertEqual(self.app.deploy_title_label.cget("text"), "GÓI MODEL CHO HYDRO")
            self.assertEqual(self.app.deploy_stop_button.cget("text"), "Dừng tạo gói")

    def test_16_completion_event_owns_source_project_until_processed(self):
        self.switch(self.bottle)
        self.app.running_training_task = "detect"
        self.app.event_queue.put(("train_done", 0))
        self.switch(self.hydro)
        self.assertEqual(self.app.project.id, self.bottle.id)
        completed_for = []
        with patch.object(self.app, "_activate_latest_trained_model", side_effect=lambda: completed_for.append(self.app.project.id)):
            self.app._drain_events()
        self.assertEqual(completed_for, [self.bottle.id])
        self.assertFalse(self.app.running_training_task)
        self.switch(self.hydro)
        self.assertEqual(self.app.project.id, self.hydro.id)

    def test_17_auto_error_releases_switch_guard(self):
        self.app.auto_label_running = True
        self.app.event_queue.put(("auto_error", "fixture auto failure"))
        self.app._drain_events()
        self.assertFalse(self.app.auto_label_running)
        app_module.messagebox.showerror.assert_called_once()
        app_module.messagebox.showerror.reset_mock()

    def test_18_failed_rollback_drops_editing_context_not_user_data(self):
        self.switch(self.bottle)
        before = {p: p.read_bytes() for p in self.workspace.glob("projects/*/project.json")}
        with patch.object(self.app, "_refresh_project_statistics", side_effect=RuntimeError("fixture persistent failure")):
            with self.assertLogs(app_module.logger, level="ERROR"):
                self.switch(self.hydro)
        self.assertIsNone(self.app.project)
        self.assertIsNone(self.app.canvas.record)
        self.assertIsNone(self.app.canvas.active_class_id)
        self.assertEqual(self.app.model_path.get(), "")
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))
        app_module.messagebox.showerror.assert_called_once()
        app_module.messagebox.showerror.reset_mock()

    def test_19_late_sam_result_cannot_modify_destination_project(self):
        self.switch(self.bottle)
        version = self.app.sam_click_request_version
        self.switch(self.hydro)
        record = self.app.canvas.record
        self.app.event_queue.put(("sam_click_done", (
            record.id, version, 0, "rect", {}, {"bbox": [0, 0, 10, 10]}, 0.9,
        )))
        self.app._drain_events()
        self.assertEqual(record.annotations, [])


    def test_20_trash_last_project_detaches_and_does_not_recreate_on_save(self):
        disposable = self.store.create_project("Disposable GUI test", classes=["test"])
        self.app._change_project_context(disposable)
        with patch.object(app_module.messagebox, "askyesno", return_value=True), \
                patch.object(self.store, "list_projects", return_value=[]), \
                patch.object(self.app.store, "list_projects", return_value=[]):
            self.app._trash_current_project()
            self.assertIsNone(self.app.project)
            self.app.save_project()
        self.assertFalse(self.store.project_dir(disposable).exists())
        restored = self.store.restore_project(disposable.id)
        self.app._change_project_context(restored)
        self.assertEqual(self.app.project.id, disposable.id)
        self.switch(self.bottle)

    def test_21_trash_cancel_and_busy_preserve_project(self):
        self.switch(self.bottle)
        path = self.store.project_dir(self.bottle) / "project.json"
        before = path.read_bytes()
        with patch.object(app_module.messagebox, "askyesno", return_value=False):
            self.app._trash_current_project()
        self.assertEqual(path.read_bytes(), before)
        self.app.import_in_progress = True
        try:
            with patch.object(app_module.messagebox, "askyesno") as confirmation:
                self.app._trash_current_project()
                confirmation.assert_not_called()
        finally:
            self.app.import_in_progress = False
        self.assertEqual(path.read_bytes(), before)


    def test_22_repair_preview_cancel_does_not_import_or_change_projects(self):
        self.switch(self.hydro)
        project = self.app.project
        before = project.to_dict()
        plan = {"slotImages": 3, "captures": 1, "keptImages": 7, "digest": "fixture"}
        self.app.import_in_progress = True
        self.app.event_queue.put(("hydro_archive_repair_confirmation", (project, "fixture.zip", plan)))
        with patch.object(app_module.messagebox, "askyesno", return_value=False) as confirm, \
                patch.object(self.app, "_start_hydro_archive_import") as start:
            self.app._drain_events()
            confirm.assert_called_once()
            start.assert_not_called()
        self.assertFalse(self.app.import_in_progress)
        self.assertEqual(project.to_dict(), before)

    def test_23_repair_preview_confirm_forwards_digest_to_same_project(self):
        self.switch(self.hydro)
        project = self.app.project
        plan = {"slotImages": 2, "captures": 1, "keptImages": 8, "digest": "verified-plan"}
        self.app.import_in_progress = True
        self.app.event_queue.put(("hydro_archive_repair_confirmation", (project, "fixture.zip", plan)))
        with patch.object(app_module.messagebox, "askyesno", return_value=True), \
                patch.object(self.app, "_start_hydro_archive_import") as start:
            self.app._drain_events()
            start.assert_called_once_with(project, "fixture.zip", "verified-plan")
        self.app.import_in_progress = False

    def test_24_edited_value_names_refresh_labeling_qa_and_raw_value_selection(self):
        from smartlabel.ui_components import ProjectSettingsDialog
        from smartlabel.hydro_labels import model_attributes
        project = self.store.create_project("Value name UI fixture", task="classify")
        apply_hydroponic_slot_template(project)
        source = self.store.project_dir(project) / "fixture.png"
        Image.new("RGB", (64, 48), "green").save(source)
        self.store.import_images(project, [source])
        project.images[0].attributes = {"plant_presence": "present", "yellow_leaf": "present", "wilt": "absent"}
        project.images[0].review_status = "reviewed"
        self.store.save(project)
        self.switch(project)
        dialog = ProjectSettingsDialog(self.app, self.app.project, self.app._save_project_settings)
        dialog.withdraw()
        row = next(r for r in dialog.attribute_groups["yellow_leaf"]["rows"] if r["value"].get() == "present")
        row["entry"].delete(0, "end")
        row["entry"].insert(0, "Phát hiện vàng lá")
        dialog._save()
        self.assertEqual(self.app.attribute_widgets["yellow_leaf"].get(), "Có · Phát hiện vàng lá")
        self.assertEqual(self.app.project.images[0].review_status, "reviewed")
        self.assertFalse(self.app.attribute_widgets["yellow_leaf"].cget("dynamic_resizing"))
        with patch.object(self.app, "_append_review_result") as result:
            self.app._run_hydro_qa()
        self.assertTrue(any("Có · Phát hiện vàng lá: 1" in str(call) for call in result.call_args_list))
        self.switch(self.bottle)
        self.switch(project)
        self.assertEqual(self.app.attribute_widgets["yellow_leaf"].get(), "Có · Phát hiện vàng lá")
        self.app.attribute_widgets["yellow_leaf"].cget("command")("Không có lá vàng")
        self.assertEqual(self.app.project.images[0].attributes["yellow_leaf"], "absent")
        self.assertEqual(self.app.project.images[0].review_status, "draft")
        self.app.attribute_widgets["yellow_leaf"].cget("command")("Có · Phát hiện vàng lá")
        loaded = self.store.load(project.id)
        self.assertEqual(loaded.images[0].attributes["yellow_leaf"], "present")
        attr = next(a for a in model_attributes(loaded) if a["id"] == "yellow_leaf")
        self.assertEqual(next(v for v in attr["values"] if v["id"] == "present")["displayName"], "Phát hiện vàng lá")


if __name__ == "__main__":
    unittest.main()
