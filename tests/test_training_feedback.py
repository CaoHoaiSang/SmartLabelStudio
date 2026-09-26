"""Exercise the real Tk log after project reset; never use the user workspace."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from threading import Event, get_ident
from time import monotonic, sleep
import json
import tkinter as tk
import unittest

from smartlabel import app as app_module
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore


class TrainingFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.update_idletasks()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display required: {exc}")
        cls.temp = TemporaryDirectory()
        cls.workspace = Path(cls.temp.name) / "workspace"
        cls.store = ProjectStore(cls.workspace)
        cls.hydro = cls.store.create_project("Hydro log fixture", task="classify")
        apply_hydroponic_slot_template(cls.hydro)
        cls.store.save(cls.hydro)
        cls.generic = cls.store.create_project("Detection log fixture", classes=["plant"])
        cls.patches = [patch.object(app_module, "WORKSPACE", cls.workspace),
                       # These are UI/ownership tests, not real checkpoint loading.
                       # Never let a base .pt already on the workstation add an
                       # unbounded library/model load to a timed cancellation test.
                       patch("smartlabel.training_preparation.inspect_model", side_effect=lambda model, *args, **kwargs: model),
                       patch.object(app_module.SmartLabelApp, "_refresh_hardware"),
                       patch.object(app_module.messagebox, "showerror"),
                       patch.object(app_module.messagebox, "showwarning"),
                       patch.object(app_module.messagebox, "showinfo")]
        for item in cls.patches:
            item.start()
        cls.app = app_module.SmartLabelApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        pending = cls.app.training_preparation_job
        if pending and pending.thread and pending.thread.is_alive():
            pending.stop()
            pending.thread.join(10)
        cls.app.destroy()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.app.training_job = None
        self.app.running_training_task = ""
        self.app.batch_training_active = False
        self.app.pending_training_note = ""
        self.app._change_project_context(self.hydro)
        app_module.messagebox.showerror.reset_mock()

    def wait_preparation(self):
        deadline = monotonic() + 10
        while self.app.training_preparation_running and monotonic() < deadline:
            self.app._drain_events()
            self.app.update()
            sleep(.01)
        self.assertFalse(self.app.training_preparation_running, "Preparation did not complete")

    def log(self, widget=None):
        return (widget or self.app.train_log).get("1.0", "end-1c")

    def test_worker_output_and_completion_visible_after_project_open(self):
        self.assertEqual(self.app.train_log._textbox.cget("state"), "disabled")
        self.app.running_training_task = "classify"
        self.app.event_queue.put(("train_line", "Epoch 1/50 · đang huấn luyện"))
        self.app.event_queue.put(("train_done", 1))
        self.app._drain_events()
        self.assertIn("Epoch 1/50", self.log())
        self.assertIn("TRAIN DỪNG/LỖI", self.log())
        self.assertEqual(self.app.train_log._textbox.cget("state"), "disabled")
        self.app.train_log.insert("end", "user edit must not change log")
        self.assertNotIn("user edit", self.log())

    def test_export_and_auto_label_logs_survive_repeated_project_switches(self):
        for project in (self.generic, self.hydro, self.generic, self.hydro):
            self.app._change_project_context(project)
            self.assertEqual(self.log(), "")
            self.app.event_queue.put(("rknn_line", "Đang xuất model"))
            self.app._drain_events()
            self.app._stop_auto_label()
            self.assertIn("Đang xuất model", self.log())
            self.assertIn("Đang yêu cầu dừng", self.log(self.app.auto_log))

    def test_log_clear_and_append_keep_only_new_run(self):
        self.app._append_log(self.app.train_log, "old run")
        self.app._replace_text(self.app.train_log, "")
        self.app._append_log(self.app.train_log, "new run")
        self.assertEqual(self.log(), "new run\n")

    def test_train_request_and_dataset_error_are_visible_before_worker(self):
        self.app.train_model_entry.delete(0, "end")
        self.app.train_model_entry.insert(0, "fixture-cls.pt")
        observed = []
        def reject_export(*args, **kwargs):
            observed.append(get_ident())
            raise ValueError("fixture: chưa đủ hai lớp trong train")
        with patch.object(self.app.datasets, "export_classification", side_effect=reject_export), \
                patch.object(app_module, "TrainingJob") as job:
            self.app._start_training_for_current_mode()
            self.assertIn("ĐÃ NHẬN YÊU CẦU TRAIN", self.log())
            self.wait_preparation()
        self.assertTrue(observed)
        self.assertNotEqual(observed[0], get_ident())
        self.assertIn("chưa đủ hai lớp", self.log())
        self.assertIn("CHƯA BẮT ĐẦU TRAIN", self.log())
        job.assert_not_called()

    def test_localization_export_failure_is_logged(self):
        self.app._change_project_context(self.generic)
        with patch.object(self.app.datasets, "export_yolo", side_effect=ValueError("fixture: thiếu nhãn")), \
                patch.object(app_module, "TrainingJob") as job:
            self.app._start_training_for_current_mode()
            self.wait_preparation()
        self.assertIn("ĐÃ NHẬN YÊU CẦU TRAIN", self.log())
        self.assertIn("thiếu nhãn", self.log())
        job.assert_not_called()

    def test_cancelled_confirmation_is_not_reported_as_running(self):
        with patch.object(self.app, "_confirm_split_strategy", return_value=False), \
                patch.object(app_module, "TrainingJob") as job:
            self.app._start_training_for_current_mode()
        self.assertIn("ĐÃ HỦY", self.log())
        job.assert_not_called()

    def test_busy_completion_keeps_existing_log_and_blocks_duplicate_start(self):
        self.app._replace_text(self.app.train_log, "existing epoch output")
        self.app.running_training_task = "classify"
        with patch.object(self.app, "_start_batch_classification_training") as start:
            self.app._start_training_for_current_mode()
        start.assert_not_called()
        self.assertIn("existing epoch output", self.log())

    def test_unexpected_preflight_exception_is_logged(self):
        with patch.object(self.app, "_start_batch_classification_training", side_effect=RuntimeError("fixture: model hỏng")):
            self.app._start_training_for_current_mode()
        self.assertIn("model hỏng", self.log())
        self.assertIn("CHƯA BẮT ĐẦU TRAIN", self.log())

    def test_split_conflict_is_reported_once_before_exports_and_can_open_repair(self):
        for open_repair in (False, True):
            with self.subTest(open_repair=open_repair), \
                    patch.object(self.app.datasets, "split_health", return_value={"conflicts": {"fixture-group": ["variant"]}}), \
                    patch.object(app_module.messagebox, "askyesno", return_value=open_repair) as question, \
                    patch.object(self.app, "_open_split_manager") as repair, \
                    patch.object(self.app.datasets, "export_classification") as export, \
                    patch.object(app_module, "TrainingJob") as job:
                self.app._start_training_for_current_mode()
                self.wait_preparation()
            export.assert_not_called()
            job.assert_not_called()
            self.assertEqual(question.call_count, 1)
            self.assertIn("fixture-group", self.log())
            self.assertIn("Không cần xóa ảnh", self.log())
            if open_repair:
                repair.assert_called_once_with(problems_only=True)
            else:
                repair.assert_not_called()

    def test_busy_state_blocks_rebalance_and_lock(self):
        with patch.object(self.app, "_can_change_project", return_value=False), \
                patch.object(self.app.datasets, "preview_rebalance") as preview, \
                patch.object(self.app.datasets, "ensure_split_assignment") as lock:
            self.app._rebalance_split_assignment()
            self.app._lock_split_assignment()
        preview.assert_not_called()
        lock.assert_not_called()

    def test_cancel_rebalance_preview_does_not_apply(self):
        with patch.object(app_module.messagebox, "askyesno", return_value=False) as question, \
                patch.object(self.app.datasets, "apply_rebalance") as apply:
            self.app._rebalance_split_assignment()
        self.assertIn("mục tiêu", question.call_args.args[1])
        apply.assert_not_called()

    def test_worker_launch_failure_releases_ownership_for_both_modes(self):
        for project, method in ((self.hydro, "export_classification"), (self.generic, "export_yolo")):
            with self.subTest(project=project.name):
                self.app._change_project_context(project)
                self.app.training_job = None
                self.app.train_model_entry.delete(0, "end")
                self.app.train_model_entry.insert(0, "fixture-cls.pt" if project is self.hydro else "fixture.pt")
                export_dir = self.workspace / project.id / "export"
                export_dir.mkdir(parents=True, exist_ok=True)
                (export_dir / "data.yaml").write_text("# fixture", encoding="utf-8")
                (export_dir / "export.json").write_text(json.dumps({
                    "task": "classify" if project is self.hydro else "detect",
                    "counts": {"yes": 2, "no": 2}, "exported_crops": 4, "exported_annotations": 4,
                }), encoding="utf-8")
                with patch.object(self.app.datasets, method, return_value=export_dir), \
                        patch.object(app_module, "TrainingJob") as job:
                    job.return_value.start.side_effect = RuntimeError("fixture: cannot create thread")
                    self.app._start_training_for_current_mode()
                    self.assertEqual(self.app.train_start_button.cget("state"), "disabled")
                    self.wait_preparation()
                    self.app._drain_events()
                self.assertIn("cannot create thread", self.log())
                self.assertIn("ĐÃ NHẬN YÊU CẦU TRAIN", self.log())
                self.assertFalse(self.app.running_training_task)
                self.assertFalse(self.app.batch_training_active)
                self.assertEqual(self.app.train_start_button.cget("state"), "normal")

    def test_ui_heartbeat_cancel_and_ownership_while_export_is_busy(self):
        entered, release, heartbeat = Event(), Event(), Event()
        def slow_export(*args, **kwargs):
            entered.set()
            release.wait(8)
            kwargs["progress"].check()
            raise AssertionError("Cancelled preparation must not finish export")
        with patch.object(self.app.datasets, "export_classification", side_effect=slow_export), \
                patch.object(app_module, "TrainingJob") as training:
            self.app._start_training_for_current_mode()
            try:
                self.assertTrue(entered.wait(3))
                self.app.after(0, heartbeat.set)
                self.app.update()
                self.assertTrue(heartbeat.is_set(), "Tk cannot process events during export")
                self.assertTrue(self.app._project_job_busy())
                self.assertFalse(self.app._can_change_project())
                current_job = self.app.training_preparation_job
                self.app._start_training_for_current_mode()
                self.assertIs(self.app.training_preparation_job, current_job)
                self.app._stop_training()
                self.assertTrue(self.app._project_job_busy(), "Cancel must retain ownership until done")
            finally:
                release.set()
                self.wait_preparation()
            training.assert_not_called()
        self.assertIn("ĐÃ DỪNG CHUẨN BỊ", self.log())
        self.assertFalse(self.app._project_job_busy())
        self.assertEqual(self.app.train_start_button.cget("state"), "normal")

    def test_preparation_thread_start_failure_releases_ownership(self):
        with patch.object(app_module.TrainingPreparationJob, "start", side_effect=RuntimeError("no thread")), \
                patch.object(app_module, "TrainingJob") as training:
            self.app._start_training_for_current_mode()
        self.assertIn("no thread", self.log())
        self.assertFalse(self.app._project_job_busy())
        self.assertEqual(self.app.train_start_button.cget("state"), "normal")
        training.assert_not_called()

    def test_cancel_after_worker_done_but_before_handoff_does_not_start_train(self):
        with patch.object(self.app.datasets, "export_classification", side_effect=ValueError("fixture error")), \
                patch.object(app_module, "TrainingJob") as training:
            self.app._start_training_for_current_mode()
            job = self.app.training_preparation_job
            try:
                job.thread.join(5)
                self.assertFalse(job.thread.is_alive())
                self.assertTrue(self.app._project_job_busy())
            finally:
                self.app._stop_training()
                self.wait_preparation()
        training.assert_not_called()
        self.assertIn("ĐÃ DỪNG CHUẨN BỊ", self.log())
        app_module.messagebox.showerror.assert_not_called()

    def test_close_requests_cancel_but_keeps_window_until_worker_finishes(self):
        entered, release = Event(), Event()
        def slow_export(*args, **kwargs):
            entered.set()
            release.wait(8)
            kwargs["progress"].check()
        with patch.object(self.app.datasets, "export_classification", side_effect=slow_export), \
                patch.object(self.app, "destroy") as destroy:
            self.app._start_training_for_current_mode()
            try:
                self.assertTrue(entered.wait(3))
                self.app._on_close()
                self.assertTrue(self.app.training_preparation_job.cancel_event.is_set())
                self.assertTrue(self.app._project_job_busy())
                destroy.assert_not_called()
            finally:
                release.set()
                self.wait_preparation()

    def test_stale_completion_cannot_release_active_preparation(self):
        from types import SimpleNamespace
        current = SimpleNamespace(source_project=self.app.project)
        previous = SimpleNamespace(source_project=self.app.project)
        self.app.training_preparation_job = current
        self.app.training_preparation_running = True
        try:
            self.app._finish_training_preparation(previous, None, ValueError("stale"), False)
            self.assertIs(self.app.training_preparation_job, current)
            self.assertTrue(self.app.training_preparation_running)
            self.assertNotIn("stale", self.log())
        finally:
            self.app.training_preparation_job = None
            self.app.training_preparation_running = False


if __name__ == "__main__":
    unittest.main()
