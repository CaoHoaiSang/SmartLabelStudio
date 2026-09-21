from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import time
import unittest
import uuid
from PIL import Image

from smartlabel.fleet_intake import FleetIntakeError
from smartlabel.fleet_review import FleetReviewSession
from smartlabel.fleet_source import dataset_preflight
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore


class FleetDatasetPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "workspace")
        self.project = self.store.create_project("Preflight", task="classify")
        apply_hydroponic_slot_template(self.project); self.store.save(self.project)
        root = self.store.project_dir(self.project)
        identifier, asset = str(uuid.uuid4()), str(uuid.uuid4())
        self.folder = root / "fleet_inbox" / identifier; self.folder.mkdir(parents=True)
        self.image = self.folder / (asset + ".png"); Image.new("RGB", (64, 64), "green").save(self.image)
        (self.folder / "custody.json").write_text(json.dumps({"importId": "a" * 64}))
        self.row = {"id": asset, "file": self.image.name, "sha256": hashlib.sha256(self.image.read_bytes()).hexdigest(),
                    "source": "hydro_camera", "groupId": "b" * 64, "reviewStatus": "reviewed", "attributes": {"plant_presence": "present"},
                    "qualification": {"schemaVersion": "FleetSourceQualificationV1", "sourceClass": "hydro_slot", "issues": [],
                                      "groupId": "b" * 64, "parentStatus": "not_shared", "trainAllowed": False, "evaluationEligible": False}}
        self.session = FleetReviewSession(root, self.project.id, "FleetImportV1." + "a" * 43)
        self.session.data = {"contributionId": identifier, "importId": "a" * 64, "images": [self.row]}
        self.session.revision = "d" * 64; self.session.deadline = time.monotonic() + 30

    def run_preflight(self, refresh=None):
        with patch.object(self.session, "refresh", side_effect=refresh or (lambda: (deepcopy(self.session.data), self.session.revision))):
            return dataset_preflight(self.session, self.project, self.store)

    def test_dry_run_has_lineage_and_partial_explicit_labels_but_never_admits_to_training(self):
        before = {file: file.read_bytes() for file in self.session.root.rglob('*') if file.is_file()}
        report = self.run_preflight()
        self.assertTrue(report["sourceReady"]); self.assertFalse(report["trainAllowed"])
        self.assertFalse(report["evaluationEligible"]); self.assertEqual(report["attributeCounts"], {"plant_presence": 1})
        self.assertEqual(report["images"][0]["groupId"], self.row["groupId"])
        self.assertNotIn(str(self.session.root), json.dumps(report)); self.assertNotIn("FleetImportV1", json.dumps(report))
        self.assertEqual(before, {file: file.read_bytes() for file in self.session.root.rglob('*') if file.is_file()})

    def test_reencoded_same_pixels_in_holdout_are_blocked_not_only_identical_files(self):
        file = self.session.root / "images" / "existing.png"
        Image.new("RGB", (64, 64), "green").save(file, compress_level=0)
        self.assertNotEqual(hashlib.sha256(file.read_bytes()).hexdigest(), self.row["sha256"])
        self.project.images.append(ImageRecord(id="old", file_name=file.name, width=64, height=64, capture_group="old_group"))
        self.store.save(self.project)
        (self.session.root / "split_assignment.json").write_text(json.dumps({"groups": {"old_group": "test"}}))
        result = self.run_preflight()
        self.assertFalse(result["sourceReady"]); self.assertIn("duplicate_existing_holdout", result["images"][0]["issues"])

    def test_missing_labels_wrong_source_and_contradictory_semantics_are_not_ready(self):
        self.row["reviewStatus"] = "draft"
        self.assertIn("label_review_required", self.run_preflight()["images"][0]["issues"])
        self.row["reviewStatus"] = "reviewed"
        self.row["attributes"] = {"plant_presence": "absent", "yellow_leaf": "present"}
        self.assertIn("label_semantics_invalid", self.run_preflight()["images"][0]["issues"])
        self.row.pop("qualification")
        self.assertIn("source_evidence_missing", self.run_preflight()["images"][0]["issues"])

    def test_revocation_label_change_project_change_and_bytes_change_during_check_discard_report(self):
        for change in ("revoked", "label", "project", "image"):
            with self.subTest(change=change):
                original = (self.session.root / "project.json").read_bytes()
                image_bytes = self.image.read_bytes(); revision = self.session.revision
                count = 0
                def refresh():
                    nonlocal count
                    count += 1
                    if count == 2:
                        if change == "revoked": raise FleetIntakeError("revoked")
                        if change == "label": self.session.revision = "e" * 64
                        if change == "project": (self.session.root / "project.json").write_text("{}")
                        if change == "image": self.image.write_bytes(b"changed")
                    return deepcopy(self.session.data), self.session.revision
                try:
                    with self.assertRaises(FleetIntakeError): self.run_preflight(refresh)
                finally:
                    (self.session.root / "project.json").write_bytes(original); self.image.write_bytes(image_bytes); self.session.revision = revision

    def test_wrong_or_stale_project_fails_before_contacting_receiver(self):
        self.project.description = "unsaved external change"
        with patch.object(self.session, "refresh") as refresh:
            with self.assertRaises(FleetIntakeError): dataset_preflight(self.session, self.project, self.store)
            refresh.assert_not_called()
