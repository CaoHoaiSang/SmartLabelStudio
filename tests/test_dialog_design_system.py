from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import time
import tkinter as tk
import unittest

import customtkinter as ctk

from smartlabel.ui_layout import dialog_bounds, setup_dialog, SourceTabs
from smartlabel.studio_dialogs import MessageDialog, InputDialog
from smartlabel import studio_dialogs as messages
from smartlabel.project_store import ProjectStore
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_overview import summarize_heldout_rows, ProjectOverview


class DialogBoundsTests(unittest.TestCase):
    def test_owner_monitor_and_dpi_are_used_without_clipping(self):
        for area in ((0, 0, 1366, 728), (-1920, 0, 0, 1040), (1920, -1080, 3840, -40)):
            for scale in (1, 1.25, 1.5, 2):
                w, h, x, y = dialog_bounds(area, (area[0] + 30, area[1] + 50, 1100, 900), 1380, 850, scale)
                self.assertGreaterEqual(x, area[0] + 16)
                self.assertGreaterEqual(y, area[1] + 32)
                self.assertLessEqual(x + round(w * scale), area[2] - 16)
                self.assertLessEqual(y + round(h * scale), area[3] - 32)

    def test_centered_on_owner_when_there_is_space(self):
        self.assertEqual(dialog_bounds((0, 0, 1920, 1040), (100, 80, 1200, 800), 600, 400),
                         (600, 400, 400, 280))


class StudioDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = ctk.CTk()
        self.root.geometry("1100x740+30+30")
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.store = ProjectStore(Path(self.temp.name) / "workspace")
        self.root.project = self.root.store.create_project("Chỉ fixture · không dữ liệu người dùng", task="classify")
        apply_hydroponic_slot_template(self.root.project)
        self.root._can_change_project = lambda: True
        self.root.evaluation_running = False
        self.root.update()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for identifier in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", identifier)
        self.root.destroy()
        self.temp.cleanup()

    def settle(self):
        deadline = time.monotonic() + .33
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(self.errors, [])

    def assert_inside(self, widget, dialog):
        self.assertTrue(widget.winfo_ismapped(), str(widget))
        self.assertGreater(widget.winfo_height(), 20)
        self.assertGreaterEqual(widget.winfo_rootx(), dialog.winfo_rootx())
        self.assertGreaterEqual(widget.winfo_rooty(), dialog.winfo_rooty())
        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), dialog.winfo_rootx() + dialog.winfo_width())
        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())

    def test_four_source_tabs_have_full_text_in_narrow_sidebar_and_sync(self):
        sidebar = ctk.CTkFrame(self.root, width=280, height=200)
        sidebar.pack(); sidebar.pack_propagate(False)
        variable = tk.StringVar(value="Giàn")
        calls = []
        tabs = SourceTabs(sidebar, variable, calls.append)
        tabs.pack(fill="x", padx=8)
        self.settle()
        for key, button in tabs.buttons.items():
            self.assertLessEqual(button._text_label.winfo_reqwidth(), button.winfo_width() - 12, key)
        tabs.buttons["TEST"].invoke()
        self.assertEqual(calls, ["TEST"])
        # A rejected source change must not visually select an uncommitted value.
        self.assertEqual(variable.get(), "Giàn")
        variable.set("Khách đóng góp")
        self.assertEqual(tabs.buttons["Khách đóng góp"].cget("fg_color"), "#256481")
        tabs.destroy()
        self.assertEqual(variable.trace_info(), [])

    def test_fleet_is_owned_nonmodal_and_buttons_fit_small_window(self):
        from smartlabel.fleet_intake_view import FleetIntakeView
        dialog = FleetIntakeView(self.root, self.root.project, self.root.store.project_dir(self.root.project))
        self.settle()
        self.assertEqual(str(dialog.transient()), str(self.root))
        self.assertFalse(bool(dialog.attributes("-topmost")))
        self.assertIsNone(self.root.grab_current())
        self.root.lift()
        self.settle()
        stack = tuple(map(str, self.root.tk.call("wm", "stackorder", self.root)))
        self.assertGreater(stack.index(str(dialog)), stack.index(str(self.root)))
        dialog.geometry("650x520")
        self.settle()
        # Footer is outside the scroll area, including when messages get long.
        close = next(w for w in self.descendants(dialog) if isinstance(w, ctk.CTkButton) and w.cget("text") == "Đóng")
        self.assert_inside(close, dialog)
        dialog.close()
        self.assertIsNone(self.root.grab_current())

    def test_nested_confirmation_cancel_restores_parent_grab(self):
        parent = ctk.CTkToplevel(self.root)
        setup_dialog(parent, self.root, 700, 500)
        self.settle()
        self.assertIs(self.root.grab_current(), parent)
        child = MessageDialog(parent, "Xác nhận", "Không được tự đồng ý.", choices=[(True, "Có"), (False, "Không")], cancel=False)
        self.settle()
        self.assertIs(self.root.grab_current(), child)
        child.cancel()
        self.assertIs(child.result, False)
        self.assertIs(self.root.grab_current(), parent)
        parent.destroy()
        self.assertIsNone(self.root.grab_current())

    def test_long_help_scrolls_footer_and_wrapping_settles(self):
        dialog = MessageDialog(self.root, "Trợ giúp ngưỡng", "Nội dung kiểm thử dài, không dùng dữ liệu thật. " * 200)
        self.settle()
        dialog.geometry("620x400")
        self.settle()
        self.assert_inside(dialog.buttons["ok"], dialog)
        scroll = next(w for w in self.descendants(dialog) if isinstance(w, ctk.CTkScrollableFrame))
        self.assertLess(scroll._parent_canvas.yview()[1], 1)
        self.assertLessEqual(dialog.winfo_rooty() + dialog.winfo_height(), dialog.winfo_screenheight())
        dialog.cancel()

    def test_input_validation_and_cancel_do_not_accept_values(self):
        dialog = InputDialog(self.root, "Tách frame", "Số N", number=True, minvalue=1, maxvalue=10)
        for invalid in ("", "abc", "0", "11"):
            dialog.entry.delete(0, "end"); dialog.entry.insert(0, invalid)
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertTrue(dialog.winfo_exists())
        dialog.entry.delete(0, "end"); dialog.entry.insert(0, "2")
        dialog.accept()
        self.assertEqual(dialog.result, 2)
        cancelled = InputDialog(self.root, "Xác nhận", "Nhập TRAIN ALL")
        cancelled.entry.insert(0, "TRAIN ALL")
        cancelled.destroy()
        self.assertIsNone(cancelled.result)

    def test_dialog_actions_visible_and_project_unchanged(self):
        from smartlabel.ui_components import NewProjectDialog, HydroBundleConfigDialog, ProjectSettingsDialog
        from smartlabel.version_dialog import DatasetVersionDialog
        from smartlabel.benchmark_dialog import ExternalBenchmarkDialog
        from smartlabel.heldout_capture_dialog import HeldoutCaptureDialog
        before = deepcopy(self.root.project.to_dict())
        factories = [lambda: NewProjectDialog(self.root, "hydroponic_slot"),
                     lambda: HydroBundleConfigDialog(self.root, {}),
                     lambda: ProjectSettingsDialog(self.root, self.root.project, lambda: None),
                     lambda: DatasetVersionDialog(self.root),
                     lambda: ExternalBenchmarkDialog(self.root),
                     lambda: HeldoutCaptureDialog(self.root)]
        for create in factories:
            dialog = create()
            self.settle()
            dialog.geometry("700x520")
            self.settle()
            close_buttons = [w for w in self.descendants(dialog) if isinstance(w, ctk.CTkButton) and w.cget("text") in ("Hủy", "HỦY", "Đóng")]
            self.assertTrue(close_buttons, type(dialog).__name__)
            self.assert_inside(close_buttons[-1], dialog)
            self.assertEqual(str(dialog.transient()), str(self.root))
            if isinstance(dialog, HeldoutCaptureDialog):
                self.assertTrue(dialog._compact_layout)
                dialog.close()
            else:
                dialog.destroy()
        self.assertEqual(self.root.project.to_dict(), before)

    def test_generic_class_name_resizes_without_hiding_delete(self):
        from smartlabel.ui_components import ProjectSettingsDialog
        generic = self.root.store.create_project("Generic", classes=["Một tên Class dài để kiểm tra bố cục"])
        dialog = ProjectSettingsDialog(self.root, generic, lambda: None)
        self.settle(); dialog.geometry("650x520"); self.settle()
        row = dialog.class_rows[0]["frame"]
        delete = next(w for w in row.winfo_children() if isinstance(w, ctk.CTkButton) and w.cget("text") == "Xóa")
        self.assert_inside(delete, dialog)
        entry = next(w for w in row.winfo_children() if isinstance(w, ctk.CTkEntry))
        self.assertGreater(entry.winfo_width(), 100)
        dialog.destroy()

    def test_shared_attribute_cards_keep_source_counts_separate(self):
        from smartlabel.app import COLORS
        from smartlabel.dataset_manager import DatasetManager
        view = ProjectOverview(self.root, COLORS)
        view.pack(fill="both", expand=True)
        summary = DatasetManager(self.root.store).summary(self.root.project)
        supplements = {"images": [{"reviewStatus": "reviewed", "enabled": True,
                                    "attributes": {"plant_presence": "present"}}]}
        heldout = {"lots": [{"lotId": "fixture"}], "images": [
            {"reviewStatus": "reviewed", "attributes": {"plant_presence": "absent"}},
            {"reviewStatus": "unlabeled", "declaredEmpty": True, "attributes": {}}]}
        with patch("smartlabel.project_overview.load_review", return_value=(supplements, "r")), \
             patch("smartlabel.project_overview.load_collection", return_value=(heldout, "r")):
            view.render(self.root.store, self.root.project, summary)
        self.settle()
        headings = {w.cget("text"): w for w in self.descendants(view) if isinstance(w, ctk.CTkLabel)}
        supplement_card = headings["ẢNH BỔ TRỢ · CHỈ TRAIN"].master
        test_card = headings["BỘ TEST ĐỘC LẬP · KHÔNG DÙNG TRAIN"].master
        supplement_text = [w.cget("text") for w in self.descendants(supplement_card) if isinstance(w, ctk.CTkLabel)]
        test_text = [w.cget("text") for w in self.descendants(test_card) if isinstance(w, ctk.CTkLabel)]
        self.assertIn("Có  1", supplement_text)
        self.assertIn("Không  1", test_text)
        self.assertNotIn("Có  1", test_text)
        chips = [w for card in (supplement_card, test_card) for w in self.descendants(card)
                 if isinstance(w, ctk.CTkLabel) and w.cget("text") in ("Có  1", "Không  1")]
        self.assertTrue(all(w.cget("fg_color") == "#1b3546" for w in chips))
        self.assertEqual(self.root.project.images, [])

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from StudioDialogTests.descendants(child)


