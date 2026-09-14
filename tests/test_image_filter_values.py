from types import SimpleNamespace
import unittest

from smartlabel.image_filters import filter_values, MISSING


class ImageFilterValueTests(unittest.TestCase):
    def test_missing_choice_follows_actual_source_and_attribute_scope(self):
        project = SimpleNamespace(attribute_schema={'state': ['ok', 'bad']}, metadata={}, classes=[],
            attribute_settings={'state': {'scope': 'image', 'default': 'ok'}}, images=[])
        record = SimpleNamespace(attributes={'state': 'ok'}, annotations=[])
        project.images.append(record)
        self.assertNotIn(MISSING, filter_values(project, ('attribute', 'state')))
        record.attributes.clear()
        self.assertIn(MISSING, filter_values(project, ('attribute', 'state')))
        self.assertNotIn(MISSING, filter_values(project, ('attribute', 'state'), []))
        record.attributes['state'] = 'ok'
        project.attribute_settings['state']['scope'] = 'annotation_crop'
        self.assertIn(MISSING, filter_values(project, ('attribute', 'state')))
        record.annotations.append(SimpleNamespace(attributes={'state': 'bad'}, class_id=0))
        self.assertNotIn(MISSING, filter_values(project, ('attribute', 'state')))
        self.assertNotIn(MISSING, filter_values(project, ('class', '')))
        record.annotations.clear()
        self.assertIn(MISSING, filter_values(project, ('class', '')))
        self.assertNotIn(MISSING, filter_values(project, ('all', '')))
