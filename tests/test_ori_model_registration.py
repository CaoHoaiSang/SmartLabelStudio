from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import unittest

from smartlabel.project_store import ProjectStore


class OriModelRegistrationTests(unittest.TestCase):
    def fixture(self, root, encoding=None):
        source = root / "best.pt"
        source.write_bytes(b"checkpoint bytes")
        metadata = {"schema": "deltax_ori_checkpoint_v1", "task": "ori",
                    "heading": "image_x_clockwise_degrees",
                    "model_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        if encoding:
            metadata["heading_encoding"] = encoding
        else:
            metadata.pop("task")  # Older accepted sidecars need neither optional field.
        source.with_suffix(".ori.json").write_text(json.dumps(metadata), encoding="utf-8")
        return source

    def test_registration_preserves_legacy_and_vector_sidecars_byte_for_byte(self):
        for encoding in (None, "cos_sin_vector_v2"):
            with self.subTest(encoding=encoding), TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = self.fixture(root, encoding)
                store = ProjectStore(root / "workspace")
                target = store.register_model(source)
                self.assertEqual(target.read_bytes(), source.read_bytes())
                self.assertEqual(target.with_suffix(".ori.json").read_bytes(), source.with_suffix(".ori.json").read_bytes())
                self.assertNotEqual(target, source)
                self.assertEqual(store.register_model(source), target)

    def test_existing_registered_model_gets_missing_sidecar_without_copying_weights(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            metadata = source.with_suffix(".ori.json").read_bytes()
            source.with_suffix(".ori.json").unlink()
            store = ProjectStore(root / "workspace")
            target = store.register_model(source)
            modified = target.stat().st_mtime_ns
            source.with_suffix(".ori.json").write_bytes(metadata)
            with patch("smartlabel.project_store.shutil.copy2", side_effect=AssertionError("weights must be preserved")):
                self.assertEqual(store.register_model(source), target)
            self.assertEqual(target.stat().st_mtime_ns, modified)
            self.assertEqual(target.with_suffix(".ori.json").read_bytes(), metadata)

    def test_invalid_metadata_is_rejected_before_registering_any_file(self):
        changes = [{"model_sha256": "wrong"}, {"heading": "up"}, {"schema": "other"},
                   {"task": "detect"}, {"heading_encoding": "unknown"}, {"heading_encoding": []}]
        for change in changes:
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = self.fixture(root)
                sidecar = source.with_suffix(".ori.json")
                metadata = json.loads(sidecar.read_text())
                sidecar.write_text(json.dumps({**metadata, **change}))
                store = ProjectStore(root / "workspace")
                with self.assertRaisesRegex(ValueError, "Metadata ORI"):
                    store.register_model(source)
                self.assertEqual(list(store.models_dir.iterdir()), [])
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            source.with_suffix(".ori.json").write_bytes(b"invalid JSON")
            store = ProjectStore(root / "workspace")
            with self.assertRaisesRegex(ValueError, "Metadata ORI"):
                store.register_model(source)
            self.assertEqual(list(store.models_dir.iterdir()), [])

    def test_plain_model_stays_plain_and_corrupt_existing_target_is_not_overwritten(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "model.pt"
            source.write_bytes(b"plain model")
            store = ProjectStore(root / "workspace")
            target = store.register_model(source)
            self.assertFalse(target.with_suffix(".ori.json").exists())
            target.write_bytes(b"existing damaged file")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                store.register_model(source)
            self.assertEqual(target.read_bytes(), b"existing damaged file")

    def test_failed_sidecar_commit_does_not_leave_a_new_unusable_model(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            store = ProjectStore(root / "workspace")
            import os
            replace = os.replace
            def fail_metadata(src, dest):
                if Path(dest).suffix == ".json":
                    raise OSError("disk unavailable")
                return replace(src, dest)
            with patch("smartlabel.project_store.os.replace", side_effect=fail_metadata):
                with self.assertRaisesRegex(OSError, "disk unavailable"):
                    store.register_model(source)
            self.assertEqual(list(store.models_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
