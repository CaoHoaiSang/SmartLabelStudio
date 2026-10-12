"""ORI raw tensors matching the existing DeltaX OriRKNNPredictor, toolkit 2.2.0."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from types import MethodType

import numpy as np
import torch


def install_ori_raw_forward(head):
    if head.__class__.__name__ != "Orienty" or head.reg_max != 16 or head.ne != 1 or head.nl != 3:
        raise ValueError("Checkpoint không đúng Orienty 3 scale / DFL 16 / 1 angle + 1 heading.")

    def forward(self, features):
        batch = features[0].shape[0]
        boxes_scores = [torch.cat((self.cv2[i](x), self.cv3[i](x)), 1) for i, x in enumerate(features)]
        angles = torch.cat([self.cv4[i](x).view(batch, 1, -1) for i, x in enumerate(features)], 2).sigmoid()
        headings = torch.cat([self.cv5[i](x).view(batch, 1, -1) for i, x in enumerate(features)], 2).clamp(-1, 1)
        return tuple(boxes_scores + [angles, headings])

    head.forward = MethodType(forward, head)


def expected_shapes(classes):
    return [[1, 64 + classes, side, side] for side in (80, 40, 20)] + [[1, 1, 8400], [1, 1, 8400]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", default="rk3588", choices=["rk3588"])
    parser.add_argument("--imgsz", type=int, default=640, choices=[640])
    parser.add_argument("--task", default="ori", choices=["ori"])
    args = parser.parse_args()
    from ultralytics import YOLO
    from deltax_ori_contract import model_architecture
    from rknn.api import RKNN
    import onnx
    import onnxruntime as ort

    source, output = Path(args.model), Path(args.output)
    metadata = json.loads(source.with_suffix(".ori.json").read_text(encoding="utf-8"))
    if (metadata.get("schema") != "deltax_ori_checkpoint_v1" or metadata.get("heading") != "image_x_clockwise_degrees"
            or metadata.get("model_sha256") != hashlib.sha256(source.read_bytes()).hexdigest()):
        raise ValueError("Thiếu/sai metadata checkpoint ORI DeltaX hoặc hash không khớp.")
    torch.set_num_threads(4)
    model = YOLO(str(source))
    network = model.model.float().eval()
    architecture = model_architecture(network)
    if "architecture" in metadata and metadata["architecture"] != architecture:
        raise ValueError("Kiến trúc trong metadata không khớp checkpoint ORI.")
    install_ori_raw_forward(network.model[-1])
    shapes = expected_shapes(len(model.names))
    # A textured input exercises all branches, rather than testing only zero activations.
    pixels = np.random.default_rng(11).integers(0, 256, size=(1, 640, 640, 3), dtype=np.uint8)
    dummy = torch.from_numpy(pixels.transpose(0, 3, 1, 2).copy()).float() / 255
    with torch.no_grad():
        reference = [x.numpy() for x in network(dummy)]
    if [list(x.shape) for x in reference] != shapes:
        raise ValueError("ORI head shapes không tương thích Studio.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ori-rknn-") as temp:
        onnx_path = Path(temp) / "ori.onnx"
        torch.onnx.export(network, dummy, onnx_path, input_names=["images"],
                          output_names=["scale_8", "scale_16", "scale_32", "obb_angle_sigmoid", "heading_normalized"],
                          opset_version=17, do_constant_folding=True)
        onnx.checker.check_model(onnx.load(onnx_path))
        exported = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"]).run(None, {"images": dummy.numpy()})
        for pt, tensor in zip(reference, exported):
            np.testing.assert_allclose(tensor, pt, atol=1e-4, rtol=1e-4)
        converter = RKNN(verbose=False)
        try:
            for stage, code in (("config", converter.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], target_platform=args.name)),
                                ("load_onnx", converter.load_onnx(model=str(onnx_path)))):
                if code != 0:
                    raise RuntimeError(f"RKNN {stage}: {code}")
            if converter.build(do_quantization=False) != 0:
                raise RuntimeError("RKNN build failed")
            if converter.init_runtime() != 0:
                raise RuntimeError("RKNN simulator init failed")
            simulated = converter.inference(inputs=[pixels], data_format=["nhwc"])
            if simulated is None or [list(x.shape) for x in simulated] != shapes:
                raise RuntimeError("RKNN simulator output layout/order không khớp Studio")
            for pt, tensor in zip(reference, simulated):
                np.testing.assert_allclose(tensor, pt, atol=0.05, rtol=0.01)
            if converter.export_rknn(str(output)) != 0:
                raise RuntimeError("RKNN export failed")
        finally:
            converter.release()
    manifest = {
        "schema": 1, "format": "rknn", "target": args.name, "compiler": "rknn-toolkit2==2.2.0",
        "task": "ori", "imgsz": [640, 640], "names": {str(k): v for k, v in model.names.items()},
        "source_model": source.name, "source_sha256": metadata["model_sha256"], "output_model": output.name,
        "architecture": architecture,
        "model_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "output_layout": "deltax_orienty_5_heads_v1", "output_shapes": shapes,
        "heading": "image_x_clockwise_degrees", "heading_scale": 180,
        "obb_angle": "(sigmoid - 0.25) * pi", "heading_refinement": "snap_to_obb_axis_4_directions",
        "normalization": {"mean": [0, 0, 0], "std": [255, 255, 255], "rgb2bgr": False},
        "input_contract": {"runtime_layout": "NHWC", "dtype": "uint8", "color": "RGB", "resize": "letterbox"},
        "verification": {"onnx_vs_pt": True, "rknn_simulator_vs_pt": True, "hardware_validated": False},
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DELTAX_RKNN_OUTPUT={output}")


if __name__ == "__main__":
    main()
