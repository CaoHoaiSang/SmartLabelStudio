"""Training transport checks with a tiny subprocess, no YOLO training or dataset."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import json
import os
import subprocess
import sys
import unittest

from smartlabel.training import TrainingConfig, TrainingJob
from smartlabel import train_worker


class TrainingJobTests(unittest.TestCase):
    def config(self):
        return TrainingConfig(model="fixture.pt", data="fixture.yaml", project_dir="unused")

    def test_utf8_output_arrives_while_worker_is_still_running(self):
        real_popen = subprocess.Popen
        lines, done = [], []
        received = Event()
        script = (
            "import sys,time; from pathlib import Path; "
            "print('Epoch 1 · có cây, vàng lá'); "
            "print('stderr fixture', file=sys.stderr); "
            "deadline=time.monotonic()+8\n"
            "while not Path(sys.argv[1]).exists() and time.monotonic()<deadline: time.sleep(.02)\n"
        )
        def on_line(line):
            lines.append(line)
            if "Epoch 1" in line:
                received.set()
        with TemporaryDirectory() as directory:
            release = Path(directory) / "release"
            def launch_fixture(command, **kwargs):
                # Preserve Python runtime flags and stream options used in production.
                prefix = command[:command.index("-m")]
                return real_popen(prefix + ["-c", script, str(release)], **kwargs)
            job = TrainingJob(self.config(), on_line, done.append)
            with patch("smartlabel.training.best_ultralytics_device", return_value="cpu"), \
                    patch("smartlabel.training.subprocess.Popen", side_effect=launch_fixture):
                job.start()
                try:
                    self.assertTrue(received.wait(4), lines)
                    self.assertEqual(done, [], "Output must not wait for process exit")
                    self.assertIsNone(job.process.poll())
                finally:
                    release.touch()
                    job.thread.join(5)
                    if job.thread.is_alive():
                        job.stop()
                        job.thread.join(5)
            self.assertFalse(job.thread.is_alive())
        self.assertEqual(done, [0])
        self.assertIn("Epoch 1 · có cây, vàng lá", lines)
        self.assertIn("stderr fixture", lines)
        self.assertTrue(any("PID" in line for line in lines))
        self.assertTrue(lines[0].startswith("KHỞI ĐỘNG TRAIN"))

    def test_device_failure_has_startup_and_error_without_launch(self):
        lines, done = [], []
        with patch("smartlabel.training.best_ultralytics_device", side_effect=RuntimeError("CUDA unavailable")), \
                patch("smartlabel.training.subprocess.Popen") as launch:
            TrainingJob(self.config(), lines.append, done.append)._run()
        self.assertIn("KHỞI ĐỘNG TRAIN", lines[0])
        self.assertIn("CUDA unavailable", lines[-1])
        self.assertEqual(done, [1])
        launch.assert_not_called()

    def test_stop_before_start_or_during_device_check_never_launches(self):
        for before_start in (True, False):
            with self.subTest(before_start=before_start):
                done = []
                job = TrainingJob(self.config(), lambda line: None, done.append)
                if before_start:
                    job.stop()
                def check_device(device):
                    job.stop()
                    return "cpu"
                with patch("smartlabel.training.best_ultralytics_device", side_effect=check_device), \
                        patch("smartlabel.training.subprocess.Popen") as launch:
                    job._run()
                launch.assert_not_called()
                self.assertEqual(done, [130])

    def test_process_start_failure_reports_completion_once(self):
        lines, done = [], []
        with patch("smartlabel.training.best_ultralytics_device", return_value="cpu"), \
                patch("smartlabel.training.subprocess.Popen", side_effect=OSError("launch failed")):
            TrainingJob(self.config(), lines.append, done.append)._run()
        self.assertIn("launch failed", lines[-1])
        self.assertEqual(done, [1])

    def test_worker_announces_library_load_even_when_import_fails(self):
        import builtins
        original_import = builtins.__import__
        def reject_ultralytics(name, *args, **kwargs):
            if name == "ultralytics":
                raise ImportError("fixture: ultralytics unavailable")
            return original_import(name, *args, **kwargs)
        output = StringIO()
        with patch("sys.argv", ["train_worker", json.dumps({"model": "fixture.pt"})]), \
                patch("builtins.__import__", side_effect=reject_ultralytics), redirect_stdout(output):
            with self.assertRaisesRegex(ImportError, "ultralytics unavailable"):
                train_worker.main()
        self.assertIn("Đang nạp thư viện", output.getvalue())

    def test_worker_bootstraps_utf8_from_legacy_windows_parent(self):
        # An already open app still uses the old launcher without its UTF-8 env.
        # Replace YOLO inside this child: exercise main(), but never train a model.
        script = """
import runpy, sys, types, json
print('inherited_encoding=' + sys.stdout.encoding, flush=True)
class FakeYOLO:
    def __init__(self, model, task):
        assert model == 'fixture.pt' and task == 'classify'
    def train(self, **kwargs):
        assert kwargs['epochs'] == 1
        print('Fixture tiếng Việt · không train thật', flush=True)
        print('Thông báo stderr', file=sys.stderr, flush=True)
sys.modules['ultralytics'] = types.SimpleNamespace(YOLO=FakeYOLO)
sys.argv = ['train_worker', json.dumps({
    'model': 'fixture.pt', 'task': 'classify', 'device': 'cpu',
    'data': 'unused', 'project_dir': 'unused', 'run_name': 'fixture',
    'epochs': 1, 'image_size': 224, 'batch': 1, 'patience': 1,
})]
runpy.run_module('smartlabel.train_worker', run_name='__main__')
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        output = result.stdout.decode("utf-8")
        self.assertIn("inherited_encoding=cp1252", output)
        self.assertIn("Đang nạp thư viện", output)
        self.assertIn("Fixture tiếng Việt", output)
        self.assertIn("TRAINING_COMPLETE", output)
        self.assertIn("Thông báo stderr", result.stderr.decode("utf-8"))

    def test_worker_missing_arguments_reports_utf8_error_before_import(self):
        result = subprocess.run(
            [sys.executable, "-m", "smartlabel.train_worker"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
        )
        self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn("Thiếu cấu hình train", result.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
