"""No user workspace: lifecycle, preview ownership and label safety regressions."""
import gc
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

import customtkinter as ctk
from PIL import Image

from smartlabel.frame_filter import FrameDecision, FrameFilterSettings, _load_preview, _run_yolo, _is_protected
from smartlabel.frame_filter_dialog import SmartFrameFilterDialog
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore
from smartlabel.ui_components import ProjectSettingsDialog


class ProjectTrashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / "workspace")
        self.project = self.store.create_project("Dự án cần giữ", classes=["chai"])
        self.source = Path(self.tmp.name) / "ảnh gốc.png"
        Image.new("RGB", (120, 80), "green").save(self.source)
        self.store.import_images(self.project, [self.source])

    def test_trash_restore_round_trip_and_keep_source(self):
        record = self.project.images[0]
        record.attributes = {"màu": "xanh"}
        record.review_status = "reviewed"
        image_bytes = self.store.image_path(self.project, record).read_bytes()
        self.store.trash_project(self.project)
        self.assertEqual(self.store.list_projects(), [])
        self.assertTrue(self.source.is_file())
        self.assertEqual(len(self.store.list_trashed_projects()), 1)
        restored = self.store.restore_project(self.project.id)
        self.assertEqual(restored.images[0].attributes, {"màu": "xanh"})
        self.assertEqual(restored.images[0].review_status, "reviewed")
        self.assertEqual(self.store.image_path(restored, record).read_bytes(), image_bytes)
        self.assertEqual(self.store.list_trashed_projects(), [])

    def test_unsafe_id_and_restore_collision_leave_data_untouched(self):
        original_id = self.project.id
        self.project.id = "../outside"
        with self.assertRaises(ValueError):
            self.store.trash_project(self.project)
        self.project.id = original_id
        self.store.trash_project(self.project)
        self.store.save(self.project)
        with self.assertRaises(ValueError):
            self.store.restore_project(original_id)
        self.assertEqual(len(self.store.list_projects()), 1)
        self.assertEqual(len(self.store.list_trashed_projects()), 1)

    def test_unicode_path_is_readable_by_smart_filter(self):
        self.assertEqual(_load_preview(self.source, FrameFilterSettings()).shape, (108, 192))

    def test_classifier_is_not_treated_as_detector_with_no_objects(self):
        from types import SimpleNamespace
        with patch.dict("sys.modules", {"ultralytics": SimpleNamespace(YOLO=lambda _: SimpleNamespace(task="classify"))}):
            with self.assertRaisesRegex(ValueError, "Classification"):
                _run_yolo([self.source], "fixture.pt", FrameFilterSettings(), None, None)
        record = self.project.images[0]
        record.review_status = "draft"
        record.attributes = {"yellow_leaf": "present"}
        self.assertTrue(_is_protected(record))


class FilterDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = ctk.CTk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        cls.root.geometry("1000x650+20+20")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        for job in cls.root.tk.call("after", "info"):
            cls.root.after_cancel(job)
        cls.root.destroy()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = ProjectStore(Path(self.tmp.name) / "workspace")
        self.project = self.store.create_project("Hydro thử ảnh", task="classify")
        apply_hydroponic_slot_template(self.project)
        for index, size in enumerate([(80, 140), (200, 75)]):
            source = Path(self.tmp.name) / f"rọ cây {index}.png"
            Image.new("RGB", size, "green" if index else "blue").save(source)
            self.store.import_images(self.project, [source])
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.dialog = SmartFrameFilterDialog(self.root, self.project, self.store, lambda *_: None)
        self.dialog._populate([FrameDecision(r.id, r.file_name, "positive", "Giữ", False) for r in self.project.images])
        self.root.update()

    def tearDown(self):
        self.dialog._close()
        self.root.update()
        self.tmp.cleanup()
        self.assertEqual(self.errors, [])

    def test_repeated_selection_resize_and_missing_image_clear_preview(self):
        for _ in range(8):
            for record in self.project.images:
                self.dialog.tree.selection_set(record.id)
                self.dialog._show_selected()
                gc.collect()
                self.root.update()
                self.assertTrue(str(self.dialog.preview_photo) in self.dialog.tk.call("image", "names"))
                self.assertEqual(str(self.dialog.preview_label.cget("image")), str(self.dialog.preview_photo))
        self.store.image_path(self.project, self.project.images[-1]).unlink()
        with self.assertLogs("smartlabel.frame_filter_dialog", level="ERROR"):
            self.dialog._show_selected()
        self.assertIsNone(self.dialog.preview_photo)
        self.assertEqual(self.dialog.preview_label.cget("image"), "")
        self.dialog._source_changed()
        self.root.update()

    def test_centered_fits_screen_and_footer_visible(self):
        self.assertGreaterEqual(self.dialog.winfo_rootx(), 0)
        self.assertGreaterEqual(self.dialog.winfo_rooty(), 0)
        self.assertLessEqual(self.dialog.winfo_rooty() + self.dialog.winfo_height(), self.dialog.winfo_screenheight())
        for control in [self.dialog.delete_button, self.dialog.preview_label]:
            self.assertGreater(control.winfo_height(), 20)
            self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                 self.dialog.winfo_rooty() + self.dialog.winfo_height())

    def test_compact_window_keeps_preview_and_actions_visible(self):
        for geometry in ("1000x640+20+20", "900x600+20+20"):
            self.dialog.geometry(geometry)
            self.root.update()
            for control in (self.dialog.preview_label, self.dialog.delete_button, self.dialog.analyze_button):
                self.assertGreater(control.winfo_height(), 20)
                self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                     self.dialog.winfo_rooty() + self.dialog.winfo_height())
                self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                     self.dialog.winfo_rootx() + self.dialog.winfo_width())

    def test_hydro_values_stable_and_generic_used_values_cannot_be_silently_renamed(self):
        self.dialog.grab_release()
        settings = ProjectSettingsDialog(self.root, self.project, lambda: None)
        expected = dict(self.project.attribute_schema)
        settings._save()
        self.assertEqual(self.project.attribute_schema, expected)
        generic = self.store.create_project("Thuộc tính riêng", classes=["chai"])
        generic.images = self.project.images
        generic.attribute_schema = {"mau": ["Xanh", "Đỏ"]}
        generic.images[0].attributes = {"mau": "Xanh"}
        settings = ProjectSettingsDialog(self.root, generic, lambda: None)
        settings.attribute_groups["mau"]["rows"][0]["value"].set("Lục")
        with patch("smartlabel.ui_components.messagebox.showerror") as error:
            settings._save()
            error.assert_called_once()
        self.assertEqual(generic.attribute_schema["mau"], ["Xanh", "Đỏ"])
        settings.destroy()
