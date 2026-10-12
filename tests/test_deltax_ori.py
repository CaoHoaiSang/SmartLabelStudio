from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import ast
import hashlib
import json
import math
import os
import subprocess
import sys
import unittest

import numpy as np
from PIL import Image

from smartlabel.dataset_manager import DatasetManager
from smartlabel.models import Annotation
from smartlabel.ori_geometry import annotation_to_ori
from smartlabel.model_export import inspect_deltax_rknn
from smartlabel.project_store import ProjectStore

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "tools" / "studio_integration"


def load_function(payload, name, namespace):
    tree = ast.parse((BUNDLE / "files" / payload).read_text(encoding="utf-8"))
    node = max((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name), key=lambda n: n.lineno)
    exec(compile(ast.Module(body=[node], type_ignores=[]), payload, "exec"), namespace)
    return namespace[name]


def label(angle=0, frame_angle=0):
    cx, cy, w, h = 100, 60, 80, 32
    r = math.radians(frame_angle)
    points = [[cx + x * math.cos(r) - y * math.sin(r), cy + x * math.sin(r) + y * math.cos(r)]
              for x, y in ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2))]
    ann = Annotation.create_box(0, [60, 44, 80, 32])
    ann.obb = points
    ann.orientation = [[cx, cy], [cx + 12 * math.cos(math.radians(angle)), cy + 12 * math.sin(math.radians(angle))]]
    return ann


