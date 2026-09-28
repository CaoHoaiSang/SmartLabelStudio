from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from PIL import Image

from smartlabel import benchmark_contract as contract, external_evaluation as evaluation
from smartlabel.dataset_manager import DatasetManager
from smartlabel.fleet_boundaries import require_legacy_training_data
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.hydro_labels import model_attributes
from smartlabel.label_schema import training_identity
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore


class ExternalBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Fixture only", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.attrs = model_attributes(self.project)
        self.thresholds = {a['id']: {'lowThreshold': .2, 'highThreshold': .8} for a in self.attrs}
        for index in range(3):
            record = ImageRecord(id=f'image_{index}', file_name=f'image_{index}.png', width=24, height=24,
                asset_role='slot', review_status='reviewed', capture_group=f'capture_{index}',
                metadata={'siteId': 'site', 'deviceId': 'device001', 'cropCycleId': 'season_external',
                          'captureId': f'capture_{index}', 'slotId': 'upper_01', 'capturedAt': '2026-09-22T10:00:00Z'},
                attributes={'plant_presence': 'absent' if index == 0 else 'present',
                            'yellow_leaf': 'not_applicable' if index == 0 else 'present' if index == 1 else 'absent',
                            'wilt': 'not_applicable' if index == 0 else 'present' if index == 1 else 'absent'})
            self.project.images.append(record)
            path = self.store.image_path(self.project, record)
            Image.new('RGB', (24, 24), (30 * index, 100, 50)).save(path)
            record.sha256 = contract.file_hash(path)
        self.store.save(self.project)
        self.before = deepcopy(self.project.to_dict())
        self.source = self.root / 'external'
        contract.export_benchmark(self.project, self.store, {contract.cycle_rows(self.project)[0]['key']}, self.source)
        self.identifier = contract.import_benchmark(self.project, self.store, self.source)
        self.datasets = {}
        for attr in self.attrs:
            key = attr['id']; path = self.root / (key + '.pt'); path.write_bytes(key.encode())
            self.project.attribute_models[key] = str(path)
            dataset = self.root / key; (dataset / 'train' / 'present').mkdir(parents=True)
            (dataset / 'val').mkdir()
            Image.new('RGB', (24, 24), (200, 20, 50)).save(dataset / 'train' / 'present' / 'learned.png')
            metadata = {'project_id': self.project.id, 'attribute_key': key, 'classification_scope': 'image',
                        'label_attribute': attr, 'source_records': [{'fileName': 'learned.png',
                         'source': {'siteId': 'site', 'deviceId': 'device001', 'cropCycleId': 'season_learned'}}]}
            (dataset / 'export.json').write_text(contract.canonical(metadata), encoding='utf-8')
            self.datasets[key] = dataset

    def factory(self, attr, path, device):
        def score(image):
            with Image.open(image) as img: red = img.getpixel((0, 0))[0]
            return (.1 if red == 0 else .9) if attr['role'] == 'presence' else (.9 if red == 30 else .1)
        return SimpleNamespace(score=score, model=SimpleNamespace(ckpt={'train_args': {'data': str(self.datasets[attr['id']])}}))

    def evaluate(self, **kwargs):
        return evaluation.evaluate_external(self.project, self.store, self.identifier, self.thresholds,
            independence_confirmed=True, classifier_factory=self.factory, **kwargs)

    def test_roundtrip_idempotent_separate_from_training_and_preserves_labels(self):
        self.assertEqual(contract.import_benchmark(self.project, self.store, self.source), self.identifier)
        self.assertEqual(len(self.project.images), 3)
        self.assertEqual(self.store.load(self.project.id).to_dict(), self.before)
        self.assertFalse((self.store.project_dir(self.project) / 'split_assignment.json').exists())
        for path in (self.source, self.source / 'images', contract.benchmark_root(self.store, self.project, self.identifier)):
            with self.assertRaisesRegex(ValueError, 'TEST ngoài'):
                require_legacy_training_data(path)

    def test_evaluate_approve_release_and_threshold_defaults(self):
        identifier, report = self.evaluate()
        self.assertEqual(report['models']['wilt']['operatingMetrics']['tp'], 1)
        evaluation.approve_evaluation(self.project, self.store, identifier, confirmed=True)
        proof = evaluation.release_evidence(self.project, self.store, self.thresholds)
        self.assertEqual(proof['models']['wilt']['checkpointSha256'], contract.file_hash(self.project.attribute_models['wilt']))
        from smartlabel.hydro_model_tools import threshold_defaults
        self.assertEqual(threshold_defaults(self.project)[0], self.thresholds)
        self.assertNotIn('dataset', str(proof))

    def test_checkpoint_threshold_benchmark_training_changes_invalidate(self):
        identifier, _ = self.evaluate()
        evaluation.approve_evaluation(self.project, self.store, identifier, confirmed=True)
        changed = deepcopy(self.thresholds); changed['wilt']['highThreshold'] = .9
        with self.assertRaisesRegex(ValueError, 'ngưỡng'): evaluation.release_evidence(self.project, self.store, changed)
        path = Path(self.project.attribute_models['wilt']); before = path.read_bytes(); path.write_bytes(b'new checkpoint')
        with self.assertRaisesRegex(ValueError, 'checkpoint'): evaluation.release_evidence(self.project, self.store, self.thresholds)
        path.write_bytes(before)
        learned = self.datasets['wilt'] / 'train' / 'present' / 'learned.png'
        Image.new('RGB', (24, 24), 'blue').save(learned)
        with self.assertRaisesRegex(ValueError, 'đã đổi'): evaluation.release_evidence(self.project, self.store, self.thresholds)

    def test_same_cycle_rejected_even_if_images_differ_and_missing_gateway(self):
        for path in self.datasets.values():
            meta = contract.read_json(path / 'export.json'); meta['source_records'][0]['source']['cropCycleId'] = 'season_external'
            (path / 'export.json').write_text(contract.canonical(meta), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Vụ TEST trùng'): self.evaluate()

    def test_duplicate_pixels_and_bytes_in_train_rejected(self):
        import shutil
        for path in self.datasets.values():
            shutil.copy2(self.store.image_path(self.project, self.project.images[1]), path / 'train' / 'present' / 'learned.png')
        with self.assertRaisesRegex(ValueError, 'trùng byte/pixel'): self.evaluate()

    def test_import_rejects_changed_hash_unknown_labels_and_path_traversal(self):
        original = contract.read_json(self.source / 'benchmark.json')
        for edit in (lambda m: m['records'][0].update(sha256='0'*64),
                     lambda m: m['records'][1]['labels'].update(wilt='uncertain'),
                     lambda m: m['records'][0].update(path='../outside.png')):
            metadata = deepcopy(original); edit(metadata)
            (self.source / 'benchmark.json').write_text(contract.canonical(metadata), encoding='utf-8')
            with self.assertRaises(ValueError): contract.import_benchmark(self.project, self.store, self.source)

    def test_cancellation_missing_class_and_attestation_block(self):
        cancel = Event(); cancel.set()
        with self.assertRaisesRegex(ValueError, 'hủy'): self.evaluate(cancel=cancel)
        with self.assertRaisesRegex(ValueError, 'xác nhận'):
            evaluation.evaluate_external(self.project, self.store, self.identifier, self.thresholds)
        root = contract.benchmark_root(self.store, self.project, self.identifier)
        manifest = contract.read_json(root / 'benchmark.json')
        for row in manifest['records'][1:]: row['labels']['wilt'] = 'positive'
        destination = self.root / 'one-class'; import shutil; shutil.copytree(root, destination)
        (destination / 'benchmark.json').write_text(contract.canonical(manifest), encoding='utf-8')
        self.identifier = contract.import_benchmark(self.project, self.store, destination)
        with self.assertRaisesRegex(ValueError, 'cả ảnh Có và Không'): self.evaluate()

    def test_save_failure_rolls_back_and_report_tampering_fails(self):
        identifier, _ = self.evaluate(); before = deepcopy(self.project.metadata)
        with patch.object(self.store, 'save', side_effect=OSError('full disk')):
            with self.assertRaises(OSError): evaluation.approve_evaluation(self.project, self.store, identifier, confirmed=True)
        self.assertEqual(self.project.metadata, before)
        path = contract.benchmark_root(self.store, self.project) / 'evaluations' / (identifier + '.json')
        report = contract.read_json(path); report['independenceAttested'] = False
        path.write_text(contract.canonical(report), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'thay đổi'): evaluation.load_evaluation(self.project, self.store, identifier)

    def test_split_rows_show_cycle_source_date_and_bulk_move_atomic(self):
        manager = DatasetManager(self.store)
        rows = manager.split_group_rows(self.project)
        self.assertIn('season_external', rows[0]['sources'])
        self.assertEqual(rows[0]['dates'], ['2026-09-22'])
        manager.set_groups_split(self.project, [r['group'] for r in rows], 'test')
        target = manager.split_assignment_path(self.project); before = target.read_bytes()
        with self.assertRaises(KeyError): manager.set_groups_split(self.project, [rows[0]['group'], 'missing'], 'train')
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(all(r['split'] == 'test' for r in manager.split_group_rows(self.project)))

    def test_no_release_from_qa_flag_only(self):
        self.project.metadata['validationStatus'] = 'validated_holdout'
        with self.assertRaisesRegex(ValueError, 'Chưa có đánh giá'): evaluation.release_evidence(self.project, self.store, self.thresholds)

    def test_approved_evidence_exports_exact_checkpoint_onnx_without_project_test(self):
        from smartlabel import hydro_export
        identifier, _ = self.evaluate()
        evaluation.approve_evaluation(self.project, self.store, identifier, confirmed=True)
        before = deepcopy(self.project.to_dict())
        config = {'datasetVersion': 'fixture', 'sourceCommit': 'fixture', 'cameraProfileIds': ['camera'],
                  'geometryProfileIds': ['geometry'], 'runtimeTarget': 'windows_onnxruntime_cpu',
                  'deploymentMode': 'operational', 'thresholds': self.thresholds}
        def convert(source, target, **kwargs):
            import onnx
            from onnx import helper, TensorProto
            model = helper.make_model(helper.make_graph(
                [helper.make_node('Constant', [], ['scores'], value=helper.make_tensor('v', TensorProto.FLOAT, [1, 2], [.2, .8]))],
                'fixture', [helper.make_tensor_value_info('images', TensorProto.FLOAT, [1, 3, 224, 224])],
                [helper.make_tensor_value_info('scores', TensorProto.FLOAT, [1, 2])]), opset_imports=[helper.make_opsetid('', 12)])
            helper.set_model_props(model, {'names': "{0: 'absent', 1: 'present'}"})
            onnx.save(model, target); return target
        with patch.object(hydro_export, 'hydro_dataset_qa', return_value={'issues': [], 'validationStatus': 'pilot_unvalidated'}), \
             patch.object(hydro_export, 'export_jetson_onnx', side_effect=convert):
            output = hydro_export.build_hydro_package(self.project, self.store, self.root / 'release', config, lambda _: None, Event())
            manifest = contract.read_json(output['bundle'] / 'bundle.json')
            self.assertEqual(manifest['deploymentMode'], 'operational')
            for key in self.thresholds:
                proof = manifest['evaluationEvidence']['models'][key]
                self.assertEqual(proof['onnxSha256'], manifest['models'][key]['sha256'])
                self.assertEqual(proof['checkpointSha256'], contract.file_hash(self.project.attribute_models[key]))
            def changed(source, target, **kwargs):
                result = convert(source, target, **kwargs)
                Path(self.project.attribute_models['wilt']).write_bytes(b'replaced mid-export')
                return result
            with patch.object(hydro_export, 'export_jetson_onnx', side_effect=changed), self.assertRaisesRegex(ValueError, '[Cc]heckpoint'):
                hydro_export.build_hydro_package(self.project, self.store, self.root / 'bad_release', config, lambda _: None, Event())
            self.assertFalse((self.root / 'bad_release').exists())
        self.assertEqual(self.project.to_dict(), before)

    def test_final_keep_test_ignores_compatibility_val_only_with_checkpoint_proof(self):
        import shutil
        attr = self.attrs[0]; dataset = self.datasets[attr['id']]
        (dataset / 'val' / 'present').mkdir()
        shutil.copy2(self.store.image_path(self.project, self.project.images[1]), dataset / 'val' / 'present' / 'image_1.png')
        metadata = contract.read_json(dataset / 'export.json')
        metadata.update(validation_enabled=False, split_strategy='final_keep_test')
        metadata['source_records'].append({'fileName': 'image_1.png', 'source': contract.source_identity(self.project.images[1])})
        (dataset / 'export.json').write_text(contract.canonical(metadata), encoding='utf-8')
        manifest, _ = contract.validate_benchmark(self.source, self.project)
        with self.assertRaisesRegex(ValueError, 'trùng'):
            evaluation.reject_overlap(manifest, evaluation.training_inventory(self.project, attr, dataset))
        evaluation.reject_overlap(manifest, evaluation.training_inventory(self.project, attr, dataset, validation_used=False))

    def test_generic_import_blocks_benchmark_images_before_copy(self):
        other = self.store.create_project('Other')
        with self.assertRaisesRegex(ValueError, 'TEST ngoài'): self.store.import_images(other, [self.source])
        self.assertFalse(other.images)

    def test_source_snapshot_export_and_legacy_missing_provenance_fail_closed(self):
        for attr in self.attrs:
            dataset = self.datasets[attr['id']]
            metadata = contract.read_json(dataset / 'export.json'); metadata.pop('source_records')
            (dataset / 'export.json').write_text(contract.canonical(metadata), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Thiếu nguồn vụ'): self.evaluate()

    def test_all_uncertain_predictions_show_zero_coverage_not_high_accuracy(self):
        result = evaluation.operating_metrics([(1, .5), (0, .5)], self.thresholds['wilt'])
        self.assertEqual(result['coverage'], 0)
        self.assertEqual(result['positiveDetectionRateAll'], 0)
