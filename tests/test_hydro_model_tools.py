from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

from PIL import Image
from smartlabel import hydro_model_tools as tools
from smartlabel.auto_label import auto_label_project
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.hydro_labels import model_attributes
from smartlabel.attribute_defaults import image_attribute_defaults
from smartlabel.label_schema import make_label_schema
from smartlabel.models import ImageRecord, Annotation
from smartlabel.project_store import ProjectStore
from smartlabel import image_filters as filters


class HydroToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Hydro", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.attrs = model_attributes(self.project)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        for a in self.attrs:
            path = self.root / f"{a['id']}.pt"
            path.write_bytes(b"fixture")
            self.project.attribute_models[a["id"]] = str(path)
        self.scores = {"plant_presence": 0.9, "yellow_leaf": 0.1, "wilt": 0.51}

    def record(self, **kwargs):
        record = ImageRecord(id=str(len(self.project.images)), file_name=f"{len(self.project.images)}.png",
                             width=64, height=64, asset_role="slot", **kwargs)
        self.project.images.append(record)
        return record

    def factory(self, attr, path, device):
        return SimpleNamespace(score=lambda _: self.scores[attr["id"]],
                               model=SimpleNamespace(ckpt={"train_args": {"data": str(self.dataset)}}))

    def auto(self, **kwargs):
        options = dict(device="cpu", confidence=0.8, unlabeled_only=True, replace_predictions=True,
                       progress=lambda *args: None, cancel_event=Event(), classifier_factory=self.factory)
        options.update(kwargs)
        return tools.propose_hydro_labels(deepcopy(self.project), self.store, **options)

    def test_auto_returns_drafts_without_mutating_source_and_enforces_presence(self):
        record = self.record()
        original = deepcopy(self.project.to_dict())
        result = self.auto()
        self.assertEqual(self.project.to_dict(), original)
        self.assertEqual(result["proposals"][0]["values"], {"plant_presence": "present", "yellow_leaf": "absent", "wilt": "uncertain"})
        self.assertEqual(tools.apply_hydro_proposals(self.project, result), (1, 0))
        self.assertEqual(record.review_status, "draft")
        record.attributes.clear()
        self.scores["plant_presence"] = 0.1
        result = self.auto()
        self.assertEqual(result["proposals"][0]["values"]["yellow_leaf"], "not_applicable")

    def test_import_placeholders_are_eligible_but_explicit_manual_unknown_is_preserved(self):
        record = self.record(attributes=image_attribute_defaults(self.project))
        result = self.auto()
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["proposals"][0]["values"]["plant_presence"], "present")
        record.metadata["hydroManualAttributes"] = ["plant_presence"]
        result = self.auto()
        self.assertEqual(result["proposals"][0]["values"]["plant_presence"], "uncertain")
        self.assertEqual(result["proposals"][0]["values"]["wilt"], "not_applicable")

    def test_recorded_defaults_can_be_suggested_even_when_default_value_is_decisive(self):
        values = {"plant_presence": "present", "yellow_leaf": "present", "wilt": "present"}
        record = self.record(attributes=deepcopy(values), metadata={"hydroAttributeDefaults": deepcopy(values)})
        result = self.auto()
        self.assertEqual(result["proposals"][0]["values"]["yellow_leaf"], "absent")
        record.metadata["hydroManualAttributes"] = ["yellow_leaf"]
        result = self.auto()
        self.assertEqual(result["proposals"][0]["values"]["yellow_leaf"], "present")
        record.metadata.clear()  # Legacy decisive labels with no provenance are preserved.
        self.assertFalse(self.auto()["proposals"])

    def test_import_records_default_provenance_only_for_hydro(self):
        source = self.root / "image.png"
        Image.new("RGB", (64, 64), "green").save(source)
        self.store.import_images(self.project, [source])
        self.assertEqual(self.project.images[0].metadata["hydroAttributeDefaults"], image_attribute_defaults(self.project))
        bottle = self.store.create_project("Bottle defaults", classes=["bottle"])
        self.store.import_images(bottle, [source])
        self.assertNotIn("hydroAttributeDefaults", bottle.images[0].metadata)

    def test_custom_value_ids_follow_semantics_instead_of_display_names(self):
        attrs = deepcopy(self.attrs)
        for attr in attrs:
            for value in attr["values"]:
                value["id"] = "custom_" + value["meaning"]
        self.project.metadata["labelSchema"] = make_label_schema(attrs)
        self.record()
        result = self.auto()
        self.assertEqual(result["proposals"][0]["values"]["plant_presence"], "custom_positive")
        self.assertEqual(result["proposals"][0]["values"]["wilt"], "custom_uncertain")

    def test_auto_preserves_reviewed_rejected_manual_and_conflicting_concurrent_edits(self):
        self.record(review_status="reviewed")
        self.record(review_status="rejected")
        manual = self.record(attributes={"plant_presence": "present", "yellow_leaf": "present"})
        result = self.auto()
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["proposals"][0]["values"]["yellow_leaf"], "present")
        manual.attributes["wilt"] = "absent"
        self.assertEqual(tools.apply_hydro_proposals(self.project, result), (0, 1))

    def test_auto_only_replaces_own_unchanged_predictions(self):
        record = self.record()
        tools.apply_hydro_proposals(self.project, self.auto())
        self.assertFalse(self.auto()["proposals"])
        record.attributes["yellow_leaf"] = "present"  # Human edit differs from old prediction.
        result = self.auto(unlabeled_only=False)
        self.assertEqual(result["proposals"][0]["values"]["yellow_leaf"], "present")
        self.assertFalse(self.auto(unlabeled_only=False, replace_predictions=False)["proposals"])

    def test_auto_cancellation_and_per_image_failure(self):
        self.record()
        cancel = Event()
        cancel.set()
        self.assertTrue(self.auto(cancel_event=cancel)["cancelled"])
        def broken(*args):
            return SimpleNamespace(score=lambda _: (_ for _ in ()).throw(ValueError("bad image")))
        result = self.auto(classifier_factory=broken)
        self.assertEqual(len(result["failed"]), 1)
        self.assertFalse(result["proposals"])

    def test_generic_detector_rejects_hydro_before_loading_model(self):
        with self.assertRaisesRegex(ValueError, "Hydro"):
            auto_label_project(self.store, self.project, "missing.pt")
        bottle = self.store.create_project("Bottle", classes=["bottle"])
        bottle.images.append(ImageRecord(id="b", file_name="b.png", width=30, height=40))
        ann = Annotation.create_box(0, [1, 2, 3, 4], source="yolo")
        with patch("smartlabel.auto_label.YoloAutoLabeler") as mocked:
            mocked.return_value = SimpleNamespace(names={0: "bottle"}, device="cpu", task="detect", predict=lambda *a: [ann])
            result = auto_label_project(self.store, bottle, "bottle.pt")
        self.assertEqual(result.detections, 1)
        self.assertEqual(bottle.images[0].annotations[0].class_id, 0)
        self.assertFalse(bottle.images[0].attributes)

    def prepare_dataset(self):
        a = self.attrs[0]
        meta = dict(project_id=self.project.id, attribute_key=a["id"], classification_scope="image",
                    label_attribute=a, validation_enabled=True, independent_test=True,
                    split_strategy="locked", classes={"absent": "absent", "present": "present"})
        for i, split in enumerate(("train", "val", "test")):
            for j, label in enumerate(("absent", "present")):
                folder = self.dataset / split / label
                folder.mkdir(parents=True)
                Image.new("RGB", (20, 20), (i * 50, j * 80, 20)).save(folder / "image.png")
        (self.dataset / "export.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def evaluate(self, split="test", **kwargs):
        return tools.evaluate_hydro_attribute(self.project, "plant_presence", self.store, split=split,
                    device="cpu", progress=lambda *a: None, classifier_factory=self.factory, **kwargs)

    def test_evaluation_writes_metrics_and_test_never_tunes_thresholds(self):
        self.prepare_dataset()
        original = deepcopy(self.project.to_dict())
        result = self.evaluate()
        self.assertEqual(result["metrics"]["samples"], 2)
        self.assertEqual(result["metrics"]["tp"], 1)
        self.assertEqual(result["metrics"]["fp"], 1)
        self.assertIsNone(result["recommendedThresholds"])
        self.assertTrue((Path(result["save_dir"]) / "evaluation_summary.json").is_file())
        self.assertEqual(original, self.project.to_dict())
        validation = self.evaluate("val")
        self.assertEqual(validation["split"], "val")
        self.assertEqual(validation["metrics"]["samples"], 2)
        self.assertIsNone(validation["recommendedThresholds"])

    def test_evaluation_rejects_wrong_attribute_synthetic_split_missing_class_and_leakage(self):
        meta = self.prepare_dataset()
        path = self.dataset / "export.json"
        for field, value in (("attribute_key", "wilt"), ("project_id", "other"), ("independent_test", False)):
            changed = dict(meta, **{field: value})
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.evaluate()
        path.write_text(json.dumps(dict(meta, validation_enabled=False)), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.evaluate("val")
        path.write_text(json.dumps(meta), encoding="utf-8")
        test_image = self.dataset / "test" / "absent" / "image.png"
        test_image.write_bytes((self.dataset / "train" / "absent" / "image.png").read_bytes())
        with self.assertRaisesRegex(ValueError, "trùng"):
            self.evaluate()
        test_image.unlink()
        with self.assertRaisesRegex(ValueError, "thiếu ảnh"):
            self.evaluate()

    def test_recommendations_require_validation_both_classes_and_signal(self):
        samples = [(0, 0.2)] * 20 + [(1, 0.8)] * 20
        self.assertIsNotNone(tools.recommend_thresholds(samples, "val"))
        self.assertIsNone(tools.recommend_thresholds(samples, "test"))
        self.assertIsNone(tools.recommend_thresholds(samples[:21], "val"))
        self.assertIsNone(tools.recommend_thresholds([(0, .5)] * 20 + [(1, .5)] * 20, "val"))
        self.assertEqual(tools.binary_metrics(samples)["f1"], 1)

    def test_assessment_distinguishes_test_from_insufficient_validation_and_release(self):
        report = {"split": "test", "metrics": tools.binary_metrics([(1, .9)] * 160 + [(0, .1)] * 13)}
        text = tools.classifier_assessment(report)
        self.assertIn("Chưa phát hiện lỗi trên bộ ảnh này", text)
        self.assertIn("Có=160 · Không=13", text)
        self.assertIn("Một phía có dưới 20 ảnh", text)
        self.assertIn("không phải lỗi hay do thiếu 20 ảnh", text)
        self.assertIn("không tự cấp quyền phát hành", text)
        report["split"] = "val"
        self.assertIn("cần ít nhất 20 ảnh Có và 20 ảnh Không", tools.classifier_assessment(report))
        report["metrics"] = tools.binary_metrics([(1, .1)] * 20 + [(0, .9)] * 20)
        self.assertIn("20 lần báo nhầm Có và 20 lần bỏ sót Có", tools.classifier_assessment(report))
        self.assertIn("chưa đạt 0.65", tools.classifier_assessment(report))
        report["recommendedThresholds"] = {"lowThreshold": .3, "highThreshold": .7}
        self.assertIn("0.30/0.70", tools.classifier_assessment(report))

    def test_threshold_defaults_restore_json_evidence_and_invalidate_changed_model(self):
        attr = self.attrs[0]
        report = dict(modelSha256=tools.file_hash(self.project.attribute_models[attr["id"]]),
                      attributeIdentity=tools.training_identity(attr), metrics={"samples": 40},
                      recommendedThresholds={"lowThreshold": .4, "highThreshold": .6})
        self.project.metadata["hydroEvaluations"] = json.loads(json.dumps({attr["id"]: {"val": report}}))
        thresholds, sources = tools.threshold_defaults(self.project)
        self.assertEqual(thresholds[attr["id"]]["lowThreshold"], .4)
        self.assertIn("validation", sources[attr["id"]])
        self.project.metadata["hydroThresholds"] = {attr["id"]: {"lowThreshold": .2, "highThreshold": .8}}
        self.project.metadata["hydroThresholdModelHashes"] = {attr["id"]: report["modelSha256"]}
        confirmed, _ = tools.threshold_defaults(self.project)
        self.assertEqual(confirmed[attr["id"]]["lowThreshold"], .2)
        Path(self.project.attribute_models[attr["id"]]).write_bytes(b"retrained")
        thresholds, sources = tools.threshold_defaults(self.project)
        self.assertEqual(thresholds[attr["id"]], tools.INITIAL_THRESHOLDS)
        self.assertIn("Checkpoint đã đổi", sources[attr["id"]])

    def test_classifier_uses_semantic_output_order_and_rejects_wrong_task_names_nan(self):
        fake = SimpleNamespace(task="classify", names={0: "present", 1: "absent"},
            predict=lambda **kwargs: [SimpleNamespace(probs=SimpleNamespace(data=SimpleNamespace(tolist=lambda: [.85, .15])))])
        with patch("ultralytics.YOLO", return_value=fake):
            classifier = tools.HydroClassifier(self.attrs[0], self.project.attribute_models["plant_presence"], "cpu")
            self.assertEqual(classifier.score("image.png"), .85)
            fake.task = "detect"
            with self.assertRaises(ValueError):
                tools.HydroClassifier(self.attrs[0], self.project.attribute_models["plant_presence"])
            fake.task, fake.names = "classify", {0: "bottle", 1: "cap"}
            with self.assertRaises(ValueError):
                tools.HydroClassifier(self.attrs[0], self.project.attribute_models["plant_presence"])
            fake.names = {0: "present", 1: "absent"}
            fake.predict = lambda **kw: [SimpleNamespace(probs=SimpleNamespace(data=SimpleNamespace(tolist=lambda: [float("nan"), .2])))]
            with self.assertRaises(ValueError):
                classifier.score("image.png")

    def test_filters_combine_status_and_stable_labels_for_hydro_and_bottle(self):
        record = self.record(attributes={"yellow_leaf": "present"}, review_status="draft")
        field = ("attribute", "yellow_leaf")
        self.assertTrue(filters.matches_image(self.project, record, "draft", field, "present"))
        self.assertFalse(filters.matches_image(self.project, record, "reviewed", field, "present"))
        self.assertFalse(filters.matches_image(self.project, record, None, field, "absent"))
        self.assertTrue(filters.matches_image(self.project, record, None, ("attribute", "wilt"), ""))
        bottle = self.store.create_project("Bottle", classes=["bottle", "cap"])
        bottle.attribute_schema = {"color": ["red", "blue"]}
        record.annotations = [Annotation.create_box(1, [0, 0, 5, 5])]
        record.annotations[0].attributes["color"] = "red"
        self.assertTrue(filters.matches_image(bottle, record, field=("class", ""), value=1))
        self.assertTrue(filters.matches_image(bottle, record, field=("attribute", "color"), value="red"))
        self.assertFalse(filters.matches_image(bottle, record, field=("attribute", "color"), value="blue"))


if __name__ == "__main__":
    unittest.main()
