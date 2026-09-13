from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import json
import unittest
import zipfile

from smartlabel import hydro_export
from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydro_labels import install_label_schema, model_keys
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.label_schema import legacy_label_schema
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore


class HydroPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Hydro fixture", task="classify")
        apply_hydroponic_slot_template(self.project)
        install_label_schema(self.project, legacy_label_schema())
        for i, label in enumerate(("absent", "present", "absent")):
            self.project.images.append(ImageRecord(
                id=f"img_{i}", file_name=f"{i}.png", width=224, height=224, review_status="reviewed",
                attributes={"plant_presence": "absent" if i == 0 else "present",
                            "yellow_leaf": "not_applicable" if i == 0 else label,
                            "wilt": "not_applicable" if i == 0 else label},
            ))
        for key in model_keys(self.project):
            source = self.root / f"{key}.pt"
            source.write_bytes(f"fixture-{key}".encode())
            source.with_suffix(".onnx").write_bytes(b"keep old sidecar")
            self.project.attribute_models[key] = str(source)
        self.store.save(self.project)
        DatasetManager(self.store).ensure_split_assignment(self.project)
        self.before = deepcopy(self.project.to_dict())
        self.split_path = self.store.project_dir(self.project) / "split_assignment.json"
        self.before_split = self.split_path.read_bytes()
        self.config = {
            "datasetVersion": "fixture-v1", "sourceCommit": "fixture-commit",
            "cameraProfileIds": ["camera-1"], "geometryProfileIds": ["geometry-1"],
            "runtimeTarget": "windows_onnxruntime_cpu", "deploymentMode": "shadow",
            "thresholds": {key: {"lowThreshold": .2, "highThreshold": .8} for key in model_keys(self.project)},
        }
        self.output = self.root / "gói_hydro"
        self.cancel = Event()
        self.messages = []
        self.qa = patch.object(hydro_export, "hydro_dataset_qa", return_value={
            "issues": [], "validationStatus": "pilot_unvalidated",
        }).start()
        self.addCleanup(patch.stopall)
        self.export = patch.object(hydro_export, "export_jetson_onnx", side_effect=self.export_fixture).start()

    def export_fixture(self, source, target, **kwargs):
        import onnx
        from onnx import helper, TensorProto
        self.assertNotEqual(source.parent, self.root)
        model = helper.make_model(helper.make_graph(
            [helper.make_node("Constant", [], ["scores"], value=helper.make_tensor("v", TensorProto.FLOAT, [1, 2], [.25, .75]))],
            "fixture", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 224, 224])],
            [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 2])]), opset_imports=[helper.make_opsetid("", 12)])
        model.ir_version = 7
        helper.set_model_props(model, {"names": "{0: 'present', 1: 'absent'}", "sourceFixture": source.read_text()})
        onnx.save(model, target)
        return target

    def build(self):
        return hydro_export.build_hydro_package(self.project, self.store, self.output, self.config,
                                                self.messages.append, self.cancel)

    def assert_preserved(self):
        self.assertEqual(self.project.to_dict(), self.before)
        self.assertEqual(self.split_path.read_bytes(), self.before_split)
        for key, value in self.project.attribute_models.items():
            self.assertEqual(Path(value).read_bytes(), f"fixture-{key}".encode())
            self.assertEqual(Path(value).with_suffix(".onnx").read_bytes(), b"keep old sidecar")
        self.assertFalse(list(self.root.glob(".hydro-package-*")))

    def test_pt_to_portable_v3_zip_in_one_workflow(self):
        result = self.build()
        self.assertEqual(self.export.call_count, 3)
        manifest = json.loads((result["bundle"] / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 3)
        self.assertEqual(manifest["runtimeTarget"], "windows_onnxruntime_cpu")
        for key, entry in manifest["models"].items():
            self.assertEqual(entry["positiveIndex"], 0)
            self.assertTrue(Path(result["onnxModels"][key]).is_file())
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(len(archive.namelist()), 4)
        self.assertTrue(any("[1/3]" in text for text in self.messages))
        self.assertTrue(any("[3/3]" in text for text in self.messages))
        self.assert_preserved()

    def test_always_exports_current_pt_not_stale_onnx_metadata(self):
        self.project.metadata["hydroOnnxModels"] = {key: "does-not-exist.onnx" for key in model_keys(self.project)}
        self.before = deepcopy(self.project.to_dict())
        self.build()
        self.assertEqual(self.export.call_count, 3)
        self.assert_preserved()

    def test_missing_model_blocks_before_conversion(self):
        self.project.attribute_models.pop("wilt")
        with self.assertRaisesRegex(ValueError, "model đã train"):
            self.build()
        self.export.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_qa_error_stops_before_conversion_without_rewriting_split(self):
        self.qa.return_value = {"issues": [{"severity": "error", "code": "missing_image"}]}
        with self.assertRaisesRegex(ValueError, "Thiếu file ảnh"):
            self.build()
        self.export.assert_not_called()
        self.assert_preserved()

    def test_bad_config_and_unsafe_runtime_fail_before_conversion(self):
        for override in ({"cameraProfileIds": []}, {"deploymentMode": "operational"}, {"thresholds": {}}):
            original = deepcopy(self.config)
            self.config.update(override)
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.build()
            self.config = original
        self.export.assert_not_called()
        self.assert_preserved()

    def test_export_failure_keeps_models_and_publishes_nothing(self):
        self.export.side_effect = RuntimeError("fixture conversion failed")
        with self.assertRaisesRegex(RuntimeError, "conversion failed"):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".zip").exists())
        self.assert_preserved()

    def test_cancel_during_onnx_waits_for_step_then_cleans_staging(self):
        def export_then_cancel(*args, **kwargs):
            result = self.export_fixture(*args, **kwargs)
            self.cancel.set()
            return result
        self.export.side_effect = export_then_cancel
        with self.assertRaises(hydro_export.HydroExportCancelled):
            self.build()
        self.assertEqual(self.export.call_count, 1)
        self.assertFalse(self.output.exists())
        self.assert_preserved()

    def test_bundle_failure_does_not_publish_partial_onnx(self):
        with patch.object(hydro_export, "write_hydro_model_bundle", side_effect=ValueError("fixture contract mismatch")):
            with self.assertRaisesRegex(ValueError, "contract mismatch"):
                self.build()
        self.assertFalse(self.output.exists())
        self.assert_preserved()

    def test_existing_package_is_never_overwritten(self):
        archive = self.output.with_suffix(".zip")
        archive.write_bytes(b"previous package")
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(archive.read_bytes(), b"previous package")
        self.export.assert_not_called()

    def test_late_zip_collision_rolls_back_only_own_directory(self):
        original = hydro_export.write_hydro_model_bundle
        def collide(*args, **kwargs):
            result = original(*args, **kwargs)
            self.output.with_suffix(".zip").write_bytes(b"other package")
            return result
        with patch.object(hydro_export, "write_hydro_model_bundle", side_effect=collide):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.output.with_suffix(".zip").read_bytes(), b"other package")
        self.assertFalse(self.output.exists())
        self.assert_preserved()

    def test_real_qa_is_still_enforced(self):
        # The fixture deliberately lacks real image/lineage files.
        from smartlabel.hydroponic import hydro_dataset_qa
        self.qa.side_effect = hydro_dataset_qa
        with self.assertRaisesRegex(ValueError, "lỗi QA"):
            self.build()
        self.export.assert_not_called()
        self.assert_preserved()
