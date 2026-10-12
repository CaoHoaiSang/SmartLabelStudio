"""Launch the pinned ORI fork in a child process, never in the desktop process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from queue import Queue, Empty
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
ORI_MODEL = "deltax-yolo11n-ori"
ORI_MODEL_PRESETS = {
    **{f"deltax-yolo11{scale}-ori": ("yolo11", scale, f"yolo11{scale}.pt") for scale in "nslmx"},
    "deltax-yolov8n-ori": ("yolov8", "n", "yolov8n.pt"),
}


def inspect_ori_model(model: str | Path) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [sys.executable, "-u", "-m", "smartlabel.ori_worker", "inspect", str(model)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, creationflags=flags, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("ORI_MODEL_INFO=") and result.returncode == 0:
            return json.loads(line.split("=", 1)[1])
    raise ValueError("Không đọc được model ORI DeltaX: " + (result.stderr or result.stdout)[-2000:])


def inspect_checkpoint(model: str | Path) -> dict:
    # A sidecar selects our fork explicitly; old Orienty checkpoints can still
    # fall back to the isolated inspector when the standard loader rejects them.
    if Path(model).with_suffix(".ori.json").is_file():
        return inspect_ori_model(model)
    from ultralytics import YOLO
    try:
        network = YOLO(str(model))
    except (AttributeError, ModuleNotFoundError):
        return inspect_ori_model(model)
    return {"task": network.task, "names": {str(k): str(v) for k, v in network.names.items()}}


def evaluate_ori_model(model_path, **config):
    payload = {"model_path": str(model_path), **{key: str(value) if isinstance(value, Path) else value for key, value in config.items()}}
    result = subprocess.run([sys.executable, "-u", "-m", "smartlabel.ori_worker", "evaluate", json.dumps(payload, ensure_ascii=False)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("ORI_EVALUATION=") and result.returncode == 0:
            return json.loads(line.split("=", 1)[1])
    raise RuntimeError("Đánh giá ORI thất bại: " + (result.stderr or result.stdout)[-4000:])


class OriAutoLabeler:
    """One isolated model process per batch, reused for every image."""

    def __init__(self, model_path, device):
        self.lines = Queue()
        self.process = subprocess.Popen([sys.executable, "-u", "-m", "smartlabel.ori_worker", "serve", str(model_path)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.device = device
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.names = {int(k): v for k, v in self._response("ORI_MODEL_INFO=", 120)["names"].items()}
        except Exception:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line.rstrip())
        self.lines.put(None)

    def _response(self, marker, timeout):
        import time
        deadline = time.monotonic() + timeout
        history = []
        while True:
            try:
                line = self.lines.get(timeout=max(.01, deadline - time.monotonic()))
            except Empty:
                self.close()
                raise RuntimeError("ORI inference hết thời gian chờ.") from None
            if line is None:
                raise RuntimeError("ORI process đã dừng: " + "\n".join(history[-12:]))
            if line.startswith("ORI_ERROR="):
                raise RuntimeError(json.loads(line.split("=", 1)[1]))
            if line.startswith(marker):
                return json.loads(line.split("=", 1)[1])
            history.append(line)

    def predict(self, image_path, confidence, image_size):
        from .models import Annotation
        self.process.stdin.write(json.dumps({"source": str(image_path), "conf": confidence, "imgsz": image_size, "device": self.device}) + "\n")
        self.process.stdin.flush()
        return [Annotation.from_dict(value) for value in self._response("ORI_PREDICTION=", 180)]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()
