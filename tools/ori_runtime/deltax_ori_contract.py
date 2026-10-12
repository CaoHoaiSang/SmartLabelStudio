"""Pure stdlib architecture identity; importing this never loads Ultralytics."""
from pathlib import Path
import re


def model_architecture(network):
    network = getattr(network, "module", network)
    cfg = getattr(network, "yaml", {})
    if not isinstance(cfg, dict):
        cfg = {}
    # Checkpoints travel between Windows training and Linux conversion.
    stem = Path(str(cfg.get("yaml_file", "")).replace("\\", "/")).stem
    family = cfg.get("deltax_architecture")
    if family not in {"yolo11", "yolov8"}:
        family = "yolo11" if stem.startswith("yolo11") else "yolov8" if stem.startswith("yolov8") else "custom"
    scale = str(cfg.get("scale") or "")
    if scale not in "nslmx" or len(scale) != 1:
        match = re.search(r"yolo[v]?\d+([nslmx])", stem)
        scale = match.group(1) if match else ""
    return {"family": family, "scale": scale}


def heading_encoding(network):
    network = getattr(network, "module", network)
    layers = getattr(network, "model", [])
    layers = getattr(layers, "model", layers)  # AutoBackend wraps the Torch network.
    head = layers[-1] if len(layers) else None
    components = getattr(head, "heading_components", 1)
    if components not in (1, 2):
        raise ValueError("Unsupported ORI heading components")
    return "cos_sin_vector_v2" if components == 2 else "normalized_degrees_v1"
