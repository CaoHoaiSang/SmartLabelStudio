"""Print actual RKNN output tensor shapes on a Rockchip device."""

from __future__ import annotations

import argparse
import numpy as np

from rknnlite.api import RKNNLite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", nargs="+")
    args = parser.parse_args()
    image = np.zeros((1, 640, 640, 3), dtype=np.uint8)
    for path in args.model:
        runtime = RKNNLite()
        load_code = runtime.load_rknn(path)
        init_code = runtime.init_runtime(core_mask=RKNNLite.NPU_CORE_0) if load_code == 0 else -1
        outputs = runtime.inference(inputs=[image]) if init_code == 0 else []
        shapes = [list(output.shape) for output in outputs]
        print(f"MODEL={path} LOAD={load_code} INIT={init_code} OUTPUTS={len(outputs)} SHAPES={shapes}")
        runtime.release()


if __name__ == "__main__":
    main()
