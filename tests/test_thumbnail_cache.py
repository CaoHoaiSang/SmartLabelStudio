from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import customtkinter as ctk
from PIL import Image

from smartlabel.ui_components import ThumbnailList


class ThumbnailCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = ctk.CTk()
        self.root.withdraw()
        self.addCleanup(self.close_root)
        self.browser = ThumbnailList(self.root, command=lambda _: None)
        self.browser.cache_limit = 4
        self.path = Path(self.temp.name) / 'preview.png'
        Image.new('RGB', (90, 70), 'green').save(self.path)

    def close_root(self):
        for task in self.root.tk.call('after', 'info'):
            self.root.after_cancel(task)
        self.root.destroy()

    def rows(self, *keys):
        return [{'key': key, 'name': key, 'path': self.path, 'status': 'draft'} for key in keys]

    def test_reuse_order_bounded_cache_and_hidden_rows_cannot_delete(self):
        self.browser.set_items(self.rows('a', 'b'))
        frame = self.browser.rows[0]['frame']
        self.browser.select(0)
        self.browser.set_items(self.rows('s1', 's2'))
        self.assertFalse(frame.winfo_manager())
        deleted = []
        self.browser.delete_command = deleted.append
        self.browser._delete_key('a')
        self.assertFalse(deleted)
        self.browser.set_items(self.rows('b', 'a'))
        self.assertIs(self.browser.rows[1]['frame'], frame)
        self.assertEqual(list(self.browser.pack_slaves()), [row['frame'] for row in self.browser.rows])
        self.assertEqual(frame.cget('border_width'), 1)
        for index in range(10):
            self.browser.set_items(self.rows(f'{index}a', f'{index}b'))
            self.assertLessEqual(len(self.browser._row_by_key), 4)
            self.assertLessEqual(len(self.browser._thumbnail_cache), 4)
        self.assertFalse(frame.winfo_exists())
        self.browser.clear_cache()
        self.assertFalse(self.browser.rows)
        self.assertFalse(self.browser._row_by_key)
        self.assertFalse(self.browser._thumbnail_cache)

    def test_modified_and_deleted_image_invalidate_thumbnail_without_rebuilding_row(self):
        self.browser.set_items(self.rows('a'))
        row = self.browser.rows[0]
        first = row['thumb'].cget('image')
        Image.new('RGB', (100, 60), 'yellow').save(self.path)
        self.browser.set_items(self.rows('a'))
        self.assertIs(self.browser.rows[0], row)
        self.assertIsNot(row['thumb'].cget('image'), first)
        self.path.unlink()
        self.browser.set_items(self.rows('a'))
        self.assertIsNone(row['thumb'].cget('image'))
        self.assertEqual(row['thumb'].cget('text'), 'Không có ảnh')
