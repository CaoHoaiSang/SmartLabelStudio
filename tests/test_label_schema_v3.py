import copy
import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from smartlabel.label_schema import (legacy_label_schema, make_label_schema, validate_label_schema,
                                    label_for, validate_model_labels)
from smartlabel.hydro_labels import install_label_schema, model_keys, enforce_presence, display_values
from smartlabel.hydroponic import apply_hydroponic_slot_template, write_hydro_model_bundle, read_onnx_label_contract
from smartlabel.project_store import ProjectStore
from smartlabel.dataset_manager import DatasetManager


def custom_schema():
    attrs = legacy_label_schema()["attributes"]
    attrs.append({"id": "dom_la", "displayName": "Đốm lá", "role": "condition", "requires": "plant_presence",
                  "values": [{"id": "co_dom", "displayName": "Có đốm lá", "meaning": "positive"},
                             {"id": "khong_dom", "displayName": "Không đốm", "meaning": "negative"},
                             {"id": "chua_chac", "displayName": "Chưa chắc", "meaning": "uncertain"},
                             {"id": "bo_qua", "displayName": "Không áp dụng", "meaning": "not_applicable"}]})
    return make_label_schema(attrs)


class LabelSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / "workspace")
        self.project = self.store.create_project("V3 test", task="classify")
        apply_hydroponic_slot_template(self.project)

    def test_legacy_read_does_not_migrate_or_mutate_project(self):
        before = copy.deepcopy(self.project)
        self.assertEqual(model_keys(self.project), ("plant_presence", "yellow_leaf", "wilt"))
        self.assertEqual(self.project, before)

    def test_schema_roundtrip_and_strict_rejections(self):
        schema = custom_schema()
        self.assertEqual(validate_label_schema(json.loads(json.dumps(schema))), schema)
        for mutation in (
            lambda s: s["attributes"][1].update(requires="missing"),
            lambda s: s["attributes"][1].update(id="plant_presence"),
            lambda s: s["attributes"][1]["values"][0].update(meaning="positive"),
            lambda s: s["attributes"][1].update(id="../model"),
            lambda s: s["attributes"][1].update(id="constructor"),
            lambda s: s["attributes"][1].update(displayName=""),
            lambda s: s["attributes"].extend(s["attributes"] * 6),
        ):
            value = copy.deepcopy(schema)
            mutation(value)
            with self.assertRaises(ValueError):
                make_label_schema(value["attributes"])
        schema["schemaId"] = "tampered"
        with self.assertRaises(ValueError):
            validate_label_schema(schema)

    def test_output_order_is_explicit_and_may_be_positive_first(self):
        attr = custom_schema()["attributes"][-1]
        entry = {"attributeId": "dom_la", "outputLabels": ["co_dom", "khong_dom"],
                 "positiveIndex": 0, "negativeIndex": 1}
        validate_model_labels(attr, entry)
        for bad in ({**entry, "positiveIndex": 1}, {**entry, "outputLabels": ["absent", "present"]}):
            with self.assertRaises(ValueError):
                validate_model_labels(attr, bad)

    def test_presence_rules_and_display_changes_preserve_saved_labels(self):
        schema = custom_schema()
        install_label_schema(self.project, schema)
        attrs = {"plant_presence": "absent", "dom_la": "co_dom"}
        enforce_presence(self.project, attrs)
        self.assertEqual(attrs["dom_la"], "bo_qua")
        self.assertEqual(display_values(self.project, "dom_la")["co_dom"], "Có đốm lá")
        self.project.attribute_models["dom_la"] = "example-not-loaded.pt"
        renamed = copy.deepcopy(schema["attributes"])
        renamed[-1]["values"][0]["displayName"] = "Co_la_dom"
        install_label_schema(self.project, make_label_schema(renamed))
        self.assertEqual(self.project.attribute_schema["dom_la"][0], "co_dom")
        renamed[-1]["values"][0]["id"] = "changed"
        with self.assertRaises(ValueError):
            install_label_schema(self.project, make_label_schema(renamed))
        self.store.save(self.project)
        self.assertEqual(self.store.load(self.project.id).metadata["labelSchema"], self.project.metadata["labelSchema"])

    def test_export_excludes_custom_uncertain_na_and_absent_plants(self):
        install_label_schema(self.project, custom_schema())
        sources = Path(self.tmp.name) / "images"
        sources.mkdir()
        for index in range(8):
            Image.new("RGB", (32, 32), (index * 30, 80, 30)).save(sources / f"{index}.jpg")
        self.store.import_images(self.project, list(sources.glob("*.jpg")))
        labels = ["co_dom", "khong_dom", "chua_chac", "bo_qua"] * 2
        for index, record in enumerate(self.project.images):
            record.review_status = "reviewed"
            record.attributes = {"plant_presence": "present" if index < 6 else "absent", "dom_la": labels[index]}
            record.metadata["plant_instance_id"] = f"plant_{index}"
        output = DatasetManager(self.store).export_classification(self.project, "dom_la")
        metadata = json.loads((output / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(set(metadata["classes"]), {"co_dom", "khong_dom"})
        self.assertEqual(metadata["exported_crops"], 4)
        self.assertEqual(metadata["label_attribute"]["id"], "dom_la")

    def test_manager_adds_condition_and_edits_display_without_relabeling(self):
        import tkinter as tk
        from smartlabel.ui_components import ProjectSettingsDialog
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        dialog = ProjectSettingsDialog(root, self.project, lambda: None)
        with patch("smartlabel.ui_components.simpledialog.askstring", return_value="Đốm lá"):
            dialog._add_attribute_group()
        row = dialog.attribute_groups["dom_la"]["rows"][0]
        row["display"].set("Không có đốm lá")
        dialog._save()
        self.assertIn("dom_la", model_keys(self.project))
        self.assertEqual(display_values(self.project, "dom_la")["absent"], "Không có đốm lá")

    def test_onnx_export_reads_actual_names_not_sorted_schema(self):
        import onnx
        from onnx import helper, TensorProto
        path = Path(self.tmp.name) / "toy.onnx"
        model = helper.make_model(helper.make_graph([], "metadata-test",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 2])],
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 2])]))
        helper.set_model_props(model, {"names": "{0: 'co_dom', 1: 'khong_dom'}"})
        onnx.save(model, path)
        contract = read_onnx_label_contract(path, custom_schema()["attributes"][-1])
        self.assertEqual(contract["positiveIndex"], 0)
        helper.set_model_props(model, {"names": "{0: 'present', 1: 'absent'}"})
        onnx.save(model, path)
        with self.assertRaises(ValueError):
            read_onnx_label_contract(path, custom_schema()["attributes"][-1])
