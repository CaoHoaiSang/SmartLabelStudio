from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import unittest
import uuid

from smartlabel.fleet_review import FleetReviewSession
from smartlabel.fleet_intake import FleetIntakeError
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore


class FleetReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "workspace")
        self.project = self.store.create_project("Fleet review", task="classify")
        apply_hydroponic_slot_template(self.project); self.store.save(self.project)
        self.root = self.store.project_dir(self.project)
        self.identifier, self.asset = str(uuid.uuid4()), str(uuid.uuid4())
        folder = self.root / "fleet_inbox" / self.identifier; folder.mkdir(parents=True)
        self.image = folder / (self.asset + ".png"); self.image.write_bytes(b"fixture bytes")
        (folder / "custody.json").write_text(json.dumps({"importId": "a" * 64}))
        self.data = {"schemaVersion": "FleetLabelReviewV1", "projectId": self.project.id,
                     "contributionId": self.identifier, "importId": "a" * 64, "trainAllowed": False,
                     "images": [{"id": self.asset, "file": self.image.name, "sha256": hashlib.sha256(self.image.read_bytes()).hexdigest(),
                                 "attributes": {}, "reviewStatus": "draft", "source": "phone"}]}
        self.result = {"ok": True, "data": self.data, "revision": "0" * 64,
                       "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
        self.session = FleetReviewSession(self.root, self.project.id, "FleetImportV1." + "a" * 43)

    def response(self, factory, status=200):
        response = factory.return_value.getresponse.return_value
        response.status = status; response.read.return_value = json.dumps(self.result).encode()

    def test_native_authorization_bounded_display_lease_and_no_default_labels(self):
        with patch("smartlabel.fleet_review.http.client.HTTPConnection") as factory:
            self.response(factory); data, revision = self.session.refresh()
            self.assertEqual(data["images"][0]["attributes"], {})
            self.assertEqual(self.session.preview_path(data["images"][0]), self.image)
            factory.assert_called_once_with("127.0.0.1", 17864, timeout=45)
            self.assertEqual(factory.return_value.request.call_args.args[1], "/smartlabel/review")
            self.session.deadline = 0
            with self.assertRaises(FleetIntakeError):
                self.session.preview_path(data["images"][0])

    def test_changed_image_withdrawal_and_wrong_project_fail_closed(self):
        with patch("smartlabel.fleet_review.http.client.HTTPConnection") as factory:
            self.response(factory); self.session.refresh()
            row = self.session.data["images"][0]
            self.image.write_bytes(b"changed")
            with self.assertRaises(FleetIntakeError): self.session.preview_path(row)
            (self.image.parent / "withdrawn.json").write_text("{}")
            with self.assertRaises(FleetIntakeError): self.session.preview_path(row)
            self.result["data"]["projectId"] = "project_other"
            self.response(factory)
            with self.assertRaises(FleetIntakeError): self.session.refresh()
            self.assertEqual(self.session.deadline, 0)

    def test_network_errors_do_not_expose_secrets_or_preserve_access(self):
        with patch("smartlabel.fleet_review.http.client.HTTPConnection") as factory:
            for status in (302, 403, 409, 500):
                self.response(factory, status)
                with self.assertRaises(FleetIntakeError) as caught: self.session.refresh()
                self.assertNotIn("a" * 43, str(caught.exception)); self.assertEqual(self.session.deadline, 0)
        self.session.close()
        with self.assertRaises(FleetIntakeError): self.session.refresh()

    def test_review_does_not_accept_unknown_labels_or_approve_without_evidence(self):
        with patch("smartlabel.fleet_review.http.client.HTTPConnection") as factory:
            self.response(factory); self.session.refresh()
            for attributes in ({}, {"invented_label": "positive"}):
                with self.assertRaises(FleetIntakeError):
                    self.session.save(self.project, self.asset, "reviewed", "0" * 64, attributes=attributes)
            before = (self.root / "project.json").read_bytes()
            self.session.save(self.project, self.asset, "rejected", "0" * 64, attributes={}, other_abnormal="Not suitable")
            body = json.loads(factory.return_value.request.call_args.args[2])
            self.assertEqual(body["mutation"]["reviewStatus"], "rejected")
            self.assertFalse(self.session.data["trainAllowed"])
            self.assertEqual((self.root / "project.json").read_bytes(), before)
