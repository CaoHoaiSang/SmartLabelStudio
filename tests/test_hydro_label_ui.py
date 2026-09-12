import copy
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from smartlabel.hydro_labels import display_values, install_label_schema, model_attributes
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.label_schema import make_label_schema
from smartlabel.project_store import ProjectStore
from smartlabel.ui_components import ProjectSettingsDialog


class HydroLabelUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / "workspace")
        self.project = self.store.create_project("Label UI fixture", task="classify")
        apply_hydroponic_slot_template(self.project)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close_root)
        self.saved = []

    def close_root(self):
        for timer in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()

    def dialog(self):
        dialog = ProjectSettingsDialog(self.root, self.project, lambda: self.saved.append(True))
        dialog.withdraw()
        return dialog

    def test_negative_display_cannot_be_reassigned_by_settings_save(self):
        dialog = self.dialog()
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Đốm lá"):
            dialog._add_attribute_group()
        row = next(r for r in dialog.attribute_groups["dom_la"]["rows"] if r["value"].get() == "absent")
        row["display"].set("Có đốm lá")
        before = copy.deepcopy(self.project)
        with patch("smartlabel.ui_components.messagebox.showerror") as error:
            dialog._save()
        self.assertFalse(self.saved)
        error.assert_called_once()
        self.assertEqual(self.project, before)

    def test_condition_title_cannot_silently_rebrand_existing_model(self):
        self.project.attribute_models["yellow_leaf"] = "fixture-never-loaded.pt"
        dialog = self.dialog()
        before = copy.deepcopy(self.project)
        dialog.attribute_groups["yellow_leaf"]["title"].set("Đốm lá")
        with patch("smartlabel.ui_components.messagebox.showerror") as error:
            dialog._save()
        self.assertFalse(self.saved)
        error.assert_called_once()
        self.assertEqual(self.project, before)

    def test_legacy_misleading_display_is_presented_by_meaning_without_migration(self):
        attrs = model_attributes(self.project)
        attrs[1]["values"][0]["displayName"] = "Có đốm lá"
        install_label_schema(self.project, make_label_schema(attrs))
        before = copy.deepcopy(self.project)
        self.assertEqual(display_values(self.project, "yellow_leaf")["absent"], "Không có lá vàng")
        self.assertEqual(self.project, before)

    def test_new_condition_has_read_only_choices_and_no_old_model_reference(self):
        import customtkinter as ctk
        self.project.attribute_models["yellow_leaf"] = "fixture-never-loaded.pt"
        dialog = self.dialog()
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Đốm lá"):
            dialog._add_attribute_group()
        for row in dialog.attribute_groups["dom_la"]["rows"]:
            self.assertFalse(any(isinstance(w, ctk.CTkEntry) for w in row["frame"].winfo_children()))
        dialog._save()
        self.assertTrue(self.saved)
        self.assertEqual(display_values(self.project, "dom_la"), {
            "absent": "Không có đốm lá", "present": "Có đốm lá",
            "uncertain": "Chưa chắc chắn", "not_applicable": "Không áp dụng"})
        self.assertNotIn("dom_la", self.project.attribute_models)
        self.assertEqual(self.project.attribute_models["yellow_leaf"], "fixture-never-loaded.pt")

    def test_declined_rename_and_cancel_leave_project_unchanged(self):
        dialog = self.dialog()
        before = copy.deepcopy(self.project)
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Vàng lá"), \
             patch("smartlabel.ui_components.messagebox.askyesno", return_value=False):
            dialog._rename_hydro_attribute("yellow_leaf")
        self.assertEqual(dialog.attribute_groups["yellow_leaf"]["title"].get(), "Lá vàng")
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Vàng lá"), \
             patch("smartlabel.ui_components.messagebox.askyesno", return_value=True):
            dialog._rename_hydro_attribute("yellow_leaf")
        dialog.destroy()
        self.assertFalse(self.saved)
        self.assertEqual(self.project, before)

    def test_explicit_same_condition_rename_preserves_custom_schema_and_model(self):
        attrs = model_attributes(self.project)
        attrs[1]["values"].reverse()
        attrs[1]["values"][0]["id"] = "skip_custom"
        install_label_schema(self.project, make_label_schema(attrs))
        self.project.attribute_models["yellow_leaf"] = "fixture-never-loaded.pt"
        before_schema = copy.deepcopy(self.project.attribute_schema)
        before_values = copy.deepcopy(attrs[1]["values"])
        dialog = self.dialog()
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Vàng lá"), \
             patch("smartlabel.ui_components.messagebox.askyesno", return_value=True) as confirm:
            dialog._rename_hydro_attribute("yellow_leaf")
        confirm.assert_called_once()
        dialog._save()
        self.assertTrue(self.saved)
        self.assertEqual(self.project.attribute_schema, before_schema)
        attr = next(a for a in model_attributes(self.project) if a["id"] == "yellow_leaf")
        self.assertEqual(attr["values"], before_values)
        self.assertEqual(attr["displayName"], "Vàng lá")
        self.assertEqual(display_values(self.project, "yellow_leaf")["absent"], "Không có vàng lá")
        self.assertEqual(display_values(self.project, "yellow_leaf")["skip_custom"], "Không áp dụng")
        self.assertEqual(self.project.attribute_models["yellow_leaf"], "fixture-never-loaded.pt")
        self.store.save(self.project)
        self.assertEqual(self.store.load(self.project.id).metadata["labelSchema"], self.project.metadata["labelSchema"])

    def test_generic_annotation_settings_keep_free_form_values(self):
        import customtkinter as ctk
        from smartlabel.models import LabelClass
        self.project = self.store.create_project("Generic annotation fixture", task="detect")
        self.project.classes = [LabelClass(0, "Bottle", "#21c7ff")]
        dialog = self.dialog()
        self.assertFalse(dialog.hydro_attributes)
        row = dialog.attribute_groups["condition"]["rows"][0]
        self.assertTrue(any(isinstance(w, ctk.CTkEntry) for w in row["frame"].winfo_children()))
        row["value"].set("custom_value")
        dialog._save()
        self.assertTrue(self.saved)
        self.assertIn("custom_value", self.project.attribute_schema["condition"])

    def test_defaults_save_reload_clear_and_cancel_without_relabeling(self):
        from smartlabel.models import ImageRecord
        self.project.images.append(ImageRecord(id="old", file_name="never-opened.png",
            width=10, height=10, attributes={"plant_presence": "absent"}, review_status="reviewed"))
        before_images = copy.deepcopy(self.project.images)
        dialog = self.dialog()
        presence = dialog.attribute_groups["plant_presence"]
        self.assertEqual(presence["default_label"].get(), "Chưa chắc chắn")
        presence["default_menu"].cget("command")("Có cây")
        dialog.attribute_groups["yellow_leaf"]["default_menu"].cget("command")("Không có lá vàng")
        self.assertEqual(presence["required_control"].cget("state"), "disabled")
        dialog._save()
        self.store.save(self.project)
        self.project = self.store.load(self.project.id)
        self.assertEqual(self.project.attribute_settings["plant_presence"]["default"], "present")
        self.assertEqual(self.project.attribute_settings["yellow_leaf"]["default"], "absent")
        self.assertEqual(self.project.images, before_images)
        dialog = self.dialog()
        self.assertEqual(dialog.attribute_groups["plant_presence"]["default_label"].get(), "Có cây")
        dialog.attribute_groups["plant_presence"]["default_menu"].cget("command")(dialog.NO_DEFAULT)
        dialog._save()
        self.assertEqual(self.project.attribute_settings["plant_presence"]["default"], "")
        before = copy.deepcopy(self.project)
        dialog = self.dialog()
        dialog.attribute_groups["plant_presence"]["default_menu"].cget("command")("Có cây")
        dialog.destroy()
        self.assertEqual(self.project, before)

    def test_custom_default_mapping_survives_display_rename(self):
        attrs = model_attributes(self.project)
        negative = next(v for v in attrs[1]["values"] if v["meaning"] == "negative")
        negative["id"] = "clean_custom"
        install_label_schema(self.project, make_label_schema(attrs))
        self.project.attribute_settings["yellow_leaf"]["default"] = "clean_custom"
        dialog = self.dialog()
        group = dialog.attribute_groups["yellow_leaf"]
        self.assertEqual(group["default_label"].get(), "Không có lá vàng")
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Vàng lá"), \
             patch("smartlabel.ui_components.messagebox.askyesno", return_value=True):
            dialog._rename_hydro_attribute("yellow_leaf")
        self.assertEqual(group["default_label"].get(), "Không có vàng lá")
        dialog._save()
        self.assertEqual(self.project.attribute_settings["yellow_leaf"]["default"], "clean_custom")

    def test_invalid_default_rejected_without_mutating_project(self):
        before = copy.deepcopy(self.project)
        dialog = self.dialog()
        dialog.attribute_groups["plant_presence"]["default"].set("not_a_label")
        with patch("smartlabel.ui_components.messagebox.showerror") as error:
            dialog._save()
        error.assert_called_once()
        self.assertFalse(self.saved)
        self.assertEqual(self.project, before)


if __name__ == "__main__":
    unittest.main()
