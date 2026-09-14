from copy import deepcopy
import json
from unittest.mock import patch
import unittest

import test_training_supplements as fixtures
from smartlabel.supplement_review import load_review, preview_path, review_state, save_review, materialize_confirmed_presence
from smartlabel.training_supplements import sha256, validated_samples, review_attributes


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
        data, _ = self.update("reviewed", attributes={"plant_presence": "present", "yellow_leaf": "absent"})
        self.assertEqual(project_before, self.project.to_dict())
        self.assertEqual(split, self.manager.split_assignment_path(self.project).read_bytes())
        export = self.manager.export_classification(self.project, "yellow_leaf")
        meta = json.loads((export / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(meta['supplement_count'], 1)
        self.assertEqual(meta['training_supplements'][0]['attributes'], {'plant_presence': 'present', 'yellow_leaf': 'absent'})
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

    def test_bad_labels_and_conflicting_presence_are_not_written(self):
        before = self.path.read_bytes()
        for attributes in ({'yellow_leaf': 'bogus'}, {'unknown': 'present'}, {'yellow_leaf': 'present'},
                           {'plant_presence': 'absent', 'yellow_leaf': 'present'}):
            with self.assertRaises(ValueError): self.update('reviewed', attributes=attributes)
            self.assertEqual(before, self.path.read_bytes())

    def test_add_remove_and_uncertain_attributes_route_each_classifier_independently(self):
        before = deepcopy(self.project.to_dict())
        self.update('reviewed', attributes={'plant_presence': 'present', 'yellow_leaf': 'present', 'wilt': 'present'})
        for key in ('yellow_leaf', 'wilt'):
            out = self.manager.export_classification(self.project, key)
            metadata = json.loads((out / 'export.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['supplement_count'], 1)
            self.assertEqual(len(list((out / 'train' / 'present').iterdir())), 1)
            self.assertFalse(list((out / 'val' / 'present').iterdir()))
            self.assertFalse(list((out / 'test' / 'present').iterdir()))
        self.assertEqual(len(validated_samples(self.store, self.project, self.attrs[0], self.assignment)), 1)
        self.update('reviewed', attributes={'plant_presence': 'present', 'yellow_leaf': 'uncertain', 'wilt': 'present'})
        self.assertEqual(validated_samples(self.store, self.project, self.yellow, self.assignment), [])
        data, _ = self.update('reviewed', attributes={'plant_presence': 'present', 'wilt': 'present'})
        self.assertNotIn('yellow_leaf', data['images'][0]['attributes'])
        self.assertEqual(before, self.project.to_dict())

    def test_draft_saves_partial_labels_and_approval_requires_training_label(self):
        self.update('draft', attributes={'wilt': 'uncertain'}, save_draft_labels=True)
        data, _ = load_review(self.store, self.project)
        self.assertEqual(data['images'][0]['attributes'], {'wilt': 'uncertain'})
        self.assertFalse(data['images'][0]['enabled'])
        with self.assertRaisesRegex(ValueError, 'lưu nháp'):
            self.update('reviewed', attributes={'wilt': 'uncertain'})
        self.update('draft', attributes={}, save_draft_labels=True)
        self.assertEqual(load_review(self.store, self.project)[0]['images'][0]['attributes'], {})

    def test_no_plant_updates_semantics_and_does_not_train_conditions(self):
        data, _ = self.update('reviewed', attributes={'plant_presence': 'absent',
                              'yellow_leaf': 'not_applicable', 'wilt': 'not_applicable'})
        self.assertEqual(data['images'][0]['presenceMeaning'], 'negative')
        self.assertEqual(validated_samples(self.store, self.project, self.yellow, self.assignment), [])
        samples = validated_samples(self.store, self.project, self.attrs[0], self.assignment)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0][1], 'absent')

    def test_archive_keeps_image_labels_history_and_can_be_restored(self):
        image = preview_path(self.store, self.project, self.row)
        before = image.read_bytes()
        data, _ = self.update('archived', attributes={'yellow_leaf': 'absent'})
        row = data['images'][0]
        self.assertEqual(review_state(row), 'Đã lưu trữ')
        self.assertEqual(row['attributes'], self.row['attributes'])
        self.assertEqual(row['reviewHistory'][-1]['decision'], 'archived')
        self.assertEqual(image.read_bytes(), before)
        self.assertEqual(validated_samples(self.store, self.project, self.yellow, self.assignment), [])
        restored, _ = self.update('reviewed', attributes={'plant_presence': 'present', 'yellow_leaf': 'present'})
        self.assertFalse(restored['images'][0]['archived'])
        self.assertEqual(len(validated_samples(self.store, self.project, self.yellow, self.assignment)), 1)

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

    def test_legacy_presence_is_consistent_in_display_training_and_explicit_repair(self):
        before = deepcopy(self.row)
        original = self.path.read_bytes()
        self.assertEqual(review_attributes(self.project, self.row), {'plant_presence': 'present', 'yellow_leaf': 'present'})
        samples = validated_samples(self.store, self.project, self.attrs[0], self.assignment)
        self.assertEqual(samples[0][1], 'present')
        self.assertEqual(samples[0][2]['attributes']['plant_presence'], 'present')
        self.assertEqual(original, self.path.read_bytes())
        data, revision, changed = materialize_confirmed_presence(self.store, self.project, self.assignment, sha256(self.path))
        self.assertEqual(changed, ['s1'])
        row = data['images'][0]
        self.assertEqual(row['attributes'], {'plant_presence': 'present', 'yellow_leaf': 'present'})
        for key in before.keys() - {'attributes'}:
            self.assertEqual(before[key], row[key])
        self.assertEqual(row['reviewHistory'][-1]['previousAttributes'], before['attributes'])
        self.assertEqual(materialize_confirmed_presence(self.store, self.project, self.assignment, revision)[2], [])

    def test_repair_preserves_explicit_presence_archives_and_detects_conflicts(self):
        self.row['attributes']['plant_presence'] = 'absent'
        self.save()
        self.assertEqual(review_attributes(self.project, self.row)['plant_presence'], 'absent')
        with self.assertRaises(ValueError):
            validated_samples(self.store, self.project, self.yellow, self.assignment)
        self.row['attributes'].pop('plant_presence')
        self.row.update(archived=True, enabled=False)
        self.save()
        before = self.path.read_bytes()
        self.assertEqual(materialize_confirmed_presence(self.store, self.project, self.assignment, sha256(self.path))[2], [])
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'đã thay đổi'):
            materialize_confirmed_presence(self.store, self.project, self.assignment, 'outdated')
        lock = self.path.with_suffix('.review.lock')
        lock.write_text('other')
        with self.assertRaisesRegex(ValueError, 'phiên SmartLabel'):
            materialize_confirmed_presence(self.store, self.project, self.assignment, sha256(self.path))
        self.assertEqual(lock.read_text(), 'other')

    def test_custom_ids_use_semantics_and_no_condition_does_not_infer_presence(self):
        from smartlabel.label_schema import legacy_label_schema, schema_id
        schema = legacy_label_schema()
        presence = next(a for a in schema['attributes'] if a['role'] == 'presence')
        presence['id'] = 'crop_in_slot'
        presence['displayName'] = 'Custom presence'
        for value in presence['values']:
            value['id'] = 'custom_' + value['meaning']
        for attr in schema['attributes']:
            if attr['role'] == 'condition':
                attr['requires'] = presence['id']
        schema['schemaId'] = schema_id(schema)
        self.project.metadata['labelSchema'] = schema
        self.assertEqual(review_attributes(self.project, self.row)['crop_in_slot'], 'custom_positive')
        row = {**self.row, 'presenceMeaning': None}
        self.assertNotIn('crop_in_slot', review_attributes(self.project, row))
        row = {**self.row, 'attributes': {'yellow_leaf': 'uncertain'}}
        self.assertNotIn('crop_in_slot', review_attributes(self.project, row))
