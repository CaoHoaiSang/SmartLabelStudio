from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from smartlabel import app as app_module
from smartlabel.fleet_dataset_view import FleetDatasetView
from smartlabel.project_store import ProjectStore
from smartlabel.hydroponic import apply_hydroponic_slot_template


class FleetDatasetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root=tk.Tk();root.withdraw();root.update_idletasks();root.destroy()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error))
        cls.temp=TemporaryDirectory();cls.store=ProjectStore(Path(cls.temp.name)/'workspace')
        cls.project=cls.store.create_project('P4 synthetic',task='classify')
        apply_hydroponic_slot_template(cls.project);cls.store.save(cls.project)
        cls.other=cls.store.create_project('Other')
        cls.patches=[patch.object(app_module,'WORKSPACE',cls.store.workspace),patch.object(app_module.SmartLabelApp,'_refresh_hardware'),
                     patch.object(app_module.messagebox,'showinfo'),patch.object(app_module.messagebox,'showerror')]
        for item in cls.patches:item.start()
        cls.app=app_module.SmartLabelApp();cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.app.tk.call('after','info'):cls.app.tk.call('after','cancel',timer)
        cls.app.destroy()
        for item in reversed(cls.patches):item.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.app.fleet_dataset_job=None;self.app._change_project_context(self.project)
        self.view=FleetDatasetView(self.app,self.project)

    def tearDown(self):
        action=getattr(self.app,'fleet_dataset_job',None)
        if action:
            action.stop()
            if action.thread:action.thread.join(3)
        if self.view.winfo_exists():self.view.close()
        self.pump(lambda:getattr(self.app,'fleet_dataset_job',None) is None)

    def pump(self,condition):
        deadline=monotonic()+4
        while not condition() and monotonic()<deadline:
            self.app.update();sleep(.01)
        self.app.update();self.assertTrue(condition())

    def test_open_is_nonmodal_and_does_not_bind_export_or_train(self):
        self.assertIsNone(self.view.grab_current())
        self.assertFalse((self.store.project_dir(self.project)/'fleet_datasets').exists())
        self.assertFalse(self.app._project_job_busy())
        self.assertIsNone(self.view.preview_value)

    def test_background_completion_keeps_project_ownership_through_callback(self):
        release=Event();observed=[]
        try:
            self.assertTrue(self.view._launch(lambda action:release.wait(3),observed.append))
            self.assertTrue(self.app._project_job_busy());self.assertFalse(self.app._can_change_project())
            self.assertEqual(observed,[])
        finally:release.set()
        self.pump(lambda:self.app.fleet_dataset_job is None)
        self.assertEqual(observed,[True]);self.assertFalse(self.app._project_job_busy())

    def test_close_does_not_retain_grab_or_apply_stale_completion(self):
        release=Event();observed=[]
        try:
            self.view._launch(lambda action:release.wait(3),observed.append)
            self.view.close();self.assertTrue(self.app._project_job_busy())
            self.assertIsNone(self.app.grab_current())
        finally:release.set()
        self.pump(lambda:self.app.fleet_dataset_job is None)
        self.assertEqual(observed,[])

    def test_changed_selection_or_project_discards_late_confirmation(self):
        for change in ('selection','project'):
            with self.subTest(change=change):
                self.app.project=self.project;release=Event();observed=[]
                try:
                    self.view._launch(lambda action:release.wait(3),observed.append)
                    if change=='selection':self.view.invalidate()
                    else:self.app.project=self.other
                finally:release.set()
                self.pump(lambda:self.app.fleet_dataset_job is None)
                self.assertEqual(observed,[])
        self.app.project=self.project

    def test_thread_start_failure_releases_app_lock(self):
        with patch('smartlabel.fleet_dataset_view.Thread.start',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.view._launch(lambda _:None,lambda _:None)
        self.assertIsNone(self.app.fleet_dataset_job);self.assertFalse(self.app._project_job_busy())

    def test_stop_keeps_lock_until_worker_has_finished(self):
        started=Event();release=Event()
        try:
            def work(action):
                started.set();release.wait(3);action.check()
            self.view._launch(work,lambda _:self.fail('cancelled completion'))
            self.assertTrue(started.wait(2));self.view.stop();self.assertTrue(self.app._project_job_busy())
        finally:release.set()
        self.pump(lambda:self.app.fleet_dataset_job is None)
        self.assertIn('Đã dừng',self.view.message.cget('text'))

    def test_train_invalid_size_is_blocked_before_materialization(self):
        self.view.snapshot = {'snapshotBindingDigest': 'a' * 64}
        self.view.parameters['image_size'].delete(0, 'end')
        self.view.parameters['image_size'].insert(0, '2048')
        with patch.object(self.view.client, 'materialize') as materialize:
            self.view.train()
            materialize.assert_not_called()
        self.assertIsNone(self.app.fleet_dataset_job)
