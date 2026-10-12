"""YOLO11 ORI identity, output contract and backwards-compatible checkpoints."""
from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import unittest

from smartlabel.ori_runtime import ORI_MODEL, ORI_MODEL_PRESETS
from tools.ori_runtime.deltax_ori_contract import model_architecture

ROOT = Path(__file__).resolve().parents[1]


class Yolo11OriTests(unittest.TestCase):
    def test_model_identity_does_not_require_loading_a_yolo_runtime(self):
        self.assertEqual(ORI_MODEL, 'deltax-yolo11n-ori')
        self.assertEqual(model_architecture(SimpleNamespace(yaml={'yaml_file': '/old/yolov8n-ori.yaml', 'scale': 'n'})),
                         {'family': 'yolov8', 'scale': 'n'})
        windows_yaml = SimpleNamespace(yaml={'yaml_file': r'D:\old\yolov8n-ori.yaml', 'scale': 'n'})
        self.assertEqual(model_architecture(windows_yaml), {'family': 'yolov8', 'scale': 'n'})
        wrapped = SimpleNamespace(module=SimpleNamespace(yaml={'deltax_architecture': 'yolo11', 'scale': 's'}))
        self.assertEqual(model_architecture(wrapped), {'family': 'yolo11', 'scale': 's'})
        for scale in 'nslmx':
            self.assertEqual(ORI_MODEL_PRESETS[f'deltax-yolo11{scale}-ori'][2], f'yolo11{scale}.pt')

    def _worker(self, code, *args, ok=True):
        # Each loader owns its pinned Ultralytics process, as in the application.
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, *map(str, args)], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_all_yolo11_scales_keep_the_studio_raw_output_contract(self):
        code = """
import sys, torch
from smartlabel.ori_worker import load_model
from tools.ori_runtime.deltax_ori_contract import model_architecture
from tools.rknn_converter.export_ori import install_ori_raw_forward
scale=sys.argv[1]
model=load_model('deltax-yolo11'+scale+'-ori')
assert model_architecture(model.model)=={'family':'yolo11','scale':scale}
assert any(m.__class__.__name__=='C3k2' for m in model.model.modules())
assert any(m.__class__.__name__=='C2PSA' for m in model.model.modules())
install_ori_raw_forward(model.model.model[-1])
size=640 if scale=='n' else 96
with torch.no_grad():outputs=model.model.eval()(torch.zeros(1,3,size,size))
expected=[[1,144,size//s,size//s] for s in (8,16,32)]+[[1,1,sum((size//s)**2 for s in (8,16,32))],[1,2,sum((size//s)**2 for s in (8,16,32))]]
assert [list(t.shape) for t in outputs]==expected
assert all(torch.isfinite(t).all() for t in outputs)
"""
        for scale in 'nslmx':
            with self.subTest(scale=scale):
                self._worker(code, scale)

    def test_old_v8_checkpoint_is_accepted_and_wrong_architecture_is_rejected(self):
        import tempfile
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'legacy.pt'
            self._worker("""
import sys,hashlib,json,torch
from pathlib import Path
from smartlabel.ori_worker import load_model
path=Path(sys.argv[1])
model=load_model('deltax-yolov8n-ori')
head=model.model.model[-1]
del head.heading_components
for branch in head.cv5:branch[-1]=torch.nn.Conv2d(branch[-1].in_channels,1,1)
torch.save({'model':model.model,'train_args':{'task':'orienty'}},path)
metadata={'schema':'deltax_ori_checkpoint_v1','heading':'image_x_clockwise_degrees','model_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
path.with_suffix('.ori.json').write_text(json.dumps(metadata))
""", path)
            inspect = "import sys;from smartlabel.ori_worker import load_model;assert load_model(sys.argv[1]).task=='orienty'"
            self._worker(inspect, path)
            sidecar = path.with_suffix('.ori.json')
            metadata = json.loads(sidecar.read_text())
            metadata['architecture'] = {'family': 'yolo11', 'scale': 'n'}
            sidecar.write_text(json.dumps(metadata))
            result = self._worker(inspect, path, ok=False)
            self.assertIn('metadata', result.stderr)
        self._worker("from smartlabel.ori_worker import load_model;load_model('deltax-yolo11z-ori')", ok=False)


if __name__ == '__main__':
    unittest.main()