class SourceStatisticsTests(unittest.TestCase):
    def test_test_counts_use_reviewed_labels_not_position_or_empty_declarations(self):
        with TemporaryDirectory() as temp:
            store = ProjectStore(Path(temp))
            project = store.create_project("fixture", task="classify")
            apply_hydroponic_slot_template(project)
            rows = [
                {"reviewStatus": "reviewed", "attributes": {"plant_presence": "present", "wilt": "absent"}},
                {"reviewStatus": "reviewed", "attributes": {"plant_presence": "absent", "wilt": "not_applicable"}},
                {"reviewStatus": "unlabeled", "emptyDeclared": True, "attributes": {}},
                {"reviewStatus": "rejected", "attributes": {"plant_presence": "present"}},
            ]
            before = deepcopy(rows)
            stats = summarize_heldout_rows(project, rows)
            self.assertEqual((stats["total"], stats["reviewed"], stats["pending"], stats["rejected"]), (4, 2, 1, 1))
            counts = {row["id"]: row["counts"] for row in stats["attributes"]}
            self.assertEqual(counts["plant_presence"]["positive"], 1)
            self.assertEqual(counts["plant_presence"]["negative"], 1)
            self.assertEqual(counts["wilt"]["not_applicable"], 1)
            self.assertEqual(project.images, [])
            self.assertEqual(rows, before)

    def test_confirmation_api_returns_native_boolean_semantics(self):
        for function, expected in ((messages.askyesno, False), (messages.askokcancel, False),
                                   (messages.askretrycancel, False), (messages.askyesnocancel, None)):
            with patch.object(messages, "_show", return_value=expected) as show:
                self.assertIs(function("Title", "Message"), expected)
                self.assertIs(show.call_args.kwargs["cancel"], expected)


if __name__ == "__main__":
    unittest.main()
