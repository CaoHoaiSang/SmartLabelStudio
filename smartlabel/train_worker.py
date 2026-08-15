from __future__ import annotations

import json
import sys


def main() -> int:
    from ultralytics import YOLO

    if len(sys.argv) != 2:
        print("Thiếu cấu hình train", flush=True)
        return 2
    config = json.loads(sys.argv[1])
    print(f"Nạp model: {config['model']}", flush=True)
    print(f"Task: {config.get('task', 'detect')}", flush=True)
    print(f"Thiết bị: {config['device']}", flush=True)
    model = YOLO(config["model"], task=config.get("task", "detect"))
    model.train(
        data=config["data"],
        epochs=int(config["epochs"]),
        imgsz=int(config["image_size"]),
        batch=int(config["batch"]),
        patience=int(config["patience"]),
        val=bool(config.get("validate", True)),
        device=config["device"],
        project=config["project_dir"],
        name=config["run_name"],
        exist_ok=False,
    )
    print("TRAINING_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
