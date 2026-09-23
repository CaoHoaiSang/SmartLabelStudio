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

    def test_paragraphs_use_available_width_not_a_self_shrinking_column(self):
        from smartlabel.ui_components import ProjectSettingsDialog, HydroBundleConfigDialog
        for dialog, prefix in ((ProjectSettingsDialog(self.root, self.root.project, lambda: None), "Mỗi tình trạng"),
                               (HydroBundleConfigDialog(self.root, {}), "Thông tin đã có")):
            self.settle()
            label = next(w for w in self.descendants(dialog) if isinstance(w, ctk.CTkLabel)
                         and str(w.cget("text")).startswith(prefix))
            for width in (980, 650, 1100):
                dialog.geometry(f"{width}x600")
                self.settle()
                self.assertGreater(label.winfo_width(), label.master.winfo_width() - 65)
                self.assertLessEqual(label.winfo_height(), 60)
                old = label.cget("wraplength")
                self.settle()
                self.assertEqual(label.cget("wraplength"), old)
            dialog.destroy()

    def test_shared_style_is_idempotent_for_already_styled_controls(self):
        from smartlabel.ui_layout import style_dialog_content
        frame = ctk.CTkFrame(self.root, fg_color="transparent")
        button = ctk.CTkButton(frame, height=34, corner_radius=8, font=("Segoe UI", 13))
        label = ctk.CTkLabel(frame, font=("Segoe UI", 13))
        with patch.object(button, "configure", wraps=button.configure) as b, patch.object(label, "configure", wraps=label.configure) as l:
            style_dialog_content(frame)
            b.assert_not_called()
            l.assert_not_called()
        frame.destroy()

    def test_titles_share_cyan_and_capture_controls_have_card_insets(self):
        from smartlabel.heldout_capture_dialog import HeldoutCaptureDialog
        from smartlabel.ui_layout import TITLE
        dialog = HeldoutCaptureDialog(self.root)
        self.settle()
        title = next(w for w in self.descendants(dialog) if isinstance(w, ctk.CTkLabel)
                     and w.cget("text") == "Thu thập ảnh TEST")
        self.assertEqual(title.cget("text_color"), TITLE)
        pane = dialog.lot_menu.master
        for widget in pane.winfo_children():
            if isinstance(widget, (ctk.CTkButton, ctk.CTkOptionMenu, ctk.CTkEntry)):
                padding = widget.pack_info()["padx"]
                self.assertGreaterEqual(int(padding if isinstance(padding, int) else padding[0]), 12)
        section = next(w for w in pane.winfo_children() if isinstance(w, ctk.CTkLabel)
                       and w.cget("text") == "2. Cấu hình chụp")
        self.assertEqual(section.cget("text_color"), TITLE)
        dialog.close()

    def test_project_trash_is_owned_above_parent_without_forcing_other_apps(self):
        from smartlabel.trash_dialog import ProjectTrashDialog
        calls = []
        dialog = ProjectTrashDialog(self.root, [self.root.project], calls.append)
        self.settle()
        self.root.lift()
        self.settle()
        self.assertEqual(str(dialog.transient()), str(self.root))
        stack = tuple(map(str, self.root.tk.call("wm", "stackorder", self.root)))
        self.assertGreater(stack.index(str(dialog)), stack.index(str(self.root)))
        self.assertIs(self.root.grab_current(), dialog)
        self.assertFalse(bool(dialog.attributes("-topmost")))
        dialog.geometry("620x420"); self.settle()
        self.assert_inside(dialog.restore_buttons[0], dialog)
        self.assertEqual(calls, [])
        dialog.restore_buttons[0].invoke()
        self.assertEqual(calls, [self.root.project])
        dialog.destroy()
        self.assertIsNone(self.root.grab_current())
        empty = ProjectTrashDialog(self.root, [], calls.append)
        self.settle()
        self.assertEqual(empty.restore_buttons, [])
        empty.destroy()

    def test_dataset_cards_pair_stack_and_recover_after_project_change(self):
        from smartlabel.ui_layout import TwoColumnCards, wrapped_label
        row = TwoColumnCards(self.root)
        row.pack(fill="x")
        first = ctk.CTkFrame(row, width=1)
        second = ctk.CTkFrame(row, width=1)
        wrapped_label(first, "Phân tập cố định theo Capture Group").pack(fill="x", padx=14)
        wrapped_label(second, "Bộ kiểm định độc lập").pack(fill="x", padx=14)
        row.set_cards(first, second)
        self.settle()
        self.assertEqual(first.grid_info()["row"], second.grid_info()["row"])
        self.assertEqual(second.grid_info()["column"], 1)
        self.assertEqual(first.winfo_height(), second.winfo_height())
        self.root.geometry("700x600"); self.settle()
        self.assertEqual(second.grid_info()["row"], 1)
        row.set_secondary_visible(False); self.settle()
        self.assertFalse(second.winfo_manager())
        self.root.geometry("1100x740"); row.set_secondary_visible(True); self.settle()
        self.assertEqual(second.grid_info()["column"], 1)

    def test_dropdown_is_padded_and_commits_one_callback_restoring_modal_grab(self):
        from smartlabel.dropdown import StudioOptionMenu
        from smartlabel.ui_layout import StudioToplevel
        parent = StudioToplevel(self.root)
        variable = tk.StringVar(value="Hai")
        calls = []
        menu = StudioOptionMenu(parent, values=["Một", "Hai", "Ba"], variable=variable, command=calls.append)
        menu.pack(fill="x", padx=20, pady=20)
        setup_dialog(parent, self.root, 700, 450); self.settle()
        menu._open_dropdown_menu(); self.settle()
        popup = menu.popup
        self.assertIsNotNone(popup)
        self.assertEqual(str(popup.transient()), str(parent))
        self.assertIs(self.root.grab_current(), popup)
        self.assertGreaterEqual(popup.winfo_width(), menu.winfo_width())
        self.assertGreaterEqual(popup.listbox.winfo_rootx() - popup.winfo_rootx(), 8)
        self.assertEqual(popup.listbox.curselection(), (1,))
        popup.select(2); popup.commit()
        self.assertEqual(variable.get(), "Ba")
        self.assertEqual(calls, ["Ba"])
        self.assertIs(self.root.grab_current(), parent)
        parent.destroy()
        self.assertIsNone(self.root.grab_current())

    def test_dropdown_escape_outside_reload_disable_and_destroy_do_not_commit(self):
        from types import SimpleNamespace
        from smartlabel.dropdown import StudioOptionMenu
        calls = []
        menu = StudioOptionMenu(self.root, values=[str(i) for i in range(100)], command=calls.append)
        menu.pack(padx=20, pady=20)
        self.settle()
        for close in (lambda p: p.event_generate("<Escape>"),
                      lambda p: p.outside(SimpleNamespace(x_root=p.winfo_rootx()-10, y_root=p.winfo_rooty())),
                      lambda p: menu.configure(values=["Mới"]),
                      lambda p: menu.configure(state="disabled")):
            menu.configure(state="normal")
            menu._open_dropdown_menu(); self.settle()
            self.assertIsNotNone(menu.popup)
            popup = menu.popup
            self.assertLessEqual(popup.winfo_rooty() + popup.winfo_height(), popup.winfo_screenheight())
            close(popup); self.settle()
            self.assertIsNone(menu.popup)
            self.assertIsNone(self.root.grab_current())
            self.assertEqual(calls, [])
        menu.configure(state="normal")
        menu._open_dropdown_menu(); self.settle()
        menu.destroy(); self.settle()
        self.assertIsNone(self.root.grab_current())

    def test_rack_statistics_have_their_own_source_background(self):
        from smartlabel.app import COLORS
        from smartlabel.dataset_manager import DatasetManager
        view = ProjectOverview(self.root, COLORS)
        view.pack(fill="both", expand=True)
        view.render(self.root.store, self.root.project, DatasetManager(self.root.store).summary(self.root.project))
        self.settle()
        labels = {w.cget("text"): w for w in self.descendants(view) if isinstance(w, ctk.CTkLabel)}
        rack = labels["ẢNH TỪ GIÀN"].master
        self.assertEqual(rack.cget("fg_color"), "#142a3c")
        self.assertIs(labels["THUỘC TÍNH TRÊN ẢNH RỌ"].master, rack)
        self.assertIsNot(labels["ẢNH BỔ TRỢ · CHỈ TRAIN"].master, rack)

    def test_dropdown_keyboard_long_names_and_no_lingering_owner_bindings(self):
        from smartlabel.dropdown import StudioOptionMenu
        calls = []
        value = tk.StringVar(value="Một")
        menu = StudioOptionMenu(self.root, values=["Một", "Hai", "Tên dự án dài " * 30],
                                variable=value, command=calls.append)
        menu.pack(fill="x", padx=20, pady=10)
        self.settle()
        previous = self.root.bind("<Configure>")
        menu._canvas.focus_force()
        menu._canvas.event_generate("<Down>"); self.settle()
        popup = menu.popup
        self.assertIsNotNone(popup)
        self.assertIn("✓", popup.listbox.get(0))
        self.assertLess(popup.listbox.xview()[1], 1)
        popup.listbox.event_generate("<Down>")
        popup.listbox.event_generate("<Return>"); self.settle()
        self.assertEqual(calls, ["Hai"])
        self.assertEqual(value.get(), "Hai")
        self.assertEqual(self.root.bind("<Configure>"), previous)
        for _ in range(3):
            menu._open_dropdown_menu(); self.settle()
            value.set("Một")
            self.assertIsNone(menu.popup)
        self.assertEqual(calls, ["Hai"])
        self.assertEqual(self.root.bind("<Configure>"), previous)
        menu._open_dropdown_menu(); self.settle()
        menu.master.event_generate("<Unmap>"); self.settle()
        self.assertIsNone(menu.popup)
        self.assertIsNone(self.root.grab_current())

    def test_generic_attribute_entries_leave_delete_action_visible(self):
        from smartlabel.ui_components import ProjectSettingsDialog
        generic = self.root.store.create_project("Generic")
        dialog = ProjectSettingsDialog(self.root, generic, lambda: None)
        self.settle()
        tabs = next(w for w in dialog.winfo_children() if isinstance(w, ctk.CTkTabview))
        tabs.set("THUỘC TÍNH")
        dialog.geometry("650x600"); self.settle()
        row = next(iter(dialog.attribute_groups.values()))["rows"][0]["frame"]
        delete = next(w for w in row.winfo_children() if isinstance(w, ctk.CTkButton))
        entry = next(w for w in row.winfo_children() if isinstance(w, ctk.CTkEntry))
        self.assertGreater(entry.winfo_width(), 100)
        self.assertLessEqual(entry.winfo_rootx() + entry.winfo_width(), delete.winfo_rootx())
        self.assertLessEqual(delete.winfo_rootx() + delete.winfo_width(), row.winfo_rootx() + row.winfo_width() - 8)
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
