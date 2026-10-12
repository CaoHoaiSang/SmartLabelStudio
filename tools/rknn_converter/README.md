# DeltaX RKNN converter

This isolated Linux x86 Docker environment is pinned to the model format used
by DeltaX Studio on Radxa:

- Ultralytics 8.4.6
- RKNN Toolkit 2.2.0
- RK3588 target
- DET/SEG input 640 x 640; Classification mặc định 224 x 224

Build:

```powershell
docker build -t deltax-rknn-converter:2.2.0-v4 tools/rknn_converter
```

The SmartLabelStudio UI invokes this image automatically. The generated
`.rknn` file is for upload through Studio `Vision AI Setting`; it is deliberately
not registered as an Auto-Label model on Windows.

The converter intentionally exports explicit DeltaX contracts instead of
the generic Ultralytics output. DET emits 9 tensors. SEG emits 13 tensors:
box DFL logits, class scores, objectness, mask coefficients per stride, plus
the mask prototype tensor. Classification emits one softmax tensor `[1,N]`.
Standard OBB and Pose are not Studio ORI. DeltaX YOLO11-ORI and legacy
YOLOv8-ORI use a separate `deltax-rknn-ori:2.2.0-v4` image, built automatically
by the existing **Xuất RKNN** button. Supply the checkpoint and matching
`.ori.json`; the result is a paired `.rknn` + `.json` export with five raw
outputs (v1 scalar or v2 cos/sin heading), architecture identity, hash and PT/ONNX/RKNN simulator verification.
See [ORI pipeline](../../docs/DELTAX_ORI_PIPELINE.md) for aliases and protocol.

Manual conversion example:

```powershell
docker run --rm `
  -v "D:\models:/work:ro" `
  -v "D:\deploy:/output" `
  deltax-rknn-converter:2.2.0-v4 `
  --model /work/best.pt `
  --output /output/bottles_rk3588.rknn `
  --name rk3588 `
  --imgsz 640
```

Classification example:

```powershell
docker run --rm `
  -v "D:\models:/work:ro" `
  -v "D:\deploy:/output" `
  deltax-rknn-converter:2.2.0-v4 `
  --model /work/condition_best.pt `
  --output /output/condition_rk3588.rknn `
  --name rk3588 `
  --task classify `
  --imgsz 224
```

Use `validate_on_radxa.py` only as an isolated smoke test. It loads files from
the paths passed on the command line and does not modify Studio settings.
