from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import gc
import tkinter as tk
import unittest

from smartlabel import app as app_module
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore


class FleetIntakeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        cls.temp = TemporaryDirectory()
        cls.store = ProjectStore(Path(cls.temp.name) / "workspace")
        cls.project = cls.store.create_project("Fleet destination", task="classify")
        apply_hydroponic_slot_template(cls.project); cls.store.save(cls.project)
        cls.other = cls.store.create_project("Other project")
        cls.patches = [patch.object(app_module, "WORKSPACE", cls.store.workspace),
                       patch.object(app_module.SmartLabelApp, "_refresh_hardware"),
                       patch.object(app_module.messagebox, "showerror"), patch.object(app_module.messagebox, "showinfo")]
        for item in cls.patches:
            item.start()
        cls.app = app_module.SmartLabelApp(); cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.app.tk.call("after", "info"):
            cls.app.tk.call("after", "cancel", timer)
        cls.app.destroy()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.app.import_in_progress = False
        self.app.fleet_intake_job = None
        self.app._change_project_context(self.project)
        gc.collect()

    def test_job_owns_exact_project_after_dialog_close_and_ui_remains_responsive(self):
        began, release = Event(), Event()
        captured = []
        def receive(root, project_id, code):
            captured.append((root, project_id, code)); began.set(); release.wait(5)
            return {"fileCount": 1}
        before = (self.store.project_dir(self.project) / "project.json").read_bytes()
        with patch.object(app_module.fleet_intake, "receive", side_effect=receive):
            self.app._open_fleet_intake(); view = self.app.fleet_intake_view
            view.code.insert(0, "FleetImportV1." + "a" * 43); view.start()
            try:
                self.assertTrue(began.wait(2)); self.assertEqual(view.code.get(), "")
                view.close()
                callbacks = []; self.app.after(0, lambda: callbacks.append(True)); self.app.update()
                self.assertTrue(callbacks); self.assertIsNone(self.app.grab_current())
                self.assertFalse(self.app._can_change_project())
                self.assertFalse(self.app._start_fleet_intake(self.other, "wrong"))
                with patch.object(self.app, "destroy") as destroy:
                    self.app._on_close(); destroy.assert_not_called()
                with patch.object(self.app, "_start_batch_classification_training") as train:
                    self.app._start_training_for_current_mode(); train.assert_not_called()
            finally:
                release.set(); self.app.fleet_intake_thread.join(3)
            self.app._drain_events()
        self.assertFalse(self.app.import_in_progress)
        self.assertEqual(captured[0][1], self.project.id)
        self.assertEqual((self.store.project_dir(self.project) / "project.json").read_bytes(), before)
        self.assertEqual(self.project.images, [])

    def test_stale_completion_cannot_unlock_a_new_job_or_other_project(self):
        current = object(); self.app.fleet_intake_job = current; self.app.import_in_progress = True
        self.app.event_queue.put(("fleet_intake_done", (object(), self.other, None, "stale")))
        self.app._drain_events()
        self.assertTrue(self.app.import_in_progress); self.assertIs(self.app.fleet_intake_job, current)

    def test_thread_start_failure_and_receiver_error_release_job_for_retry(self):
        with patch.object(app_module.Thread, "start", side_effect=RuntimeError("fixture")):
            self.assertFalse(self.app._start_fleet_intake(self.project, "unused"))
        self.assertFalse(self.app.import_in_progress)
        with patch.object(app_module.fleet_intake, "receive", side_effect=RuntimeError("never expose secret")):
            self.assertTrue(self.app._start_fleet_intake(self.project, "unused"))
            self.app.fleet_intake_thread.join(3); self.app._drain_events()
        self.assertFalse(self.app.import_in_progress)
        self.assertNotIn("never expose secret", str(app_module.messagebox.showinfo.call_args))

    def test_stale_dialog_cannot_import_after_user_switches_project(self):
        self.app._open_fleet_intake(); view = self.app.fleet_intake_view
        self.app._change_project_context(self.other)
        with patch.object(app_module.fleet_intake, "receive") as receive:
            view.start(); receive.assert_not_called()
        view.close()
        self.assertFalse(self.app.import_in_progress)
