# DeltaX RKNN converter

This isolated Linux x86 Docker environment is pinned to the model format used
by DeltaX Studio on Radxa:

- Ultralytics 8.4.6
- RKNN Toolkit 2.2.0
- RK3588 target
- DET/SEG input 640 x 640; Classification mặc định 224 x 224

Build:

```powershell
docker build -t deltax-rknn-converter:2.2.0-v3 tools/rknn_converter
```

The SmartLabelStudio UI invokes this image automatically. The generated
`.rknn` file is for upload through Studio `Vision AI Setting`; it is deliberately
not registered as an Auto-Label model on Windows.

The converter intentionally exports explicit DeltaX contracts instead of
the generic Ultralytics output. DET emits 9 tensors. SEG emits 13 tensors:
box DFL logits, class scores, objectness, mask coefficients per stride, plus
the mask prototype tensor. Classification emits one softmax tensor `[1,N]`.
OBB and custom ORI remain blocked.

Manual conversion example:

```powershell
docker run --rm `
  -v "D:\models:/work:ro" `
  -v "D:\deploy:/output" `
  deltax-rknn-converter:2.2.0-v3 `
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
  deltax-rknn-converter:2.2.0-v3 `
  --model /work/condition_best.pt `
  --output /output/condition_rk3588.rknn `
  --name rk3588 `
  --task classify `
  --imgsz 224
```

Use `validate_on_radxa.py` only as an isolated smoke test. It loads files from
the paths passed on the command line and does not modify Studio settings.
