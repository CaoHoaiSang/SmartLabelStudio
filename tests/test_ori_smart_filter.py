from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import math
import unittest

import numpy as np

from smartlabel.annotation_geometry import direction, envelope
from smartlabel.frame_filter import FrameFilterSettings, _detection_metrics, _run_yolo
from smartlabel import ori_worker


class Array:
    def __init__(self, values): self.values = np.asarray(values)
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return self.values
    def tolist(self): return self.values.tolist()


def result(angle=32, empty=False):
    cx, cy, w, h = 100, 80, 80, 40
    r = math.radians(angle)
    corners = [[cx+x*math.cos(r)-y*math.sin(r), cy+x*math.sin(r)+y*math.cos(r)]
               for x, y in ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2))]
    bbox = envelope(corners)
    class Boxes:
        def __len__(self): return 0 if empty else 1
    boxes = Boxes()
    boxes.conf = Array([] if empty else [.8])
    boxes.cls = Array([] if empty else [0])
    boxes.xyxy = Array([] if empty else [[bbox[0],bbox[1],bbox[0]+bbox[2],bbox[1]+bbox[3]]])
    boxes.xyxyxyxy = Array([] if empty else [corners])
    boxes.xywhr = Array([] if empty else [[cx,cy,w,h,r]])
    return SimpleNamespace(boxes=None, obb=boxes, orig_shape=(160,200))


