from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
import uuid

from smartlabel import fleet_intake
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore
from smartlabel.dataset_manager import DatasetManager


class FleetIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "workspace")
        self.project = self.store.create_project("Fleet fixture", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.store.save(self.project)
        self.root = self.store.project_dir(self.project)
        self.id = str(uuid.uuid4())
        self.folder = self.root / "fleet_inbox" / self.id
        self.folder.mkdir(parents=True)
        self.result = {"ok": True, "contributionId": self.id, "importId": "c" * 64, "projectId": self.project.id,
                       "stage": "review_pending", "trainAllowed": False, "fileCount": 0}
        self.manifest = {**self.result, "schemaVersion": "FleetProjectImportV1", "contribution": {"source": "phone"}, "files": []}
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        (self.folder / "custody.json").write_text(json.dumps({"importId": self.result["importId"]}))

    def test_list_is_metadata_only_does_not_modify_labels_and_withdrawn_is_hidden(self):
        before = (self.root / "project.json").read_bytes()
        rows = fleet_intake.list_staged(self.root, self.project.id)
        self.assertEqual(rows[0]["source"], "phone")
        self.assertEqual((self.root / "project.json").read_bytes(), before)
        self.assertEqual(self.project.images, [])
        (self.folder / "withdrawn.json").write_text("{}")
        self.assertEqual(fleet_intake.list_staged(self.root, self.project.id), [])

    def test_project_mismatch_and_wrong_contract_are_rejected(self):
        with self.assertRaises(fleet_intake.FleetIntakeError):
            fleet_intake.list_staged(self.root, "project_other")
        self.manifest["trainAllowed"] = True
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        with self.assertRaises(fleet_intake.FleetIntakeError):
            fleet_intake.list_staged(self.root, self.project.id)

    def test_only_fixed_loopback_native_request_and_verified_target_can_succeed(self):
        with patch.object(fleet_intake.http.client, "HTTPConnection") as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = json.dumps(self.result).encode()
            code = "FleetImportV1." + "a" * 43
            result = fleet_intake.receive(self.root, self.project.id, code)
            factory.assert_called_once_with("127.0.0.1", 17864, timeout=300)
            args = factory.return_value.request.call_args.args
            self.assertEqual(args[:2], ("POST", "/smartlabel/import"))
            self.assertEqual(json.loads(args[2])["projectId"], self.project.id)
            self.assertEqual(args[3]["X-Fleet-Client"], "SmartLabel")
            self.assertFalse(result["trainAllowed"])
            response.read.return_value = json.dumps({**self.result, "projectId": "project_wrong"}).encode()
            with self.assertRaises(fleet_intake.FleetIntakeError):
                fleet_intake.receive(self.root, self.project.id, code)
            factory.return_value.close.assert_called()

    def test_errors_do_not_leak_ticket_and_do_not_follow_redirects(self):
        code = "FleetImportV1." + "z" * 43
        with patch.object(fleet_intake.http.client, "HTTPConnection") as factory:
            response = factory.return_value.getresponse.return_value
            for status in (302, 403, 409, 500):
                response.status = status
                response.read.return_value = json.dumps({"error": code}).encode()
                with self.assertRaises(fleet_intake.FleetIntakeError) as caught:
                    fleet_intake.receive(self.root, self.project.id, code)
                self.assertNotIn(code, str(caught.exception))
        with self.assertRaises(fleet_intake.FleetIntakeError):
            fleet_intake.receive(self.root, self.project.id, "preview-ticket")

    def test_fleet_staging_is_not_a_dataset_version_or_split_source(self):
        (self.folder / "fixture.png").write_bytes(b"not a training image")
        manager = DatasetManager(self.store)
        version = manager.create_version(self.project, "Without Fleet staging")
        self.assertFalse(any("fleet_inbox" in str(file) for file in version.rglob("*")))
        self.assertFalse(any(file.suffix == ".png" for file in version.rglob("*")))
        self.assertEqual(self.store.load(self.project.id).images, [])

    def test_generic_import_cannot_bypass_staging_or_warehouse_custody(self):
        staged = self.folder / "fixture.png"
        staged.write_bytes(b"fixture not decoded")
        normal = Path(self.temp.name) / "normal.png"
        normal.write_bytes(b"must not be copied before the whole selection passes")
        before = (self.root / "project.json").read_bytes()
        for selection in ([normal, staged], [self.root / "fleet_inbox"], [self.store.workspace]):
            with self.assertRaises(fleet_intake.FleetIntakeError):
                self.store.import_images(self.project, selection)
        warehouse = Path(self.temp.name) / "company_store"
        warehouse.mkdir()
        (warehouse / ".fleet-storage-v1.json").write_text('{"schemaVersion":"FleetStorageV1"}')
        (warehouse / "fixture.png").write_bytes(b"fixture")
        with self.assertRaises(fleet_intake.FleetIntakeError):
            self.store.import_images(self.project, [warehouse])
        self.assertEqual((self.root / "project.json").read_bytes(), before)
        self.assertEqual(self.project.images, [])
        self.assertEqual(list((self.root / "images").iterdir()), [])
