"""Print task, classes, input size and final head type of Ultralytics checkpoints."""

from __future__ import annotations

import argparse

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", nargs="+")
    args = parser.parse_args()
    for path in args.model:
        model = YOLO(path)
        network = model.model
        head = network.model[-1]
        print(
            f"MODEL={path} TASK={model.task} HEAD={type(head).__name__} "
            f"NAMES={model.names} ARGS={getattr(network, 'args', {})}"
        )


if __name__ == "__main__":
    main()
