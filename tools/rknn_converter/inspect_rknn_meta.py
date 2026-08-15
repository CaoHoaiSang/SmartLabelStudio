"""Inspect printable metadata embedded in RKNN files without loading the NPU."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", nargs="+")
    args = parser.parse_args()
    for name in args.model:
        path = Path(name)
        text = path.read_bytes().decode("latin1", errors="ignore")
        compiler = re.search(r"compiler version: ([^\x00\r\n]+)", text)
        shapes = re.findall(r"'shape': (\[[0-9, ]+\])", text)
        unique: list[str] = []
        for shape in shapes:
            if shape not in unique:
                unique.append(shape)
        print(f"MODEL={path.name} SIZE={path.stat().st_size}")
        print(f"COMPILER={compiler.group(1).strip() if compiler else 'unknown'}")
        print(f"SHAPES={';'.join(unique)}")


if __name__ == "__main__":
    main()
