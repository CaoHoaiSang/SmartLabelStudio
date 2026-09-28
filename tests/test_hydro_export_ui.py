"""Real Tk + background job integration in isolated temporary projects."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
from unittest.mock import patch
import gc
import tkinter as tk
import unittest

from smartlabel import app as app_module, hydro_export
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore


class HydroExportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk()
            root.withdraw()
            root.update_idletasks()
            root.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display required: {exc}")
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.store = ProjectStore(cls.root / "workspace")
        cls.project = cls.store.create_project("Hydro UI fixture", task="classify")
        apply_hydroponic_slot_template(cls.project)
        for key in ("plant_presence", "yellow_leaf", "wilt"):
            path = cls.root / f"{key}.pt"
            path.write_bytes(b"fixture only")
            cls.project.attribute_models[key] = str(path)
        cls.store.save(cls.project)
        cls.other = cls.store.create_project("Other project", classes=["plant"])
        cls.patches = [patch.object(app_module, "WORKSPACE", cls.store.workspace),
                       patch.object(app_module.SmartLabelApp, "_refresh_hardware"),
                       patch.object(app_module.messagebox, "showerror"),
                       patch.object(app_module.messagebox, "showinfo")]
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
        self.app.hydro_export_running = False
        self.app.hydro_export_job = None
        self.app._change_project_context(self.project)
        self.app.project.metadata.pop("lastHydroBundle", None)
        gc.collect()  # Collect old Tk variables on the main thread before a worker starts.
        self.before = deepcopy(self.app.project.metadata)
        app_module.messagebox.showerror.reset_mock()
        app_module.messagebox.showinfo.reset_mock()
        self.config = {"thresholds": {}, "datasetVersion": "fixture-v1", "sourceCommit": "fixture",
                       "runtimeTarget": "windows_onnxruntime_cpu", "deploymentMode": "shadow",
                       "cameraProfileIds": ["camera-1"], "geometryProfileIds": ["geometry-1"]}
        config_patch = patch.object(app_module, "ask_hydro_bundle_config", return_value=self.config)
        directory_patch = patch.object(app_module.filedialog, "askdirectory", return_value=str(self.root))
        self.config_dialog = config_patch.start()
        self.directory_dialog = directory_patch.start()
        self.addCleanup(config_patch.stop)
        self.addCleanup(directory_patch.stop)

    def result(self, output):
        return {"bundle": output, "archive": output.with_suffix(".zip"),
                "validationStatus": "pilot_unvalidated", "onnxModels": {}}

    def log(self):
        return self.app.train_log.get("1.0", "end-1c")

    def test_background_keeps_ui_responsive_and_owns_project_until_completion(self):
        entered, release = Event(), Event()
        main_thread = get_ident()
        def build(project, store, output, config, progress, cancel):
            self.assertNotEqual(get_ident(), main_thread)
            progress("[2/3] ONNX fixture")
            entered.set()
            if not release.wait(5):
                raise RuntimeError("fixture release timeout")
            return self.result(output)
        with patch.object(hydro_export, "build_hydro_package", side_effect=build):
            self.app._export_hydro_bundle()
            job = self.app.hydro_export_job
            try:
                self.assertTrue(entered.wait(2))
                callbacks = []
                self.app.after(0, lambda: callbacks.append(True))
                self.app.update()
                self.assertTrue(callbacks)
                self.assertIn("ONNX fixture", self.log())
                self.assertFalse(self.app._can_change_project())
                with patch.object(self.app, "_start_batch_classification_training") as train:
                    self.app._start_training_for_current_mode()
                train.assert_not_called()
                self.app._export_hydro_bundle()
                self.assertIs(self.app.hydro_export_job, job)
            finally:
                release.set()
                job.thread.join(3)
            self.assertTrue(self.app.hydro_export_running)
            self.app._drain_events()
        self.assertFalse(self.app.hydro_export_running)
        self.assertEqual(self.app.project.metadata["lastHydroBundle"], str(job.output))
        self.assertIn("ZIP để tải lên Hydro", self.log())
        self.assertEqual(self.app.hydro_bundle_export_button.cget("state"), "normal")
        self.assertEqual(self.app.deploy_stop_button.cget("state"), "disabled")
        self.assertEqual(self.config_dialog.call_count, 1)
        self.assertEqual(self.directory_dialog.call_count, 1)

    def test_cancel_and_close_wait_for_active_step_without_saving_metadata(self):
        entered, release = Event(), Event()
        def build(project, store, output, config, progress, cancel):
            entered.set()
            release.wait(5)
            if cancel.is_set():
                raise hydro_export.HydroExportCancelled()
            return self.result(output)
        with patch.object(hydro_export, "build_hydro_package", side_effect=build):
            self.app._export_hydro_bundle()
            job = self.app.hydro_export_job
            try:
                self.assertTrue(entered.wait(2))
                with patch.object(self.app, "destroy") as destroy:
                    self.app._on_close()
                    destroy.assert_not_called()
                self.assertTrue(job.cancel_event.is_set())
                self.assertTrue(self.app.hydro_export_running)
            finally:
                release.set()
                job.thread.join(3)
            self.app._drain_events()
        self.assertEqual(self.app.project.metadata, self.before)
        self.assertIn("ĐÃ DỪNG TẠO GÓI", self.log())
        self.assertFalse(self.app.hydro_export_running)

    def test_worker_error_keeps_old_metadata_and_allows_retry(self):
        with patch.object(hydro_export, "build_hydro_package", side_effect=ValueError("fixture invalid model")):
            self.app._export_hydro_bundle()
            self.app.hydro_export_job.thread.join(3)
            self.app._drain_events()
        self.assertEqual(self.app.project.metadata, self.before)
        self.assertIn("fixture invalid model", self.log())
        self.assertFalse(self.app.hydro_export_running)

    def test_cancel_config_or_directory_does_not_create_job(self):
        with patch.object(app_module, "HydroBundleJob") as job:
            self.config_dialog.return_value = None
            self.app._export_hydro_bundle()
            self.config_dialog.return_value = self.config
            self.directory_dialog.return_value = ""
            self.app._export_hydro_bundle()
        job.assert_not_called()
        self.assertEqual(self.app.project.metadata, self.before)

    def test_missing_models_is_explained_before_config_dialog(self):
        paths = self.app.project.attribute_models
        self.app.project.attribute_models = {}
        try:
            self.app._export_hydro_bundle()
        finally:
            self.app.project.attribute_models = paths
        self.config_dialog.assert_not_called()
        self.assertIn("CHƯA TẠO GÓI HYDRO", self.log())

    def test_thread_start_failure_releases_busy_state(self):
        with patch.object(app_module.HydroBundleJob, "start", side_effect=RuntimeError("fixture thread failed")):
            self.app._export_hydro_bundle()
        self.assertFalse(self.app.hydro_export_running)
        self.assertIn("fixture thread failed", self.log())
        self.assertEqual(self.app.hydro_bundle_export_button.cget("state"), "normal")

    def test_stale_completion_does_not_release_new_job(self):
        current = object()
        self.app.hydro_export_job = current
        self.app.hydro_export_running = True
        self.app._finish_hydro_export(object(), None, "old error", False)
        self.assertIs(self.app.hydro_export_job, current)
        self.assertTrue(self.app.hydro_export_running)
        self.assertEqual(self.app.project.metadata, self.before)

    def test_metadata_save_error_keeps_created_package_and_reports_path(self):
        def build(project, store, output, config, progress, cancel):
            output.with_suffix(".zip").write_bytes(b"fixture package")
            return self.result(output)
        with patch.object(hydro_export, "build_hydro_package", side_effect=build):
            self.app._export_hydro_bundle()
            job = self.app.hydro_export_job
            job.thread.join(3)
            with patch.object(self.app.store, "save", side_effect=OSError("fixture disk full")):
                self.app._drain_events()
        self.assertEqual(job.output.with_suffix(".zip").read_bytes(), b"fixture package")
        self.assertEqual(self.app.project.metadata, self.before)
        self.assertIn("Gói đã lưu nhưng", self.log())
