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
        self.app.image_page_size = 50
        self.app.supplement_view.active = False
        self.app.supplement_view.selected = None
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

    def choose(self, key, value):
        menu, choices = self.view.form[key]
        caption = next(c for c, v in choices.items() if v == value)
        menu.set(caption)
        self.app._attribute_changed(key, caption)
        self.complete_save()

    def filter_attribute(self, key, value):
        from smartlabel import image_filters
        self.app.label_filter_field.set(next(c for c, f in self.app.label_filter_fields.items() if f == ('attribute', key)))
        self.app._label_filter_changed()
        self.app.label_filter_value.set(next(c for c, v in self.app.label_filter_values.items() if v == value))
        self.app._change_image_filter()

    def test_same_widgets_filters_and_source_only_records(self):
        before = deepcopy(self.app.project.to_dict())
        widgets = (self.app.canvas, self.app.image_list, self.app.attribute_panel,
                   self.app.image_filter, self.app.label_filter_field, self.app.label_filter_value)
        self.assertEqual(len(self.view.rows), 27)
        self.assertIs(self.view.preview, self.app.canvas)
        self.assertEqual(self.view.values(), {'plant_presence': 'present', 'yellow_leaf': 'present', 'wilt': 'not_applicable'})
        self.assertFalse(hasattr(self.view, 'batch_filter'))
        self.assertFalse(hasattr(self.view, 'stage_filter'))
        self.filter_attribute('wilt', 'not_applicable')
        self.assertEqual(len(self.view.filtered), 27)
        self.assertNotIn('', self.app.label_filter_values.values())
        self.filter_attribute('plant_presence', 'present')
        self.assertEqual(len(self.view.filtered), 27)
        self.assertNotIn('', self.app.label_filter_values.values())
        self.app._show_label_workspace('Giàn')
        self.assertFalse(self.view.active)
        self.assertEqual(widgets, (self.app.canvas, self.app.image_list, self.app.attribute_panel,
                         self.app.image_filter, self.app.label_filter_field, self.app.label_filter_value))
        self.assertEqual(self.app.image_list.rows[0]['key'], 'parent')
        self.assertEqual(before, self.app.project.to_dict())

    def test_shared_edit_autosaves_draft_and_approve_next_and_export(self):
        before = deepcopy(self.app.project.to_dict())
        self.choose('wilt', 'present')
        self.assertFalse(self.view.selected['enabled'])
        self.assertEqual(self.view.selected['attributes'], {'plant_presence': 'present', 'yellow_leaf': 'present', 'wilt': 'present'})
        self.app._approve_image_next()
        self.complete_save()
        self.assertEqual(self.view.selected['id'], 's1')
        data = json.loads(manifest_path(self.store, self.hydro).read_text(encoding='utf-8'))
        self.assertTrue(data['images'][0]['enabled'])
        self.assertEqual(before, self.app.project.to_dict())
        from smartlabel.training_supplements import validated_samples
        attr = next(a for a in model_attributes(self.hydro) if a['id'] == 'wilt')
        self.assertEqual(len(validated_samples(self.store, self.hydro, attr, {'plant': 'train'})), 1)

    def test_filtered_edit_keeps_image_and_zoom_and_shows_independent_counter(self):
        self.app.tabs.set('GÁN NHÃN')
        self.filter_attribute('yellow_leaf', 'present')
        row_id = self.view.selected['id']
        self.app.canvas.zoom(1.4)
        image, scale = self.app.canvas.image, self.app.canvas.scale
        menu, choices = self.view.form['yellow_leaf']
        menu._dropdown_callback(next(k for k, v in choices.items() if v == 'absent'))
        self.complete_save()
        self.assertEqual(self.view.selected['id'], row_id)
        self.assertEqual(self.view.values()['yellow_leaf'], 'absent')
        self.assertIs(self.app.canvas.image, image)
        self.assertEqual(self.app.canvas.scale, scale)
        self.assertNotIn(self.view.selected, self.view.filtered)
        self.assertIn('không còn thuộc bộ lọc', self.app.label_save_status.cget('text'))
        self.assertEqual(self.app.image_position_label.cget('text'), '1 / 27')
        self.app._next_image()
        self.assertEqual(self.view.selected['id'], 's1')
        self.assertEqual(self.app.image_position_label.cget('text'), '2 / 27')

    def test_source_return_does_not_reuse_wrong_preview_and_reload_is_contextual(self):
        source_pixel = self.app.canvas.image.getpixel((0, 0))
        self.assertTrue(self.app.label_reload_button.winfo_manager())
        self.app._show_label_workspace('Giàn')
        self.assertFalse(self.app.label_reload_button.winfo_manager())
        self.assertNotEqual(self.app.canvas.image.getpixel((0, 0)), source_pixel)
        self.app._show_label_workspace('Bổ trợ')
        self.assertEqual(self.app.canvas.image.getpixel((0, 0)), source_pixel)
        self.assertTrue(self.app.label_reload_button.winfo_manager())

    def test_selected_source_metadata_never_reuses_rack_count_or_dimensions(self):
        self.assertEqual(self.app.image_position_label.cget('text'), '1 / 27')
        self.assertIn('60×50', self.app.current_image_label.cget('text'))
        self.assertIn('Ảnh bổ trợ 1/27 · 60×50', self.app.title())

        self.view.show_row(self.view.rows[4])
        self.assertEqual(self.app.image_position_label.cget('text'), '5 / 27')
        self.assertIn('Ảnh bổ trợ 5/27 · 60×50', self.app.title())

        self.app._show_label_workspace('Giàn')
        self.assertEqual(self.app.image_position_label.cget('text'), '1 / 1')
        self.assertIn('Ảnh 1/1 · 50×50', self.app.title())

        self.app._show_label_workspace('Bổ trợ')
        self.assertEqual(self.app.image_position_label.cget('text'), '5 / 27')
        self.assertIn('Ảnh bổ trợ 5/27 · 60×50', self.app.title())

    def test_draft_does_not_scan_split_or_rebuild_hidden_statistics(self):
        self.app.tabs.set('GÁN NHÃN')
        with patch.object(self.app.datasets, 'ensure_split_assignment', side_effect=AssertionError('draft must not scan split')), \
             patch.object(self.app, '_refresh_project_statistics') as refresh:
            self.choose('wilt', 'present')
            refresh.assert_not_called()
        self.assertTrue(self.app.project_statistics_dirty)

    def test_cancel_navigation_prompts_once_and_warmup_failure_keeps_review_available(self):
        row_id = self.view.selected['id']
        self.app.other_abnormal_var.set('Unsaved fixture note')
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=False) as ask:
            self.app._next_image()
            ask.assert_called_once()
        self.assertEqual(self.view.selected['id'], row_id)
        self.view.sync_details()
        self.view.warm_started = False
        with patch('smartlabel.supplement_review_view.Thread', side_effect=RuntimeError('no worker')):
            self.view.warm_review_pixels()
        self.assertFalse(self.view.busy)
        self.assertFalse(self.view.warm_started)
        self.choose('wilt', 'present')
        self.assertEqual(self.view.values()['wilt'], 'present')

    def test_approve_after_filtered_edit_advances_to_following_image_not_first(self):
        self.filter_attribute('yellow_leaf', 'present')
        self.view.show_row(self.view.filtered[5])
        self.choose('yellow_leaf', 'absent')
        self.assertEqual(self.view.selected['id'], 's5')
        self.app._approve_image_next()
        self.complete_save()
        self.assertEqual(self.view.selected['id'], 's6')

    def test_absent_or_unassigned_presence_clears_conditions_like_capture(self):
        self.choose('plant_presence', 'absent')
        self.assertEqual(self.view.values(), {'plant_presence': 'absent', 'yellow_leaf': 'not_applicable', 'wilt': 'not_applicable'})
        self.assertEqual(self.view.selected['presenceMeaning'], 'negative')
        self.choose('plant_presence', '')
        self.assertNotIn('plant_presence', self.view.values())
        self.assertEqual(self.view.values()['yellow_leaf'], 'not_applicable')
        self.assertIsNone(self.view.selected['presenceMeaning'])

    def test_reject_restore_and_filter_membership_keeps_permanent_delete_available(self):
        self.assertEqual(self.app.image_list.rows[0]['delete'].winfo_manager(), 'pack')
        self.app._reject_image()
        self.complete_save()
        self.assertEqual(len(self.view.filtered), 27)
        self.app.image_filter.set('Từ chối')
        self.app._change_image_filter()
        self.assertEqual(self.view.selected['id'], 's0')
        self.assertEqual(self.app.image_list.rows[0]['delete'].winfo_manager(), 'pack')
        self.assertEqual(self.app.restore_image_button.cget('state'), 'normal')
        self.app._restore_image()
        self.complete_save()
        self.assertFalse(self.view.filtered)
        self.app.image_filter.set('Bản nháp')
        self.app._change_image_filter()
        self.assertEqual(self.view.selected['id'], 's0')
        self.app._reject_image()
        self.complete_save()
        self.app.image_filter.set('Từ chối')
        self.app._change_image_filter()
        self.assertEqual(self.view.selected['id'], 's0')
        self.assertEqual(len(self.app.project.images), 1)

    def test_permanent_delete_requires_confirmation_and_removes_only_supplement(self):
        row = self.view.rows[0]
        path = manifest_path(self.store, self.hydro).parent / row['file']
        supplement_before = path.read_bytes()
        self.addCleanup(path.write_bytes, supplement_before)
        captured = self.store.image_path(self.hydro, self.hydro.images[0])
        captured_before = captured.read_bytes()
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=False):
            self.app._delete_image_from_thumbnail('supplement:s0')
        self.assertTrue(path.is_file())
        self.assertEqual(len(self.view.rows), 27)
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=True):
            self.app._delete_image_from_thumbnail('supplement:s0')
        self.assertFalse(path.exists())
        self.assertEqual(len(self.view.rows), 26)
        self.assertNotIn('s0', {item['id'] for item in self.view.rows})
        self.assertEqual(len(self.app.project.images), 1)
        self.assertEqual(captured.read_bytes(), captured_before)

    def test_deletion_respects_all_job_ownership_flags_and_releases_controls(self):
        path = manifest_path(self.store, self.hydro)
        before = path.read_bytes()
        flags = ('import_in_progress', 'supplement_review_running', 'auto_label_running',
                 'evaluation_running', 'running_training_task', 'batch_training_active',
                 'running_rknn_task', 'rknn_batch_active', 'hydro_export_running')
        for flag in flags:
            with self.subTest(flag=flag):
                old = getattr(self.app, flag)
                try:
                    setattr(self.app, flag, True)
                    # A finished worker still owns the project until completion
                    # clears its flag. No live subprocess is needed for this gate.
                    self.view.sync_delete_controls()
                    self.assertEqual(self.app.image_list.rows[0]['delete'].cget('state'), 'disabled')
                    with patch('smartlabel.supplement_review_view.messagebox.askyesno') as confirm:
                        self.app._delete_current_image()
                        self.app._delete_image_from_thumbnail('supplement:s0')
                        confirm.assert_not_called()
                    self.assertEqual(path.read_bytes(), before)
                finally:
                    setattr(self.app, flag, old)
                    self.view.sync_delete_controls()
                self.assertEqual(self.app.image_list.rows[0]['delete'].cget('state'), 'normal')

    def test_delete_rechecks_job_revision_and_project_after_confirmation(self):
        path = manifest_path(self.store, self.hydro)
        before = path.read_bytes()
        original_project, original_revision = self.app.project, self.view.revision
        for change in ('job', 'project', 'revision', 'source'):
            with self.subTest(change=change):
                def change_during_confirmation(*_args, **_kwargs):
                    if change == 'job': self.app.hydro_export_running = True
                    elif change == 'project': self.app.project = self.bottle
                    elif change == 'revision': self.view.revision = 'external-revision'
                    else: self.view.active = False
                    return True
                try:
                    with patch('smartlabel.supplement_review_view.messagebox.askyesno', side_effect=change_during_confirmation):
                        self.app._delete_image_from_thumbnail('supplement:s0')
                    self.assertEqual(path.read_bytes(), before)
                    self.assertTrue((path.parent / self.view.rows[0]['file']).is_file())
                finally:
                    self.app.hydro_export_running = False
                    self.app.project = original_project
                    self.view.revision = original_revision
                    self.view.active = True
                    self.view.sync_delete_controls()

    def test_delete_invalid_target_or_old_project_never_falls_back_to_selected(self):
        path = manifest_path(self.store, self.hydro)
        before = path.read_bytes()
        with patch('smartlabel.supplement_review_view.messagebox.askyesno') as confirm:
            self.app._delete_image_from_thumbnail('supplement:does-not-exist')
            original = self.app.project
            try:
                self.app.project = self.bottle
                self.app._delete_current_image()
            finally:
                self.app.project = original
            confirm.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_historical_archived_row_appears_as_rejected_and_can_be_restored(self):
        path = manifest_path(self.store, self.hydro)
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['images'][0].update(archived=True, enabled=False, reviewStatus='reviewed')
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        self.view.reload(check_unsaved=False)
        self.app.image_filter.set('Từ chối')
        self.app._change_image_filter()
        self.assertEqual(self.view.selected['id'], 's0')
        self.assertEqual(self.app.approve_image_button.cget('state'), 'disabled')
        self.assertEqual(self.app.restore_image_button.cget('state'), 'normal')
        self.app._restore_image()
        self.complete_save()
        self.app.image_filter.set('Bản nháp')
        self.app._change_image_filter()
        self.assertEqual(self.view.selected['id'], 's0')

    def test_unsaved_note_cancel_busy_switch_and_bottle_isolation(self):
        self.app.other_abnormal_var.set('Rách lá')
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=False):
            self.app._show_label_workspace('Giàn')
            self.app._change_project_context(self.bottle)
        self.assertTrue(self.view.active)
        self.assertEqual(self.app.project.id, self.hydro.id)
        self.app._save_other_abnormal()
        self.assertTrue(self.view.busy)
        self.app._show_label_workspace('Giàn')
        self.assertTrue(self.view.active)
        self.complete_save()
        self.assertEqual(self.view.selected['otherAbnormal'], 'Rách lá')
        self.app._change_project_context(self.bottle)
        self.assertFalse(self.view.active)
        self.assertFalse(self.app.canvas.read_only)
        self.assertIsNone(self.view.project)
        self.assertFalse(self.app.label_workspace_switch.winfo_manager())

    def test_same_geometry_at_minimum_large_zoom_navigation_and_shortcuts(self):
        self.app.deiconify()
        try:
            for geometry in ('1180x720', '1600x900'):
                self.app.geometry(geometry)
                self.app.tabs.set('GÁN NHÃN')
                self.app.update()
                time.sleep(.15)
                self.app.update()
                self.assertGreater(self.app.canvas.winfo_width(), 250)
                self.assertGreater(self.app.canvas.winfo_height(), 260)
                shared = (self.app.canvas.winfo_geometry(), self.app.attribute_panel.winfo_geometry())
                self.app._show_label_workspace('Giàn')
                self.app.update()
                self.assertEqual(shared, (self.app.canvas.winfo_geometry(), self.app.attribute_panel.winfo_geometry()))
                self.app._show_label_workspace('Bổ trợ')
                self.app.update()
            before = deepcopy(self.app.project.to_dict())
            self.app.canvas.undo()
            self.app.canvas.delete_selected()
            self.app._annotation_changed()
            self.assertEqual(before, self.app.project.to_dict())
            self.app._next_image()
            self.assertEqual(self.view.selected['id'], 's1')
            self.app._previous_image()
            self.assertEqual(self.view.selected['id'], 's0')
            self.app.canvas.zoom(1.2)
            self.assertEqual(self.app.zoom_percent_label.cget('text'), f'{round(self.app.canvas.scale * 100)}%')
        finally:
            self.app.withdraw()

    def test_failure_keeps_edits_and_stale_revision_cannot_overwrite(self):
        with patch('smartlabel.supplement_review_view.Thread.start', side_effect=RuntimeError('thread unavailable')):
            self.choose('wilt', 'present')
        self.assertIn('thread unavailable', self.app.title())
        self.assertEqual(self.view.values()['wilt'], 'present')
        self.assertFalse(self.view.busy)
        manifest_path(self.store, self.hydro).write_text(json.dumps({**self.manifest, 'externalEdit': True}), encoding='utf-8')
        self.view.save('draft', save_draft_labels=True)
        self.complete_save()
        self.assertIn('thay đổi', self.app.title())
        self.assertTrue(self.view.selected['enabled'])

    def test_shared_pager_and_qa_return_to_capture_with_unsaved_guard(self):
        self.app.image_page_size = 10
        self.view.refresh_list()
        self.app._change_image_page(1)
        self.assertEqual(self.view.selected['id'], 's10')
        self.assertEqual(len(self.app.image_list.rows), 10)
        self.app._change_image_page(1)
        self.assertEqual(self.view.selected['id'], 's20')
        self.assertEqual(len(self.app.image_list.rows), 7)
        self.app.other_abnormal_var.set('Chưa lưu')
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=False):
            self.app._open_qa_image('parent')
        self.assertTrue(self.view.active)
        self.assertEqual(self.view.selected['id'], 's20')
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=True):
            self.app._open_qa_image('parent')
        self.assertFalse(self.view.active)
        self.assertEqual(self.app.canvas.record.id, 'parent')
        self.assertFalse(self.app.canvas.read_only)

    def test_pending_defaults_review_button_and_shortcut_no_duplicate_approval(self):
        self.assertEqual(self.view.record_for(self.view.selected).review_status, 'draft')
        self.assertEqual(self.app.approve_image_button.cget('state'), 'normal')
        self.view.save('reviewed')
        self.complete_save()
        self.assertEqual(self.app.approve_image_button.cget('state'), 'disabled')
        self.assertEqual(self.app.unapprove_image_button.cget('state'), 'normal')
        original = manifest_path(self.store, self.hydro).read_bytes()
        self.app._approve_image_next()
        self.assertFalse(self.view.busy)
        self.assertEqual(original, manifest_path(self.store, self.hydro).read_bytes())
        self.app._next_image()
        self.assertEqual(self.view.selected['id'], 's1')
        self.assertEqual(self.app.approve_image_button.cget('state'), 'normal')

    def test_warm_source_switch_reuses_rows_and_never_prompts_for_capture_labels(self):
        widgets = {row['key']: row['frame'] for row in self.app.image_list.rows}
        with patch('smartlabel.supplement_review_view.messagebox.askyesno', return_value=False) as confirm:
            for _ in range(3):
                self.app._show_label_workspace('Giàn')
                self.assertEqual(self.app.canvas.record.id, 'parent')
                self.app._show_label_workspace('Bổ trợ')
                self.assertEqual(self.app.canvas.record.id, 's0')
            confirm.assert_not_called()
        self.assertEqual(widgets, {row['key']: row['frame'] for row in self.app.image_list.rows})

    def test_explicit_clear_survives_reload_and_missing_filter_is_source_specific(self):
        self.choose('wilt', '')
        self.assertNotIn('wilt', self.view.values())
        self.view.reload()
        self.assertNotIn('wilt', self.view.values())
        self.filter_attribute('wilt', '')
        self.assertEqual([r['id'] for r in self.view.filtered], ['s0'])
        self.app._show_label_workspace('Giàn')
        self.filter_attribute('wilt', 'absent')
        self.assertNotIn('', self.app.label_filter_values.values())
        self.app._show_label_workspace('Bổ trợ')
        self.assertIn('', self.app.label_filter_values.values())
        self.assertEqual([r['id'] for r in self.view.filtered], ['s0'])
