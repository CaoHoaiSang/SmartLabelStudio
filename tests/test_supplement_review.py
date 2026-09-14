from copy import deepcopy
import json
from unittest.mock import patch
import unittest

import test_training_supplements as fixtures
from smartlabel.supplement_review import load_review, preview_path, review_state, save_review
from smartlabel.training_supplements import sha256, validated_samples


class SupplementReviewTests(unittest.TestCase):
    setUp = fixtures.SupplementTests.setUp
    save = fixtures.SupplementTests.save

    def update(self, decision, **kwargs):
        return save_review(self.store, self.project, self.assignment, "s1", decision, sha256(self.path), **kwargs)

    def test_review_exclusion_reapproval_and_label_correction_reach_export(self):
        project_before = deepcopy(self.project.to_dict())
        split = self.manager.split_assignment_path(self.project).read_bytes()
        for decision in ("draft", "rejected"):
            data, revision = self.update(decision)
            self.assertFalse(data['images'][0]['enabled'])
            self.assertEqual(validated_samples(self.store, self.project, self.yellow, self.assignment), [])
            self.assertEqual(revision, sha256(self.path))
        data, _ = self.update("reviewed", attributes={"yellow_leaf": "absent"})
        self.assertEqual(project_before, self.project.to_dict())
        self.assertEqual(split, self.manager.split_assignment_path(self.project).read_bytes())
        export = self.manager.export_classification(self.project, "yellow_leaf")
        meta = json.loads((export / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(meta['supplement_count'], 1)
        self.assertEqual(meta['training_supplements'][0]['attributes'], {'yellow_leaf': 'absent'})
        self.assertEqual(len(list((export / 'train' / 'absent').iterdir())), 2)
        row = data['images'][0]
        self.assertEqual(row['provenance'], self.row['provenance'])
        self.assertEqual(row['sha256'], self.row['sha256'])
        self.assertEqual(len(row['reviewHistory']), 3)
        self.assertEqual(row['reviewHistory'][-1]['previous']['attributes'], {'yellow_leaf': 'present'})

    def test_revision_conflict_and_concurrent_writer_leave_bytes_untouched(self):
        _, revision = load_review(self.store, self.project)
        self.manifest['externalEdit'] = True
        self.save()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'đã thay đổi'):
            save_review(self.store, self.project, self.assignment, 's1', 'draft', revision)
        self.assertEqual(before, self.path.read_bytes())
        lock = self.path.with_suffix('.review.lock')
        lock.write_text('other Studio')
        with self.assertRaisesRegex(ValueError, 'phiên SmartLabel khác'):
            self.update('draft')
        self.assertEqual(lock.read_text(), 'other Studio')
        self.assertEqual(before, self.path.read_bytes())

    def test_export_validation_runs_before_approval_write(self):
        for change in ('hash', 'split', 'meaning', 'duplicate'):
            with self.subTest(change=change):
                before_manifest = deepcopy(self.manifest)
                if change == 'hash': self.row['sha256'] = 'wrong'
                if change == 'split': self.assignment['train'] = 'test'
                if change == 'meaning': self.manifest['labelIdentities'] = {}
                if change == 'duplicate':
                    other = deepcopy(self.row)
                    other['id'] = 's2'
                    self.manifest['images'].append(other)
                self.save()
                before = self.path.read_bytes()
                with self.assertRaises(ValueError): self.update('reviewed')
                self.assertEqual(before, self.path.read_bytes())
                self.manifest = before_manifest
                self.row = self.manifest['images'][0]
                self.assignment['train'] = 'train'

    def test_invalid_preview_can_be_excluded_without_accepting_form_labels(self):
        self.row['file'] = '../outside.png'
        self.save()
        with self.assertRaises(ValueError): preview_path(self.store, self.project, self.row)
        data, _ = self.update('rejected', attributes={'yellow_leaf': 'absent'})
        self.assertEqual(data['images'][0]['attributes'], {'yellow_leaf': 'present'})
        self.assertEqual(review_state(data['images'][0]), 'Từ chối')

    def test_bad_labels_and_added_attributes_are_not_written(self):
        before = self.path.read_bytes()
        for attributes in ({'yellow_leaf': 'uncertain'}, {'yellow_leaf': 'present', 'wilt': 'absent'}):
            with self.assertRaises(ValueError): self.update('reviewed', attributes=attributes)
            self.assertEqual(before, self.path.read_bytes())

    def test_atomic_replace_failure_cleans_own_temporary_files_and_preserves_manifest(self):
        before = self.path.read_bytes()
        with patch('smartlabel.supplement_review.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): self.update('draft')
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(list(self.path.parent.glob('.review-*')))
        self.assertFalse(self.path.with_suffix('.review.lock').exists())

    def test_outside_edit_during_validation_is_preserved(self):
        def external_edit(*_args):
            self.manifest['externalEdit'] = 'keep'
            self.save()
        with patch('smartlabel.supplement_review.validate_manifest_samples', side_effect=external_edit):
            with self.assertRaisesRegex(ValueError, 'cập nhật bên ngoài'): self.update('reviewed')
        self.assertEqual(json.loads(self.path.read_text())['externalEdit'], 'keep')
        self.assertNotIn('reviewHistory', json.loads(self.path.read_text())['images'][0])

    def test_bottle_sidecar_is_never_read_or_written_and_duplicate_ids_block(self):
        self.project.metadata.clear()
        before = self.path.read_bytes()
        self.assertEqual(load_review(self.store, self.project), (None, None))
        with self.assertRaisesRegex(ValueError, 'Hydro'): self.update('draft')
        self.assertEqual(before, self.path.read_bytes())
        self.project.metadata['template'] = 'Hydroponic Slot Condition'
        self.manifest['images'].append(deepcopy(self.row))
        self.save()
        with self.assertRaisesRegex(ValueError, 'trùng'): load_review(self.store, self.project)
