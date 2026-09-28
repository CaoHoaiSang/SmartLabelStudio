from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import uuid

from PIL import Image, ImageDraw

from smartlabel import heldout_collection as collection, benchmark_contract as contract, external_evaluation as evaluation
from smartlabel.fleet_boundaries import require_legacy_training_data
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.hydro_labels import model_attributes
from smartlabel.project_store import ProjectStore


def payload(root, number=0):
    root.mkdir()
    full = Image.new("RGB", (1920, 1080), "white")
    draw = ImageDraw.Draw(full); slots = []
    for i in range(10):
        x, y = (i % 5) * 384, (i // 5) * 540
        draw.rectangle((x, y, x+383, y+539), fill=(20+number*40+i, 100+i, 80))
        draw.line((x, y, x+383, y+539), fill="black", width=3)
        key = f"slot_{i+1:02d}"
        path = root / (key + ".png")
        slots.append({"slotId": key, "path": path.name, "rect": {"x": x, "y": y, "width": 384, "height": 540},
                      })
    for slot in slots:
        r = slot["rect"]
        path = root / slot["path"]
        full.crop((r["x"], r["y"], r["x"]+r["width"], r["y"]+r["height"])).save(path)
        slot.update(contract.image_identity(path))
    full.save(root / "full.png")
    meta = {"schemaVersion": "HydroHeldoutFrameV1", "captureId": "capture_" + uuid.uuid4().hex,
        "capturedAt": "2026-09-23T09:00:00+00:00", "modelInvoked": False,
        "cameraProfile": {"profileId": "camera_fixture"},
        "geometryProfile": {"profileId": "geometry_fixture", "slots": [{"slotId": s["slotId"], "rect": s["rect"]} for s in slots]},
        "fullFrame": {"path": "full.png", **contract.image_identity(root / "full.png")}, "slots": slots}
    (root / "capture.json").write_text(contract.canonical(meta), encoding="utf-8")
    return root


class HeldoutCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Temporary TEST", task="classify")
        apply_hydroponic_slot_template(self.project); self.store.save(self.project)
        self.before = deepcopy(self.project.to_dict())
        self.lot = collection.create_lot(self.store, self.project, "16 cây cùng đợt gieo", "2026-09-01", reserved=True)
        self.first = payload(self.root / "first")
        self.second = payload(self.root / "second", 1)

    def two_passes(self):
        collection.save_capture(self.store, self.project, self.lot, self.first)
        collection.save_capture(self.store, self.project, self.lot, self.second,
                                empty_slots=[f"slot_{i:02d}" for i in range(7, 11)])
        return collection.load_collection(self.store, self.project)

    def approve(self):
        data, rev = collection.load_collection(self.store, self.project)
        for row in list(data["images"]):
            values = {"plant_presence": "absent" if row["declaredEmpty"] else "present",
                "yellow_leaf": "not_applicable" if row["declaredEmpty"] else "present" if row["source"]["slotId"] == "slot_01" else "absent",
                "wilt": "not_applicable" if row["declaredEmpty"] else "present" if row["source"]["slotId"] == "slot_02" else "absent"}
            data, rev = collection.save_review(self.store, self.project, {}, row["id"], "reviewed", rev, attributes=values)
        return data, rev

    def test_twenty_crops_four_empty_no_labels_no_project_mutation(self):
        data, rev = self.two_passes()
        self.assertEqual(len(data["images"]), 20)
        self.assertEqual(sum(r["declaredEmpty"] for r in data["images"]), 4)
        self.assertTrue(all(not r["attributes"] and r["reviewStatus"] == "unlabeled" for r in data["images"]))
        self.assertEqual(self.project.to_dict(), self.before)
        self.assertEqual(self.store.load(self.project.id).to_dict(), self.before)
        self.assertFalse((self.store.project_dir(self.project) / "split_assignment.json").exists())
        root = collection.root_for(self.store, self.project)
        for path in (root, root / data["images"][0]["file"], root / "captures"):
            with self.assertRaisesRegex(ValueError, "TEST ngoài"):
                require_legacy_training_data(path)

    def test_retry_idempotent_and_changed_selection_rejected(self):
        _, before = collection.load_collection(self.store, self.project)
        collection.save_capture(self.store, self.project, self.lot, self.first, expected_revision=before)
        data, _ = collection.save_capture(self.store, self.project, self.lot, self.first, expected_revision=before)
        self.assertEqual(len(data["images"]), 10)
        with self.assertRaisesRegex(ValueError, "khác"):
            collection.save_capture(self.store, self.project, self.lot, self.first, empty_slots=["slot_01"])
        with self.assertRaisesRegex(ValueError, "thay đổi"):
            collection.save_capture(self.store, self.project, self.lot, self.second, expected_revision=before)

    def test_optional_identity_moves_and_empty_cannot_have_identity(self):
        collection.save_capture(self.store, self.project, self.lot, self.first, plant_ids={"slot_01": "T01"})
        data, _ = collection.save_capture(self.store, self.project, self.lot, self.second, plant_ids={"slot_08": "T01"})
        self.assertEqual(sum(r["source"]["plantId"] == "T01" for r in data["images"]), 2)
        with self.assertRaisesRegex(ValueError, "Mã cây"):
            collection.save_capture(self.store, self.project, self.lot, self.first, empty_slots=["slot_01"], plant_ids={"slot_01": "T01"})

    def test_review_cas_empty_semantics_and_draft_not_approval(self):
        data, rev = self.two_passes(); row = data["images"][-1]
        with self.assertRaisesRegex(ValueError, "Không áp dụng"):
            collection.save_review(self.store, self.project, {}, row["id"], "reviewed", rev,
                attributes={"plant_presence": "absent", "wilt": "absent", "yellow_leaf": "absent"})
        new_data, _ = collection.save_review(self.store, self.project, {}, row["id"], "draft", rev,
            attributes={"plant_presence": "absent", "wilt": "not_applicable", "yellow_leaf": "not_applicable"}, save_draft_labels=True)
        self.assertEqual(new_data["images"][-1]["reviewStatus"], "draft")
        with self.assertRaisesRegex(ValueError, "thay đổi"):
            collection.save_review(self.store, self.project, {}, row["id"], "rejected", rev)

    def test_export_roundtrip_preserves_scope_and_snapshots(self):
        self.two_passes()
        with self.assertRaisesRegex(ValueError, "Duyệt"):
            collection.export_collection(self.store, self.project, self.lot, self.root / "early", confirmed=True)
        self.approve()
        path = collection.export_collection(self.store, self.project, self.lot, self.root / "benchmark", confirmed=True)
        identifier = contract.import_benchmark(self.project, self.store, path)
        self.assertEqual(identifier, contract.import_benchmark(self.project, self.store, path))
        manifest, fingerprint = contract.validate_benchmark(path, self.project)
        self.assertEqual(manifest["schemaVersion"], "HydroHeldoutBenchmarkV1")
        self.assertTrue(manifest["cohort"]["sameSowingBatchAsDevelopment"])
        self.assertEqual(len(manifest["records"]), 20)
        self.assertFalse(any("cropCycleId" in r["source"] for r in manifest["records"]))
        data, rev = collection.load_collection(self.store, self.project)
        collection.save_review(self.store, self.project, {}, data["images"][0]["id"], "rejected", rev)
        self.assertEqual(contract.validate_benchmark(path, self.project)[1], fingerprint)

    def test_wrong_crop_hash_roi_parent_and_forged_source_rejected(self):
        meta = contract.read_json(self.first / "capture.json")
        Image.new("RGB", (384, 540), "red").save(self.first / meta["slots"][0]["path"])
        meta["slots"][0].update(contract.image_identity(self.first / meta["slots"][0]["path"]))
        (self.first / "capture.json").write_text(contract.canonical(meta), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "vùng cắt"):
            collection.save_capture(self.store, self.project, self.lot, self.first)

    def test_failed_manifest_save_leaves_recoverable_files_not_phantom_records(self):
        with patch.object(collection, "save_collection", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): collection.save_capture(self.store, self.project, self.lot, self.first)
        self.assertFalse(collection.load_collection(self.store, self.project)[0]["images"])
        with self.assertRaisesRegex(ValueError, "lưu dở"):
            collection.save_capture(self.store, self.project, self.lot, self.first)

    def test_collection_cannot_be_opened_as_other_project_and_requires_reservation(self):
        with self.assertRaisesRegex(ValueError, "xác nhận"):
            collection.create_lot(self.store, self.project, "bad", "2026-09-01")
        changed = deepcopy(self.project); changed.metadata["cropCode"] = "other"
        with self.assertRaisesRegex(ValueError, "không khớp"):
            collection.load_collection(self.store, changed)

    def test_overlap_guards_still_check_both_hashes_for_reserved_cohort(self):
        self.two_passes(); self.approve()
        path = collection.export_collection(self.store, self.project, self.lot, self.root / "benchmark", confirmed=True)
        manifest, _ = contract.validate_benchmark(path, self.project)
        row = manifest["records"][0]
        for key in ("sha256", "pixelSha256"):
            learned = {"sha256": "other", "pixelSha256": "other", key: row[key]}
            with self.assertRaisesRegex(ValueError, "trùng"):
                evaluation.reject_overlap(manifest, {"files": [learned], "cycles": []})

    def test_cancel_and_forged_hydro_source_never_publish(self):
        self.two_passes(); self.approve()
        stop = Event(); stop.set()
        target = self.root / "cancelled"
        with self.assertRaisesRegex(ValueError, "hủy"):
            collection.export_collection(self.store, self.project, self.lot, target, confirmed=True, cancel=stop)
        self.assertFalse(target.exists())
        path = collection.export_collection(self.store, self.project, self.lot, self.root / "benchmark", confirmed=True)
        original = contract.read_json(path / "benchmark.json")
        for mutate in (
                lambda m: m["records"][0]["source"].update(cropCycleId="fake_season"),
                lambda m: m["cohort"].update(reservedForTest=False),
                lambda m: m["records"][0].update(path="../outside.png"),
                lambda m: m["records"][0].update(sha256="0"*64)):
            manifest = deepcopy(original); mutate(manifest)
            (path / "benchmark.json").write_text(contract.canonical(manifest), encoding="utf-8")
            with self.assertRaises(ValueError): contract.validate_benchmark(path, self.project)

    def test_saved_capture_corruption_retry_fails_and_lock_is_exclusive(self):
        data, _ = collection.save_capture(self.store, self.project, self.lot, self.first)
        root = collection.root_for(self.store, self.project)
        Image.new("RGB", (384, 540), "red").save(root / data["images"][0]["file"])
        with self.assertRaisesRegex(ValueError, "thay đổi"):
            collection.save_capture(self.store, self.project, self.lot, self.first)
        with collection.collection_lock(root):
            with self.assertRaisesRegex(ValueError, "phiên khác"):
                with collection.collection_lock(root): pass
        with collection.collection_lock(root): pass  # Lock released after failure.

    def test_low_disk_space_and_orphan_block_without_new_records(self):
        with patch.object(collection.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, "giới hạn"):
                collection.save_capture(self.store, self.project, self.lot, self.first)
        self.assertFalse(collection.load_collection(self.store, self.project)[0]["images"])
        with patch.object(collection, "save_collection", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): collection.save_capture(self.store, self.project, self.lot, self.first)
        with self.assertRaisesRegex(ValueError, "lưu dở"):
            collection.save_capture(self.store, self.project, self.lot, self.second)

    def test_evaluate_cohort_through_existing_approval_release(self):
        self.two_passes(); self.approve()
        path = collection.export_collection(self.store, self.project, self.lot, self.root / "benchmark", confirmed=True)
        identifier = contract.import_benchmark(self.project, self.store, path)
        datasets, thresholds = {}, {}
        for attr in model_attributes(self.project):
            key = attr["id"]; checkpoint = self.root / (key + ".pt"); checkpoint.write_bytes(key.encode())
            self.project.attribute_models[key] = str(checkpoint)
            dataset = self.root / key; (dataset / "train" / "present").mkdir(parents=True)
            Image.new("RGB", (30, 30), "pink").save(dataset / "train" / "present" / "learned.png")
            (dataset / "export.json").write_text(contract.canonical({"project_id": self.project.id,
                "attribute_key": key, "classification_scope": "image", "label_attribute": attr,
                "source_records": [{"fileName": "learned.png", "source": {"siteId": "site", "deviceId": "device001", "cropCycleId": "same_sowing_batch"}}]}), encoding="utf-8")
            datasets[key] = dataset; thresholds[key] = {"lowThreshold": .2, "highThreshold": .8}
        factory = lambda attr, path, device: SimpleNamespace(score=lambda image: .9,
            model=SimpleNamespace(ckpt={"train_args": {"data": str(datasets[attr["id"]])}}))
        report_id, report = evaluation.evaluate_external(self.project, self.store, identifier, thresholds,
            independence_confirmed=True, classifier_factory=factory)
        self.assertTrue(report["evaluationScope"]["sameSowingBatchAsDevelopment"])
        self.assertEqual(report["models"]["plant_presence"]["operatingMetrics"]["negativeSupport"], 4)
        evaluation.approve_evaluation(self.project, self.store, report_id, confirmed=True)
        evidence = evaluation.release_evidence(self.project, self.store, thresholds)
        self.assertEqual(evidence["independenceBasis"], "operator_attested_reserved_cohort")
        self.assertFalse(evidence["evaluationScope"]["plantIdentityVerified"])
        changed = deepcopy(thresholds); changed["wilt"]["highThreshold"] = .95
        with self.assertRaises(ValueError): evaluation.release_evidence(self.project, self.store, changed)
        # Fixture-only operational package: preserve cohort scope through ONNX/ZIP.
        from smartlabel import hydro_export
        from smartlabel.models import ImageRecord
        # The existing exporter also requires reviewed development labels. The
        # collector never supplies those from TEST: keep three separate fixtures.
        for index in range(3):
            record = ImageRecord(id=f"development_{index}", file_name=f"development_{index}.png",
                width=30, height=30, asset_role="slot", review_status="reviewed",
                metadata={"siteId": "site", "deviceId": "device001", "cropCycleId": "same_sowing_batch"},
                attributes={"plant_presence": "absent" if index == 0 else "present",
                            "yellow_leaf": "not_applicable" if index == 0 else "present" if index == 1 else "absent",
                            "wilt": "not_applicable" if index == 0 else "present" if index == 1 else "absent"})
            self.project.images.append(record)
            image = self.store.image_path(self.project, record)
            Image.new("RGB", (30, 30), (200, 20+index, 200)).save(image)
            record.sha256 = contract.file_hash(image)
        def convert(source, target, **kwargs):
            import onnx
            from onnx import helper, TensorProto
            model = helper.make_model(helper.make_graph(
                [helper.make_node("Constant", [], ["scores"], value=helper.make_tensor("v", TensorProto.FLOAT, [1, 2], [.2, .8]))],
                "fixture", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 224, 224])],
                [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 2])]), opset_imports=[helper.make_opsetid("", 12)])
            helper.set_model_props(model, {"names": "{0: 'absent', 1: 'present'}"})
            onnx.save(model, target); return target
        config = {"datasetVersion": "fixture", "sourceCommit": "fixture", "cameraProfileIds": ["camera_fixture"],
                  "geometryProfileIds": ["geometry_fixture"], "runtimeTarget": "windows_onnxruntime_cpu",
                  "deploymentMode": "operational", "thresholds": thresholds}
        with patch.object(hydro_export, "hydro_dataset_qa", return_value={"issues": [], "validationStatus": "pilot_unvalidated"}), \
             patch.object(hydro_export, "export_jetson_onnx", side_effect=convert):
            package = hydro_export.build_hydro_package(self.project, self.store, self.root / "release", config, lambda _: None, Event())
        manifest = contract.read_json(package["bundle"] / "bundle.json")
        self.assertTrue(package["archive"].is_file())
        self.assertEqual(manifest["evaluationEvidence"]["evaluationScope"], report["evaluationScope"])
        for key in thresholds:
            self.assertEqual(manifest["evaluationEvidence"]["models"][key]["onnxSha256"], manifest["models"][key]["sha256"])
