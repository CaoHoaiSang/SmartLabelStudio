from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
import json
import hashlib
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydroponic import (
    CaptureManifestError,
    CaptureRepairConfirmationRequired,
    SLOT_IDS,
    apply_hydroponic_slot_template,
    describe_hydro_qa_issue,
    hydro_dataset_qa,
    import_capture_dataset_archive,
    import_capture_manifest,
    validate_capture_manifest,
    write_hydro_model_bundle,
)
from smartlabel.project_store import ProjectStore
from tools.hydro_pipeline_smoke import crop_context_for_timestamp


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

    def test_pipeline_smoke_entrypoint_loads_from_repository_root(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/hydro_pipeline_smoke.py", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hydro SmartLabel", result.stdout)

    def test_pipeline_smoke_recomputes_crop_context_for_generated_timestamp(self) -> None:
        context = crop_context_for_timestamp(
            {
                "cropDisplayName": "Cải ngọt cọng xanh",
                "sowingDate": "2026-08-03",
                "nftStartDate": "2026-08-19",
                "timezone": "Asia/Bangkok",
                "localDate": "2026-09-05",
                "daysAfterSowing": 33,
                "daysAfterNft": 17,
            },
            datetime.fromisoformat("2026-09-06T18:30:00+00:00"),
        )

        self.assertEqual(context["localDate"], "2026-09-07")
        self.assertEqual(context["daysAfterSowing"], 35)
        self.assertEqual(context["daysAfterNft"], 19)

    def test_hydro_template_accepts_a_portable_crop_identity(self) -> None:
        project = self.store.create_project("Xà lách slots", task="classify")
        apply_hydroponic_slot_template(
            project, crop_code="xa_lach", crop_display_name="Xà lách Romaine",
        )
        self.assertEqual(project.metadata["cropCode"], "xa_lach")
        self.assertEqual(project.metadata["cropDisplayName"], "Xà lách Romaine")
        self.assertEqual(project.attribute_settings["plant_presence"]["title"], "Có Xà lách Romaine trong rọ")
        with self.assertRaisesRegex(ValueError, "cropCode"):
            apply_hydroponic_slot_template(project, crop_code="Xà lách", crop_display_name="Xà lách")

    def create_manifest(self, capture_id: str = "cap_001") -> Path:
        data_root = self.root / "camera_data"
        capture_dir = data_root / "captures" / "2026" / "08" / "20" / capture_id
        slot_dir = capture_dir / "slots"
        slot_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), "green").save(capture_dir / "full.jpg")
        Image.new("RGB", (1000, 400), "darkgreen").save(capture_dir / "upper_roi.jpg")
        Image.new("RGB", (1000, 400), "olive").save(capture_dir / "lower_roi.jpg")
        capture_color = (sum(capture_id.encode("utf-8")) % 180) + 40
        for index, slot_id in enumerate(SLOT_IDS):
            Image.new("RGB", (180, 300), (index * 20, 100, capture_color)).save(slot_dir / f"{slot_id}.jpg")
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
            "cropContext": {
                "cropDisplayName": "Cải ngọt cọng xanh", "sowingDate": "2026-08-03",
                "nftStartDate": "2026-08-19", "timezone": "Asia/Bangkok",
                "localDate": "2026-08-20", "daysAfterSowing": 17, "daysAfterNft": 1,
            },
            "datasetReview": {"status": "approved", "reason": None, "note": ""},
        }
        manifest_path = capture_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def create_dataset_archive(
        self,
        capture_ids: list[str],
        *,
        extra_file: bool = False,
        review_status: str = "approved",
        corrected_sowing_date: str | None = None,
    ) -> Path:
        manifests = [self.create_manifest(capture_id) for capture_id in capture_ids]
        if review_status != "approved":
            for manifest_path in manifests:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["datasetReview"]["status"] = review_status
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rows = []
        crop_cycles = set()
        camera_profiles = set()
        geometry_profiles = set()
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative_manifest = manifest_path.relative_to(self.root / "camera_data").as_posix()
            rows.append({
                "captureId": manifest["captureId"],
                "capturedAt": manifest["capturedAt"],
                "trigger": manifest["trigger"],
                "cropCycleId": manifest["cropCycleId"],
                "manifestPath": relative_manifest,
                "manifestSha256": sha256(manifest_path),
                "slotCount": 10,
            })
            if corrected_sowing_date:
                rows[-1]["effectiveCropContext"] = {
                    **manifest["cropContext"],
                    "sowingDate": corrected_sowing_date,
                    "daysAfterSowing": 18,
                }
                rows[-1]["cropContextCorrectionIds"] = ["crop_cycle_correction_test"]
            crop_cycles.add(manifest["cropCycleId"])
            camera_profiles.add(manifest["cameraProfileId"])
            geometry_profiles.add(manifest["geometryProfileId"])
        index = {
            "kind": "HydroDatasetExportV1",
            "schemaVersion": 1,
            "datasetExportId": "hydro_export_test_01",
            "createdAt": "2026-08-26T00:00:00Z",
            "deviceId": "device001",
            "siteId": "site-1",
            "cropCode": "cai_ngot",
            "captureCount": len(rows),
            "slotImageCount": len(rows) * 10,
            "cropCycleIds": sorted(crop_cycles),
            "cameraProfileIds": sorted(camera_profiles),
            "geometryProfileIds": sorted(geometry_profiles),
            "captures": rows,
        }
        if corrected_sowing_date:
            index["cropCycle"] = {
                "cropCycleId": "cai_ngot_2026-08-03",
                "cropCode": "cai_ngot",
                "cropDisplayName": "Cải ngọt cọng xanh",
                "sowingDate": corrected_sowing_date,
                "nftStartDate": "2026-08-19",
            }
            index["cropCycleCorrections"] = [{
                "correctionId": "crop_cycle_correction_test",
                "cropCycleId": "cai_ngot_2026-08-03",
                "kind": "sowing_date_shift",
                "correctedAt": "2026-08-27T00:00:00Z",
            }]
        archive_path = self.root / "hydro_dataset.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as package:
            package.writestr("dataset-export.json", json.dumps(index))
            for manifest_path in manifests:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                package.write(manifest_path, manifest_path.relative_to(self.root / "camera_data").as_posix())
                for asset in manifest["assets"]:
                    source = self.root / "camera_data" / Path(*asset["relativePath"].split("/"))
                    package.write(source, asset["relativePath"])
            if extra_file:
                package.writestr("unexpected.txt", "not part of the dataset contract")
        return archive_path

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
        self.assertTrue(all(record.metadata["daysAfterSowing"] == 17 for record in self.project.images))
        self.assertTrue(all(record.metadata["daysAfterNft"] == 1 for record in self.project.images))
        self.assertTrue(all(record.metadata["datasetReviewStatus"] == "approved" for record in self.project.images))
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

    def test_dataset_archive_imports_multiple_approved_captures_and_is_idempotent(self) -> None:
        archive_path = self.create_dataset_archive(["cap_archive_01", "cap_archive_02"])

        result = import_capture_dataset_archive(self.store, self.project, archive_path)

        self.assertEqual(result["capturesImported"], 2)
        self.assertEqual(result["capturesSkipped"], 0)
        self.assertEqual(result["slotImagesImported"], 20)
        self.assertEqual(len(self.project.images), 20)
        self.assertEqual({r.import_batch for r in self.project.images}, {self.project.last_import_batch})
        original_batch = self.project.last_import_batch
        self.assertEqual({record.metadata["captureId"] for record in self.project.images}, {"cap_archive_01", "cap_archive_02"})
        self.assertTrue(all(record.metadata["datasetReviewStatus"] == "approved" for record in self.project.images))
        repeated = import_capture_dataset_archive(self.store, self.project, archive_path)
        self.assertEqual(repeated["capturesImported"], 0)
        self.assertEqual(repeated["capturesSkipped"], 2)
        self.assertEqual(repeated["slotImagesImported"], 0)
        self.assertEqual(self.project.last_import_batch, original_batch)
        self.assertEqual(len(self.project.images), 20)

    def test_archive_defaults_seed_new_images_but_do_not_approve_or_relabel_existing(self):
        import copy
        archive = self.create_dataset_archive(["cap_defaults"])
        for key, value in {"plant_presence": "present", "yellow_leaf": "absent", "wilt": "present"}.items():
            self.project.attribute_settings[key]["default"] = value
        import_capture_dataset_archive(self.store, self.project, archive)
        for record in self.project.images:
            self.assertEqual(record.attributes, {"plant_presence": "present", "yellow_leaf": "absent", "wilt": "present"})
            self.assertEqual(record.review_status, "unlabeled")
        with self.assertRaises(ValueError):
            DatasetManager(self.store).export_classification(self.project, "yellow_leaf")
        self.project.images[0].review_status = "reviewed"
        before = copy.deepcopy(self.project.images)
        self.project.attribute_settings["yellow_leaf"]["default"] = "present"
        repeated = import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(repeated["capturesSkipped"], 1)
        self.assertEqual(self.project.images, before)

    def test_archive_delete_all_and_reimport_keeps_parent_evidence(self):
        archive = self.create_dataset_archive(["cap_restore_1", "cap_restore_2"])
        import_capture_dataset_archive(self.store, self.project, archive)
        parents = {p: p.read_bytes() for p in (self.store.project_dir(self.project) / "assets").rglob("*") if p.is_file()}
        from smartlabel.frame_filter import latest_import_records
        removed, _ = self.store.delete_images(self.project, latest_import_records(self.project))
        self.assertEqual(removed, 20)
        self.assertEqual(len(self.project.images), 0)
        result = import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(result["slotImagesImported"], 20)
        self.assertTrue(all(p.read_bytes() == data for p, data in parents.items()))

    def test_reimport_rejects_changed_parent_and_does_not_remove_evidence(self):
        archive = self.create_dataset_archive(["cap_conflict"])
        import_capture_dataset_archive(self.store, self.project, archive)
        self.store.delete_images(self.project, list(self.project.images))
        parent = self.store.project_dir(self.project) / "assets" / "cap_conflict" / "full.jpg"
        parent.write_bytes(b"different old evidence")
        with self.assertRaisesRegex(CaptureManifestError, "differs; kept unchanged"):
            import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(parent.read_bytes(), b"different old evidence")
        self.assertEqual(self.project.images, [])

    def test_last_archive_batch_excludes_preexisting_capture(self):
        first = self.create_dataset_archive(["cap_preexisting"])
        import_capture_dataset_archive(self.store, self.project, first)
        old_ids = {r.id for r in self.project.images}
        second = self.create_dataset_archive(["cap_preexisting", "cap_new"])
        import_capture_dataset_archive(self.store, self.project, second)
        from smartlabel.frame_filter import latest_import_records
        latest = latest_import_records(self.project)
        self.assertEqual(len(latest), 10)
        self.assertFalse(old_ids.intersection(r.id for r in latest))

    def test_partial_capture_requires_confirmation_then_preserves_existing_labels(self):
        archive = self.create_dataset_archive(["cap_repair"])
        import_capture_dataset_archive(self.store, self.project, archive)
        kept = self.project.images[0]
        kept.attributes = {"plant_presence": "present", "yellow_leaf": "present", "wilt": "absent"}
        kept.review_status = "reviewed"
        self.store.delete_images(self.project, self.project.images[-3:])
        before = [record.to_dict() for record in self.project.images]
        project_file = self.store.project_dir(self.project) / "project.json"
        disk_before = project_file.read_bytes()
        with self.assertRaises(CaptureRepairConfirmationRequired) as pending:
            import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(pending.exception.plan["slotImages"], 3)
        self.assertEqual(project_file.read_bytes(), disk_before)
        self.assertEqual([r.to_dict() for r in self.project.images], before)
        result = import_capture_dataset_archive(self.store, self.project, archive,
            confirmed_repair_digest=pending.exception.plan["digest"])
        self.assertEqual(result["capturesRepaired"], 1)
        self.assertEqual(result["slotImagesImported"], 3)
        self.assertEqual([r.to_dict() for r in self.project.images[:7]], before)
        self.assertTrue(all(r.review_status == "unlabeled" for r in self.project.images[7:]))
        self.assertEqual(len({r.metadata["assetId"] for r in self.project.images}), 10)
        from smartlabel.frame_filter import latest_import_records
        self.assertEqual(len(latest_import_records(self.project)), 3)
        self.assertEqual(import_capture_dataset_archive(self.store, self.project, archive)["slotImagesImported"], 0)

    def test_stale_repair_confirmation_requires_new_preview_before_importing_anything(self):
        archive = self.create_dataset_archive(["cap_stale_plan", "cap_other"])
        import_capture_dataset_archive(self.store, self.project, archive)
        self.store.delete_images(self.project, [self.project.images[0]])
        with self.assertRaises(CaptureRepairConfirmationRequired) as pending:
            import_capture_dataset_archive(self.store, self.project, archive)
        self.store.delete_images(self.project, [self.project.images[0]])
        with self.assertRaises(CaptureRepairConfirmationRequired) as updated:
            import_capture_dataset_archive(self.store, self.project, archive,
                confirmed_repair_digest=pending.exception.plan["digest"])
        self.assertEqual(updated.exception.plan["slotImages"], 2)
        self.assertEqual(len(self.project.images), 18)

    def test_repair_save_failure_rolls_back_new_files_and_keeps_existing_records(self):
        archive = self.create_dataset_archive(["cap_io_failure"])
        import_capture_dataset_archive(self.store, self.project, archive)
        self.store.delete_images(self.project, self.project.images[-2:])
        before = self.project.to_dict()
        folder = self.store.project_dir(self.project)
        before_files = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
        with self.assertRaises(CaptureRepairConfirmationRequired) as pending:
            import_capture_dataset_archive(self.store, self.project, archive)
        with patch.object(self.store, "save", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                import_capture_dataset_archive(self.store, self.project, archive,
                    confirmed_repair_digest=pending.exception.plan["digest"])
        self.assertEqual(self.project.to_dict(), before)
        self.assertEqual({p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}, before_files)

    def test_repair_never_overwrites_corrupt_existing_image_or_geometry(self):
        archive = self.create_dataset_archive(["cap_tampered"])
        import_capture_dataset_archive(self.store, self.project, archive)
        self.store.delete_images(self.project, self.project.images[-1:])
        kept = self.project.images[0]
        kept.lineage["rectInFullFrame"]["x"] += 1
        with self.assertRaisesRegex(CaptureManifestError, "Geometry"):
            import_capture_dataset_archive(self.store, self.project, archive)
        kept.lineage["rectInFullFrame"]["x"] -= 1
        image = self.store.image_path(self.project, kept)
        image.write_bytes(b"existing corrupt evidence")
        with self.assertRaisesRegex(CaptureManifestError, "file"):
            import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(image.read_bytes(), b"existing corrupt evidence")
        self.assertEqual(len(self.project.images), 9)

    def legacy_context_archive(self, *, cycle_id="cai_ngot_2026-08-03", sowing_date="2026-08-03", remove_context=True):
        archive = self.create_dataset_archive(["cap_legacy_context"])
        with zipfile.ZipFile(archive) as package:
            files = {name: package.read(name) for name in package.namelist()}
        index = json.loads(files["dataset-export.json"])
        index["cropCycle"] = {"cropCycleId": cycle_id, "cropCode": "cai_ngot",
            "cropDisplayName": "Cải ngọt cọng xanh", "sowingDate": sowing_date, "nftStartDate": "2026-08-19"}
        index["cropCycleCorrections"] = []
        if remove_context:
            for row in index["captures"]:
                manifest = json.loads(files[row["manifestPath"]]); manifest.pop("cropContext", None)
                files[row["manifestPath"]] = json.dumps(manifest).encode()
                row["manifestSha256"] = hashlib.sha256(files[row["manifestPath"]]).hexdigest()
        files["dataset-export.json"] = json.dumps(index).encode()
        with zipfile.ZipFile(archive, "w") as package:
            for name, data in files.items(): package.writestr(name, data)
        return archive

    def test_legacy_crop_context_uses_bundled_cycle_without_rewriting_original(self):
        archive = self.legacy_context_archive()
        archive_sha = sha256(archive)
        import_capture_dataset_archive(self.store, self.project, archive)
        metadata = self.project.images[0].metadata
        self.assertEqual(metadata["sowingDate"], "2026-08-03")
        self.assertEqual(metadata["daysAfterSowing"], 17)
        self.assertEqual(metadata["daysAfterNft"], 1)
        self.assertEqual(metadata["cropContextSource"], "dataset_crop_cycle")
        self.assertIsNone(metadata["originalSowingDate"])
        self.assertEqual(metadata["cropContextCorrectionIds"], [])
        self.assertEqual(sha256(archive), archive_sha)

    def test_legacy_crop_context_repairs_missing_metadata_preserving_labels(self):
        archive = self.legacy_context_archive()
        import_capture_dataset_archive(self.store, self.project, archive)
        for record in self.project.images:
            for key in ("cropDisplayName", "captureLocalDate", "sowingDate", "nftStartDate", "daysAfterSowing", "daysAfterNft", "timezone", "cropContextSource", "originalSowingDate"):
                record.metadata.pop(key, None)
        record = self.project.images[0]
        record.metadata["sowingDate"] = "2026-08-03"  # Earlier partial enrichment is not an original manifest value.
        record.attributes["plant_presence"] = "present"  # Synthetic fixture, not a user's plant label.
        record.review_status = "reviewed"
        self.store.save(self.project)
        result = import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(result["capturesMetadataUpdated"], 1)
        self.assertEqual(record.attributes["plant_presence"], "present")
        self.assertEqual(record.review_status, "reviewed")
        self.assertEqual(record.metadata["daysAfterSowing"], 17)
        self.assertIsNone(record.metadata["originalSowingDate"])
        repeated = import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(repeated["capturesMetadataUpdated"], 0)

    def test_legacy_crop_context_rejects_wrong_cycle_or_invalid_dates_before_writes(self):
        for options in ({"cycle_id": "other_cycle"}, {"sowing_date": "not-a-date"}, {"sowing_date": "2026-09-03"}):
            with self.subTest(options=options), self.assertRaises(CaptureManifestError):
                import_capture_dataset_archive(self.store, self.project, self.legacy_context_archive(**options))
            self.assertEqual(self.project.images, [])

    def test_legacy_crop_context_never_overrides_recorded_manifest_dates(self):
        archive = self.legacy_context_archive(sowing_date="2026-08-02", remove_context=False)
        import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual(self.project.images[0].metadata["sowingDate"], "2026-08-03")
        self.assertEqual(self.project.images[0].metadata["originalSowingDate"], "2026-08-03")

    def test_legacy_crop_context_conflict_or_save_failure_preserves_existing_metadata(self):
        archive = self.legacy_context_archive()
        import_capture_dataset_archive(self.store, self.project, archive)
        first, last = self.project.images[0], self.project.images[-1]
        first.metadata["sowingDate"] = None
        last.metadata["sowingDate"] = "2026-08-01"
        before = [dict(record.metadata) for record in self.project.images]
        with self.assertRaisesRegex(CaptureManifestError, "conflicts"):
            import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual([record.metadata for record in self.project.images], before)
        last.metadata["sowingDate"] = "2026-08-03"
        before = [dict(record.metadata) for record in self.project.images]
        with patch.object(self.store, "save", side_effect=OSError("disk unavailable")), self.assertRaises(OSError):
            import_capture_dataset_archive(self.store, self.project, archive)
        self.assertEqual([record.metadata for record in self.project.images], before)

    def test_dataset_archive_applies_audited_crop_context_correction_without_rewriting_manifest(self) -> None:
        initial_archive = self.create_dataset_archive(["cap_archive_corrected"])
        initial_result = import_capture_dataset_archive(self.store, self.project, initial_archive)
        self.assertEqual(initial_result["capturesImported"], 1)
        self.assertTrue(all(record.metadata["sowingDate"] == "2026-08-03" for record in self.project.images))

        archive_path = self.create_dataset_archive(["cap_archive_corrected"], corrected_sowing_date="2026-08-02")

        result = import_capture_dataset_archive(self.store, self.project, archive_path)

        self.assertEqual(result["capturesImported"], 0)
        self.assertEqual(result["capturesSkipped"], 1)
        self.assertEqual(result["capturesMetadataUpdated"], 1)
        self.assertTrue(all(record.metadata["sowingDate"] == "2026-08-02" for record in self.project.images))
        self.assertTrue(all(record.metadata["daysAfterSowing"] == 18 for record in self.project.images))
        self.assertTrue(all(record.metadata["originalSowingDate"] == "2026-08-03" for record in self.project.images))
        self.assertTrue(all(record.metadata["cropContextCorrectionIds"] == ["crop_cycle_correction_test"] for record in self.project.images))

        with zipfile.ZipFile(archive_path) as package:
            index = json.loads(package.read("dataset-export.json"))
            original_manifest = json.loads(package.read(index["captures"][0]["manifestPath"]))
        self.assertEqual(original_manifest["cropContext"]["sowingDate"], "2026-08-03")

        repeated = import_capture_dataset_archive(self.store, self.project, archive_path)
        self.assertEqual(repeated["capturesImported"], 0)
        self.assertEqual(repeated["capturesMetadataUpdated"], 0)

    def test_dataset_archive_rejects_unapproved_unsafe_or_unexpected_content_before_import(self) -> None:
        pending_archive = self.create_dataset_archive(["cap_archive_pending"], review_status="pending")
        with self.assertRaisesRegex(CaptureManifestError, "not approved"):
            import_capture_dataset_archive(self.store, self.project, pending_archive)
        self.assertEqual(self.project.images, [])

        unexpected_archive = self.create_dataset_archive(["cap_archive_extra"], extra_file=True)
        with self.assertRaisesRegex(CaptureManifestError, "file list is inconsistent"):
            import_capture_dataset_archive(self.store, self.project, unexpected_archive)
        self.assertEqual(self.project.images, [])

        unsafe_archive = self.root / "unsafe_dataset.zip"
        with zipfile.ZipFile(unsafe_archive, "w") as package:
            package.writestr("dataset-export.json", "{}")
            package.writestr("../outside.txt", "blocked")
        with self.assertRaisesRegex(CaptureManifestError, "unsafe archive member"):
            import_capture_dataset_archive(self.store, self.project, unsafe_archive)
        self.assertEqual(self.project.images, [])

    def test_manifest_import_rejects_excluded_capture_or_inconsistent_crop_age(self) -> None:
        excluded_path = self.create_manifest("cap_excluded")
        excluded = json.loads(excluded_path.read_text(encoding="utf-8"))
        excluded["datasetReview"] = {"status": "excluded", "reason": "blur", "note": ""}
        excluded_path.write_text(json.dumps(excluded), encoding="utf-8")
        with self.assertRaisesRegex(CaptureManifestError, "excluded"):
            validate_capture_manifest(excluded_path)

        age_path = self.create_manifest("cap_bad_age")
        bad_age = json.loads(age_path.read_text(encoding="utf-8"))
        bad_age["cropContext"]["daysAfterSowing"] = 99
        age_path.write_text(json.dumps(bad_age), encoding="utf-8")
        with self.assertRaisesRegex(CaptureManifestError, "daysAfterSowing"):
            validate_capture_manifest(age_path)

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
        self.assertEqual(report["pilotReadiness"]["status"], "empty_dataset")
        self.assertFalse(report["pilotReadiness"]["shadowBundleReady"])

    def test_hydro_qa_issue_description_is_vietnamese_and_keeps_context(self) -> None:
        detail = describe_hydro_qa_issue({
            "code": "incomplete_capture_slots",
            "captureId": "capture-01",
            "missing": ["upper_05", "lower_05"],
            "duplicates": ["upper_01"],
        })

        self.assertIn("thiếu hoặc trùng rọ", detail)
        self.assertIn("capture capture-01", detail)
        self.assertIn("thiếu upper_05, lower_05", detail)
        self.assertIn("slot trùng upper_01", detail)

    def test_hydro_qa_still_blocks_duplicate_slots_and_links_a_record(self) -> None:
        import_capture_manifest(self.store, self.project, self.create_manifest())
        self.project.images[1].metadata["slotId"] = self.project.images[0].metadata["slotId"]

        report = hydro_dataset_qa(self.project, self.store)

        duplicate = next(issue for issue in report["issues"]
                         if issue["code"] == "incomplete_capture_slots")
        self.assertEqual(duplicate["severity"], "error")
        self.assertEqual(duplicate["duplicates"], ["upper_01"])
        self.assertTrue(duplicate["imageId"])

    def test_hydro_training_readiness_does_not_count_validation_or_test_labels(self) -> None:
        import_capture_manifest(self.store, self.project, self.create_manifest())
        for index, record in enumerate(self.project.images):
            record.review_status = "reviewed"
            record.attributes["plant_presence"] = "absent" if index == 0 else "present"
            for key in ("yellow_leaf", "wilt"):
                record.attributes[key] = "not_applicable" if index == 0 else ("present" if index % 2 else "absent")
        # Both classes exist globally and in validation, but the one training
        # plant has only positive labels. Holdout/unassigned rows cannot fix it.
        groups = [str(record.metadata["plant_instance_id"]) for record in self.project.images]
        for other_split in ("val", "test", None):
            with self.subTest(other_split=other_split):
                assignment = {group: other_split for group in groups}
                assignment[groups[1]] = "train"
                report = hydro_dataset_qa(self.project, self.store, {"groups": assignment})
                readiness = report["pilotReadiness"]
                self.assertEqual(readiness["status"], "class_pair_incomplete")
                self.assertFalse(readiness["shadowBundleReady"])
                for model in readiness["models"].values():
                    self.assertEqual(model["reviewedTrainable"], {"present": 1, "absent": 0})
                    self.assertFalse(model["workflowTrainable"])

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
        self.assertTrue(all(
            item["workflowTrainable"]
            for item in report["pilotReadiness"]["models"].values()
        ))
        self.assertFalse(any(issue["code"] == "absolute_source_path" for issue in report["issues"]))

        removed = self.project.images.pop()
        self.store.image_path(self.project, removed).unlink()
        incomplete = hydro_dataset_qa(self.project, self.store, assignment)
        excluded = [issue for issue in incomplete["issues"] if issue["code"] == "capture_slots_excluded"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["severity"], "warning")
        self.assertTrue(excluded[0]["imageId"])

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
        self.assertTrue(manifest["bundleId"].startswith("hydro_cai_ngot_"))
        self.assertEqual(manifest["cropCode"], "cai_ngot")
        self.assertEqual(manifest["pipeline"], "fixed_slot_multilabel_v1")
        self.assertEqual(manifest["runtimeTarget"], "jetson_nano_tensorrt_fp16")
        self.assertEqual(manifest["deploymentMode"], "shadow")
        self.assertEqual(manifest["models"]["yellow_leaf"]["labels"], ["absent", "present"])
        self.assertEqual(manifest["models"]["yellow_leaf"]["resizeMode"], "short_side_center_crop")
        self.assertGreater(manifest["labelDistribution"]["plant_presence"]["absent"], 0)
        self.assertFalse(any(Path(item["path"]).is_absolute() for item in manifest["models"].values()))
        self.assertTrue(output.with_suffix(".zip").is_file())
        with zipfile.ZipFile(output.with_suffix(".zip")) as package:
            self.assertEqual(
                sorted(package.namelist()),
                ["bundle.json", "models/plant_presence.onnx", "models/wilt.onnx", "models/yellow_leaf.onnx"],
            )

        windows_output = write_hydro_model_bundle(
            self.project, self.root / "windows_bundle", models,
            {key: {"lowThreshold": 0.25, "highThreshold": 0.75} for key in models},
            dataset_version="dataset-v1", source_commit="abc123", camera_profile_ids=["camera-1"],
            geometry_profile_ids=["geometry-1"], runtime_target="windows_onnxruntime_cpu",
        )
        windows_manifest = json.loads((windows_output / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(windows_manifest["runtimeTarget"], "windows_onnxruntime_cpu")
        self.assertEqual(windows_manifest["deploymentMode"], "shadow")
        self.assertNotIn("minimumTensorRTVersion", windows_manifest)
        with self.assertRaisesRegex(ValueError, "independent validated holdout"):
            write_hydro_model_bundle(
                self.project, self.root / "unsafe_windows_bundle", models,
                {key: {"lowThreshold": 0.25, "highThreshold": 0.75} for key in models},
                dataset_version="dataset-v1", source_commit="abc123", camera_profile_ids=["camera-1"],
                geometry_profile_ids=["geometry-1"], runtime_target="windows_onnxruntime_cpu",
                deployment_mode="operational",
            )

        self.project.metadata["cropCode"] = "xa_lach"
        self.project.metadata["cropDisplayName"] = "Xà lách Romaine"
        custom_output = write_hydro_model_bundle(
            self.project, self.root / "custom_crop_bundle", models,
            {key: {"lowThreshold": 0.25, "highThreshold": 0.75} for key in models},
            dataset_version="dataset-v1", source_commit="abc123", camera_profile_ids=["camera-1"],
            geometry_profile_ids=["geometry-1"],
        )
        custom_manifest = json.loads((custom_output / "bundle.json").read_text(encoding="utf-8"))
        self.assertTrue(custom_manifest["bundleId"].startswith("hydro_xa_lach_"))
        self.assertEqual(custom_manifest["cropCode"], "xa_lach")

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
