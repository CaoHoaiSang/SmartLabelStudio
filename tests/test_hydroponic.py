from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from PIL import Image

from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydroponic import (
    CaptureManifestError,
    SLOT_IDS,
    apply_hydroponic_slot_template,
    describe_hydro_qa_issue,
    hydro_dataset_qa,
    import_capture_manifest,
    validate_capture_manifest,
    write_hydro_model_bundle,
)
from smartlabel.project_store import ProjectStore


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class HydroponicMvpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Cải ngọt slots", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.store.save(self.project)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_manifest(self, capture_id: str = "cap_001") -> Path:
        data_root = self.root / "camera_data"
        capture_dir = data_root / "captures" / "2026" / "08" / "20" / capture_id
        slot_dir = capture_dir / "slots"
        slot_dir.mkdir(parents=True)
        Image.new("RGB", (1920, 1080), "green").save(capture_dir / "full.jpg")
        Image.new("RGB", (1000, 400), "darkgreen").save(capture_dir / "upper_roi.jpg")
        Image.new("RGB", (1000, 400), "olive").save(capture_dir / "lower_roi.jpg")
        for index, slot_id in enumerate(SLOT_IDS):
            Image.new("RGB", (180, 300), (index * 20, 100, 40)).save(slot_dir / f"{slot_id}.jpg")
        prefix = f"captures/2026/08/20/{capture_id}"
        full_id = f"{capture_id}_full"
        assets = [{
            "assetId": full_id, "role": "full_frame", "relativePath": f"{prefix}/full.jpg",
            "sha256": sha256(capture_dir / "full.jpg"), "width": 1920, "height": 1080,
        }]
        roi_rects = {"upper": {"x": 100, "y": 100, "width": 1000, "height": 400}, "lower": {"x": 100, "y": 580, "width": 1000, "height": 400}}
        for rack in ("upper", "lower"):
            roi_id = f"{capture_id}_{rack}_roi"
            roi_path = capture_dir / f"{rack}_roi.jpg"
            assets.append({
                "assetId": roi_id, "role": "roi", "rackId": rack, "parentAssetId": full_id,
                "relativePath": f"{prefix}/{rack}_roi.jpg", "sha256": sha256(roi_path),
                "width": 1000, "height": 400, "rectInFullFrame": roi_rects[rack],
            })
        for index, slot_id in enumerate(SLOT_IDS):
            rack = "upper" if slot_id.startswith("upper") else "lower"
            position = index % 5
            slot_path = slot_dir / f"{slot_id}.jpg"
            assets.append({
                "assetId": f"{capture_id}_{slot_id}", "role": "slot", "slotId": slot_id, "rackId": rack,
                "parentAssetId": f"{capture_id}_{rack}_roi", "relativePath": f"{prefix}/slots/{slot_id}.jpg",
                "sha256": sha256(slot_path), "width": 180, "height": 300,
                "rectInFullFrame": {"x": 120 + position * 190, "y": 140 if rack == "upper" else 620, "width": 180, "height": 300},
                "quality": {"brightness": 100, "contrast": 20, "sharpness": 50},
            })
        manifest = {
            "schemaVersion": 1, "captureId": capture_id, "siteId": "site-1", "deviceId": "device001",
            "cropCycleId": "cai_ngot_2026-08-03", "cropCode": "cai_ngot", "capturedAt": "2026-08-20T00:00:00Z",
            "trigger": "scheduled", "cameraProfileId": "camera-1", "geometryProfileId": "geometry-1",
            "qualityStatus": "accepted", "assets": assets,
        }
        manifest_path = capture_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_project_v1_migrates_in_memory_and_saves_as_v2(self) -> None:
        payload = self.project.to_dict()
        payload["schema_version"] = 1
        for record in payload["images"]:
            for key in ("attributes", "metadata", "parent_asset_id", "asset_role", "lineage", "sha256"):
                record.pop(key, None)
        project_path = self.store.project_dir(self.project) / "project.json"
        project_path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = self.store.load(project_path)
        self.assertEqual(loaded.schema_version, 2)
        self.store.save(loaded)
        self.assertEqual(json.loads(project_path.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_manifest_import_checks_lineage_checksum_and_imports_only_ten_slots(self) -> None:
        manifest_path = self.create_manifest()
        manifest, resolved = validate_capture_manifest(manifest_path)
        self.assertEqual(len(resolved), 13)
        self.assertEqual(manifest["cropCode"], "cai_ngot")

        added, skipped = import_capture_manifest(self.store, self.project, manifest_path)
        self.assertEqual((added, skipped), (10, 0))
        self.assertEqual(len(self.project.images), 10)
        self.assertTrue(all(record.asset_role == "slot" for record in self.project.images))
        self.assertTrue(all(record.source_path == "" for record in self.project.images))
        self.assertEqual(len({record.metadata["plant_instance_id"] for record in self.project.images}), 10)
        for record in self.project.images:
            self.assertTrue((self.store.project_dir(self.project) / record.lineage["fullFrameRelativePath"]).is_file())
            self.assertTrue((self.store.project_dir(self.project) / record.lineage["roiRelativePath"]).is_file())
        with self.assertRaisesRegex(CaptureManifestError, "already imported"):
            import_capture_manifest(self.store, self.project, manifest_path)

        broken = json.loads(manifest_path.read_text(encoding="utf-8"))
        broken["assets"][-1]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(broken), encoding="utf-8")
        with self.assertRaisesRegex(CaptureManifestError, "checksum"):
            validate_capture_manifest(manifest_path)

    def test_import_rejects_project_crop_or_site_mismatch(self) -> None:
        manifest_path = self.create_manifest()
        self.project.metadata["siteId"] = "different-site"
        with self.assertRaisesRegex(CaptureManifestError, "siteId"):
            import_capture_manifest(self.store, self.project, manifest_path)
        self.project.metadata.pop("siteId")
        self.project.metadata["cropCode"] = "xa_lach"
        with self.assertRaisesRegex(CaptureManifestError, "cropCode"):
            import_capture_manifest(self.store, self.project, manifest_path)

    def test_image_level_export_excludes_uncertain_and_na_and_marks_single_cycle_pilot(self) -> None:
        import_capture_manifest(self.store, self.project, self.create_manifest())
        for index, record in enumerate(self.project.images):
            record.review_status = "reviewed"
            record.attributes["plant_presence"] = "present"
            record.attributes["yellow_leaf"] = "uncertain" if index == 0 else ("present" if index % 2 else "absent")
            record.attributes["wilt"] = "absent"
        self.store.save(self.project)
        manager = DatasetManager(self.store)
        exported = manager.export_classification(self.project, "yellow_leaf")
        metadata = json.loads((exported / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["classification_scope"], "image")
        self.assertEqual(metadata["validation_status"], "pilot_unvalidated")
        self.assertIn("uncertain", metadata["excluded_labels"])
        self.assertFalse((exported / "train" / "uncertain").exists())
        self.assertEqual(metadata["exported_crops"], 9)

    def test_hydro_qa_warns_instead_of_passing_an_empty_dataset(self) -> None:
        report = hydro_dataset_qa(self.project, self.store)

        self.assertEqual(report["images"], 0)
        issue = next(issue for issue in report["issues"] if issue["code"] == "empty_dataset")
        self.assertEqual(issue["severity"], "warning")
        self.assertEqual(issue["message"], "Dataset chưa có ảnh để kiểm tra.")
        self.assertEqual(report["validationStatus"], "pilot_unvalidated")

    def test_hydro_qa_issue_description_is_vietnamese_and_keeps_context(self) -> None:
        detail = describe_hydro_qa_issue({
            "code": "incomplete_capture_slots",
            "captureId": "capture-01",
            "missing": ["upper_05", "lower_05"],
            "duplicates": ["upper_01"],
        })

        self.assertIn("không đủ đúng 10 slot", detail)
        self.assertIn("capture capture-01", detail)
        self.assertIn("thiếu upper_05, lower_05", detail)
        self.assertIn("slot trùng upper_01", detail)

    def test_hydro_qa_and_bundle_are_portable_and_checksum_bound(self) -> None:
        import_capture_manifest(self.store, self.project, self.create_manifest())
        for index, record in enumerate(self.project.images):
            record.review_status = "reviewed"
            record.attributes["plant_presence"] = "absent" if index == 0 else "present"
            if index == 0:
                record.attributes["yellow_leaf"] = "not_applicable"
                record.attributes["wilt"] = "not_applicable"
            else:
                record.attributes["yellow_leaf"] = "present" if index % 2 else "absent"
                record.attributes["wilt"] = "absent" if index % 2 else "present"
        self.store.save(self.project)
        assignment = DatasetManager(self.store).ensure_split_assignment(self.project, force_rebalance=True)
        report = hydro_dataset_qa(self.project, self.store, assignment)
        self.assertEqual(report["validationStatus"], "pilot_unvalidated")
        self.assertFalse(any(issue["code"] == "absolute_source_path" for issue in report["issues"]))

        removed = self.project.images.pop()
        self.store.image_path(self.project, removed).unlink()
        incomplete = hydro_dataset_qa(self.project, self.store, assignment)
        self.assertTrue(any(issue["code"] == "incomplete_capture_slots" for issue in incomplete["issues"]))

        models = {}
        for key in ("plant_presence", "yellow_leaf", "wilt"):
            model = self.root / f"{key}.onnx"
            model.write_bytes((key + "-onnx-fixture").encode("ascii"))
            models[key] = model
        output = write_hydro_model_bundle(
            self.project, self.root / "bundle", models,
            {key: {"lowThreshold": 0.25, "highThreshold": 0.75} for key in models},
            dataset_version="dataset-v1", source_commit="abc123", camera_profile_ids=["camera-1"],
            geometry_profile_ids=["geometry-1"],
        )
        manifest = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["pipeline"], "fixed_slot_multilabel_v1")
        self.assertEqual(manifest["models"]["yellow_leaf"]["labels"], ["absent", "present"])
        self.assertGreater(manifest["labelDistribution"]["plant_presence"]["absent"], 0)
        self.assertFalse(any(Path(item["path"]).is_absolute() for item in manifest["models"].values()))

    def test_bundle_rejects_a_classifier_without_both_reviewed_labels(self) -> None:
        import_capture_manifest(self.store, self.project, self.create_manifest())
        models = {}
        for key in ("plant_presence", "yellow_leaf", "wilt"):
            model = self.root / f"{key}.onnx"
            model.write_bytes(key.encode("ascii"))
            models[key] = model
        with self.assertRaisesRegex(ValueError, "reviewed present and absent"):
            write_hydro_model_bundle(
                self.project, self.root / "invalid_bundle", models,
                {key: {"lowThreshold": 0.25, "highThreshold": 0.75} for key in models},
                dataset_version="dataset-v1", source_commit="abc123", camera_profile_ids=["camera-1"],
                geometry_profile_ids=["geometry-1"],
            )


if __name__ == "__main__":
    unittest.main()
