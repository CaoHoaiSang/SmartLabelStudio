from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Callable
import json
import os
import shutil
import subprocess
import time
import uuid


CONVERTER_IMAGE = "deltax-rknn-converter:2.2.0-v3"


def diagnose_rknn_environment(timeout: int = 8) -> tuple[bool, str]:
    """Fast preflight used by the UI before asking where to save a model."""
    if not shutil.which("docker"):
        return False, "Không tìm thấy Docker Desktop trong PATH."
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.Architecture}}|{{.OSType}}|{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return False, "Docker Linux Engine không phản hồi trong thời gian cho phép."
    except Exception as exc:
        return False, f"Không kiểm tra được Docker: {exc}"
    architecture, os_type, version = (result.stdout.strip().split("|") + ["", "", ""])[:3]
    if result.returncode != 0 or not architecture or not os_type or not version:
        detail = (result.stderr or result.stdout).strip()
        return False, (
            "Docker Desktop đã cài nhưng Linux Engine chưa chạy. "
            "Hãy mở Docker Desktop và chờ trạng thái Engine running. "
            "Nếu gặp WSL 0x800705aa, hãy lưu công việc, đóng bớt ứng dụng và khởi động lại Windows."
            + (f"\n\nDocker: {detail}" if detail else "")
        )
    if architecture not in {"x86_64", "amd64"} or os_type != "linux":
        return False, f"Cần Docker Linux amd64; hiện tại nhận {architecture or '?'} / {os_type or '?'}."
    return True, f"Docker Linux Engine sẵn sàng · {architecture} · server {version}"


@dataclass
class RknnExportConfig:
    model: Path
    output: Path
    converter_dir: Path
    image_size: int = 640
    target: str = "rk3588"
    class_count: int = 1
    task: str = "detect"


def inspect_deltax_rknn(path: str | Path, *, image_size: int, class_count: int, task: str = "detect") -> dict:
    """Reject RKNN files that do not match a supported DeltaX runtime contract."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError("File RKNN không tồn tại hoặc quá nhỏ.")
    text = path.read_bytes().decode("latin1", errors="ignore")
    if "compiler version: 2.2.0" not in text:
        raise RuntimeError("RKNN không được tạo bằng compiler 2.2.0 tương thích Studio hiện tại.")
    if task == "classify":
        expected_shape = f"'shape': [1, {class_count}]"
        sidecar = path.with_suffix(".json")
        metadata_shape_ok = False
        if sidecar.is_file():
            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                metadata_shape_ok = (
                    metadata.get("task") == "classify"
                    and metadata.get("output_shapes") == [[1, class_count]]
                    and metadata.get("output_layout") == "deltax_classification_softmax_1_output"
                )
            except (OSError, ValueError, TypeError):
                metadata_shape_ok = False
        if expected_shape not in text and not metadata_shape_ok:
            raise RuntimeError(
                "RKNN Classification không đúng output [1, số lớp thuộc tính]: " + expected_shape
            )
        return {
            "path": str(path.resolve()),
            "size": path.stat().st_size,
            "compiler": "2.2.0",
            "target": "rk3588",
            "task": task,
            "layout": "deltax_classification_softmax_1_output",
            "outputs": 1,
            "input_size": image_size,
            "classes": class_count,
        }
    if task not in {"detect", "segment"}:
        raise RuntimeError(f"Task RKNN chưa được hỗ trợ: {task}")
    expected = []
    for stride in (8, 16, 32):
        side = image_size // stride
        expected.extend(
            (
                f"'shape': [1, 64, {side}, {side}]",
                f"'shape': [1, {class_count}, {side}, {side}]",
                f"'shape': [1, 1, {side}, {side}]",
            )
        )
        if task == "segment":
            expected.append(f"'shape': [1, 32, {side}, {side}]")
    if task == "segment":
        expected.append(f"'shape': [1, 32, {image_size // 4}, {image_size // 4}]")
    missing = [shape for shape in expected if shape not in text]
    if missing:
        output_count = 13 if task == "segment" else 9
        raise RuntimeError(f"RKNN không đúng layout {output_count} đầu ra {task} của DeltaX: " + ", ".join(missing[:3]))
    output_count = 13 if task == "segment" else 9
    layout = "deltax_yolorknn_segment_13_heads" if task == "segment" else "deltax_yolorknn_detect_9_heads"
    return {
        "path": str(path.resolve()),
        "size": path.stat().st_size,
        "compiler": "2.2.0",
        "target": "rk3588",
        "task": task,
        "layout": layout,
        "outputs": output_count,
    }


class RknnExportJob:
    def __init__(
        self,
        config: RknnExportConfig,
        on_line: Callable[[str], None],
        on_done: Callable[[int, Path | None, str], None],
    ) -> None:
        self.config = config
        self.on_line = on_line
        self.on_done = on_done
        self.process: subprocess.Popen | None = None
        self.thread: Thread | None = None
        self.container_name = f"deltax-rknn-{uuid.uuid4().hex[:10]}"
        self.cancel_event = Event()

    @staticmethod
    def _window_flags() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Đang có tác vụ export RKNN.")
        self.cancel_event.clear()
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def _raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise InterruptedError("Đã dừng xuất RKNN theo yêu cầu.")

    def _check(self, command: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        process = subprocess.Popen(
            command,
            cwd=str(self.config.converter_dir.parent.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=self._window_flags(),
        )
        self.process = process
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(command, 124, stdout, stderr or "Hết thời gian chờ.")
        finally:
            if self.process is process:
                self.process = None

    def _ensure_docker(self) -> None:
        self._raise_if_cancelled()
        if not shutil.which("docker"):
            raise RuntimeError("Không tìm thấy Docker Desktop. Hãy cài Docker Desktop trước khi export RKNN.")
        status = self._check(["docker", "info", "--format", "{{.Architecture}}"], timeout=20)
        ready = status.returncode == 0 and status.stdout.strip() in {"x86_64", "amd64"}
        if not ready and os.name == "nt":
            self.on_line("Docker chưa chạy · đang khởi động Docker Desktop…")
            self._check(["docker", "desktop", "start"], timeout=60)
            self._raise_if_cancelled()
            for _ in range(30):
                self._raise_if_cancelled()
                status = self._check(["docker", "info", "--format", "{{.Architecture}}"], timeout=10)
                ready = status.returncode == 0 and status.stdout.strip() in {"x86_64", "amd64"}
                if ready:
                    break
                if self.cancel_event.wait(2):
                    self._raise_if_cancelled()
        if not ready:
            raise RuntimeError("Docker Linux engine chưa sẵn sàng: " + (status.stderr or status.stdout).strip())
        if "x86_64" not in status.stdout and "amd64" not in status.stdout:
            raise RuntimeError(f"RKNN converter cần Docker x86_64, nhận được: {status.stdout.strip()}")

    def _ensure_image(self) -> None:
        self._raise_if_cancelled()
        found = self._check(["docker", "image", "inspect", CONVERTER_IMAGE], timeout=20)
        if found.returncode == 0:
            return
        self.on_line("Lần đầu sử dụng · đang dựng môi trường RKNN Toolkit 2.2.0…")
        self._stream(
            ["docker", "build", "-t", CONVERTER_IMAGE, str(self.config.converter_dir)],
            cwd=self.config.converter_dir.parent.parent,
        )

    def _stream(self, command: list[str], *, cwd: Path | None = None) -> int:
        self._raise_if_cancelled()
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd or self.config.converter_dir.parent.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=self._window_flags(),
        )
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if self.cancel_event.is_set():
                self.process.terminate()
                raise InterruptedError("Đã dừng xuất RKNN theo yêu cầu.")
            clean = line.rstrip()
            if clean:
                self.on_line(clean)
        return self.process.wait()

    def _run(self) -> None:
        output: Path | None = None
        error = ""
        code = 1
        try:
            self._raise_if_cancelled()
            self._ensure_docker()
            self._raise_if_cancelled()
            self._ensure_image()
            self._raise_if_cancelled()
            model = self.config.model.resolve()
            output = self.config.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            self.on_line(f"Nguồn PT : {model}")
            self.on_line(f"Đích RKNN: {output}")
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                self.container_name,
                "-v",
                f"{model.parent}:/work:ro",
                "-v",
                f"{output.parent}:/output",
                CONVERTER_IMAGE,
                "--model",
                f"/work/{model.name}",
                "--output",
                f"/output/{output.name}",
                "--name",
                self.config.target,
                "--imgsz",
                str(self.config.image_size),
                "--task",
                self.config.task,
            ]
            code = self._stream(command)
            if code != 0:
                raise RuntimeError(f"Docker converter dừng với mã {code}")
            report = inspect_deltax_rknn(
                output,
                image_size=self.config.image_size,
                class_count=self.config.class_count,
                task=self.config.task,
            )
            self.on_line(
                f"RKNN hợp lệ · compiler {report['compiler']} · {report['outputs']} outputs · "
                f"{report['size'] / 1024 / 1024:.2f} MB"
            )
            code = 0
        except Exception as exc:
            error = str(exc)
            self.on_line("EXPORT RKNN LỖI: " + error)
            code = 1
        self.on_done(code, output if code == 0 else None, error)

    def stop(self) -> None:
        self.cancel_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if shutil.which("docker"):
            def stop_container():
                subprocess.run(
                    ["docker", "stop", "-t", "1", self.container_name],
                    capture_output=True,
                    timeout=10,
                    creationflags=self._window_flags(),
                )
            Thread(target=stop_container, daemon=True).start()
