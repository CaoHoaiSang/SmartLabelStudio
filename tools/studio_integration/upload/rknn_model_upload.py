"""Validated model-pair storage for Studio; no NPU or robot dependencies."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

MAX_METADATA_BYTES = 65536
_STORE_LOCK = threading.RLock()


def validate_metadata(metadata_json, model_bytes):
    if metadata_json is None:
        return None
    if not isinstance(metadata_json, str) or len(metadata_json.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError("Model JSON must be text smaller than 64 KiB")
    meta = json.loads(metadata_json)
    if not isinstance(meta, dict):
        raise ValueError("Model JSON must be an object")
    names = meta.get("names")
    if not isinstance(names, dict) or not 1 <= len(names) <= 1000:
        raise ValueError("ORI JSON must contain indexed class names")
    labels = [names.get(str(i)) for i in range(len(names))]
    if (any(not isinstance(n, str) or not n.strip() or n != n.strip()
            or any(c in n for c in ",\r\n\x00") for n in labels)
            or len(set(labels)) != len(labels)):
        raise ValueError("ORI class names must be unique, consecutive and usable in Studio")
    encoding = meta.get("heading_encoding", "normalized_degrees_v1")
    components = {"normalized_degrees_v1": 1, "cos_sin_vector_v2": 2}.get(encoding)
    if components is None:
        raise ValueError("Unsupported ORI heading encoding")
    expected_shapes = [[1, 64 + len(labels), side, side] for side in (80, 40, 20)] + [[1, 1, 8400], [1, components, 8400]]
    required = {
        "schema": 1, "format": "rknn", "task": "ori", "target": "rk3588",
        "compiler": "rknn-toolkit2==2.2.0", "imgsz": [640, 640],
        "output_layout": f"deltax_orienty_5_heads_v{components}", "output_shapes": expected_shapes,
        "heading": "image_x_clockwise_degrees", "heading_scale": 180,
        "obb_angle": "(sigmoid - 0.25) * pi",
        "heading_refinement": "align_obb_axes_to_heading_vector" if components == 2 else "snap_to_obb_axis_4_directions",
        "normalization": {"mean": [0, 0, 0], "std": [255, 255, 255], "rgb2bgr": False},
        "input_contract": {"runtime_layout": "NHWC", "dtype": "uint8", "color": "RGB", "resize": "letterbox"},
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
    }
    for key, value in required.items():
        if meta.get(key) != value:
            raise ValueError(f"ORI JSON does not match model or Studio contract: {key}")
    verification = meta.get("verification")
    if not isinstance(verification, dict) or any(verification.get(k) is not True for k in ("onnx_vs_pt", "rknn_simulator_vs_pt")):
        raise ValueError("ORI export must pass PyTorch/ONNX and RKNN simulator checks")
    return meta


def save_model_pair(models_dir, file_name, model_bytes, metadata_json=None, can_save=lambda: True):
    """Commit a pair while stopped; rollback both files on a filesystem error.

    The model is replaced last. A legacy replacement removes stale metadata.
    Same-process writers are serialized and staging filenames are unique.
    """
    if not isinstance(file_name, str) or not file_name or file_name in {".rknn", "..rknn"}:
        raise ValueError("Invalid model filename")
    if any(c in file_name for c in '/\\\x00\r\n') or not file_name.lower().endswith(".rknn"):
        raise ValueError("Choose a filename ending in .rknn without path separators")
    if not isinstance(model_bytes, bytes) or not model_bytes:
        raise ValueError("Model file is empty")
    meta = validate_metadata(metadata_json, model_bytes)
    root = Path(models_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    model = root / (file_name[:-5] + ".rknn")
    sidecar = model.with_suffix(".json")
    with _STORE_LOCK:
        if not can_save():
            raise ValueError("System is running, cannot upload model file")
        if model.is_symlink() or sidecar.is_symlink():
            raise ValueError("Model destination must not be a symlink")
        with tempfile.TemporaryDirectory(prefix=".rknn-upload-", dir=root) as tmp:
            staging = Path(tmp)
            old_model = model.read_bytes() if model.exists() else None
            old_meta = sidecar.read_bytes() if sidecar.exists() else None
            (staging / "model").write_bytes(model_bytes)
            if meta is not None:
                (staging / "metadata").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if not can_save():
                raise ValueError("System started during upload; model was not changed")
            changed = False
            try:
                if meta is not None:
                    os.replace(staging / "metadata", sidecar)
                elif sidecar.exists():
                    sidecar.unlink()
                changed = True
                os.replace(staging / "model", model)
            except OSError:
                if changed:
                    for dest, contents in ((model, old_model), (sidecar, old_meta)):
                        if contents is None:
                            dest.unlink(missing_ok=True)
                        else:
                            restore = staging / (dest.suffix + "-restore")
                            restore.write_bytes(contents)
                            os.replace(restore, dest)
                raise
    return model.stem, meta
