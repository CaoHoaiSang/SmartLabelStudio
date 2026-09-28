from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from smartlabel.models import Annotation, ImageRecord, Project, LabelClass
from smartlabel.project_store import ProjectStore
from smartlabel.training_supplements import ReviewPixelCache, pixel_hash


class LabelPersistenceTests(unittest.TestCase):
    def test_save_contract_and_detached_snapshot_preserve_all_task_fields(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(folder)
            project = Project.create('Hydro and object data')
            ann = Annotation.create_box(0, [1, 2, 30, 40])
            ann.points = [[1, 2], [3, 4], [5, 6]]
            ann.attributes = {'cap': 'yes'}
            record = ImageRecord(id='r', file_name='r.png', width=60, height=50, annotations=[ann],
                attributes={'wilt': 'present'}, metadata={'nested': {'list': [1, 2]}}, lineage={'parent': 'p'})
            project.images = [record]
            project.classes = [LabelClass(0, 'bottle')]
            snapshot = project.to_dict()
            self.assertEqual(snapshot, asdict(project))
            snapshot['images'][0]['annotations'][0]['points'][0][0] = 999
            snapshot['images'][0]['metadata']['nested']['list'].append(999)
            self.assertEqual(ann.points[0][0], 1)
            self.assertEqual(record.metadata['nested']['list'], [1, 2])
            with patch.object(Project, 'to_dict', side_effect=AssertionError('save must not deep copy entire project')):
                store.save(project)
            saved = json.loads((store.project_dir(project) / 'project.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, asdict(project))
            self.assertEqual(store.load(project.id).to_dict(), asdict(project))

    def test_pixel_cache_reuses_decode_but_rechecks_bytes_and_is_bounded(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'test.bmp'
            Image.new('RGB', (20, 20), 'green').save(path)
            cache = ReviewPixelCache(limit=2)
            first = cache.fingerprint(path)
            self.assertEqual(first[1], pixel_hash(path))
            with patch('smartlabel.training_supplements.Image.open', side_effect=AssertionError('repeat decode')):
                self.assertEqual(cache.fingerprint(path), first)
            import os
            stamp = path.stat()
            Image.new('RGB', (20, 20), 'yellow').save(path)
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertNotEqual(cache.fingerprint(path), first)
            Image.new('RGB', (20, 20), 'red').save(path)
            cache.fingerprint(path)
            self.assertEqual(len(cache.values), 2)
            path.write_bytes(b'invalid image')
            with self.assertRaises(OSError):
                cache.fingerprint(path)

