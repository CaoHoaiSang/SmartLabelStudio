import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from smartlabel.hydro_release_candidate import (
    load_release_candidate,
    release_object_sha256,
    validate_release_candidate,
    verify_candidate_archive,
)


class HydroReleaseCandidateContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"PK-test-only-Hydro-P2-candidate\n"
        self.candidate = {
            "schema": "HydroModelReleaseCandidateV1",
            "purpose": "hydro-model",
            "bundleId": "hydro_cai_ngot_20261005T140000Z",
            "bundleZipSha256": hashlib.sha256(self.payload).hexdigest(),
            "bundleZipBytes": len(self.payload),
            "bundleContractSha256": hashlib.sha256(b"bundle-contract").hexdigest(),
            "bundleSchemaVersion": 3,
            "pipeline": "fixed_slot_multilabel_v3",
            "cropCode": "cai_ngot",
            "runtimeTarget": "windows_onnxruntime_cpu",
            "deploymentMode": "shadow",
            "validationStatus": "pilot_unvalidated",
            "labelSchemaSha256": hashlib.sha256(b"label-schema").hexdigest(),
            "evaluationEvidenceSha256": None,
            "datasetVersion": "dataset-test-20261005",
            "sourceCommit": "be853f00f007252a273ab43bc9df3a3555122806",
            "lineage": {"kind": "legacy_only"},
            "createdAt": "2026-10-05T14:00:00+00:00",
        }

    def test_valid_candidate_and_archive_identity(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "bundle.zip"
            archive.write_bytes(self.payload)
            result = verify_candidate_archive(self.candidate, archive)
        self.assertEqual(result["bundleId"], self.candidate["bundleId"])
        self.assertIsNot(result, self.candidate)
        self.assertIsNot(result["lineage"], self.candidate["lineage"])

    def test_unknown_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "không được phép"):
            validate_release_candidate({**self.candidate, "force": True})

    def test_fleet_lineage_is_fail_closed(self):
        candidate = {**self.candidate, "lineage": {"kind": "includes_fleet"}}
        with self.assertRaisesRegex(ValueError, "legacy_only"):
            validate_release_candidate(candidate)

    def test_unknown_runtime_and_pipeline_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "không đúng hợp đồng"):
            validate_release_candidate({**self.candidate, "runtimeTarget": "generic_cuda"})
        with self.assertRaisesRegex(ValueError, "không đúng hợp đồng"):
            validate_release_candidate({**self.candidate, "pipeline": "fixed_slot_multilabel_v2"})

    def test_validation_evidence_and_schema_hash_rules_are_strict(self):
        with self.assertRaisesRegex(ValueError, "không khớp"):
            validate_release_candidate({**self.candidate, "labelSchemaSha256": None})
        with self.assertRaisesRegex(ValueError, "không khớp"):
            validate_release_candidate({
                **self.candidate,
                "deploymentMode": "operational",
                "validationStatus": "validated_holdout",
            })

    def test_changed_archive_size_and_hash_are_rejected(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "bundle.zip"
            archive.write_bytes(self.payload + b"x")
            with self.assertRaisesRegex(ValueError, "Dung lượng"):
                verify_candidate_archive(self.candidate, archive)
            changed = bytearray(self.payload)
            changed[-1] ^= 1
            archive.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_candidate_archive(self.candidate, archive)

    def test_non_string_status_fields_raise_value_error(self):
        for field in ("runtimeTarget", "deploymentMode", "validationStatus"):
            with self.assertRaises(ValueError):
                validate_release_candidate({**self.candidate, field: ["windows_onnxruntime_cpu"]})

    def test_fractional_seconds_and_unvalidated_v2_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "không đúng hợp đồng"):
            validate_release_candidate({**self.candidate, "createdAt": "2026-10-05T14:00:00.12+00:00"})
        with self.assertRaisesRegex(ValueError, "không đúng hợp đồng"):
            validate_release_candidate({**self.candidate, "createdAt": "2026-10-05T14:00:00.123456+00:00"})
        with self.assertRaisesRegex(ValueError, "không khớp"):
            validate_release_candidate({
                **self.candidate, "bundleSchemaVersion": 2, "pipeline": "fixed_slot_multilabel_v2",
                "deploymentMode": "operational", "validationStatus": "operational_unvalidated",
                "labelSchemaSha256": None,
            })

    def test_invalid_calendar_date_and_smoke_status_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "không đúng hợp đồng"):
            validate_release_candidate({**self.candidate, "createdAt": "2026-02-31T00:00:00Z"})
        with self.assertRaisesRegex(ValueError, "không đúng hợp đồng"):
            validate_release_candidate({**self.candidate, "validationStatus": "pipeline_smoke_only"})

    def test_bundle_contract_hash_reuses_the_exporter_algorithm(self):
        digest = release_object_sha256({
            "cropCode": "cai_ngot", "schemaVersion": 3, "label": "à",
            "operationalAcceptance": {"ignored": True},
        })
        self.assertEqual(digest, "3f23393a3a9ba7b3beabcf752e3c75279b3b1b74e812e01980617d7a7663b624")

    def test_loader_rejects_duplicate_json_fields(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "release_candidate.json"
            document = json.dumps(self.candidate, ensure_ascii=False)
            document = document.replace(
                '"purpose": "hydro-model"',
                '"purpose": "hydro-model", "purpose": "hydro-model"',
            )
            path.write_text(document, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "trùng lặp"):
                load_release_candidate(path)


if __name__ == "__main__":
    unittest.main()
