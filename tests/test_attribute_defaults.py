import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from smartlabel.attribute_defaults import image_attribute_defaults
from smartlabel.hydro_labels import install_label_schema, model_attributes
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.label_schema import make_label_schema
from smartlabel.project_store import ProjectStore


class AttributeDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Defaults fixture", task="classify")

    def test_image_import_respects_scope_and_never_overwrites_existing_review(self):
        self.project.attribute_schema = {"scene": ["bright", "dark"], "object": ["ok"], "invalid": ["ok"]}
        self.project.attribute_settings = {
            "scene": {"default": "bright", "scope": "image"},
            "object": {"default": "ok", "scope": "annotation_crop"},
            "invalid": {"default": "missing", "scope": "image"},
        }
        source = self.root / "image.png"
        Image.new("RGB", (16, 16), "red").save(source)
        self.assertEqual(self.store.import_images(self.project, [source]), (1, 0))
        record = self.project.images[0]
        self.assertEqual(record.attributes, {"scene": "bright"})
        self.assertEqual(record.review_status, "unlabeled")
        record.review_status = "reviewed"
        before = copy.deepcopy(record)
        self.project.attribute_settings["scene"]["default"] = "dark"
        self.assertEqual(self.store.import_images(self.project, [source]), (0, 1))
        self.assertEqual(record, before)

    def test_hydro_defaults_follow_custom_meanings_and_presence_dependency(self):
        apply_hydroponic_slot_template(self.project)
        attrs = model_attributes(self.project)
        for attr in attrs:
            for value in attr["values"]:
                value["id"] = "custom_" + value["meaning"]
        install_label_schema(self.project, make_label_schema(attrs))
        settings = self.project.attribute_settings
        settings["plant_presence"]["default"] = "custom_positive"
        settings["yellow_leaf"]["default"] = "custom_negative"
        settings["wilt"]["default"] = "custom_positive"
        before = copy.deepcopy(self.project)
        self.assertEqual(image_attribute_defaults(self.project), {
            "plant_presence": "custom_positive", "yellow_leaf": "custom_negative", "wilt": "custom_positive"})
        self.assertEqual(self.project, before)
        for value in ("", "invalid", "custom_negative", "custom_uncertain"):
            with self.subTest(value=value):
                settings["plant_presence"]["default"] = value
                defaults = image_attribute_defaults(self.project)
                self.assertEqual(defaults["yellow_leaf"], "custom_not_applicable")
                self.assertEqual(defaults["wilt"], "custom_not_applicable")


if __name__ == "__main__":
    unittest.main()
