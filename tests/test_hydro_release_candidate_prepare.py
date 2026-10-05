import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from smartlabel.fleet_boundaries import FleetIntakeError
from smartlabel.hydro_release_candidate import (
    prepare_fleet_release_candidate,
    release_object_sha256,
    verify_candidate_archive,
)
from smartlabel.project_store import ProjectStore


def bundle(**overrides):
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
        "labelSchema": {"schemaId": "LabelSchemaV1", "attributes": [{"id": "plant_presence"}]},
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

    def write_zip(self, document):
        archive = self.root / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("bundle.json", json.dumps(document, ensure_ascii=False))
        return archive

    def test_legacy_project_candidate_uses_zip_bundle_hash(self):
        document = bundle()
        archive = self.write_zip(document)
        candidate = prepare_fleet_release_candidate(archive, self.project, self.store)
        self.assertEqual(candidate["bundleContractSha256"], release_object_sha256(document))
        self.assertEqual(candidate["labelSchemaSha256"], release_object_sha256(document["labelSchema"]))
        self.assertEqual(candidate["bundleZipSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertIsNone(candidate["evaluationEvidenceSha256"])
        self.assertEqual(self.project_file.read_bytes(), self.before_project)
        self.assertEqual(json.dumps(self.project.metadata, sort_keys=True), self.before_metadata)

    def test_fleet_marker_is_rejected_without_writing_candidate(self):
        self.project.metadata["fleetLineage"] = {"kind": "includes_fleet"}
        archive = self.write_zip(bundle())
        with self.assertRaises(FleetIntakeError):
            prepare_fleet_release_candidate(archive, self.project, self.store)
        self.assertFalse((archive.parent / "release_candidate.json").exists())

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
        self.assertFalse((self.root / "release_candidate.json").exists())

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


if __name__ == "__main__":
    unittest.main()
