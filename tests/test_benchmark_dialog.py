"""Real Tk widgets with temporary projects; no interaction with the user's Studio."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import time
import tkinter as tk
import unittest
import customtkinter as ctk
from smartlabel import benchmark_dialog as ui
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore


class BenchmarkDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app = ctk.CTk(); self.app.withdraw(); self.addCleanup(self.app.destroy)
        self.app.store = ProjectStore(Path(self.temp.name) / 'workspace')
        self.app.project = self.app.store.create_project('Fixture', task='classify')
        apply_hydroponic_slot_template(self.app.project)
        self.app.evaluation_running = False
        self.app._can_change_project = lambda: not self.app.evaluation_running
        self.dialog = ui.ExternalBenchmarkDialog(self.app); self.dialog.withdraw()
        self.addCleanup(self.dialog.destroy)

    def drain(self):
        deadline = time.monotonic() + 4
        while self.dialog.busy and time.monotonic() < deadline:
            self.app.update(); time.sleep(.01)
        self.assertFalse(self.dialog.busy)

    def test_background_ownership_cancel_close_and_controls(self):
        entered, release = Event(), Event(); results = []
        def work():
            entered.set(); release.wait(3); return 'fixture'
        self.dialog.run(work, results.append)
        self.assertTrue(entered.wait(2)); self.assertTrue(self.app.evaluation_running)
        self.assertEqual(self.dialog.controls[0].cget('state'), 'disabled')
        with patch.object(ui.messagebox, 'showinfo') as info:
            self.dialog.close(); info.assert_called_once()
        self.dialog.cancel.set(); self.assertTrue(self.dialog.cancel.is_set())
        release.set(); self.dialog.thread.join(3)
        self.assertTrue(self.app.evaluation_running)  # Still owned until callback.
        self.drain()
        self.assertEqual(results, ['fixture']); self.assertFalse(self.app.evaluation_running)

    def test_project_change_never_applies_completion_to_new_project(self):
        release = Event(); results = []
        self.dialog.run(lambda: release.wait(2), results.append)
        self.app.project = self.app.store.create_project('Other')
        release.set(); self.dialog.thread.join(3); self.drain()
        self.assertEqual(results, [])

    def test_error_restores_ui_and_never_approves(self):
        with patch.object(ui.messagebox, 'showerror') as error:
            self.dialog.run(lambda: (_ for _ in ()).throw(ValueError('bad checksum')), lambda _: self.fail('no result'))
            self.dialog.thread.join(3); self.drain(); error.assert_called_once()
        self.assertIsNone(self.dialog.report_id)
        self.assertEqual(self.dialog.controls[0].cget('state'), 'normal')
