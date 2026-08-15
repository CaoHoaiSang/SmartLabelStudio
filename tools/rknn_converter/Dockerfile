FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/tmp/Ultralytics

RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libgomp1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# RKNN Toolkit 2.2.0 requires Torch <=2.1.0. Install the CPU wheels explicitly
# so Docker does not pull the much larger CUDA runtime into the converter image.
RUN pip install --no-cache-dir \
        torch==2.1.0+cpu torchvision==0.16.0+cpu \
        --index-url https://download.pytorch.org/whl/cpu

COPY vendor/rknn_toolkit2-2.2.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl /tmp/rknn_toolkit2-2.2.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
RUN pip install --no-cache-dir /tmp/rknn_toolkit2-2.2.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl --no-deps \
    && pip install --no-cache-dir \
        protobuf==3.20.3 "psutil>=5.9.0" "ruamel.yaml>=0.17.21" \
        "scipy>=1.9.3" "tqdm>=4.64.1" "opencv-python-headless>=4.5.5.64" \
        "fast-histogram>=0.11" "numpy<=1.26.4" onnx==1.14.1 \
        onnxruntime==1.16.0 ultralytics==8.4.6
RUN pip install --no-cache-dir "onnxslim>=0.1.71"

COPY export_rknn.py /opt/deltax/export_rknn.py
ENTRYPOINT ["python", "/opt/deltax/export_rknn.py"]
