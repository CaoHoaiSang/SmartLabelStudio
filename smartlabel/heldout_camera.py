"""Bounded acquisition worker using the installed Hydro camera implementation.

No Hydro API mutations, service control, model loading or operational capture calls.
"""
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
import json
import os
import socket
import subprocess
import sys
import time
import uuid

from .benchmark_contract import canonical, image_identity, read_json
from .heldout_collection import collection_lock, now


def assert_camera_service_stopped():
    """Windows pilot only. Operator must also disable the service supervisor restart."""
    if sys.platform != "win32":
        raise ValueError("Thu ảnh trực tiếp hiện chỉ hỗ trợ pilot Windows; chưa mở camera ở nền tảng khác.")
    with socket.socket() as sock:
        sock.settimeout(.3)
        if sock.connect_ex(("127.0.0.1", 8091)) == 0:
            raise ValueError("Dịch vụ Camera Hydro (8091) đang chạy. Dừng riêng Camera và cơ chế tự khởi động lại trước khi thay cây.")
    command = ("$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Where-Object { "
               "$_.Name -match '^python(w)?(.exe)?$' -and $_.CommandLine -match 'hydro_ai_camera[.]cli' "
               "-and $_.CommandLine -match '\\bserve\\b' }).Count")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        raise ValueError("Chưa kiểm tra được tiến trình Camera; không mở thiết bị.")
    if int(result.stdout.strip()):
        raise ValueError("Tiến trình Camera Hydro còn hoạt động; chưa nhường camera cho công cụ TEST.")


def prepare_profiles(library, camera_file, geometry_file):
    library = Path(library).resolve()
    if not (library / "hydro_ai_camera" / "contracts.py").is_file():
        raise ValueError("Chọn thư mục ai_camera chứa thư viện Hydro đã cài trên máy.")
    geometry = read_json(Path(geometry_file))
    # Hydro V2 keeps the active geometry inside its site profile; do not require
    # operators to copy an older standalone geometry file instead.
    geometry = geometry.get("geometryProfile", geometry)
    return {"library": str(library), "camera": read_json(Path(camera_file)), "geometry": geometry}


