from copy import deepcopy
import gc
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from smartlabel import app as app_module
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.hydro_labels import model_attributes
from smartlabel.label_schema import training_identity
from smartlabel.models import ImageRecord
from smartlabel.project_store import ProjectStore
from smartlabel.training_supplements import manifest_path, sha256


class SupplementReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.store = ProjectStore(Path(cls.temp.name) / 'workspace')
        cls.hydro = cls.store.create_project('Hydro review', task='classify')
        apply_hydroponic_slot_template(cls.hydro)
        cls.hydro.metadata['cropCode'] = 'cai_ngot'
        parent = ImageRecord(id='parent', file_name='parent.png', asset_role='slot', width=50, height=50,
            review_status='reviewed', capture_group='plant', attributes={'plant_presence': 'present', 'yellow_leaf': 'absent', 'wilt': 'absent'})
        cls.hydro.images.append(parent)
        Image.new('RGB', (50, 50), 'green').save(cls.store.image_path(cls.hydro, parent))
        cls.store.save(cls.hydro)
        cls.bottle = cls.store.create_project('Bottle', classes=['bottle'])
        cls.manifest = {'schemaVersion': 1, 'projectId': cls.hydro.id,
            'labelIdentities': {a['id']: training_identity(a) for a in model_attributes(cls.hydro)}, 'images': []}
        path = manifest_path(cls.store, cls.hydro)
        path.parent.mkdir()
        for i in range(27):
            file = path.parent / f'edited_{i}.png'
            Image.new('RGB', (60, 50), (180 + i, 200, 30)).save(file)
            cls.manifest['images'].append({'id': f's{i}', 'file': file.name, 'sha256': sha256(file), 'enabled': True,
                'kind': 'synthetic', 'split': 'train', 'cropCode': 'cai_ngot', 'reviewStatus': 'reviewed', 'reviewNote': 'fixture',
                'attributes': {'yellow_leaf': 'present'}, 'presenceMeaning': 'positive',
                'growthStage': 'large' if i < 24 else 'small', 'batchId': 'fixture',
                'provenance': {'parentImageId': 'parent', 'parentSha256': sha256(cls.store.image_path(cls.hydro, parent)),
                               'method': 'fixture', 'prompt': 'fixture'}})
        path.write_text(json.dumps(cls.manifest), encoding='utf-8')
        (cls.store.project_dir(cls.hydro) / 'split_assignment.json').write_text(json.dumps({'groups': {'plant': 'train'}}))
        cls.patches = [patch.object(app_module, 'WORKSPACE', cls.store.workspace),
                       patch.object(app_module.SmartLabelApp, '_refresh_hardware'),
                       patch.object(app_module.messagebox, 'showerror'), patch.object(app_module.messagebox, 'showinfo')]
        for item in cls.patches: item.start()
        cls.app = app_module.SmartLabelApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        for item in reversed(cls.patches): item.stop()
        cls.temp.cleanup()

    def setUp(self):
        manifest_path(self.store, self.hydro).write_text(json.dumps(self.manifest), encoding='utf-8')
        self.app._change_project_context(deepcopy(self.hydro))
        self.app._open_training_supplements()
        self.view = self.app.supplement_view
        app_module.messagebox.showerror.reset_mock()
        gc.collect()

    def tearDown(self):
        app_module.messagebox.showerror.assert_not_called()

    def complete_save(self):
        deadline = time.monotonic() + 8
        while self.view.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertFalse(self.view.busy)
        self.assertFalse(self.app.supplement_review_running)

    def test_gallery_only_sidecar_rows_filter_navigation_and_no_project_mutation(self):
        before = deepcopy(self.app.project.to_dict())
        self.assertEqual(len(self.view.rows), 27)
        self.assertNotIn('parent', [r['id'] for r in self.view.rows])
        self.assertEqual(len(self.view.list_buttons), 24)
        self.view.change_page(1)
        self.assertEqual(self.view.selected['id'], 's24')
        self.view.navigate(1)
        self.assertEqual(self.view.selected['id'], 's25')
        self.view.stage_filter.set('Cây nhỏ')
        self.view.apply_filters()
        self.assertEqual([r['id'] for r in self.view.filtered], ['s24', 's25', 's26'])
        self.assertEqual(before, self.app.project.to_dict())

    def test_async_reject_reapprove_and_draft_reconcile_filters(self):
        self.view.status_filter.set('Đang dùng train')
        self.view.apply_filters()
        self.view.save('rejected')
        self.assertFalse(self.app._can_change_project())
        self.complete_save()
        self.assertEqual(len(self.view.filtered), 26)
        self.view.status_filter.set('Từ chối')
        self.view.apply_filters()
        self.assertEqual(self.view.selected['id'], 's0')
        menu, choices = self.view.form['yellow_leaf']
        menu.set(next(k for k, v in choices.items() if v == 'absent'))
        self.view.save('reviewed')
        self.complete_save()
        data = json.loads(manifest_path(self.store, self.hydro).read_text(encoding='utf-8'))
        self.assertEqual(data['images'][0]['attributes']['yellow_leaf'], 'absent')
        self.assertTrue(data['images'][0]['enabled'])
        self.assertIsNone(self.view.selected)

    def test_all_project_attributes_can_be_added_then_saved_as_draft_and_approved(self):
        before = deepcopy(self.app.project.to_dict())
        self.assertEqual(set(self.view.form), {'plant_presence', 'yellow_leaf', 'wilt'})
        self.assertEqual(self.view.values(), {'yellow_leaf': 'present'})
        menu, choices = self.view.form['wilt']
        menu.set(next(caption for caption, value in choices.items() if value == 'present'))
        self.view.save('draft', save_draft_labels=True)
        self.complete_save()
        self.assertFalse(self.view.selected['enabled'])
        self.assertEqual(self.view.selected['attributes']['wilt'], 'present')
        self.assertIn(('wilt', 'present'), self.view.attribute_map.values())
        self.view.save('reviewed')
        self.complete_save()
        self.assertTrue(self.view.selected['enabled'])
        self.assertEqual(before, self.app.project.to_dict())
        self.assertNotIn('plant_presence', self.view.selected['attributes'])

    def test_presence_change_updates_condition_fields_without_inheriting_parent_labels(self):
        menu, choices = self.view.form['plant_presence']
        menu.set(next(caption for caption, value in choices.items() if value == 'absent'))
        self.view.attribute_changed('plant_presence')
        self.assertEqual(self.view.values(), {'plant_presence': 'absent', 'yellow_leaf': 'not_applicable', 'wilt': 'not_applicable'})
        self.view.save('reviewed')
        self.complete_save()
        self.assertEqual(self.view.selected['presenceMeaning'], 'negative')

    def test_archived_images_are_outside_default_list_and_can_be_restored(self):
        self.view.save('archived')
        self.complete_save()
        self.assertEqual(len(self.view.filtered), 26)
        self.assertNotIn('s0', [row['id'] for row in self.view.filtered])
        self.view.status_filter.set('Đã lưu trữ')
        self.view.apply_filters()
        self.assertEqual(self.view.selected['id'], 's0')
        self.view.save('reviewed')
        self.complete_save()
        self.assertFalse(self.view.filtered)
        self.view.status_filter.set('Tất cả')
        self.view.apply_filters()
        self.assertEqual(len(self.view.filtered), 27)

    def test_unsaved_form_preserved_on_cancel_and_bottle_context_has_no_supplements(self):
        menu, choices = self.view.form['yellow_leaf']
        menu.set(next(k for k, v in choices.items() if v == 'absent'))
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=False):
            self.view.select(self.view.rows[1])
            self.app._change_project_context(self.bottle)
        self.assertEqual(self.view.selected['id'], 's0')
        self.assertEqual(self.app.project.id, self.hydro.id)
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=True):
            self.app._change_project_context(self.bottle)
        self.assertFalse(self.app.label_workspace_switch.winfo_manager())
        self.assertFalse(self.view.winfo_manager())
        self.assertIsNone(self.view.project)
        self.assertFalse(self.view.rows)
        self.assertFalse(self.app.project_summary.winfo_manager())
        self.assertTrue(self.app.project_overview._parent_frame.winfo_manager())
        self.assertTrue(self.app.capture_workspace.winfo_manager())

    def test_visible_layout_at_minimum_and_large_window_and_overview_expansion(self):
        self.app.deiconify()
        try:
            for geometry in ('1180x720', '1600x900'):
                self.app.geometry(geometry)
                self.app.update()
                self.app.canvas.focus_force()
                self.app._show_label_workspace('Ảnh bổ trợ')
                self.assertEqual(self.app.focus_get(), self.view.preview)
                header = self.view.source_switch.master
                title = next(w for w in header.winfo_children() if hasattr(w, 'cget') and w.cget('text') == 'DANH SÁCH ẢNH')
                self.assertGreaterEqual(self.view.source_switch.winfo_rootx(), title.winfo_rootx() + title.winfo_width())
                self.assertLessEqual(self.view.source_switch.winfo_rootx() + self.view.source_switch.winfo_width(),
                                     self.view.list_card.winfo_rootx() + self.view.list_card.winfo_width())
                self.assertEqual(self.app.label_source.get(), 'Bổ trợ')
                self.assertGreater(self.view.preview.winfo_width(), 250)
                self.assertGreater(self.view.preview.winfo_height(), 260)
                self.assertLessEqual(self.view.details.winfo_rootx() + self.view.details.winfo_width(),
                                     self.app.winfo_rootx() + self.app.winfo_width())
                self.app.tabs.set('DỰ ÁN')
                self.app.update()
                time.sleep(.15)  # CTkTabview finishes its delayed tab transition.
                self.app.update()
                self.assertTrue(self.app.project_overview.winfo_ismapped())
                self.assertFalse(self.app.project_summary.winfo_ismapped())
                self.app.project_overview.toggle_details()
                self.app.update()
                for frame in self.app.project_overview.split_frames:
                    self.assertEqual(bool(frame.winfo_manager()), self.app.project_overview.details_visible)
                self.app.tabs.set('GÁN NHÃN')
                self.app.update()
                time.sleep(.15)
                self.app.update()
        finally:
            self.app.withdraw()

    def test_thread_start_failure_releases_guard_and_stale_manifest_save_is_visible(self):
        with patch('smartlabel.supplement_review_view.Thread.start', side_effect=RuntimeError('thread unavailable')):
            self.view.save('draft')
            self.complete_save()
        self.assertIn('thread unavailable', self.view.feedback.cget('text'))
        manifest_path(self.store, self.hydro).write_text(json.dumps({**self.manifest, 'externalEdit': True}), encoding='utf-8')
        self.view.save('draft')
        self.complete_save()
        self.assertIn('thay đổi', self.view.feedback.cget('text'))
        self.assertTrue(self.view.selected['enabled'])
