"""Read-only smoke test for a Classification RKNN on an RK3588 Radxa."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from rknnlite.api import RKNNLite


def center_crop_rgb(image_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    source_h, source_w = rgb.shape[:2]
    scale = max(width / max(source_w, 1), height / max(source_h, 1))
    resized = cv2.resize(
        rgb,
        (max(width, round(source_w * scale)), max(height, round(source_h * scale))),
        interpolation=cv2.INTER_LINEAR,
    )
    top = max(0, (resized.shape[0] - height) // 2)
    left = max(0, (resized.shape[1] - width) // 2)
    return np.ascontiguousarray(resized[top : top + height, left : left + width], dtype=np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--meta", type=Path, default=None)
    args = parser.parse_args()

    metadata_path = args.meta or args.model.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    input_size = metadata.get("imgsz", [224, 224])
    height, width = int(input_size[0]), int(input_size[1])
    labels = {str(key): value for key, value in metadata.get("names", {}).items()}
    image = cv2.imread(str(args.image))
    if image is None:
        raise RuntimeError(f"Không đọc được ảnh: {args.image}")
    tensor = center_crop_rgb(image, width, height)

    runtime = RKNNLite()
    try:
        load_code = runtime.load_rknn(str(args.model))
        if load_code != 0:
            raise RuntimeError(f"load_rknn lỗi: {load_code}")
        init_code = runtime.init_runtime()
        if init_code != 0:
            raise RuntimeError(f"init_runtime lỗi: {init_code}")
        outputs = runtime.inference(inputs=[tensor])
        if len(outputs) != 1:
            raise RuntimeError(f"Classifier phải có 1 output, nhận được {len(outputs)}")
        probabilities = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
        index = int(probabilities.argmax())
        confidence = float(probabilities[index])
        print(
            json.dumps(
                {
                    "index": index,
                    "label": labels.get(str(index), str(index)),
                    "confidence": confidence,
                    "output_shape": list(outputs[0].shape),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        runtime.release()


if __name__ == "__main__":
    raise SystemExit(main())

