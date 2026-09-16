import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image
from smartlabel.hydroponic import (apply_hydroponic_slot_template, import_capture_manifest,
    import_capture_dataset_archive, validate_capture_manifest, hydro_dataset_qa,
    write_hydro_model_bundle, CaptureManifestError, CaptureRepairConfirmationRequired)
from smartlabel.project_store import ProjectStore
from smartlabel.hydro_topology import topology_slots


def capture_v2(root, counts=(5, 7, 6)):
    capture_id = "cap_variable_test"
    prefix = "captures/2026/09/08/" + capture_id
    folder = root / prefix; folder.mkdir(parents=True)
    views = [{"viewId": "tube_%d" % i, "rackId": "rack_%d" % i,
              "slotIds": ["tube_%d_%02d" % (i, j + 1) for j in range(count)]} for i, count in enumerate(counts, 1)]
    assets = []
    def asset(role, name, size, **metadata):
        path = folder / (name + ".jpg"); path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (len(assets) * 7 % 240, 120, 60)).save(path)
        assets.append({"assetId": capture_id + "_" + name.replace("/", "_"), "role": role,
            "relativePath": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": size[0], "height": size[1], **metadata})
        return assets[-1]
    full = asset("full_frame", "full", (1920, 1080))
    for i, view in enumerate(views):
        rect = {"x": 0, "y": i * 300, "width": 1900, "height": 280}
        lineage = {"rackId": view["viewId"], "viewId": view["viewId"], "actualRackId": view["rackId"]}
        roi = asset("roi", view["viewId"] + "_roi", (1900, 280), parentAssetId=full["assetId"], rectInFullFrame=rect, **lineage)
        for j, slot in enumerate(view["slotIds"]):
            asset("slot", "slots/" + slot, (150, 200), slotId=slot, parentAssetId=roi["assetId"],
                rectInFullFrame={"x": j * 200, "y": i * 300 + 20, "width": 150, "height": 200}, **lineage)
    manifest = {"schemaVersion": 2, "topology": {"views": views}, "views": views,
        "captureId": capture_id, "siteId": "site_1", "deviceId": "device001", "cropCycleId": "cai_ngot_2026-08-03",
        "cropCode": "cai_ngot", "cameraProfileId": "camera_1", "geometryProfileId": "geometry_2",
        "capturedAt": "2026-09-08T00:00:00Z", "trigger": "scheduled", "bindingId": "binding_1", "bindingRevision": 2,
        "qualityStatus": "accepted", "datasetReview": {"status": "approved"}, "assets": assets}
    path = folder / "manifest.json"; path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


class HydroTopologyV2Tests(unittest.TestCase):
    def test_variable_manifest_import_qa_and_model_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path, manifest = capture_v2(root)
            store = ProjectStore(root / "workspace"); project = store.create_project("Variable tubes", task="classify")
            apply_hydroponic_slot_template(project)
            self.assertEqual(import_capture_manifest(store, project, path), (18, 0))
            self.assertEqual(project.images[-1].metadata["plant_instance_id"], "cai_ngot_2026-08-03:rack_3:6")
            for i, record in enumerate(project.images):
                record.review_status = "reviewed"
                record.attributes = {"plant_presence": "absent" if i % 3 == 0 else "present",
                    "yellow_leaf": "not_applicable" if i % 3 == 0 else "present" if i % 3 == 1 else "absent",
                    "wilt": "not_applicable" if i % 3 == 0 else "present" if i % 3 == 1 else "absent"}
            store.save(project)
            report = hydro_dataset_qa(project, store)
            self.assertFalse(any(issue["code"] in {"incomplete_capture_slots", "capture_topology_invalid"} for issue in report["issues"]))
            models = {}
            for key in ("plant_presence", "yellow_leaf", "wilt"):
                models[key] = root / (key + ".onnx"); models[key].write_bytes(b"test-only-not-a-real-model")
            output = write_hydro_model_bundle(project, root / "bundle", models,
                {key: {"lowThreshold": .3, "highThreshold": .7} for key in models},
                dataset_version="fixture", source_commit="test", camera_profile_ids=["camera_1"], geometry_profile_ids=["geometry_2"])
            bundle = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle["schemaVersion"], 2)
            self.assertEqual(bundle["pipeline"], "fixed_slot_multilabel_v2")
            project.images.pop()
            excluded = [issue for issue in hydro_dataset_qa(project, store)["issues"]
                        if issue["code"] == "capture_slots_excluded"]
            self.assertEqual(len(excluded), 1)
            self.assertEqual(excluded[0]["severity"], "warning")
            self.assertTrue(excluded[0]["imageId"])
            manifest["assets"][-1]["rackId"] = "tube_1"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(CaptureManifestError): validate_capture_manifest(path)

    def test_variable_zip_counts_idempotency_and_no_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path, manifest = capture_v2(root)
            index = {"kind": "HydroDatasetExportV2", "schemaVersion": 2, "datasetExportId": "export_fixture", "createdAt": manifest["capturedAt"],
                **{k: manifest[k] for k in ("siteId", "deviceId", "cropCode")}, "captureCount": 1, "slotImageCount": 18,
                "cropCycleIds": [manifest["cropCycleId"]], "cameraProfileIds": [manifest["cameraProfileId"]], "geometryProfileIds": [manifest["geometryProfileId"]],
                "captures": [{**{k: manifest[k] for k in ("captureId", "capturedAt", "trigger", "cropCycleId")},
                    "manifestPath": path.relative_to(root).as_posix(), "manifestSha256": hashlib.sha256(path.read_bytes()).hexdigest(), "slotCount": len(topology_slots(manifest))}]}
            archive_path = root / "dataset.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("dataset-export.json", json.dumps(index))
                archive.write(path, path.relative_to(root).as_posix())
                for asset in manifest["assets"]: archive.write(root / asset["relativePath"], asset["relativePath"])
            store = ProjectStore(root / "workspace"); project = store.create_project("ZIP", task="classify")
            apply_hydroponic_slot_template(project)
            import_capture_dataset_archive(store, project, archive_path)
            import_capture_dataset_archive(store, project, archive_path)
            self.assertEqual(len(project.images), 18)
            self.assertTrue(all(not record.source_path for record in project.images))
            # Three unequal tubes (5/7/6), not a fixed ten-slot repair path.
            kept_before = [r.to_dict() for r in project.images if r not in (project.images[4], project.images[11], project.images[17])]
            store.delete_images(project, [project.images[4], project.images[11], project.images[17]])
            with self.assertRaises(CaptureRepairConfirmationRequired) as pending:
                import_capture_dataset_archive(store, project, archive_path)
            self.assertEqual(pending.exception.plan["slotImages"], 3)
            result = import_capture_dataset_archive(store, project, archive_path,
                confirmed_repair_digest=pending.exception.plan["digest"])
            self.assertEqual(result["slotImagesImported"], 3)
            self.assertEqual([r.to_dict() for r in project.images[:15]], kept_before)
            self.assertEqual({r.metadata["slotId"] for r in project.images}, set(topology_slots(manifest)))
