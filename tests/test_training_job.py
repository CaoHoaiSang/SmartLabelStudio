"""Training transport checks with a tiny subprocess, no YOLO training or dataset."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import json
import subprocess
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


if __name__ == "__main__":
    unittest.main()
