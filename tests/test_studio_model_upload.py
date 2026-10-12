"""Exercise the actual Radxa upload handlers without Qt, NPU or robot control."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.studio_integration.upload import rknn_model_upload as store
from tools.studio_integration.upload.prepare_patch import console_patch
from tools.studio_integration.upload.apply_patch import apply
from tools.studio_integration import apply_patch as runtime_patch

ROOT = Path(__file__).resolve().parents[1]
BINARY = b"synthetic model bytes for contract tests"


def metadata():
    return {
        'schema': 1, 'format': 'rknn', 'task': 'ori', 'target': 'rk3588',
        'compiler': 'rknn-toolkit2==2.2.0', 'imgsz': [640, 640],
        'names': {'0': 'part: test'}, 'model_sha256': hashlib.sha256(BINARY).hexdigest(),
        'output_layout': 'deltax_orienty_5_heads_v1',
        'output_shapes': [[1, 65, s, s] for s in (80, 40, 20)] + [[1, 1, 8400]] * 2,
        'heading': 'image_x_clockwise_degrees', 'heading_scale': 180,
        'obb_angle': '(sigmoid - 0.25) * pi', 'heading_refinement': 'snap_to_obb_axis_4_directions',
        'normalization': {'mean': [0, 0, 0], 'std': [255, 255, 255], 'rgb2bgr': False},
        'input_contract': {'runtime_layout': 'NHWC', 'dtype': 'uint8', 'color': 'RGB', 'resize': 'letterbox'},
        'verification': {'onnx_vs_pt': True, 'rknn_simulator_vs_pt': True, 'hardware_validated': False},
    }


class ModelPairTests(unittest.TestCase):
    def test_valid_pair_and_legacy_replacement_removes_stale_json(self):
        with TemporaryDirectory() as tmp:
            name, meta = store.save_model_pair(tmp, 'renamed.RKNN', BINARY, json.dumps(metadata()))
            self.assertEqual(name, 'renamed')
            self.assertEqual(meta['names'], {'0': 'part: test'})
            self.assertEqual((Path(tmp) / 'renamed.rknn').read_bytes(), BINARY)
            self.assertFalse(meta['verification']['hardware_validated'])
            store.save_model_pair(tmp, 'renamed.rknn', b'legacy')
            self.assertFalse((Path(tmp) / 'renamed.json').exists())
            self.assertEqual(list(Path(tmp).iterdir()), [Path(tmp) / 'renamed.rknn'])

    def test_invalid_pair_cannot_replace_either_existing_file(self):
        changes = [dict(model_sha256='wrong'), dict(task='pose'), dict(target='rk3568'),
                   dict(imgsz=[320, 320]), dict(output_shapes=[[1, 65, 80, 80]]),
                   dict(names={'1': 'part'}), dict(names={'0': 'part,wrong'}),
                   dict(names={'0': 'same', '1': 'same'}), dict(verification={}),
                   dict(normalization={}), dict(input_contract={}), dict(heading_scale=360)]
        with TemporaryDirectory() as tmp:
            model, sidecar = Path(tmp) / 'part.rknn', Path(tmp) / 'part.json'
            model.write_bytes(b'old model'); sidecar.write_bytes(b'old metadata')
            for changeset in changes:
                with self.subTest(changeset=changeset), self.assertRaises(ValueError):
                    store.save_model_pair(tmp, 'part.rknn', BINARY, json.dumps({**metadata(), **changeset}))
                self.assertEqual(model.read_bytes(), b'old model')
                self.assertEqual(sidecar.read_bytes(), b'old metadata')

    def test_filename_limits_empty_and_invalid_json(self):
        with TemporaryDirectory() as tmp:
            for name in ('../x.rknn', 'a\\b.rknn', '', '.rknn', 'x.json'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    store.save_model_pair(tmp, name, BINARY)
            for value in ('[]', '{', ' ' * 65537, 123):
                with self.subTest(value=str(value)[:15]), self.assertRaises(ValueError):
                    store.save_model_pair(tmp, 'a.rknn', BINARY, value)
            with self.assertRaises(ValueError):
                store.save_model_pair(tmp, 'a.rknn', b'')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_running_and_start_during_staging_preserve_destination(self):
        with TemporaryDirectory() as tmp:
            states = iter([True, False])
            with self.assertRaisesRegex(ValueError, 'started'):
                store.save_model_pair(tmp, 'a.rknn', BINARY, can_save=lambda: next(states))
            self.assertEqual(list(Path(tmp).iterdir()), [])
            with self.assertRaisesRegex(ValueError, 'running'):
                store.save_model_pair(tmp, 'a.rknn', BINARY, can_save=lambda: False)

    def test_failed_model_replace_restores_complete_previous_pair(self):
        with TemporaryDirectory() as tmp:
            model, sidecar = Path(tmp) / 'a.rknn', Path(tmp) / 'a.json'
            model.write_bytes(b'old'); sidecar.write_bytes(b'old json')
            real_replace = os.replace
            def fail_once(src, dest):
                if Path(src).name == 'model':
                    raise OSError('injected commit failure')
                real_replace(src, dest)
            with patch.object(store.os, 'replace', side_effect=fail_once), self.assertRaises(OSError):
                store.save_model_pair(tmp, 'a.rknn', BINARY, json.dumps(metadata()))
            self.assertEqual(model.read_bytes(), b'old')
            self.assertEqual(sidecar.read_bytes(), b'old json')
            self.assertEqual(len(list(Path(tmp).iterdir())), 2)

    def test_concurrent_pairs_never_leave_model_and_json_from_different_uploads(self):
        with TemporaryDirectory() as tmp:
            errors = []
            def upload(index):
                data = BINARY + bytes([index])
                meta = metadata(); meta['model_sha256'] = hashlib.sha256(data).hexdigest()
                try:
                    store.save_model_pair(tmp, 'a.rknn', data, json.dumps(meta))
                except Exception as exc:
                    errors.append(exc)
            workers = [threading.Thread(target=upload, args=(i,)) for i in range(8)]
            for worker in workers: worker.start()
            for worker in workers: worker.join()
            self.assertEqual(errors, [])
            digest = hashlib.sha256((Path(tmp) / 'a.rknn').read_bytes()).hexdigest()
            self.assertEqual(json.loads((Path(tmp) / 'a.json').read_text())['model_sha256'], digest)


class UploadHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        fixture = (ROOT / 'tests/fixtures/studio_upload/console_upload.py').read_text()
        changed = console_patch(fixture)
        class Thread:
            def __init__(self, target, args, daemon): self.target, self.args = target, args
            def start(self): self.target(*self.args)
        env = {'__file__': str(Path(self.temp.name) / 'Console.py'),
               'os': os, 'base64': base64, 'time': __import__('time'),
               'threading': SimpleNamespace(Thread=Thread), 'save_model_pair': store.save_model_pair}
        with patch.dict('sys.modules', {'rknn_model_upload': store}):
            exec(compile(changed, 'Radxa Console upload handlers', 'exec'), env)
        self.owner = env['Console']()
        self.owner.is_system_running = False
        self.owner._rknn_upload_sessions = {}
        self.owner._rknn_upload_sessions_lock = threading.RLock()
        self.owner.system_settings = {'aix': {'list_models': []}}
        self.events = []
        self.owner.emitToServer = lambda event, data: self.events.append((event, data))

    def chunks(self, paired=True):
        encoded = base64.b64encode(BINARY).decode()
        self.parts = [encoded[:8], encoded[8:]]
        for i, data in enumerate(self.parts):
            self.owner.upload_rknn_file_chunk(dict(upload_id='session', file_name='part.rknn',
                total_chunks=2, chunk_index=i, chunk_data=data, **({'upload_contract': 'paired-v1'} if paired else {})))

    def finalize(self, **kwargs):
        self.owner.upload_rknn_file_finalize(dict(upload_id='session', file_name='part.rknn', total_chunks=2,
            require_metadata=True, metadata_json=json.dumps(metadata()), **kwargs))

    def result(self):
        return [d for e, d in self.events if e == 'rknn_upload_response'][-1]

    def test_paired_chunks_wait_for_finalize_then_return_verified_names(self):
        self.chunks()
        self.assertFalse((Path(self.temp.name) / 'models/part.rknn').exists())
        self.assertFalse(any(e == 'rknn_upload_response' for e, d in self.events))
        self.owner.upload_rknn_file_chunk(dict(upload_id='session', file_name='part.rknn', total_chunks=2,
            chunk_index=0, chunk_data=self.parts[0], upload_contract='paired-v1'))
        self.assertEqual([d for e, d in self.events if e == 'rknn_upload_chunk_ack'][-1]['status'], 'duplicate')
        self.finalize()
        self.assertEqual(self.result()['status'], 'success')
        self.assertEqual(self.result()['metadata']['names'], {'0': 'part: test'})
        self.assertEqual(self.owner.system_settings['aix']['list_models'], ['part'])
        self.assertEqual(self.owner._rknn_upload_sessions, {})

    def test_legacy_clients_still_auto_finalize(self):
        self.chunks(paired=False)
        self.assertEqual(self.result()['status'], 'success')
        self.assertIsNone(self.result()['metadata'])

    def test_wrong_sha_keeps_previous_pair_and_cleans_session(self):
        root = Path(self.temp.name) / 'models'; root.mkdir()
        (root / 'part.rknn').write_bytes(b'previous'); (root / 'part.json').write_bytes(b'previous json')
        self.chunks()
        bad = metadata(); bad['model_sha256'] = 'wrong'
        self.owner.upload_rknn_file_finalize(dict(upload_id='session', file_name='part.rknn', total_chunks=2,
            metadata_json=json.dumps(bad)))
        self.assertEqual(self.result()['status'], 'error')
        self.assertEqual((root / 'part.rknn').read_bytes(), b'previous')
        self.assertEqual((root / 'part.json').read_bytes(), b'previous json')
        self.assertEqual(self.owner._rknn_upload_sessions, {})

    def test_running_during_finalize_cannot_save(self):
        self.chunks(); self.owner.is_system_running = True
        self.finalize()
        self.assertEqual(self.result()['status'], 'error')
        self.assertFalse((Path(self.temp.name) / 'models').exists())

    def test_missing_required_json_and_mismatched_finalize_cannot_save(self):
        self.chunks()
        for changed in ({'require_metadata': True}, {'file_name': 'other.rknn'}, {'total_chunks': 1}):
            request = dict(upload_id='session', file_name='part.rknn', total_chunks=2)
            request.update(changed); self.owner.upload_rknn_file_finalize(request)
            self.assertEqual(self.result()['status'], 'error')
        self.assertFalse((Path(self.temp.name) / 'models').exists())


class PatchApplyTests(unittest.TestCase):
    def test_original_installer_and_live_upload_response_spacing_are_supported(self):
        source = (ROOT / 'tests/fixtures/studio_upload/console_upload.py').read_text()
        old = '"message": f"File {file_name} uploaded successfully",\n'
        alternate = source.replace(old, old.replace(',\n', ', \n'))
        self.assertIn('"metadata": metadata', console_patch(alternate))

    def test_runtime_layout_updates_installed_library_and_accepts_reviewed_previous_patch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); bundle = root / 'bundle'; backend = root / 'backend'
            bundle.mkdir(); package = backend / 'venv/lib/python3.11/site-packages/YOLORKNN'
            package.mkdir(parents=True)
            target = package / 'ops.py'; target.write_bytes(b'previous patch')
            payload = bundle / 'ops.py'; payload.write_bytes(b'updated patch')
            (bundle / 'manifest.json').write_text(json.dumps({'files': [dict(
                path='deltax_pp_sw/ultralytics_rknn-new/YOLORKNN/ops.py', payload='ops.py',
                before_sha256=hashlib.sha256(b'original').hexdigest(),
                compatible_sha256=[hashlib.sha256(b'previous patch').hexdigest()],
                after_sha256=hashlib.sha256(b'updated patch').hexdigest())]}))
            with patch.object(runtime_patch, '__file__', str(bundle / 'apply_patch.py')):
                runtime_patch.apply(backend, root / 'backup', 'radxa')
                runtime_patch.apply(backend, root / 'backup', 'radxa')
            self.assertEqual(target.read_bytes(), b'updated patch')
            self.assertEqual((root / 'backup/venv/lib/python3.11/site-packages/YOLORKNN/ops.py').read_bytes(), b'previous patch')

    def test_changed_source_is_rejected_before_any_mutation_and_apply_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); bundle = root / 'bundle'; backend = root / 'backend'; web = root / 'web'
            for p in (bundle, backend, web): p.mkdir()
            entries = []
            for name in ('one.py', 'two.py'):
                (backend / name).write_bytes(b'before'); (bundle / name).write_bytes(b'after')
                entries.append(dict(profile='backend', path=name, payload=name,
                    before_sha256=hashlib.sha256(b'before').hexdigest(), after_sha256=hashlib.sha256(b'after').hexdigest()))
            (bundle / 'manifest.json').write_text(json.dumps({'files': entries}))
            (backend / 'two.py').write_bytes(b'user edit')
            with self.assertRaises(ValueError): apply(bundle, backend, web, root / 'backup')
            self.assertEqual((backend / 'one.py').read_bytes(), b'before')
            (backend / 'two.py').write_bytes(b'before')
            apply(bundle, backend, web, root / 'backup'); apply(bundle, backend, web, root / 'backup')
            self.assertEqual((backend / 'one.py').read_bytes(), b'after')
            self.assertEqual((root / 'backup/backend/one.py').read_bytes(), b'before')


if __name__ == '__main__':
    unittest.main()
