"""SAM point ownership and toolbar regressions using temporary projects."""
import copy
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
import test_obb_ori_editing as fixtures
from smartlabel.auto_label import Sam2Adapter
from smartlabel.models import Annotation


class PromptAdapterTests(unittest.TestCase):
    def test_box_refinement_passes_both_signs_and_requests_single_mask(self):
        adapter = Sam2Adapter.__new__(Sam2Adapter)
        adapter.np = np
        called = {}
        def predict(**kwargs):
            called.update(kwargs)
            return np.zeros((1,80,120), dtype=bool), np.array([.8]), np.zeros((1,256,256))
        adapter.predictor = SimpleNamespace(predict=predict)
        mask, score = adapter.mask_from_prompts([10,20,90,70], [[40,40],[80,60]], [1,0])
        self.assertEqual(called['point_coords'].tolist(), [[40,40],[80,60]])
        self.assertEqual(called['point_labels'].tolist(), [1,0])
        self.assertEqual(called['box'].tolist(), [10,20,90,70])
        self.assertFalse(called['multimask_output'])
        self.assertEqual(mask.shape, (80,120))
        self.assertAlmostEqual(score, .8)

    def test_invalid_prompt_labels_do_not_call_model(self):
        adapter = Sam2Adapter.__new__(Sam2Adapter)
        for points, labels in (([],[]), ([[1,2]],[2]), ([[1,2]],[1,0])):
            with self.assertRaises(ValueError):
                adapter.mask_from_prompts([0,0,10,10], points, labels)


class SamPromptAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ObbOriAppTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixtures.ObbOriAppTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixtures.ObbOriAppTests.setUp(self)
        self.app.sam_refine_session = None
        self.app.sam_request_versions.clear()
        self.app.canvas.clear_prompts()
        self.checkpoint = self.workspace / 'fixture-sam.pt'
        self.checkpoint.write_bytes(b'fixture; no model loaded')
        self.app.sam_checkpoint.set(str(self.checkpoint))
        self.calls, self.workers = [], []
        mask = np.zeros((600,800), dtype=bool)
        mask[220:380,320:480] = True
        def predict(box, points, labels):
            self.calls.append((box, copy.deepcopy(points), list(labels)))
            return mask, .9
        self.app.sam_adapter = SimpleNamespace(config='fixture', set_image=lambda *args: None,
            mask_from_prompts=predict, mask_from_box=lambda *args: (mask,.9))
        def thread(target, **kwargs):
            self.workers.append(target)
            return SimpleNamespace(start=lambda: None)
        patcher = patch.object(self.module, 'Thread', side_effect=thread)
        patcher.start()
        self.addCleanup(patcher.stop)

    def click(self, x=400, y=300):
        px, py = self.app.canvas.to_canvas(x,y)
        self.app.canvas._press(SimpleNamespace(x=px,y=py,state=0))

    def finish(self):
        self.workers[-1]()
        self.app._drain_events()

    def test_sign_switch_and_result_keep_points_tool_and_disable_point_create(self):
        self.app.sam_click_enabled.set(True)
        self.app._set_tool('sam_positive')
        self.assertFalse(self.app.sam_click_enabled.get())
        self.click()
        self.finish()
        self.assertEqual(self.app.canvas.mode, 'sam_positive')
        self.assertEqual(self.app.annotation_geometry.get(), 'SEG')
        self.assertEqual(self.calls[-1][2], [1])
        self.app._set_tool('sam_negative')
        self.click(460,350)
        self.finish()
        self.assertEqual(self.calls[-1][2], [1,0])
        self.assertEqual(self.app.canvas.mode, 'sam_negative')
        self.assertEqual(len(self.app.canvas.prompt_points), 2)
        self.assertEqual(len(self.app.canvas.record.annotations), 1)
        self.assertFalse(self.ann.approved)
        self.assertEqual(self.app.canvas.record.review_status, 'draft')

    def test_changing_object_resets_prompts_and_ignores_previous_result(self):
        self.app._set_tool('sam_positive')
        self.click()
        version = self.app.sam_request_versions[self.ann.id]
        before = self.ann.to_dict()
        second = Annotation.create_box(0,[40,40,80,60])
        self.app.canvas.record.annotations.append(second)
        self.app.canvas.selected_id = second.id
        self.app._annotation_selected(second.id)
        self.assertFalse(self.app.canvas.prompt_points)
        self.app.event_queue.put(('sam_done', ('r',self.ann.id,version,[[1,1],[5,1],[5,5]],.8)))
        self.app._drain_events()
        self.assertEqual(self.ann.to_dict(), before)
        self.app._set_tool('sam_negative')
        self.click(60,60)
        self.finish()
        self.assertEqual(self.calls[-1][2], [0])
        self.assertEqual(self.calls[-1][0], [40,40,120,100])

    def test_rapid_clicks_skip_superseded_worker_and_use_all_points(self):
        self.app._set_tool('sam_positive')
        self.click(400,300)
        self.app._set_tool('sam_negative')
        self.click(470,360)
        self.workers[0]()
        self.assertFalse(self.calls)
        self.finish()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[-1][2], [1,0])

    def test_image_change_invalidates_refinement_and_manual_view_drops_old_error(self):
        self.app._set_tool('sam_positive')
        self.click()
        version = self.app.sam_request_versions[self.ann.id]
        self.app._geometry_changed('OBB')
        self.assertFalse(self.app.canvas.prompt_points)
        with patch.object(self.app,'_set_status') as status:
            self.app.event_queue.put(('sam_refine_error',(self.ann.id,version,'late failure')))
            self.app._drain_events()
            status.assert_not_called()
        self.app._set_tool('sam_positive')
        self.click()
        self.app._load_current_image()
        self.assertFalse(self.app.sam_request_versions)
        self.assertIsNone(self.app.sam_refine_session)
        self.assertEqual(self.app.canvas.mode, 'select')

    def test_seed_box_stays_fixed_through_multiple_results(self):
        original = list(self.ann.bbox)
        self.app._set_tool('sam_positive')
        self.click()
        self.finish()
        self.ann.bbox = [100,100,20,20]
        self.click(410,310)
        self.finish()
        x,y,w,h = original
        self.assertEqual(self.calls[-1][0], [x,y,x+w,y+h])

    def test_no_selection_and_readonly_cannot_start_refinement(self):
        self.app.canvas.read_only = True
        self.app._set_tool('sam_positive')
        self.app._run_sam_refine(True)
        self.assertFalse(self.workers)
        self.app.canvas.read_only = False
        self.app.canvas.selected_id = None
        self.app._annotation_selected(None)
        self.app.sam_click_enabled.set(True)
        self.app._set_tool('sam_negative')
        self.assertFalse(self.app.sam_click_enabled.get())
        self.assertEqual(self.app.canvas.mode, 'select')

    def test_geometry_and_rotation_share_row_separator_and_fit_minimum_window(self):
        self.app.tabs.set('GÁN NHÃN')
        self.app.geometry('1180x720')
        self.app.deiconify()
        try:
            self.app.update()
            menu = self.app.obb_rotation_step_menu
            left, right = self.app.obb_rotate_left_button,self.app.obb_rotate_right_button
            sep = self.app.geometry_rotation_separator
            self.assertEqual(menu.master.master, self.app.geometry_selector.master)
            self.assertLess(self.app.geometry_selector.winfo_rootx(), sep.winfo_rootx())
            self.assertLess(sep.winfo_rootx(), menu.winfo_rootx())
            self.assertLess(menu.winfo_rootx(), left.winfo_rootx())
            self.assertLess(left.winfo_rootx(), right.winfo_rootx())
            self.assertGreater(right.winfo_width(), 40)
            label = self.app.obb_rotation_angle_label
            self.assertLessEqual(label.winfo_rootx()+label.winfo_width(), sep.master.winfo_rootx()+sep.master.winfo_width())
            self.assertLess(abs(menu.winfo_rooty()-self.app.geometry_selector.winfo_rooty()), 10)
        finally:
            self.app.withdraw()
            self.app.geometry('1500x900')


if __name__ == '__main__':
    unittest.main()
