from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import time
import unittest
import customtkinter as ctk

from smartlabel import heldout_capture_dialog as ui, heldout_collection as collection
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore


class HeldoutDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app = ctk.CTk(); self.app.withdraw(); self.addCleanup(self.app.destroy)
        self.app.store = ProjectStore(Path(self.temp.name) / "workspace")
        self.app.project = self.app.store.create_project("Temporary", task="classify")
        apply_hydroponic_slot_template(self.app.project)
        self.app.evaluation_running = False
        self.app._can_change_project = lambda: not self.app.evaluation_running
        self.error = patch.object(ui.messagebox, "showerror").start()
        self.addCleanup(patch.stopall)
        self.dialog = ui.HeldoutCaptureDialog(self.app); self.dialog.withdraw()
        self.addCleanup(self.dialog.temp.cleanup); self.addCleanup(self.dialog.destroy)
        self.addCleanup(self.cancel_timers)

    def cancel_timers(self):
        for identifier in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", identifier)

    def drain(self):
        deadline = time.monotonic()+5
        while self.dialog.busy and time.monotonic() < deadline:
            self.app.update(); time.sleep(.01)
        self.assertFalse(self.dialog.busy)

    def test_presets_keep_all_ten_slots_four_empty_and_optional_codes(self):
        self.dialog.config = {"camera": {"profileId": "fixture"}, "geometry": {"profileId": "fixture", "slots": [{"slotId": str(i)} for i in range(10)]}}
        self.dialog.show_profiles(); self.dialog.preset(True)
        self.assertEqual(sum(v.get() for v in self.dialog.empty_vars.values()), 4)
        self.assertEqual(len(self.dialog.plant_entries), 10)
        self.dialog.preset(False)
        self.assertFalse(any(v.get() for v in self.dialog.empty_vars.values()))
        self.dialog.show_profiles()  # Replacing geometry does not leave dead controls.
        self.assertTrue(all(w.winfo_exists() for w in self.dialog.controls))

    def test_job_ownership_cancel_close_and_no_cross_project_callback(self):
        release = Event(); done = []
        self.dialog.run(lambda: release.wait(2), done.append)
        self.assertTrue(self.app.evaluation_running)
        with patch.object(ui.messagebox, "showinfo"):
            self.assertFalse(self.dialog.close())
        self.app.project = self.app.store.create_project("Other")
        self.dialog.cancel.set(); release.set(); self.dialog.thread.join(3); self.drain()
        self.assertEqual(done, [])
        self.assertFalse(self.app.evaluation_running)

    def test_create_lot_does_not_change_project_or_auto_approve(self):
        self.dialog.date_entry.insert(0, "2026-09-01"); self.dialog.reserved.select()
        self.dialog.create_lot()
        self.error.assert_not_called()
        data, _ = collection.load_collection(self.app.store, self.app.project)
        self.assertEqual(data["lots"][0]["declaredPlantCount"], 16)
        self.assertTrue(data["lots"][0]["sameSowingBatchAsDevelopment"])
        self.assertEqual(data["images"], [])
        self.assertEqual(self.app.project.images, [])

    def test_thread_start_failure_and_completion_error_restore_controls(self):
        with patch("smartlabel.benchmark_dialog.Thread.start", side_effect=RuntimeError("fixture")):
            self.dialog.run(lambda: None, lambda _: None)
        self.assertFalse(self.app.evaluation_running)
        self.assertFalse(self.dialog.busy)
        self.assertEqual(self.dialog.controls[0].cget("state"), "normal")
        self.error.assert_called_once(); self.error.reset_mock()
        def failed(_): raise ValueError("fixture callback")
        self.dialog.run(lambda: True, failed); self.dialog.thread.join(3); self.drain()
        self.assertFalse(self.app.evaluation_running)
        self.error.assert_called_once()