def run_worker(config, destination, *, capture=False, confirmed=False, cancel=None, timeout=45):
    if capture and confirmed is not True:
        raise ValueError("Xác nhận Camera Hydro đã dừng và đã bố trí cây TEST trước khi chụp.")
    if capture:
        assert_camera_service_stopped()
    destination = Path(destination).absolute()
    destination.mkdir(parents=True, exist_ok=True)
    request = {**config, "destination": str(destination), "capture": capture}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with TemporaryDirectory(prefix=".worker-", dir=destination) as temp:
        request_path = Path(temp) / "request.json"
        request_path.write_text(canonical(request), encoding="utf-8")
        process = subprocess.Popen([sys.executable, "-m", "smartlabel.heldout_camera", str(request_path)],
            cwd=str(Path(__file__).resolve().parent.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=flags)
        started = time.monotonic()
        try:
            while True:
                if cancel and cancel.is_set():
                    raise ValueError("Đã hủy chụp; không lưu ảnh vào lô TEST.")
                if time.monotonic() - started > timeout:
                    raise ValueError("Camera không phản hồi trong thời hạn; đã đóng worker, chưa lưu ảnh.")
                try:
                    stdout, stderr = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode:
                raise ValueError((stdout.strip() or "Không thu được ảnh; kiểm tra thư viện Camera và cấu hình.")[-1600:])
            if capture:
                assert_camera_service_stopped()  # Reject if the supervisor resumed while capturing.
            return json.loads(stdout)
        finally:
            if process.poll() is None:
                process.kill(); process.communicate(timeout=5)


def produce_frame(frame, config, destination, *, controls=None):
    """Shared ROI + quality calculations, no inference. Injectable frame for fixtures."""
    import cv2
    from hydro_ai_camera.capture_pipeline import _crop, _quality, _capture_quality_assessment, _apply_asset_quality_statuses
    from hydro_ai_camera.contracts import validate_camera_profile, validate_geometry_profile
    camera = validate_camera_profile(config["camera"], require_locked=True)
    geometry = validate_geometry_profile(config["geometry"], require_locked=True)
    if frame is None or frame.shape != (1080, 1920, 3) or len(geometry["slots"]) != 10:
        raise ValueError("Ảnh phải đúng 1920×1080 và bố cục 10 rọ đã xác nhận.")
    destination = Path(destination)
    (destination / "heldout_frame.json").write_text(canonical({"testOnly": True}), encoding="utf-8")
    assets = [{"assetId": "full", "role": "full_frame", "quality": _quality(frame)}]
    for rack, rect in geometry["rois"].items():
        assets.append({"assetId": rack, "role": "roi", "rackId": rack, "quality": _quality(_crop(frame, rect))})
    slots = []
    for slot in geometry["slots"]:
        identifier = slot["slotId"]
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier):
            raise ValueError("Mã ROI không an toàn.")
        image = _crop(frame, slot["rect"])
        path = destination / (identifier + ".png")
        if not cv2.imwrite(str(path), image):
            raise ValueError("Không ghi được ảnh rọ; kiểm tra dung lượng ổ đĩa.")
        asset = {"assetId": identifier, "role": "slot", "slotId": identifier,
                 "rackId": slot["rackId"], "quality": _quality(image)}
        assets.append(asset)
        slots.append({**asset, "rect": slot["rect"], "path": path.name, **image_identity(path)})
    assessment = _capture_quality_assessment(assets, camera)
    _apply_asset_quality_statuses(assets, assessment)
    for slot in slots:
        quality = next(a for a in assets if a["assetId"] == slot["assetId"])
        slot["qualityStatus"] = quality.get("qualityStatus", "unknown")
    full = destination / "full.png"
    if not cv2.imwrite(str(full), frame):
        raise ValueError("Không ghi được ảnh toàn cảnh.")
    meta = {"schemaVersion": "HydroHeldoutFrameV1", "captureId": "capture_" + uuid.uuid4().hex,
            "capturedAt": now(), "cameraProfile": camera, "geometryProfile": geometry,
            "actualControls": controls or {}, "qualityAssessment": assessment,
            "fullFrame": {"path": full.name, **image_identity(full)}, "slots": slots,
            "modelInvoked": False, "source": "SmartLabel local heldout collector"}
    (destination / "capture.json").write_text(canonical(meta), encoding="utf-8")
    return meta


def worker(request):
    library = Path(request["library"]).resolve()
    sys.path.insert(0, str(library))
    from hydro_ai_camera.contracts import validate_camera_profile, validate_geometry_profile
    camera = validate_camera_profile(request["camera"], require_locked=True)
    geometry = validate_geometry_profile(request["geometry"], require_locked=True)
    if geometry.get("cameraProfileId") not in (None, camera["profileId"]):
        raise ValueError("Cấu hình ROI không thuộc camera profile đã chọn.")
    if camera["backend"] != "dshow" or len(geometry["slots"]) != 10:
        raise ValueError("Pilot này dùng cấu hình DirectShow Windows và 10 ROI hiện hữu.")
    if not request["capture"]:
        return {"camera": camera, "geometry": geometry, "library": str(library)}
    from hydro_ai_camera.runtime import CameraRuntime
    # Do not construct CameraRuntime: __init__ binds operational configuration,
    # monitoring, outbox and model state. Only reuse acquisition methods.
    # Serializes our own collectors across projects/processes; the Hydro service
    # still requires the explicit operator hand-off and pre/post checks.
    with collection_lock(Path(gettempdir()) / "smartlabel-heldout-camera"):
        assert_camera_service_stopped()
        runtime = CameraRuntime.__new__(CameraRuntime)
        frame, actual, verification = runtime._capture_frame_and_controls(camera, require_verified=True)
        assert_camera_service_stopped()
        return produce_frame(frame, request, request["destination"], controls={"values": actual, "verification": verification})


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        value = worker(read_json(Path(sys.argv[1])))
        print(canonical(value))
    except Exception as error:
        print(f"Thu thập TEST chưa hoàn tất: {error}")
        raise SystemExit(1)
