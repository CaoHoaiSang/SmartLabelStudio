from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Callable
import json
import subprocess
import sys

from .hardware import best_ultralytics_device


@dataclass
class TrainingConfig:
    model: str
    data: str
    project_dir: str
    task: str = "detect"
    run_name: str = "candidate"
    epochs: int = 50
    image_size: int = 640
    batch: int = 8
    patience: int = 15
    device: str = "auto"
    validate: bool = True


class TrainingJob:
    def __init__(self, config: TrainingConfig, on_line: Callable[[str], None], on_done: Callable[[int], None]):
        self.config = config
        self.on_line = on_line
        self.on_done = on_done
        self.process: subprocess.Popen | None = None
        self.thread: Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Job train đang chạy")
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            device = best_ultralytics_device(self.config.device)
            payload = dict(self.config.__dict__)
            payload["device"] = device
            command = [sys.executable, "-m", "smartlabel.train_worker", json.dumps(payload, ensure_ascii=False)]
            self.process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.on_line(line.rstrip())
            code = self.process.wait()
        except Exception as exc:
            self.on_line(f"LỖI: {exc}")
            code = 1
        self.on_done(code)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
