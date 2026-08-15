"""Smoke-test DeltaX SEG RKNN files through the installed SegRKNNPredictor."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import cv2
import numpy as np


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
        model = YOLORKNN(Task.SEG, model_path, args.names, conf=args.conf)
        result = model.inference(image)
        elapsed_ms = (time.perf_counter() - started) * 1000
        box_count = 0 if result.boxes is None else len(result.boxes)
        mask_data = None if result.masks is None else result.masks.data
        mask_count = 0 if mask_data is None else len(mask_data)
        mask_pixels = 0 if mask_data is None else int(np.count_nonzero(mask_data))
        print(
            f"MODEL={Path(model_path).name} LOAD_INFER_MS={elapsed_ms:.1f} "
            f"BOXES={box_count} MASKS={mask_count} MASK_PIXELS={mask_pixels}"
        )
        if result.boxes is not None:
            for index, (xyxy, confidence, class_id) in enumerate(
                zip(result.boxes.xyxy, result.boxes.conf, result.boxes.cls)
            ):
                area = 0 if mask_data is None else int(np.count_nonzero(mask_data[index]))
                print(
                    f"  DET={index} CLASS={int(class_id)} CONF={float(confidence):.4f} MASK_PIXELS={area} "
                    f"XYXY={','.join(f'{float(value):.1f}' for value in xyxy)}"
                )
        model.predictor.runtime.deinitialize()


if __name__ == "__main__":
    main()