class OriSmartFilterTests(unittest.TestCase):
    def test_rotated_results_are_counted_with_rotated_area_not_envelope(self):
        metrics = _detection_metrics(result(), 200,160,.2)
        self.assertEqual(metrics['accepted'],1)
        self.assertAlmostEqual(metrics['coverage'],.1)
        self.assertEqual(metrics['edge'],0)
        self.assertEqual(_detection_metrics(result(empty=True),200,160,.2)['accepted'],0)
        self.assertEqual(_detection_metrics(result(),200,160,.9)['weak'],1)

    def test_standard_rect_metrics_are_preserved(self):
        class Boxes(SimpleNamespace):
            def __len__(self):return 2
        boxes=Boxes(conf=Array([.8,.1]),xyxy=Array([[0,0,40,20],[50,30,60,40]]))
        metrics=_detection_metrics(SimpleNamespace(boxes=boxes),100,50,.2)
        self.assertEqual(metrics,{'accepted':1.,'weak':1.,'confidence':.8,'coverage':.16,'edge':1.})

    def test_ori_filter_reuses_one_process_for_chunks_and_closes_on_error_or_cancel(self):
        with TemporaryDirectory() as tmp:
            model=Path(tmp)/'best.pt';model.with_suffix('.ori.json').write_text('{}')
            paths=[Path(f'image{i}.jpg') for i in range(25)]
            sessions=[]
            class Worker:
                def __init__(self,*args): self.batches=[];self.closed=False;sessions.append(self)
                def filter_metrics(self,chunk,threshold):
                    self.batches.append(len(chunk));return [{'accepted':1.} for _ in chunk]
                def close(self):self.closed=True
            with patch('smartlabel.ori_runtime.OriAutoLabeler',Worker):
                metrics=_run_yolo(paths,model,FrameFilterSettings(),None,None)
                self.assertEqual(len(metrics),25)
                self.assertEqual(sessions[-1].batches,[24,1])
                self.assertTrue(sessions[-1].closed)
                cancel=Event();cancel.set()
                with self.assertRaises(InterruptedError):_run_yolo(paths,model,FrameFilterSettings(),None,cancel)
                self.assertTrue(sessions[-1].closed)
                with patch.object(Worker,'filter_metrics',return_value=[]):
                    with self.assertRaisesRegex(ValueError,'không trả đủ'):
                        _run_yolo(paths,model,FrameFilterSettings(),None,None)
                self.assertTrue(sessions[-1].closed)
                with patch.object(Worker,'filter_metrics',side_effect=RuntimeError('ORI_ERROR')):
                    with self.assertRaisesRegex(RuntimeError,'ORI_ERROR'):
                        _run_yolo(paths,model,FrameFilterSettings(),None,None)
                self.assertTrue(sessions[-1].closed)

    def test_worker_filter_rpc_and_manual_auto_arrow_geometry_agree(self):
        for angle in (0,32,90,179,-179,-90):
            with self.subTest(angle=angle):
                positive=result(angle)
                model=SimpleNamespace(names={0:'part'},predict=lambda **args:[positive])
                requests=[{'_ori_operation':'filter_metrics','threshold':.2,'source':['a.jpg'],'conf':.05},
                          {'source':'a.jpg','conf':.25}]
                output=io.StringIO()
                with patch.object(ori_worker,'load_model',return_value=model), \
                     patch('sys.argv',['ori_worker','serve','best.pt']), \
                     patch('sys.stdin',io.StringIO('\n'.join(json.dumps(v) for v in requests))),redirect_stdout(output):
                    self.assertEqual(ori_worker.main(),0)
                lines=output.getvalue().splitlines()
                metrics=json.loads(next(line.split('=',1)[1] for line in lines if line.startswith('ORI_FILTER_METRICS=')))
                self.assertEqual(metrics[0]['accepted'],1)
                ann=json.loads(next(line.split('=',1)[1] for line in lines if line.startswith('ORI_PREDICTION=')))[0]
                tip=ann['orientation']
                expected=direction(ann['bbox'],ann['obb'],[100+math.cos(math.radians(angle)),80+math.sin(math.radians(angle))],(200,160),True)
                for a,b in zip(tip,expected):self.assertLess(math.dist(a,b),1e-5)
                self.assertAlmostEqual(math.dist(*tip),40,places=5)
                self.assertEqual(ann['kind'],'ori')

    def test_invalid_padding_detection_does_not_break_valid_auto_labels(self):
        padding=result()
        padding.obb.xywhr=Array([[-100,80,80,40,0]])
        padding.obb.xyxyxyxy=Array([[[-140,60],[-60,60],[-60,100],[-140,100]]])
        padding.obb.xyxy=Array([[-140,60,-60,100]])
        valid=result()
        mixed=SimpleNamespace(boxes=None,obb=SimpleNamespace(
            xyxyxyxy=Array(padding.obb.xyxyxyxy.tolist()+valid.obb.xyxyxyxy.tolist()),
            xywhr=Array(padding.obb.xywhr.tolist()+valid.obb.xywhr.tolist()),
            conf=Array([.9,.8]),cls=Array([0,0])),orig_shape=(160,200))
        model=SimpleNamespace(names={0:'part'},predict=lambda **args:[mixed])
        output=io.StringIO()
        with patch.object(ori_worker,'load_model',return_value=model), \
             patch('sys.argv',['ori_worker','serve','best.pt']), \
             patch('sys.stdin',io.StringIO(json.dumps({'source':'a.jpg'}))),redirect_stdout(output):
            ori_worker.main()
        annotations=json.loads(next(line.split('=',1)[1] for line in output.getvalue().splitlines() if line.startswith('ORI_PREDICTION=')))
        self.assertEqual(len(annotations),1)
        self.assertEqual(annotations[0]['orientation'][0],[100.,80.])

    def test_corner_roundoff_does_not_change_predicted_heading(self):
        positive=result(32)
        positive.obb.xyxyxyxy=Array([[[x+2e-5,y-3e-5] for x,y in positive.obb.xyxyxyxy.tolist()[0]]])
        model=SimpleNamespace(names={0:'part'},predict=lambda **args:[positive])
        output=io.StringIO()
        with patch.object(ori_worker,'load_model',return_value=model), \
             patch('sys.argv',['ori_worker','serve','best.pt']), \
             patch('sys.stdin',io.StringIO(json.dumps({'source':'a.jpg'}))),redirect_stdout(output):
            ori_worker.main()
        ann=json.loads(next(line.split('=',1)[1] for line in output.getvalue().splitlines() if line.startswith('ORI_PREDICTION=')))[0]
        start,end=ann['orientation']
        actual=math.degrees(math.atan2(end[1]-start[1],end[0]-start[0]))
        self.assertAlmostEqual(actual,32,places=7)


if __name__=='__main__':unittest.main()
