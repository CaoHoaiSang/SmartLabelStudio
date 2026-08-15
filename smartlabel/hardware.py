from __future__ import annotations

from dataclasses import dataclass, asdict
import importlib.util
import platform


@dataclass
class HardwareProfile:
    python: str
    os: str
    torch_available: bool
    cuda_available: bool
    cuda_device: str
    onnxruntime_available: bool
    onnx_providers: list[str]
    openvino_available: bool
    openvino_devices: list[str]

    def to_dict(self):
        return asdict(self)


def inspect_hardware() -> HardwareProfile:
    torch_available = importlib.util.find_spec("torch") is not None
    cuda_available = False
    cuda_device = ""
    if torch_available:
        try:
            import torch
            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                cuda_device = torch.cuda.get_device_name(0)
        except Exception:
            pass
    ort_available = importlib.util.find_spec("onnxruntime") is not None
    providers: list[str] = []
    if ort_available:
        try:
            import onnxruntime as ort
            providers = list(ort.get_available_providers())
        except Exception:
            pass
    ov_available = importlib.util.find_spec("openvino") is not None
    ov_devices: list[str] = []
    if ov_available:
        try:
            from openvino import Core
            ov_devices = list(Core().available_devices)
        except Exception:
            pass
    return HardwareProfile(
        python=platform.python_version(),
        os=platform.platform(),
        torch_available=torch_available,
        cuda_available=cuda_available,
        cuda_device=cuda_device,
        onnxruntime_available=ort_available,
        onnx_providers=providers,
        openvino_available=ov_available,
        openvino_devices=ov_devices,
    )


def best_ultralytics_device(preference: str = "auto") -> str:
    profile = inspect_hardware()
    if preference == "cuda":
        if not profile.cuda_available:
            raise RuntimeError("CUDA chưa sẵn sàng. Hãy cài PyTorch CUDA và NVIDIA Driver phù hợp.")
        return "0"
    if preference == "cpu":
        return "cpu"
    return "0" if profile.cuda_available else "cpu"

