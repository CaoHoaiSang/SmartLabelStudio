from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import time
import unittest

from smartlabel import app as app_module, heldout_collection as collection
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.project_store import ProjectStore
from test_heldout_collection import payload


class HeldoutReviewUiTests(unittest.TestCase):
    def test_shared_form_empty_review_navigation_project_change(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); store = ProjectStore(root / "workspace")
            project = store.create_project("TEST fixture", task="classify")
            apply_hydroponic_slot_template(project); store.save(project)
            lot = collection.create_lot(store, project, "16", "2026-09-01", reserved=True)
            collection.save_capture(store, project, lot, payload(root / "frame"), empty_slots=["slot_01"])
            with patch.object(app_module, "WORKSPACE", store.workspace), patch.object(app_module.SmartLabelApp, "_refresh_hardware"), patch.object(app_module.messagebox, "showerror") as error, patch.object(app_module.messagebox, "askyesno", return_value=True):
                app = app_module.SmartLabelApp(); app.withdraw()
                try:
                    app._change_project_context(deepcopy(project)); app._show_label_workspace("TEST")
                    view = app.supplement_view
                    self.assertIs(view, app.heldout_label_view)
                    self.assertIs(view.preview, app.canvas)
                    self.assertTrue(view.preview_ok)
                    self.assertEqual(len(view.rows), 10)
                    field, captions = view.form["plant_presence"]
                    caption = next(k for k, v in captions.items() if v == "absent")
                    field.set(caption); app._attribute_changed("plant_presence", caption)
                    self.drain(app, view)
                    self.assertEqual(view.values()["wilt"], "not_applicable")
                    app._approve_image_next(); self.drain(app, view)
                    self.assertEqual(collection.load_collection(store, project)[0]["images"][0]["reviewStatus"], "reviewed")
                    self.assertEqual(app.project.images, [])
                    app._show_label_workspace("Giàn")
                    self.assertIs(app.supplement_view, app.supplement_base_view)
                    app._show_label_workspace("TEST")
                    other = store.create_project("Other"); app._change_project_context(other)
                    self.assertFalse(app._supplement_active())
                    error.assert_not_called()
                finally:
                    for identifier in app.tk.call("after", "info"):
                        app.tk.call("after", "cancel", identifier)
                    app.destroy()

    def drain(self, app, view):
        deadline = time.monotonic()+10
        while view.busy and time.monotonic() < deadline:
            app.update(); time.sleep(.01)
        self.assertFalse(view.busy)
