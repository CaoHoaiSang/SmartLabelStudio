"""Real Tk widgets over temporary fixtures, never the user's running application."""
import tkinter as tk
import unittest
from unittest.mock import patch, Mock
import customtkinter as ctk

import test_split_health as fixtures
from smartlabel import split_dialog


class SplitDialogTests(unittest.TestCase):
    def setUp(self):
        fixtures.SplitHealthTests.setUp(self)
        try:
            self.root = ctk.CTk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.geometry("1200x800")
        self.root.update()
        self.addCleanup(self.close_root)
        self.changed = Mock()
        self.dialog = split_dialog.SplitManagerDialog(self.root, self.manager, self.project, self.changed,
                                                       problems_only=True)
        self.addCleanup(self.dialog.destroy)
        self.root.update()

    save_manifest = fixtures.SplitHealthTests.save_manifest

    def close_root(self):
        for timer in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(timer)
        self.root.destroy()

    def test_focus_filter_reason_and_coverage(self):
        self.assertEqual([r["group"] for r in self.dialog.rows], ["g7"])
        self.assertIn("1 ảnh bổ trợ", self.dialog.health_label.cget("text"))
        self.assertTrue(self.dialog.repair_button.winfo_manager())
        self.assertIn("Có/Không", self.dialog.coverage.get("1.0", "end"))
        self.dialog.listbox.select_set(0)
        self.dialog._show_selected()
        self.assertIn("1 biến thể", self.dialog.detail.cget("text"))
        self.assertIn("Đã duyệt Có/Không", self.dialog.detail.cget("text"))

    def test_cancel_repair_changes_nothing(self):
        before = self.split.read_bytes()
        with patch.object(split_dialog.messagebox, "askokcancel", return_value=False) as confirmation:
            self.dialog._repair()
        self.assertIn("DỰ KIẾN SAU KHI CHUYỂN", confirmation.call_args.args[1])
        self.assertIn("Lá vàng", confirmation.call_args.args[1])
        self.assertEqual(before, self.split.read_bytes())
        self.changed.assert_not_called()

    def test_confirm_repair_clears_conflict_and_keeps_other_groups(self):
        with patch.object(split_dialog.messagebox, "askokcancel", return_value=True):
            self.dialog._repair()
        self.assertFalse(self.dialog.health["conflicts"])
        self.assertEqual(self.dialog.rows, [])
        self.assertFalse(self.dialog.repair_button.winfo_manager())
        self.changed.assert_called_once()
        result = self.manager.ensure_split_assignment(self.project, persist=False)["groups"]
        self.assertEqual(result, {**self.assignment, "g7": "train"})

    def test_stale_repair_fails_without_moving_groups(self):
        before = self.split.read_bytes()
        self.project.images[0].attributes["plant_presence"] = "uncertain"
        with patch.object(split_dialog.messagebox, "askokcancel", return_value=True), \
                patch.object(split_dialog.messagebox, "showerror") as error:
            self.dialog._repair()
        self.assertIn("thay đổi", error.call_args.args[1])
        self.assertEqual(before, self.split.read_bytes())
        self.changed.assert_not_called()

    def test_protected_manual_move_explains_before_confirmation(self):
        self.dialog.listbox.select_set(0)
        before = self.split.read_bytes()
        with patch.object(split_dialog.messagebox, "showwarning") as warning, \
                patch.object(split_dialog.messagebox, "askyesno") as confirm:
            self.dialog._move("test")
        confirm.assert_not_called()
        self.assertIn("Bổ trợ", warning.call_args.args[1])
        self.assertEqual(before, self.split.read_bytes())

    def test_all_filter_keeps_all_rows_and_horizontal_scroll(self):
        self.dialog.filter_menu.set("Tất cả")
        self.dialog._refresh()
        self.assertEqual(len(self.dialog.rows), 10)
        self.assertTrue(self.dialog.listbox.cget("xscrollcommand"))
        self.assertGreater(self.dialog.coverage.winfo_width(), 400)

    def test_compact_window_keeps_actions_and_list_accessible(self):
        self.dialog.geometry("820x650")
        self.root.update()
        self.assertGreater(self.dialog.listbox.winfo_height(), 75)
        buttons = []
        def collect(widget):
            for child in widget.winfo_children():
                if isinstance(child, ctk.CTkButton) and child.cget("text") in ("→ TRAIN", "→ VALIDATION", "→ TEST", "Đóng"):
                    buttons.append(child)
                collect(child)
        collect(self.dialog)
        self.assertEqual(len(buttons), 4)
        for button in buttons:
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 self.dialog.winfo_rooty() + self.dialog.winfo_height())


if __name__ == "__main__":
    unittest.main()
