"""Pure stdlib architecture identity; importing this never loads Ultralytics."""
from pathlib import Path
import re


def model_architecture(network):
    network = getattr(network, "module", network)
    cfg = getattr(network, "yaml", {})
    if not isinstance(cfg, dict):
        cfg = {}
    stem = Path(str(cfg.get("yaml_file", ""))).stem
    family = cfg.get("deltax_architecture")
    if family not in {"yolo11", "yolov8"}:
        family = "yolo11" if stem.startswith("yolo11") else "yolov8" if stem.startswith("yolov8") else "custom"
    scale = str(cfg.get("scale") or "")
    if scale not in "nslmx" or len(scale) != 1:
        match = re.search(r"yolo[v]?\d+([nslmx])", stem)
        scale = match.group(1) if match else ""
    return {"family": family, "scale": scale}
