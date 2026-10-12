from pathlib import Path
from types import SimpleNamespace
import ast,json,math,subprocess,sys,unittest,os
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'tools/studio_integration'

def method(payload,name,namespace):
    tree=ast.parse((BUNDLE/'files'/payload).read_text(encoding='utf-8'))
    node=max((n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name),key=lambda n:n.lineno)
    exec(compile(ast.Module(body=[node],type_ignores=[]),payload,'exec'),namespace)
    return namespace[name]

class OriHeadingV2Tests(unittest.TestCase):
    def test_vector_decoder_all_cardinal_headings_and_rejects_unknown_shape(self):
        fn=method('2.py','_prepare_endnodes',{'np':np,'math':math,'List':list,'sigmoid':lambda x:1/(1+np.exp(-x))})
        heading=np.zeros((1,2,8400),np.float32)
        for i,deg in enumerate([0,90,180,-90]):heading[0,:,i]=[math.cos(math.radians(deg)),math.sin(math.radians(deg))]
        tensors=[np.zeros((1,65,s,s),np.float32) for s in (80,40,20)]+[np.zeros((1,1,8400),np.float32),heading]
        result=fn(SimpleNamespace(names=['part']),tensors)
        np.testing.assert_allclose(result[3][0,:4,0]*180,[0,90,180,-90],atol=1e-4)
        with self.assertRaises(ValueError):fn(SimpleNamespace(names=['part']),tensors[:-1]+[np.zeros((1,3,8400))])
        with self.assertRaisesRegex(ValueError,'metadata'):
            fn(SimpleNamespace(names=['part'],expected_heading_components=1),tensors)

    def test_ori_preview_arrow_matches_image_heading_and_default_legacy_is_preserved(self):
        import cv2
        class Capture:
            def __getattr__(self,n):return getattr(cv2,n)
            def arrowedLine(self,image,start,end,*a,**kw):self.arrow=(start,end);return image
            def boxPoints(self,box):self.box=list(box);return cv2.boxPoints(box)
        cv=Capture();ns={'math':math,'np':np,'cv2':cv}
        draw=method('5.py','draw_rotated_objs',ns)
        display=method('5.py','find_display_angle',ns)
        owner=SimpleNamespace(color_type=[(0,255,0)])
        owner.find_display_angle=lambda x:display(owner,x)
        for deg in [0,32,90,180,-90,-150]:
            obj=[0,(200,200),(180,80),-deg,.9];before=repr(obj)
            for ori in [False,True]:
                draw(owner,np.zeros((400,400,3),np.uint8),[obj],ori_image_heading=ori)
                start,end=cv.arrow;actual=math.degrees(math.atan2(end[1]-start[1],end[0]-start[0]))
                expected=deg if ori else deg-90
                self.assertLess(abs((actual-expected+180)%360-180),1)
                self.assertLess(abs((cv.box[2]-deg+90)%180-90),1e-6)
                self.assertEqual(repr(obj),before)

    def test_v2_frame_follows_vector_without_quantizing_and_legacy_is_unchanged(self):
        fn=method('4.py','regularize_orientBoxes',{'np':np,'PI':math.pi,'TWO_PI':2*math.pi})
        box=np.array([[100.,100.,80.,40.,math.radians(12.)]])
        old,old_deg=fn(box,np.array([92.]))
        new,new_deg=fn(box,np.array([92.]),align_to_heading=True)
        np.testing.assert_allclose(old_deg,[102.],atol=1e-5)
        np.testing.assert_allclose(new_deg,[92.],atol=1e-5)
        np.testing.assert_allclose(new[:,2:4],[[40.,80.]])

    def test_v2_upload_metadata_cannot_be_relabelled_as_legacy(self):
        import hashlib
        from tools.studio_integration.upload.rknn_model_upload import validate_metadata
        binary=b'test model'
        meta={'schema':1,'format':'rknn','task':'ori','target':'rk3588','compiler':'rknn-toolkit2==2.2.0','imgsz':[640,640],
              'names':{'0':'part'},'model_sha256':hashlib.sha256(binary).hexdigest(),'output_layout':'deltax_orienty_5_heads_v2',
              'output_shapes':[[1,65,s,s] for s in (80,40,20)]+[[1,1,8400],[1,2,8400]],'heading_encoding':'cos_sin_vector_v2',
              'heading':'image_x_clockwise_degrees','heading_scale':180,'obb_angle':'(sigmoid - 0.25) * pi',
              'heading_refinement':'align_obb_axes_to_heading_vector','normalization':{'mean':[0,0,0],'std':[255,255,255],'rgb2bgr':False},
              'input_contract':{'runtime_layout':'NHWC','dtype':'uint8','color':'RGB','resize':'letterbox'},
              'verification':{'onnx_vs_pt':True,'rknn_simulator_vs_pt':True}}
        self.assertEqual(validate_metadata(json.dumps(meta),binary)['heading_encoding'],'cos_sin_vector_v2')
        with self.assertRaises(ValueError):validate_metadata(json.dumps({**meta,'heading_encoding':'normalized_degrees_v1'}),binary)
        with self.assertRaises(ValueError):validate_metadata(json.dumps({**meta,'heading_refinement':'snap_to_obb_axis_4_directions'}),binary)

    def test_vector_loss_keeps_gradients_wraps_and_raw_export_preserves_old_head(self):
        code=r"""
import copy,math,torch
from smartlabel.ori_worker import load_model
m=load_model('deltax-yolo11n-ori')
from ultralytics.utils.loss import v8OrientationLoss
from ultralytics.data.augment import RandomPerspective
from ultralytics.models.yolo.orienty.val import OrientationValidator
import numpy as np,cv2
from tools.rknn_converter.export_ori import install_ori_raw_forward,expected_shapes
from tools.ori_runtime.deltax_ori_contract import heading_encoding
lossfn=v8OrientationLoss.calculate_degs_loss
for values,deg in [([-6.5,2.],90),([0.,0.],-90),([-1.,0.],0)]:
 p=torch.tensor([[values]],requires_grad=True)
 loss=lossfn(None,torch.tensor([deg]),torch.tensor([[True]]),torch.tensor([[0]]),torch.tensor([0]),p)
 loss.backward();assert torch.isfinite(p.grad).all() and p.grad.abs().sum()>0
p=torch.tensor([[[math.cos(math.radians(179)),math.sin(math.radians(179))]]])
assert lossfn(None,torch.tensor([-179.]),torch.tensor([[True]]),torch.tensor([[0]]),torch.tensor([0]),p)<.001
head=m.model.model[-1];assert heading_encoding(m.model)=='cos_sin_vector_v2'
validator=OrientationValidator(args={'task':'orienty','plots':False})
validator.training=True
validator.data={'val':''}
validator.init_metrics(m.model)
assert validator.align_to_heading
# Image heading and annotation vector rotate together, independent of translation.
matrix=np.eye(3);matrix[:2]=cv2.getRotationMatrix2D((200,100),30,1)
rotated=RandomPerspective().apply_degs(np.array([90.],np.float32),matrix)
assert abs(float(rotated[0])-60)<1e-4
for branch in head.cv5:
 branch[-1].weight.data.zero_();branch[-1].bias.data.copy_(torch.tensor([0.,-1.]))
with torch.no_grad():native=m.model.eval()(torch.zeros(1,3,96,96))[0]
assert torch.allclose(native[:,-2],torch.full_like(native[:,-2],-90.))
install_ori_raw_forward(head)
with torch.no_grad():out=m.model.eval()(torch.zeros(1,3,640,640))
assert [list(t.shape) for t in out]==expected_shapes(80,2)
assert torch.allclose(out[-1][:,0],torch.zeros_like(out[-1][:,0])) and torch.allclose(out[-1][:,1],-torch.ones_like(out[-1][:,1]))
# Old pickles have single-component convolutions and no new attribute.
del head.heading_components
for branch in head.cv5:
 branch[-1]=torch.nn.Conv2d(branch[-1].in_channels,1,1);branch[-1].weight.data.zero_();branch[-1].bias.data.fill_(2.)
assert heading_encoding(m.model)=='normalized_degrees_v1'
with torch.no_grad():old=m.model.eval()(torch.zeros(1,3,640,640))
assert [list(t.shape) for t in old]==expected_shapes(80,1) and torch.all(old[-1]==1)
print('VECTOR_AND_LEGACY_OK')
"""
        r=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('VECTOR_AND_LEGACY_OK',r.stdout)

if __name__=='__main__':unittest.main()
