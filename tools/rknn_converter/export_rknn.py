from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from types import MethodType

import torch
from rknn.api import RKNN
from ultralytics import YOLO


class DeltaXRawHead(torch.nn.Module):
    """Expose YOLO raw heads in the tensor order consumed by DeltaX YOLORKNN."""

    def __init__(self, network: torch.nn.Module) -> None:
        super().__init__()
        self.network = network

    def forward(self, images: torch.Tensor):
        return self.network(images)


def install_deltax_raw_forward(head: torch.nn.Module, task: str) -> None:
    """Patch the final head for DeltaX DET (9 outputs) or SEG (13 outputs)."""

    def raw_forward(self, features):
        box_head = self.one2many["box_head"]
        cls_head = self.one2many["cls_head"]
        outputs = []
        proto = self.proto(features[0]) if task == "segment" else None
        for index, feature in enumerate(features):
            boxes = box_head[index](feature)
            scores = cls_head[index](feature).sigmoid()
            objectness = scores.amax(dim=1, keepdim=True)
            if task == "segment":
                masks = self.cv4[index](feature)
                outputs.extend((boxes, scores, objectness, masks))
            else:
                outputs.extend((boxes, scores, objectness))
        if proto is not None:
            outputs.append(proto)
        return tuple(outputs)

    head.forward = MethodType(raw_forward, head)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeltaX-compatible YOLO PT to RKNN exporter")
    parser.add_argument("--model", default="/work/model.pt")
    parser.add_argument("--output", default="/output/model.rknn")
    parser.add_argument("--name", default="rk3588")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--task", choices=("detect", "segment", "classify"), default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.imgsz <= 0:
        raise RuntimeError("imgsz phải là số dương.")
    model_path = Path(args.model).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Work on a private writable copy because the Windows model mount is read-only.
    with tempfile.TemporaryDirectory(prefix="deltax-rknn-") as temp_dir:
        working_model = Path(temp_dir) / model_path.name
        shutil.copy2(model_path, working_model)
        model = YOLO(str(working_model))
        if args.task and model.task != args.task:
            raise RuntimeError(f"Task checkpoint là {model.task!r}, nhưng ứng dụng yêu cầu {args.task!r}.")
        if model.task not in {"detect", "segment", "classify"}:
            raise RuntimeError(
                f"DeltaX-compatible RKNN export supports detect, segment and classify, got {model.task!r}. "
                "Other tasks need their matching Studio decoder contract."
            )
        if model.task in {"detect", "segment"} and args.imgsz != 640:
            raise RuntimeError("DeltaX RKNNRuntime và bộ giải mã DET/SEG hiện yêu cầu imgsz=640.")

        network = model.model.float().eval()
        head = network.model[-1]
        head.export = model.task == "classify"
        box_channels = int(getattr(head, "reg_max", 0)) * 4
        mask_channels = int(getattr(head, "nm", 0))
        if model.task in {"detect", "segment"}:
            head.export = False
            if model.task == "segment" and mask_channels != 32:
                raise RuntimeError(f"DeltaX SegRKNNPredictor requires 32 mask channels, got {mask_channels}.")
            install_deltax_raw_forward(head, model.task)
        wrapper = DeltaXRawHead(network).eval()
        onnx_path = working_model.with_suffix(".deltax.onnx")
        dummy = torch.zeros(1, 3, args.imgsz, args.imgsz, dtype=torch.float32)
        if model.task == "classify":
            output_names = ["probabilities"]
        else:
            kinds = ("boxes", "scores", "objectness", "masks") if model.task == "segment" else ("boxes", "scores", "objectness")
            output_names = [f"scale_{scale}_{kind}" for scale in (8, 16, 32) for kind in kinds]
            if model.task == "segment":
                output_names.append("mask_prototypes")
        torch.onnx.export(
            wrapper,
            dummy,
            onnx_path,
            input_names=["images"],
            output_names=output_names,
            opset_version=17,
            do_constant_folding=True,
        )

        converter = RKNN(verbose=False)
        try:
            ret = converter.config(
                mean_values=[[0, 0, 0]],
                std_values=[[255, 255, 255]],
                target_platform=args.name,
            )
            if ret != 0:
                raise RuntimeError(f"RKNN config failed: {ret}")
            ret = converter.load_onnx(model=str(onnx_path))
            if ret != 0:
                raise RuntimeError(f"RKNN load_onnx failed: {ret}")
            ret = converter.build(do_quantization=False)
            if ret != 0:
                raise RuntimeError(f"RKNN build failed: {ret}")
            ret = converter.export_rknn(str(output_path))
            if ret != 0:
                raise RuntimeError(f"RKNN export failed: {ret}")
        finally:
            converter.release()

    output_shapes = []
    if model.task == "classify":
        output_shapes.append([1, len(model.names)])
    else:
        for stride in (8, 16, 32):
            side = args.imgsz // stride
            output_shapes.extend(
                ([1, box_channels, side, side], [1, len(model.names), side, side], [1, 1, side, side])
            )
            if model.task == "segment":
                output_shapes.append([1, mask_channels, side, side])
        if model.task == "segment":
            output_shapes.append([1, mask_channels, args.imgsz // 4, args.imgsz // 4])

    manifest = {
        "schema": 1,
        "format": "rknn",
        "target": args.name,
        "compiler": "rknn-toolkit2==2.2.0",
        "ultralytics": "8.4.6",
        "source_model": model_path.name,
        "output_model": output_path.name,
        "task": model.task,
        "imgsz": [args.imgsz, args.imgsz],
        "names": {str(key): value for key, value in model.names.items()},
        "normalization": {"mean": [0, 0, 0], "std": [255, 255, 255], "rgb2bgr": False},
        "input_contract": {
            "runtime_layout": "NHWC",
            "dtype": "uint8",
            "color": "RGB",
            "resize": "center_crop" if model.task == "classify" else "letterbox",
        },
        "output_layout": (
            "deltax_classification_softmax_1_output"
            if model.task == "classify"
            else "deltax_yolorknn_segment_13_heads"
            if model.task == "segment"
            else "deltax_yolorknn_detect_9_heads"
        ),
        "output_shapes": output_shapes,
    }
    output_path.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DELTAX_RKNN_OUTPUT={output_path}")


if __name__ == "__main__":
    main()
