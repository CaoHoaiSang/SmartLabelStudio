import hashlib
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from smartlabel.fleet_boundaries import FleetIntakeError
from smartlabel.hydro_release_candidate import (
    prepare_fleet_release_candidate,
    release_object_sha256,
    verify_candidate_archive,
)
from smartlabel.label_schema import legacy_label_schema
from smartlabel.project_store import ProjectStore


MODEL_BYTES = {
    "models/plant_presence.onnx": b"presence-model",
    "models/yellow_leaf.onnx": b"yellow-model",
    "models/wilt.onnx": b"wilt-model",
}


def bundle(**overrides):
    schema = legacy_label_schema()
    models = {
        attribute["id"]: {
            "path": f"models/{attribute['id']}.onnx",
            "sha256": hashlib.sha256(MODEL_BYTES[f"models/{attribute['id']}.onnx"]).hexdigest(),
            "lowThreshold": 0.3,
            "highThreshold": 0.7,
        }
        for attribute in schema["attributes"]
    }
    value = {
        "schemaVersion": 3,
        "bundleId": "hydro_cai_ngot_20261005T140000Z",
        "cropCode": "cai_ngot",
        "pipeline": "fixed_slot_multilabel_v3",
        "runtimeTarget": "windows_onnxruntime_cpu",
        "deploymentMode": "shadow",
        "validationStatus": "pilot_unvalidated",
        "datasetVersion": "dataset-test-20261005",
        "sourceCommit": "be853f00f007252a273ab43bc9df3a3555122806",
        "createdAt": "2026-10-05T14:00:00+00:00",
        "labelSchema": schema,
        "models": models,
    }
    value.update(overrides)
    return value


class PrepareFleetCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Legacy hydro", task="classify")
        self.project_file = self.store.project_dir(self.project) / "project.json"
        self.before_project = self.project_file.read_bytes()
        self.before_metadata = json.dumps(self.project.metadata, sort_keys=True)

    def write_zip(self, document, name="bundle.zip", entries=None):
        archive = self.root / name
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("bundle.json", json.dumps(document, ensure_ascii=False))
            for path, content in (MODEL_BYTES.items() if entries is None else entries):
                package.writestr(path, content)
        return archive

    def candidate_path(self, archive):
        return archive.with_name(archive.stem + ".release_candidate.json")

    def test_legacy_project_candidate_uses_zip_bundle_hash(self):
        document = bundle()
        archive = self.write_zip(document)
        candidate = prepare_fleet_release_candidate(archive, self.project, self.store)
        self.assertEqual(candidate["bundleContractSha256"], release_object_sha256(document))
        self.assertEqual(candidate["labelSchemaSha256"], release_object_sha256(document["labelSchema"]))
        self.assertEqual(candidate["bundleZipSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertIsNone(candidate["evaluationEvidenceSha256"])
        self.assertTrue(self.candidate_path(archive).is_file())
        self.assertEqual(self.project_file.read_bytes(), self.before_project)
        self.assertEqual(json.dumps(self.project.metadata, sort_keys=True), self.before_metadata)

    def test_fleet_marker_is_rejected_without_writing_candidate(self):
        self.project.metadata["fleetLineage"] = {"kind": "includes_fleet"}
        archive = self.write_zip(bundle())
        with self.assertRaises(FleetIntakeError):
            prepare_fleet_release_candidate(archive, self.project, self.store)
        self.assertFalse(self.candidate_path(archive).exists())

    def test_changed_zip_after_create_is_detected(self):
        archive = self.write_zip(bundle())
        candidate = prepare_fleet_release_candidate(archive, self.project, self.store)
        archive.write_bytes(archive.read_bytes() + b"x")
        with self.assertRaisesRegex(ValueError, "ZIP"):
            verify_candidate_archive(candidate, archive)

    def test_invalid_bundle_is_rejected(self):
        document = bundle()
        document.pop("pipeline")
        archive = self.write_zip(document)
        with self.assertRaises(ValueError):
            prepare_fleet_release_candidate(archive, self.project, self.store)
        self.assertFalse(self.candidate_path(archive).exists())

    def test_unvalidated_operational_must_match_acceptance_inside_zip(self):
        document = bundle(
            deploymentMode="operational", validationStatus="operational_unvalidated",
            operationalAcceptance={"schemaVersion": "HydroOperationalAcceptanceV1", "bundleContractSha256": "0" * 64},
        )
        archive = self.write_zip(document)
        with self.assertRaisesRegex(ValueError, "không khớp"):
            prepare_fleet_release_candidate(archive, self.project, self.store)
        document["operationalAcceptance"]["bundleContractSha256"] = release_object_sha256(document)
        archive.unlink()
        archive = self.write_zip(document)
        candidate = prepare_fleet_release_candidate(archive, self.project, self.store)
        self.assertEqual(candidate["validationStatus"], "operational_unvalidated")
        self.assertEqual(candidate["bundleContractSha256"], document["operationalAcceptance"]["bundleContractSha256"])

    def test_more_than_32_zip_entries_is_rejected(self):
        entries = [(f"extra/{index}", b"x") for index in range(32)]
        archive = self.write_zip(bundle(), entries=entries)
        with self.assertRaisesRegex(ValueError, "32"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_more_than_uncompressed_limit_is_rejected(self):
        archive = self.write_zip(bundle())
        with patch("smartlabel.hydro_release_candidate.MAX_BUNDLE_UNCOMPRESSED_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "1 GiB"):
                prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_absolute_zip_entry_is_rejected(self):
        archive = self.write_zip(bundle(), entries=[("/absolute.onnx", b"x")])
        with self.assertRaisesRegex(ValueError, "không an toàn"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_parent_traversal_zip_entry_is_rejected(self):
        archive = self.write_zip(bundle(), entries=[("../escape.onnx", b"x")])
        with self.assertRaisesRegex(ValueError, "không an toàn"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_symlink_zip_entry_is_rejected(self):
        archive = self.root / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("bundle.json", json.dumps(bundle()))
            link = zipfile.ZipInfo("models/plant_presence.onnx")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(link, "target")
        with self.assertRaisesRegex(ValueError, "liên kết"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_duplicate_zip_entry_is_rejected(self):
        archive = self.root / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("bundle.json", json.dumps(bundle()))
            package.writestr("bundle.json", json.dumps(bundle()))
        with self.assertRaisesRegex(ValueError, "trùng lặp"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_extra_file_is_rejected(self):
        entries = list(MODEL_BYTES.items()) + [("unexpected.txt", b"x")]
        archive = self.write_zip(bundle(), entries=entries)
        with self.assertRaisesRegex(ValueError, "chỉ được chứa"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_missing_declared_model_file_is_rejected(self):
        entries = list(MODEL_BYTES.items())[1:]
        archive = self.write_zip(bundle(), entries=entries)
        with self.assertRaisesRegex(ValueError, "thiếu tệp model"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_model_sha256_mismatch_is_rejected(self):
        archive = self.write_zip(bundle(), entries=[
            (path, b"tampered" if path.endswith("wilt.onnx") else content)
            for path, content in MODEL_BYTES.items()
        ])
        with self.assertRaisesRegex(ValueError, "SHA-256 model"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_v3_model_set_must_match_label_schema(self):
        document = bundle()
        document["models"].pop("wilt")
        archive = self.write_zip(document)
        with self.assertRaisesRegex(ValueError, "Tập model"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_legacy_model_set_must_have_three_fixed_keys(self):
        document = bundle(schemaVersion=2)
        document.pop("labelSchema")
        document["models"].pop("wilt")
        archive = self.write_zip(document)
        with self.assertRaisesRegex(ValueError, "ba model legacy"):
            prepare_fleet_release_candidate(archive, self.project, self.store)

    def test_invalid_model_thresholds_are_rejected(self):
        document = bundle()
        document["models"]["wilt"]["lowThreshold"] = 0.8
        with self.assertRaisesRegex(ValueError, "Ngưỡng model"):
            prepare_fleet_release_candidate(self.write_zip(document), self.project, self.store)

    def test_jetson_requires_minimum_tensorrt_version(self):
        document = bundle(runtimeTarget="jetson_nano_tensorrt_fp16")
        with self.assertRaisesRegex(ValueError, "minimumTensorRTVersion"):
            prepare_fleet_release_candidate(self.write_zip(document), self.project, self.store)

    def test_two_archives_create_distinct_candidates(self):
        first = self.write_zip(bundle(bundleId="bundle-first"), "first.zip")
        second = self.write_zip(bundle(bundleId="bundle-second"), "second.zip")
        prepare_fleet_release_candidate(first, self.project, self.store)
        prepare_fleet_release_candidate(second, self.project, self.store)
        self.assertTrue((self.root / "first.release_candidate.json").is_file())
        self.assertTrue((self.root / "second.release_candidate.json").is_file())


if __name__ == "__main__":
    unittest.main()
