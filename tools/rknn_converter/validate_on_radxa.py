"""Read-only smoke test for a DeltaX DET RKNN model on a Rockchip Radxa."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import cv2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="/home/radxa/deltax_pp_sw/ultralytics_rknn-new")
    parser.add_argument("--image", required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--names", nargs="+", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()

    sys.path.insert(0, args.runtime)
    from YOLORKNN import Task, YOLORKNN

    image = cv2.imread(args.image)
    if image is None:
        raise RuntimeError(f"Cannot read image: {args.image}")

    for model_path in args.model:
        started = time.perf_counter()
        model = YOLORKNN(Task.DET, model_path, args.names, conf=args.conf)
        result = model.inference(image)
        elapsed_ms = (time.perf_counter() - started) * 1000
        boxes = result.boxes
        count = 0 if boxes is None else len(boxes)
        print(f"MODEL={Path(model_path).name} LOAD_INFER_MS={elapsed_ms:.1f} BOXES={count}")
        if boxes is not None:
            for index, (xyxy, confidence, class_id) in enumerate(zip(boxes.xyxy, boxes.conf, boxes.cls)):
                print(
                    f"  DET={index} CLASS={int(class_id)} CONF={float(confidence):.4f} "
                    f"XYXY={','.join(f'{float(value):.1f}' for value in xyxy)}"
                )
        model.predictor.runtime.deinitialize()


if __name__ == "__main__":
    main()
