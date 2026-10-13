"""Dedicated process for DeltaX Orienty checkpoints and training."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from .ori_runtime import ORI_MODEL_PRESETS

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT / "tools" / "ori_runtime"


def stamp_checkpoints(trainer):
    """Keep completed epoch checkpoints usable after a cancelled training job."""
    for name in ("best.pt", "last.pt"):
        checkpoint = Path(trainer.save_dir) / "weights" / name
        if checkpoint.is_file():
            sidecar = checkpoint.with_suffix(".ori.json")
            staged = sidecar.with_suffix(".json.tmp")
            # Pure helper import: stamping does not load standard Ultralytics.
            from tools.ori_runtime.deltax_ori_contract import model_architecture, heading_encoding
            staged.write_text(json.dumps({
                "schema": "deltax_ori_checkpoint_v1", "task": "ori",
                "runtime": "deltax-orienty-8.3.38-v2",
                "heading": "image_x_clockwise_degrees",
                "model_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "architecture": model_architecture(getattr(trainer, "model", None)),
                "heading_encoding": heading_encoding(getattr(trainer, "model", None)),
            }, indent=2), encoding="utf-8")
            os.replace(staged, sidecar)


def load_model(path):
    if "ultralytics" in sys.modules:
        raise RuntimeError("ORI phải chạy trong tiến trình riêng trước khi nạp Ultralytics.")
    os.environ["YOLO_CONFIG_DIR"] = str(Path(os.environ.get("LOCALAPPDATA", os.environ.get("TMPDIR", "/tmp"))) / "SmartLabel" / "ori-settings")
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    sys.path.insert(0, str(FORK))
    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS
    SETTINGS.update({"sync": False})
    path = str(path)
    if path in ORI_MODEL_PRESETS:
        family, scale, _ = ORI_MODEL_PRESETS[path]
        folder = "11" if family == "yolo11" else "v8"
        path = str(FORK / "ultralytics" / "cfg" / "models" / folder / f"{family}{scale}-ori.yaml")
    elif path.startswith("deltax-"):
        raise ValueError("Model ORI DeltaX không được hỗ trợ; chọn YOLO11 n/s/m/l/x hoặc YOLOv8n cũ.")
    if Path(path).suffix.lower() == ".pt":
        try:
            metadata = json.loads(Path(path).with_suffix(".ori.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Checkpoint ORI cần metadata .ori.json. Model ORI cũ chưa xác nhận quy ước góc; hãy train lại bằng task ori.") from exc
        if metadata.get("schema") != "deltax_ori_checkpoint_v1" or metadata.get("heading") != "image_x_clockwise_degrees" or metadata.get("model_sha256") != hashlib.sha256(Path(path).read_bytes()).hexdigest():
            raise ValueError("Metadata ORI sai quy ước góc hoặc SHA256 checkpoint không khớp.")
    model = YOLO(path)
    if model.task != "orienty" or model.model.model[-1].__class__.__name__ != "Orienty":
        raise ValueError("Task ORI cần kiến trúc Orienty hoặc checkpoint ORI DeltaX tương thích.")
    if Path(path).suffix.lower() == ".pt" and "architecture" in metadata:
        from tools.ori_runtime.deltax_ori_contract import model_architecture, heading_encoding
        if metadata["architecture"] != model_architecture(model.model):
            raise ValueError("Kiến trúc trong metadata không khớp checkpoint ORI.")
    if Path(path).suffix.lower() == ".pt":
        from tools.ori_runtime.deltax_ori_contract import heading_encoding
        if metadata.get("heading_encoding", "normalized_degrees_v1") != heading_encoding(model.model):
            raise ValueError("Metadata ORI không khớp cách mã hóa hướng của checkpoint.")
    return model


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    action, arg = sys.argv[1:3]
    if action == "train":
        config = json.loads(arg)
        from .fleet_boundaries import require_legacy_training_data, require_legacy_model
        require_legacy_training_data(config["data"])
        require_legacy_model(config["model"], context=config["project_dir"])
        import yaml
        data = yaml.safe_load(Path(config["data"]).read_text(encoding="utf-8"))
        if data.get("deltax_ori_contract") != "corners_normalized_heading_v1":
            raise ValueError("Task ORI cần dataset ORI DeltaX mới (bốn góc + hướng). Export lại với task ori.")
        model = load_model(config["model"])
        if config["model"] in ORI_MODEL_PRESETS and config.get("pretrained_backbone", True):
            family, scale, pretrained = ORI_MODEL_PRESETS[config["model"]]
            cache = Path(os.environ.get("LOCALAPPDATA", os.environ.get("TMPDIR", "/tmp"))) / "SmartLabel" / "ori-models"
            cache.mkdir(parents=True, exist_ok=True)
            print(f"ORI · nạp {family}{scale} pretrained; hai nhánh góc vẫn học từ nhãn của dự án.", flush=True)
            model.load(str(cache / pretrained))
        import torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        if getattr(model.model.model[-1], "heading_components", 1) == 1:
            print("Train tiếp checkpoint cũ: tạo nhánh hướng cos/sin mới; giữ backbone/OBB và file checkpoint gốc.", flush=True)
        print("ORI DeltaX · khung xoay và hướng cos/sin 360° · runtime riêng", flush=True)
        model.add_callback("on_model_save", stamp_checkpoints)
        model.train(
            data=config["data"], epochs=int(config["epochs"]), imgsz=int(config["image_size"]),
            batch=int(config["batch"]), patience=int(config["patience"]),
            device=config["device"], project=config["project_dir"], name=config["run_name"],
            exist_ok=False, val=bool(config.get("validate", True)), workers=0, amp=False,
            plots=False, pretrained=False, perspective=0.0, degrees=180.0, fliplr=0.0, flipud=0.0,
        )
        stamp_checkpoints(model.trainer)  # Final optimizer stripping changes the bytes.
        print("TRAINING_COMPLETE", flush=True)
    elif action == "serve":
        import math
        from .models import Annotation
        from .annotation_geometry import direction
        model = load_model(arg)
        print("ORI_MODEL_INFO=" + json.dumps({"names": {str(k): str(v) for k, v in model.names.items()}}), flush=True)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                operation = request.pop("_ori_operation", "predict")
                if operation not in {"predict", "filter_metrics"}:
                    raise ValueError("Yêu cầu ORI không hợp lệ.")
                if operation == "filter_metrics":
                    from .frame_filter import _detection_metrics
                    threshold = float(request.pop("threshold"))
                    metrics = []
                    for result in model.predict(**request, verbose=False):
                        height, width = result.orig_shape
                        metrics.append(_detection_metrics(result, width, height, threshold))
                    print("ORI_FILTER_METRICS=" + json.dumps(metrics))
                    continue
                annotations = []
                for result in model.predict(**request, verbose=False):
                    if result.obb is None:
                        continue
                    for points, box, cls, conf in zip(result.obb.xyxyxyxy.cpu().tolist(), result.obb.xywhr.cpu().tolist(), result.obb.cls.cpu().tolist(), result.obb.conf.cpu().tolist()):
                        xs, ys = [p[0] for p in points], [p[1] for p in points]
                        ann = Annotation.create_box(int(cls), [min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)], source="yolo", confidence=float(conf), model_version=Path(arg).name)
                        ann.kind, ann.obb = "ori", points
                        cx, cy, width, height, radians = box
                        image_height, image_width = result.orig_shape
                        ann.orientation = direction(
                            ann.bbox, ann.obb, [cx + math.cos(radians), cy + math.sin(radians)],
                            (image_width, image_height), snap=False,
                        )
                        if ann.orientation is None:
                            continue  # Padding/degenerate detections cannot form an editable ORI label.
                        annotations.append(ann.to_dict())
                print("ORI_PREDICTION=" + json.dumps(annotations), flush=True)
            except Exception as exc:
                print("ORI_ERROR=" + json.dumps(str(exc)), flush=True)
    elif action == "evaluate":
        config = json.loads(arg)
        from .evaluation import evaluate_yolo_model
        model = load_model(config.pop("model_path"))
        result = evaluate_yolo_model(model.ckpt_path, _model=model, **config)
        print("ORI_EVALUATION=" + json.dumps(result, ensure_ascii=False))
    elif action == "inspect":
        model = load_model(arg)
        print("ORI_MODEL_INFO=" + json.dumps({"task": "ori", "names": {str(k):str(v) for k,v in model.names.items()}}))
    else:
        raise ValueError("Tác vụ ORI không hợp lệ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
