from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Callable
import json
import os
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
    fleet_dataset: dict | None = None


class TrainingJob:
    def __init__(self, config: TrainingConfig, on_line: Callable[[str], None], on_done: Callable[[int], None]):
        self.config = config
        self.on_line = on_line
        self.on_done = on_done
        self.process: subprocess.Popen | None = None
        self.thread: Thread | None = None
        self.cancel_event = Event()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Job train đang chạy")
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            if self.cancel_event.is_set():
                self.on_done(130)
                return
            self.on_line("KHỞI ĐỘNG TRAIN · Đang kiểm tra thiết bị CPU/CUDA…")
            from .fleet_boundaries import require_legacy_training_data
            if self.config.fleet_dataset is not None:
                from .fleet_training import validate_managed_config
                validate_managed_config(dict(self.config.__dict__))
            else:
                from .fleet_boundaries import require_legacy_model
                require_legacy_training_data(self.config.data)
                require_legacy_model(self.config.model, context=self.config.project_dir)
            device = best_ultralytics_device(self.config.device)
            if self.cancel_event.is_set():
                self.on_line("ĐÃ DỪNG · Chưa mở tiến trình huấn luyện.")
                self.on_done(130)
                return
            self.on_line(f"Thiết bị train: {device} · Đang mở tiến trình huấn luyện…")
            payload = dict(self.config.__dict__)
            payload["device"] = device
            command = [sys.executable, "-u", "-m", "smartlabel.train_worker", json.dumps(payload, ensure_ascii=False)]
            self.process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            if self.cancel_event.is_set():
                self.stop()  # Covers cancellation while Popen was creating the child.
            self.on_line(f"TIẾN TRÌNH TRAIN ĐÃ MỞ · PID {self.process.pid} · Chờ nạp model/dataset.")
            assert self.process.stdout is not None
            with self.process.stdout as output:
                for line in output:
                    self.on_line(line.rstrip())
            code = self.process.wait()
            if self.config.fleet_dataset is not None:
                from .fleet_dataset import FleetDatasetClient
                context = self.config.fleet_dataset
                result = FleetDatasetClient.for_training(context).finish_training(context, code)
                if code == 0 and result['state'] != 'complete':
                    raise RuntimeError('Receiver chưa xác nhận lineage; run chưa được dùng tạo gói.')
                if result['state'] == 'complete':
                    self.on_line('ĐÃ GHI LINEAGE · ' + result['runId'])
        except Exception as exc:
            self.on_line(f"LỖI: {exc}")
            code = 1
        self.on_done(code)

    def stop(self) -> None:
        self.cancel_event.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass  # Process completed between poll and terminate.
