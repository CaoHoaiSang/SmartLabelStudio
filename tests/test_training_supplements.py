from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from smartlabel.dataset_manager import DatasetManager
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.hydro_labels import model_attributes
from smartlabel.hydro_statistics import overview_lines
from smartlabel.label_schema import training_identity
from smartlabel.models import ImageRecord, Annotation
from smartlabel.project_store import ProjectStore
from smartlabel.training_supplements import manifest_path, sha256, validated_samples, summary_lines


class SupplementTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ProjectStore(Path(temp.name) / "workspace")
        self.project = self.store.create_project("Hydro", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.project.metadata["cropCode"] = "cai_ngot"
        self.manager = DatasetManager(self.store)
        self.attrs = model_attributes(self.project)
        self.yellow = next(a for a in self.attrs if a["id"] == "yellow_leaf")
        for i, split in enumerate(("train", "val", "test")):
            record = ImageRecord(id=split, file_name=f"{split}.png", width=32, height=32,
                asset_role="slot", review_status="reviewed", capture_group=split,
                attributes={"plant_presence": "present", "yellow_leaf": "absent", "wilt": "absent"})
            self.project.images.append(record)
            Image.new("RGB", (32, 32), (0, 80 + i * 20, 0)).save(self.store.image_path(self.project, record))
        self.assignment = {k: k for k in ("train", "val", "test")}
        self.manager.split_assignment_path(self.project).write_text(json.dumps({"groups": self.assignment}))
        self.path = manifest_path(self.store, self.project)
        self.path.parent.mkdir()
        Image.new("RGB", (32, 32), "yellow").save(self.path.parent / "yellow.png")
        self.row = {"id": "s1", "enabled": True, "file": "yellow.png",
                    "sha256": sha256(self.path.parent / "yellow.png"), "kind": "synthetic", "split": "train",
                    "cropCode": "cai_ngot", "reviewStatus": "reviewed", "reviewNote": "Visible yellow leaf",
                    "attributes": {"yellow_leaf": "present"}, "presenceMeaning": "positive",
                    "provenance": {"parentImageId": "train", "parentSha256": sha256(self.store.image_path(self.project, self.project.images[0])),
                                   "method": "test fixture", "prompt": "yellow test fixture"}}
        self.manifest = {"schemaVersion": 1, "projectId": self.project.id,
                         "labelIdentities": {a['id']: training_identity(a) for a in self.attrs}, "images": [self.row]}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def validate(self):
        return validated_samples(self.store, self.project, self.yellow, self.assignment)

    def test_only_requested_classifier_receives_supplement_and_snapshot_preserves_provenance(self):
        out = self.manager.export_classification(self.project, "yellow_leaf")
        meta = json.loads((out / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["supplement_count"], 1)
        self.assertEqual(meta["counts"], {"absent": 3, "present": 1})
        self.assertEqual(len(list((out / "train" / "present").glob("*.jpg"))), 1)
        self.assertFalse(list((out / "val" / "present").iterdir()))
        self.assertFalse(list((out / "test" / "present").iterdir()))
        self.assertEqual(meta["training_supplements"][0]["provenance"], self.row["provenance"])
        presence = self.manager.export_classification(self.project, "plant_presence")
        self.assertEqual(json.loads((presence / "export.json").read_text(encoding="utf-8"))["supplement_count"], 0)

    def test_supplements_never_enter_compatibility_validation_mirrors(self):
        for strategy in ("final_keep_test", "train_all"):
            with self.subTest(strategy=strategy):
                out = self.manager.export_classification(self.project, "yellow_leaf", split_strategy=strategy)
                self.assertEqual(len(list((out / "train" / "present").iterdir())), 1)
                self.assertEqual(len(list((out / "val" / "present").iterdir())), 0)
                self.assertEqual(len(list((out / "test" / "present").iterdir())), 0)

    def test_parent_in_holdout_blocks_even_final_train_all(self):
        self.assignment["train"] = "test"
        self.manager.split_assignment_path(self.project).write_text(json.dumps({"groups": self.assignment}))
        with self.assertRaisesRegex(ValueError, "VAL/TEST"):
            self.manager.export_classification(self.project, "yellow_leaf", split_strategy="train_all")

    def test_manifest_validation_does_not_mutate_project_or_split(self):
        before = deepcopy(self.project.to_dict())
        split = self.manager.split_assignment_path(self.project).read_bytes()
        self.validate()
        self.assertEqual(before, self.project.to_dict())
        self.assertEqual(split, self.manager.split_assignment_path(self.project).read_bytes())

    def test_corrupt_image_hash_and_parent_hash_block(self):
        for target in (self.row, self.row["provenance"]):
            with self.subTest(target=target):
                key = "sha256" if target is self.row else "parentSha256"
                old = target[key]
                target[key] = "changed"
                self.save()
                with self.assertRaises(ValueError): self.validate()
                target[key] = old

    def test_path_escape_duplicate_and_review_fail_closed(self):
        for update in ({"file": "../images/train.png"}, {"split": "val"}, {"reviewStatus": "draft"},
                       {"cropCode": "lettuce"}, {"presenceMeaning": "negative"}, {"attributes": {"yellow_leaf": "uncertain"}}):
            old = deepcopy(self.row)
            self.row.update(update)
            self.save()
            with self.subTest(update=update), self.assertRaises(ValueError): self.validate()
            self.row.clear(); self.row.update(old)
        self.manifest["images"].append(deepcopy(self.row))
        self.save()
        with self.assertRaisesRegex(ValueError, "trùng"): self.validate()

    def test_pixel_duplicate_reencoded_from_test_is_rejected(self):
        source = self.store.image_path(self.project, self.project.images[2])
        with Image.open(source) as image: image.save(self.path.parent / "yellow.png", compress_level=0)
        self.row['sha256'] = sha256(self.path.parent / "yellow.png")
        self.save()
        with self.assertRaisesRegex(ValueError, "trùng nội dung"): self.validate()

    def test_disabled_bad_row_is_not_used(self):
        self.row.update(enabled=False, file="nonexistent.png")
        self.manifest['labelIdentities'] = {}
        self.save()
        self.assertEqual(self.validate(), [])

    def test_attribute_train_exclusion_blocks_before_snapshot_creation(self):
        self.project.attribute_settings['yellow_leaf']['train_exclude'].append('present')
        with self.assertRaisesRegex(ValueError, 'bị loại khỏi train'):
            self.manager.export_classification(self.project, 'yellow_leaf')
        self.assertFalse(list((self.store.project_dir(self.project) / 'exports').glob('classify_*')))

    def test_external_requires_attribution_and_does_not_claim_capture(self):
        self.row.update(kind="external", provenance={})
        self.save()
        with self.assertRaises(ValueError): self.validate()
        self.row["provenance"] = {"url": "https://example.org/dataset", "author": "Fixture", "license": "CC0-1.0",
                                  "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/", "retrievedAt": "2026-09-13"}
        self.save()
        self.assertEqual(len(self.validate()), 1)

    def test_semantics_mismatch_rejected_display_rename_allowed(self):
        self.manifest['labelIdentities']['yellow_leaf']['role'] = 'presence'
        self.save()
        with self.assertRaisesRegex(ValueError, "Ý nghĩa"): self.validate()
        self.manifest['labelIdentities'] = {a['id']: training_identity(a) for a in self.attrs}
        self.yellow['displayName'] = 'Custom title'
        self.save()
        self.assertEqual(len(self.validate()), 1)

    def test_bottle_ignores_hydro_sidecar_and_retains_geometry_statistics(self):
        self.project.metadata.clear()
        self.project.images[0].annotations.append(Annotation(id="a1", class_id=0, bbox=[1, 1, 20, 20]))
        self.path.write_text('broken JSON')
        self.assertEqual(self.validate(), [])
        stats = self.manager.summary(self.project)
        self.assertEqual(stats['annotations'], 1)
        self.assertNotIn('image_attributes', stats)

    def test_statistics_distinguish_pending_na_missing_and_eligible_labels_without_writing(self):
        self.project.images[0].attributes['yellow_leaf'] = 'present'
        self.project.images[1].attributes['plant_presence'] = 'absent'
        self.project.images[1].attributes['yellow_leaf'] = 'not_applicable'
        self.project.images[2].review_status = 'draft'
        before = self.manager.split_assignment_path(self.project).read_bytes()
        rows = self.manager.summary(self.project)['image_attributes']
        yellow = next(a for a in rows if a['id'] == 'yellow_leaf')
        self.assertEqual(yellow['reviewed'], {'positive': 1, 'not_applicable': 1})
        self.assertEqual(yellow['pending'], {'negative': 1})
        self.assertEqual(yellow['splits'], {'train': {'positive': 1}, 'val': {}, 'test': {}})
        self.assertIn('TEST còn thiếu', '\n'.join(overview_lines(rows)))
        self.assertEqual(before, self.manager.split_assignment_path(self.project).read_bytes())

    def test_bad_sidecar_is_visible_in_overview_without_crashing(self):
        self.path.write_text('{')
        self.assertIn('cần kiểm tra', '\n'.join(summary_lines(self.store, self.project)))


if __name__ == '__main__':
    unittest.main()
