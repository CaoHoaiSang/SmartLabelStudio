from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import os
import subprocess
import sys
import unittest

from smartlabel import heldout_camera as camera


class HeldoutCameraGuardTests(unittest.TestCase):
    def test_v2_site_geometry_extraction_keeps_source_untouched(self):
        from smartlabel.benchmark_contract import canonical
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hydro_ai_camera").mkdir(); (root / "hydro_ai_camera" / "contracts.py").touch()
            camera_file = root / "camera.json"; camera_file.write_text('{"profileId":"camera"}')
            site_file = root / "site.json"
            contents = canonical({"schemaVersion": 2, "geometryProfile": {"profileId": "active_geometry"}})
            site_file.write_text(contents, encoding="utf-8")
            result = camera.prepare_profiles(root, camera_file, site_file)
            self.assertEqual(result["geometry"]["profileId"], "active_geometry")
            self.assertEqual(site_file.read_text(encoding="utf-8"), contents)
    def test_no_confirmation_never_opens_or_spawns(self):
        with patch.object(camera.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "Xác nhận"):
                camera.run_worker({}, "unused", capture=True)
            popen.assert_not_called()

    def test_active_service_port_fails_closed(self):
        with patch.object(camera.sys, "platform", "win32"), patch.object(camera.socket, "socket") as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value = 0
            with self.assertRaisesRegex(ValueError, "8091"): camera.assert_camera_service_stopped()

    def test_failed_process_check_or_running_service_blocks(self):
        with patch.object(camera.sys, "platform", "win32"), patch.object(camera.socket, "socket") as sock, patch.object(camera.subprocess, "run") as run:
            sock.return_value.__enter__.return_value.connect_ex.return_value = 1
            for code, output in ((1, ""), (0, "not a count"), (0, "1")):
                run.return_value = SimpleNamespace(returncode=code, stdout=output)
                with self.assertRaises(ValueError): camera.assert_camera_service_stopped()
            run.return_value = SimpleNamespace(returncode=0, stdout="0")
            camera.assert_camera_service_stopped()
            self.assertIn(r"\bserve\b", run.call_args.args[0][-1])

    def test_timeout_and_cancel_kill_only_own_worker(self):
        with TemporaryDirectory() as root, patch.object(camera.subprocess, "Popen") as popen:
            process = popen.return_value
            process.poll.return_value = None
            process.communicate.return_value = ("", "")
            stop = Event(); stop.set()
            with self.assertRaisesRegex(ValueError, "hủy"):
                camera.run_worker({}, root, cancel=stop)
            process.kill.assert_called_once()
            process.reset_mock()
            with self.assertRaisesRegex(ValueError, "thời hạn"):
                camera.run_worker({}, root, timeout=-1)
            process.kill.assert_called_once()


LIBRARY = Path(os.environ.get("HYDRO_CAMERA_LIBRARY", "D:/Hydroponic_IoT_ESP32/03_Edge_Server/ai_camera"))


@unittest.skipUnless((LIBRARY / "hydro_ai_camera" / "contracts.py").is_file(), "Hydro acquisition library not installed")
class HeldoutSharedPipelineTests(unittest.TestCase):
    def test_real_shared_roi_quality_and_profile_worker_without_camera(self):
        import numpy as np
        from PIL import Image
        from smartlabel import heldout_collection as collection
        from smartlabel.hydroponic import apply_hydroponic_slot_template
        from smartlabel.project_store import ProjectStore
        config = {"library": str(LIBRARY), "camera": {
            "schemaVersion": 1, "profileId": "camera_fixture", "status": "locked", "backend": "dshow",
            "device": 1, "width": 1920, "height": 1080, "rotationDegrees": 0,
            "timezone": "Asia/Bangkok", "scheduleTimes": ["07:00"], "controls": {
                "exposureAuto": False, "exposure": -9, "gain": 0, "whiteBalanceAuto": False,
                "whiteBalance": 5000, "powerLineFrequency": 50}},
            "geometry": {"schemaVersion": 1, "profileId": "geometry_fixture", "status": "locked",
                "frame": {"width": 1920, "height": 1080}, "rois": {
                    "upper": {"x": 0, "y": 0, "width": 1920, "height": 540},
                    "lower": {"x": 0, "y": 540, "width": 1920, "height": 540}},
                "slots": [{"slotId": f"{rack}_{i+1:02d}", "rackId": rack,
                           "rect": {"x": i*384, "y": y, "width": 384, "height": 540}}
                          for rack, y in (("upper", 0), ("lower", 540)) for i in range(5)]}}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            # This subprocess validates config only. It must never call VideoCapture.
            validated = camera.run_worker(config, root / "validate")
            self.assertEqual(validated["camera"]["profileId"], "camera_fixture")
            from copy import deepcopy
            wrong = deepcopy(config); wrong["geometry"]["cameraProfileId"] = "other"
            with self.assertRaisesRegex(ValueError, "không thuộc"):
                camera.run_worker(wrong, root / "wrong")
            sys.path.insert(0, str(LIBRARY))
            try:
                frame = np.random.default_rng(7).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
                target = root / "frame"; target.mkdir()
                with patch("cv2.VideoCapture", side_effect=AssertionError("no hardware")):
                    result = camera.produce_frame(frame, config, target)
                self.assertEqual(len(result["slots"]), 10)
                self.assertFalse(result["modelInvoked"])
                store = ProjectStore(root / "workspace"); project = store.create_project("fixture", task="classify")
                apply_hydroponic_slot_template(project)
                lot = collection.create_lot(store, project, "16 plants", "2026-09-01", reserved=True)
                collection.save_capture(store, project, lot, target,
                    empty_slots=[s["slotId"] for s in result["slots"][6:]])
                rows = collection.load_collection(store, project)[0]["images"]
                self.assertEqual(sum(r["declaredEmpty"] for r in rows), 4)
            finally:
                sys.path.remove(str(LIBRARY))