class OriDatasetTests(unittest.TestCase):
    def test_epoch_checkpoint_metadata_survives_cancellation_and_refreshes_after_stripping(self):
        from smartlabel.ori_worker import stamp_checkpoints
        with TemporaryDirectory() as temp:
            weights = Path(temp) / "weights"
            weights.mkdir()
            checkpoint = weights / "best.pt"
            checkpoint.write_bytes(b"completed epoch")
            trainer = SimpleNamespace(save_dir=temp)
            stamp_checkpoints(trainer)
            info = json.loads(checkpoint.with_suffix(".ori.json").read_text())
            self.assertEqual(info["model_sha256"], hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            self.assertFalse((weights / "last.ori.json").exists())
            checkpoint.write_bytes(b"stripped final model")
            stamp_checkpoints(trainer)
            self.assertNotEqual(info["model_sha256"], json.loads(checkpoint.with_suffix(".ori.json").read_text())["model_sha256"])
            self.assertFalse(list(weights.glob("*.tmp")))

    def test_non_square_image_preserves_independent_corners_and_pixel_heading(self):
        ann = label(32, 32)
        values = [float(x) for x in annotation_to_ori(ann, 200, 120).split()]
        self.assertEqual(len(values), 10)
        np.testing.assert_allclose(np.array(values[1:9]).reshape(4, 2) * [200, 120], ann.obb, atol=2e-6)
        # Heading is normalized with its own vector, then restored by the trainer.
        r = math.radians(values[-1])
        self.assertAlmostEqual(math.degrees(math.atan2(math.sin(r) * 120, math.cos(r) * 200)), 32, places=5)

    def test_head_tail_remain_distinct(self):
        self.assertEqual(float(annotation_to_ori(label(), 200, 120).split()[-1]), 0)
        self.assertEqual(float(annotation_to_ori(label(180), 200, 120).split()[-1]), -180)

    def test_missing_off_center_free_angle_and_degenerate_labels_are_rejected(self):
        variants = [label(), label(), label(20), label(), label()]
        variants[0].orientation = []
        variants[1].orientation[0] = [60, 60]
        variants[3].obb[1] = variants[3].obb[0]
        variants[4].orientation[1] = [float("nan"), 10]
        for ann in variants:
            with self.subTest(ann=ann), self.assertRaises(ValueError):
                annotation_to_ori(ann, 200, 120)

    def test_export_checks_all_labels_before_creating_snapshot_and_does_not_mutate_them(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.png"
            Image.new("RGB", (200, 120)).save(source)
            store = ProjectStore(root / "workspace")
            project = store.create_project("ORI", classes=["part"])
            store.import_images(project, [source])
            record = project.images[0]
            record.review_status = "reviewed"
            record.annotations = [label()]
            record.annotations[0].orientation = []
            manager = DatasetManager(store)
            with self.assertRaisesRegex(ValueError, "chưa xuất dataset"):
                manager.export_yolo(project, task="ori")
            self.assertEqual(list((store.project_dir(project) / "exports").iterdir()), [])
            record.annotations = [label(180)]
            before = record.annotations[0].to_dict()
            exported = manager.export_yolo(project, task="ori")
            self.assertEqual(record.annotations[0].to_dict(), before)
            self.assertIn("corners_normalized_heading_v1", (exported / "data.yaml").read_text())
            text = next((exported / "labels").rglob("*.txt")).read_text()
            self.assertEqual(len(text.split()), 10)
            self.assertEqual(float(text.split()[-1]), -180)


class StudioContractTests(unittest.TestCase):
    def test_aix_metadata_rejection_reports_original_error_when_no_model_was_opened(self):
        errors = []
        def reject(*args, **kwargs):
            raise ValueError('ORI metadata and labels do not match')
        start = load_function('0.py', 'start_aix', {
            'os': os, 'platform': SimpleNamespace(system=lambda: 'Linux'), 'USE_YOLORKNN': True,
            'Task': SimpleNamespace(DET=0, ORI=1), 'YOLORKNN': reject,
            'log_error': lambda *args: None, 'LogModule': SimpleNamespace(AIX=0),
            'LogLevel': SimpleNamespace(ERROR=0)})
        with TemporaryDirectory() as tmp:
            (Path(tmp) / 'part.rknn').write_bytes(b'metadata-rejection fixture')
            owner = SimpleNamespace(scan_models=lambda: None, enabled=True, models_dir=tmp,
                aix_project_name='part', model_list=['part'], model_type='ORI', aix_list_objects=['part'],
                conf=.5, iou=.5, aix_error_signal=SimpleNamespace(emit=errors.append))
            start(owner)
            self.assertFalse(hasattr(owner, 'model'))
            self.assertEqual(errors, ['Error initializing AIX model: ORI metadata and labels do not match'])

    def test_metadata_rejection_happens_before_opening_npu_and_legacy_still_loads(self):
        from enum import Enum
        from typing import Type, List
        class Task(Enum):
            DET = 0
            SEG = 1
            OBB = 2
            ORI = 3
        opened = []
        class Predictor:
            def __init__(self, **kwargs):
                opened.append(kwargs)
        tree = ast.parse((BUNDLE / "files" / "3.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "YOLORKNN")
        namespace = {"Task":Task, "BaseYoloModel":object, "Path":Path, "hashlib":hashlib, "json":json, "Type":Type,"List":List,
            **{name:Predictor for name in ("BaseRKNNYoloPredictor","DetRKNNPredictor","SegRKNNPredictor","OBBRKNNPredictor","OriRKNNPredictor")}}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),"Studio YOLORKNN","exec"),namespace)
        with TemporaryDirectory() as temp:
            model = Path(temp) / "ori.rknn"
            model.write_bytes(b"synthetic model fixture")
            manifest = {"task":"ori","target":"rk3588","compiler":"rknn-toolkit2==2.2.0", "output_layout":"deltax_orienty_5_heads_v1",
                "output_shapes":[[1,65,s,s] for s in (80,40,20)]+[[1,1,8400]]*2,"imgsz":[640,640],"heading":"image_x_clockwise_degrees",
                "names":{"0":"part"}, "model_sha256":hashlib.sha256(model.read_bytes()).hexdigest()}
            for change in ({"model_sha256":"wrong"}, {"names":{"0":"other"}}, {"task":"pose"}, {"imgsz":[320,320]}):
                model.with_suffix(".json").write_text(json.dumps({**manifest,**change}))
                with self.assertRaises(ValueError):
                    namespace["YOLORKNN"](Task.ORI,str(model),["part"])
                self.assertEqual(opened,[])
            model.with_suffix(".json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "requires the ORI task"):
                namespace["YOLORKNN"](Task.DET,str(model),["part"])
            self.assertEqual(opened,[])
            namespace["YOLORKNN"](Task.ORI,str(model),["part"])
            self.assertEqual(len(opened),1)
            model.with_suffix(".json").unlink()
            namespace["YOLORKNN"](Task.ORI,str(model),["part"])
            self.assertEqual(len(opened),2)

    def test_all_four_directions_and_wrap_choose_nearest_frame_axis(self):
        snap = load_function("4.py", "regularize_orientBoxes", {"np": np, "PI": math.pi, "TWO_PI": 2 * math.pi})
        frames = np.repeat([[100., 60., 80., 32., math.radians(120)]], 4, axis=0)
        frames, headings = snap(frames, np.array([120., -150., -60., 30.]))
        np.testing.assert_allclose(headings, [120, -150, -60, 30], atol=1e-5)
        np.testing.assert_allclose(frames[:, 2:4], [[80,32], [32,80], [80,32], [32,80]])

    def test_ori_decoder_rejects_wrong_output_count_shape_classes_and_nonfinite(self):
        prepare = load_function("2.py", "_prepare_endnodes", {"np": np, "sigmoid": lambda x: 1/(1+np.exp(-x)), "List": list})
        owner = SimpleNamespace(names=["part"])
        tensors = [np.zeros((1,65,s,s), np.float32) for s in (80,40,20)] + [np.zeros((1,1,8400), np.float32)] * 2
        self.assertEqual(len(prepare(owner, tensors)), 12)
        for invalid in (tensors[:4], [np.zeros((1,66,80,80))]+tensors[1:], tensors[:3]+[np.zeros((1,1,8399))]+tensors[4:]):
            with self.assertRaises(ValueError):
                prepare(owner, invalid)
        tensors[0][0,0,0,0] = float("nan")
        with self.assertRaisesRegex(ValueError, "NaN"):
            prepare(owner, tensors)

    def test_aix_legacy_obb_radians_and_ori_degrees_keep_existing_tracking_sign(self):
        process = load_function("0.py", "process_object_infos", {"math": math, "platform": SimpleNamespace(system=lambda: "Linux")})
        received = []
        owner = SimpleNamespace(_get_conf_threshold=lambda name: .1, model_type="ORI", aix_list_objects=["part"],
            is_rotated_box_touching_edge=lambda *args: False, is_has_request_save_annotations=False,
            got_objects=SimpleNamespace(emit=lambda infos: received.extend(infos)))
        base = {"name":"part", "x":100,"y":60,"w":80,"h":32,"conf":.9}
        process(owner, {"type":"obb", "data":[{**base,"angle":math.pi/6}]}, 200, 120)
        self.assertAlmostEqual(received[-1][3], -30)
        process(owner, {"type":"orient", "data":[{**base,"deg":60,"angle":1}]}, 200, 120)
        self.assertEqual(received[-1][3], -60)
        process(owner, {"type":"orient", "data":[{**base,"deg":float("nan")}]}, 200, 120)
        self.assertEqual(len(received), 2)

    def test_ori_rknn_requires_bound_manifest_shapes_hash_and_simulator_check(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "model.rknn"
            shapes = [[1,65,s,s] for s in (80,40,20)] + [[1,1,8400]] * 2
            path.write_bytes(("compiler version: 2.2.0\n"+"\n".join(f"'shape': {s}" for s in shapes)).encode()+b"\0"*2048)
            manifest = {"task":"ori","target":"rk3588","output_layout":"deltax_orienty_5_heads_v1","output_shapes":shapes,"imgsz":[640,640],
                "heading":"image_x_clockwise_degrees","model_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"verification":{"rknn_simulator_vs_pt":True}}
            path.with_suffix(".json").write_text(json.dumps(manifest))
            self.assertEqual(inspect_deltax_rknn(path,image_size=640,class_count=1,task="ori")["outputs"],5)
            for change in ({"model_sha256":"changed"}, {"heading":"up"}, {"verification":{}}, {"output_shapes":[[1,6,8400]]}):
                path.with_suffix(".json").write_text(json.dumps({**manifest, **change}))
                with self.assertRaises(RuntimeError):
                    inspect_deltax_rknn(path,image_size=640,class_count=1,task="ori")


class OriForkTests(unittest.TestCase):
    def test_isolated_fork_loader_augmentation_metrics_loss_and_raw_output_contract(self):
        code = '''
import math, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from smartlabel.ori_worker import load_model
model = load_model("deltax-yolov8n-ori")
from ultralytics.utils.ops import vectorFromDegree, degreeFromVector, regularize_orientyBoxes
from ultralytics.utils.instance import Instances
from ultralytics.utils.metrics import deg_tolerances
from ultralytics.utils.loss import v8OrientationLoss
from ultralytics.models.yolo.orienty.val import OrientationValidator
from ultralytics.data.utils import verify_image_label
from tools.rknn_converter.export_ori import install_ori_raw_forward, expected_shapes
assert abs(degreeFromVector(vectorFromDegree(32))-32) < 1e-6
instances=Instances(np.array([[.5,.5,.4,.3]]), np.array([[[.3,.3],[.7,.3],[.7,.6],[.3,.6]]]), degs=np.array([math.degrees(math.atan2(math.sin(math.radians(32))/120,math.cos(math.radians(32))/200))]), normalized=True)
instances.denormalize(200,120)
assert abs(instances.degs[0]-32)<1e-5
instances.flipud(120); assert abs(instances.degs[0]+32)<1e-5
instances.fliplr(200); assert abs(instances.degs[0]+148)<1e-5
assert abs(float(deg_tolerances(torch.tensor([179.]), torch.tensor([-179.]))[0,0])-.9)<1e-5
assert float(deg_tolerances(torch.tensor([0.]), torch.tensor([11.]))[0,0])==0
loss=v8OrientationLoss.calculate_degs_loss(None,torch.tensor([179.]),torch.tensor([[True]]),torch.tensor([[0]]),torch.tensor([0]),torch.tensor([[[-179.]]]))
assert loss<.001 and loss>0
validator=OrientationValidator(args={"plots":False})
validator.iouv=torch.linspace(.5,.95,10)
pred=torch.tensor([[500.,500.,40.,20.,.9,0.,0.,0.]])
truth=torch.tensor([[50.,50.,40.,20.,0.]])
assert not validator._process_batch(pred,truth,torch.tensor([0]),torch.tensor([0.])).any()
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);Image.new("RGB",(200,120)).save(p/"image.png")
 (p/"label.txt").write_text("0 .3 .3 .7 .3 .7 .6 .3 .6 -180")
 result=verify_image_label((str(p/"image.png"),str(p/"label.txt"),"",False,1,0,0,True))
 assert result[0] is not None and len(result[3][0])==4 and result[4][0]==-180
 (p/"label.txt").write_text("0 .5 .5 .4 .3 0")
 assert verify_image_label((str(p/"image.png"),str(p/"label.txt"),"",False,1,0,0,True))[0] is None
head=model.model.model[-1]
for branch in head.cv5:
 branch[-1].weight.data.zero_();branch[-1].bias.data.fill_(.5)
for branch in head.cv4:
 branch[-1].weight.data.zero_();branch[-1].bias.data.zero_()
install_ori_raw_forward(head)
with torch.no_grad(): outputs=model.model.eval()(torch.zeros((1,3,640,640)))
assert [list(x.shape) for x in outputs]==expected_shapes(80)
assert torch.allclose(outputs[-1],torch.full_like(outputs[-1],.5))
assert torch.allclose(outputs[-2],torch.full_like(outputs[-2],.5))
print("ORI_FORK_CONTRACT_OK")
'''
        result = subprocess.run([sys.executable,"-X","utf8","-c",code],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120,
                                env={**os.environ,"PYTHONIOENCODING":"utf-8"})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("ORI_FORK_CONTRACT_OK",result.stdout)


if __name__ == "__main__":
    unittest.main()
