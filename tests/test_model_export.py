from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest
from unittest.mock import patch

from smartlabel.model_export import diagnose_rknn_environment, inspect_deltax_rknn
from smartlabel.evaluation import quality_rating


def fake_rknn_bytes(class_count: int = 3, image_size: int = 640, task: str = "detect") -> bytes:
    fragments = ["compiler version: 2.2.0"]
    if task == "classify":
        fragments.append(f"'shape': [1, {class_count}]")
        return ("RKNN\x00" + "\n".join(fragments)).encode("latin1") + b"\x00" * 2048
    for stride in (8, 16, 32):
        side = image_size // stride
        fragments.extend(
            (
                f"'shape': [1, 64, {side}, {side}]",
                f"'shape': [1, {class_count}, {side}, {side}]",
                f"'shape': [1, 1, {side}, {side}]",
            )
        )
        if task == "segment":
            fragments.append(f"'shape': [1, 32, {side}, {side}]")
    if task == "segment":
        fragments.append(f"'shape': [1, 32, {image_size // 4}, {image_size // 4}]")
    return ("RKNN\x00" + "\n".join(fragments)).encode("latin1") + b"\x00" * 2048


class RknnInspectionTests(unittest.TestCase):
    def test_quality_rating_requires_both_localization_and_recall(self) -> None:
        self.assertIn("Rất tốt", quality_rating(0.86, 0.90, 0.90))
        self.assertIn("Chưa đủ", quality_rating(0.80, 0.95, 0.55))

    @patch("smartlabel.model_export.shutil.which", return_value="docker.exe")
    @patch("smartlabel.model_export.subprocess.run")
    def test_docker_cli_without_running_linux_engine_is_rejected(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["docker", "info"], 0, "||\n", "Docker Desktop is unable to start"
        )
        ready, detail = diagnose_rknn_environment()
        self.assertFalse(ready)
        self.assertIn("Linux Engine chưa chạy", detail)
        self.assertIn("unable to start", detail)

    def test_accepts_classification_single_output_layout(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "condition.rknn"
            model.write_bytes(fake_rknn_bytes(class_count=4, image_size=224, task="classify"))
            report = inspect_deltax_rknn(model, image_size=224, class_count=4, task="classify")
            self.assertEqual(report["outputs"], 1)
            self.assertEqual(report["layout"], "deltax_classification_softmax_1_output")

    def test_classification_rejects_wrong_class_count(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "condition.rknn"
            model.write_bytes(fake_rknn_bytes(class_count=3, image_size=224, task="classify"))
            with self.assertRaisesRegex(RuntimeError, "output"):
                inspect_deltax_rknn(model, image_size=224, class_count=4, task="classify")

    def test_classification_accepts_converter_sidecar_contract(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "condition.rknn"
            model.write_bytes(b"compiler version: 2.2.0" + b"\x00" * 2048)
            model.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "task": "classify",
                        "output_layout": "deltax_classification_softmax_1_output",
                        "output_shapes": [[1, 4]],
                    }
                ),
                encoding="utf-8",
            )
            report = inspect_deltax_rknn(model, image_size=224, class_count=4, task="classify")
            self.assertEqual(report["classes"], 4)

    def test_accepts_deltax_nine_output_layout(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "bottles.rknn"
            model.write_bytes(fake_rknn_bytes())
            report = inspect_deltax_rknn(model, image_size=640, class_count=3)
            self.assertEqual(report["compiler"], "2.2.0")
            self.assertEqual(report["outputs"], 9)
            self.assertEqual(report["layout"], "deltax_yolorknn_detect_9_heads")

    def test_rejects_generic_single_output_rknn(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "generic.rknn"
            model.write_bytes(b"compiler version: 2.2.0\x00'shape': [1, 7, 8400]" + b"\x00" * 2048)
            with self.assertRaisesRegex(RuntimeError, "9 đầu ra"):
                inspect_deltax_rknn(model, image_size=640, class_count=3)

    def test_accepts_deltax_thirteen_output_segment_layout(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "bottles_seg.rknn"
            model.write_bytes(fake_rknn_bytes(class_count=3, task="segment"))
            report = inspect_deltax_rknn(model, image_size=640, class_count=3, task="segment")
            self.assertEqual(report["task"], "segment")
            self.assertEqual(report["outputs"], 13)
            self.assertEqual(report["layout"], "deltax_yolorknn_segment_13_heads")

    def test_segment_rejects_detection_layout(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "detect_only.rknn"
            model.write_bytes(fake_rknn_bytes(class_count=3))
            with self.assertRaisesRegex(RuntimeError, "13 đầu ra segment"):
                inspect_deltax_rknn(model, image_size=640, class_count=3, task="segment")

    def test_rejects_wrong_compiler(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory) / "old.rknn"
            model.write_bytes(fake_rknn_bytes().replace(b"2.2.0", b"1.6.0"))
            with self.assertRaisesRegex(RuntimeError, "compiler 2.2.0"):
                inspect_deltax_rknn(model, image_size=640, class_count=3)


if __name__ == "__main__":
    unittest.main()
