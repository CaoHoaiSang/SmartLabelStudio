from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
import zipfile

from PIL import Image

from smartlabel.dataset_manager import DatasetManager
from smartlabel.deployment import build_vision_bundle_manifest, classifier_manifest_entry, write_classifier_pt_bundle
from smartlabel.models import Annotation
from smartlabel.project_store import ProjectStore
from smartlabel.quality import inspect_project
from smartlabel.auto_label import Sam2Adapter, YoloAutoLabeler, mask_to_geometry
from smartlabel.frame_filter import (
    SOURCE_ALL,
    SOURCE_IMPORTED,
    SOURCE_VIDEO,
    FrameFilterSettings,
    analyze_smart_images,
    analyze_video_frames,
    image_records_for_filter,
    image_records_for_source,
    imported_image_records,
    latest_import_records,
    video_frame_records,
)
from smartlabel.frame_filter_dialog import PREVIEW_BACKGROUND, PREVIEW_SIZE, build_contained_preview
from smartlabel.frame_filter_dialog import SmartFrameFilterDialog
from smartlabel.ui_components import PROJECT_TEMPLATE_HELP, PROJECT_TEMPLATE_LABELS
from smartlabel.ui_components import ToolTip
from smartlabel.app import PROJECT_ACTION_GROUPS, PROJECT_ACTION_TOOLTIPS, REVIEW_ACTION_GROUPS


class SmartLabelCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "workspace")
        self.project = self.store.create_project("Test", classes=["a", "b"])
        self.source = self.root / "source"
        self.source.mkdir()
        Image.new("RGB", (100, 80), "red").save(self.source / "image_1.jpg")

    def test_sam_mask_geometry_prefers_component_containing_click(self):
        import numpy as np

        mask = np.zeros((100, 140), dtype=np.uint8)
        mask[10:70, 10:70] = 1       # larger unrelated component
        mask[30:55, 95:125] = 1     # clicked component
        geometry = mask_to_geometry(mask, anchor_point=(110, 40))

        self.assertEqual(geometry["bbox"], [95.0, 30.0, 30.0, 25.0])
        self.assertGreaterEqual(len(geometry["points"]), 4)
        self.assertEqual(len(geometry["obb"]), 4)

    def test_sam_point_only_prompt_does_not_require_box(self):
        import numpy as np

        calls = []

        class FakePredictor:
            def predict(self, **kwargs):
                calls.append(kwargs)
                masks = np.zeros((2, 12, 12), dtype=np.uint8)
                masks[1, 2:9, 3:10] = 1
                return masks, np.asarray([0.2, 0.9], dtype=np.float32), None

        adapter = object.__new__(Sam2Adapter)
        adapter.predictor = FakePredictor()
        adapter.np = np
        mask, score = adapter.mask_from_points([[6.0, 5.0]], [1])

        self.assertIsNone(calls[0]["box"])
        self.assertEqual(calls[0]["point_coords"].shape, (1, 2))
        self.assertEqual(int(mask.sum()), 49)
        self.assertAlmostEqual(score, 0.9, places=5)

    def tearDown(self):
        self.temp.cleanup()

    def test_import_deduplicates_and_persists(self):
        added, skipped = self.store.import_images(self.project, [self.source])
        self.assertEqual((added, skipped), (1, 0))
        added, skipped = self.store.import_images(self.project, [self.source])
        self.assertEqual((added, skipped), (0, 1))
        loaded = self.store.load(self.project.id)
        self.assertEqual(len(loaded.images), 1)
        self.assertEqual((loaded.images[0].width, loaded.images[0].height), (100, 80))

    def test_filter_preview_contains_complete_wide_and_tall_images(self):
        for size in ((1200, 180), (180, 1200)):
            source = Image.new("RGB", size, "red")
            split = size[0] // 2
            for x in range(split, size[0]):
                for y in range(size[1]):
                    source.putpixel((x, y), (0, 0, 255))
            preview, (left, top, width, height) = build_contained_preview(source)
            self.assertEqual(preview.size, PREVIEW_SIZE)
            self.assertGreaterEqual(left, 10)
            self.assertGreaterEqual(top, 10)
            self.assertLessEqual(left + width, PREVIEW_SIZE[0] - 10)
            self.assertLessEqual(top + height, PREVIEW_SIZE[1] - 10)
            left_sample = preview.getpixel((left + max(1, width // 4), top + max(1, height // 2)))
            right_sample = preview.getpixel((left + max(1, width * 3 // 4), top + max(1, height // 2)))
            self.assertGreater(left_sample[0], left_sample[2])
            self.assertGreater(right_sample[2], right_sample[0])
            self.assertEqual(preview.getpixel((0, 0)), PREVIEW_BACKGROUND)

    def test_filter_table_compacts_long_text_to_balanced_cells(self):
        filename = "0123456789_very_long_camera_filename_that_should_not_take_the_table.jpg"
        compact = SmartFrameFilterDialog._compact_file_name(filename)
        wrapped = SmartFrameFilterDialog._wrap_table_text(
            "AI không thấy vật và đây là một lý do rất dài cần được xuống dòng thay vì chiếm toàn bộ bảng"
        )
        self.assertLessEqual(len(compact), 34)
        self.assertIn("…", compact)
        self.assertLessEqual(len(wrapped.splitlines()), 2)
        self.assertTrue(all(len(line) <= 43 for line in wrapped.splitlines()))
        separated = SmartFrameFilterDialog._with_column_separator("ẢNH NHẬP\nBẢO VỆ")
        self.assertEqual(separated.count("│"), 2)

    def test_latest_import_scope_excludes_existing_images(self):
        self.store.import_images(self.project, [self.source])
        first_batch = self.project.last_import_batch
        self.assertTrue(first_batch)
        self.assertEqual(self.project.images[0].import_batch, first_batch)

        second_source = self.root / "second_source"
        second_source.mkdir()
        Image.new("RGB", (100, 80), "blue").save(second_source / "image_2.jpg")
        self.store.import_images(self.project, [second_source])
        second_batch = self.project.last_import_batch
        self.assertNotEqual(first_batch, second_batch)
        self.assertEqual([item.file_name for item in latest_import_records(self.project)], [self.project.images[-1].file_name])
        self.assertEqual(len(image_records_for_filter(self.project, include_existing=False)), 1)
        self.assertEqual(len(image_records_for_filter(self.project, include_existing=True)), 2)

        # A duplicate-only import must not replace the last successful batch.
        added, skipped = self.store.import_images(self.project, [second_source])
        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(self.project.last_import_batch, second_batch)
        loaded = self.store.load(self.project.id)
        self.assertEqual(loaded.last_import_batch, second_batch)
        self.assertEqual(loaded.images[-1].import_batch, second_batch)

    def test_legacy_import_times_are_migrated_into_separate_batches(self):
        first_source = self.root / "legacy_first"
        second_source = self.root / "legacy_second"
        first_source.mkdir()
        second_source.mkdir()
        Image.new("RGB", (80, 60), "red").save(first_source / "old_1.jpg")
        Image.new("RGB", (80, 60), "green").save(first_source / "old_2.jpg")
        Image.new("RGB", (80, 60), "blue").save(second_source / "new_1.jpg")
        self.store.import_images(self.project, [first_source])
        self.store.import_images(self.project, [second_source])
        for index, record in enumerate(self.project.images):
            record.import_batch = ""
            record.created_at = "2026-01-01T00:00:00+00:00" if index < 2 else "2026-01-01T01:00:00+00:00"
        self.project.last_import_batch = ""
        self.store.save(self.project)

        changed = self.store.ensure_import_batches(self.project)

        self.assertTrue(changed)
        self.assertEqual(self.project.images[0].import_batch, self.project.images[1].import_batch)
        self.assertNotEqual(self.project.images[1].import_batch, self.project.images[2].import_batch)
        self.assertEqual(self.project.last_import_batch, self.project.images[2].import_batch)
        self.assertEqual(latest_import_records(self.project), [self.project.images[2]])

    def test_delete_image_removes_project_copy_and_all_annotation_metadata(self):
        self.store.import_images(self.project, [self.source])
        record = self.project.images[0]
        record.annotations.append(Annotation.create_box(1, [10, 20, 30, 40]))
        record.annotations[0].attributes["condition"] = "can_dep"
        record.review_status = "reviewed"
        self.store.save(self.project)
        project_copy = self.store.image_path(self.project, record)

        removed = self.store.delete_image(self.project, record)

        self.assertEqual(removed, 1)
        self.assertFalse(project_copy.exists())
        self.assertTrue((self.source / "image_1.jpg").exists())
        loaded = self.store.load(self.project.id)
        self.assertEqual(loaded.images, [])
        self.assertEqual(loaded.last_import_batch, "")

    def test_delete_latest_import_keeps_previous_batch_and_original_sources(self):
        self.store.import_images(self.project, [self.source])
        first_record = self.project.images[0]
        first_batch = self.project.last_import_batch

        latest_source = self.root / "accidental_bottle_import"
        latest_source.mkdir()
        Image.new("RGB", (100, 80), "blue").save(latest_source / "bottle_1.jpg")
        Image.new("RGB", (100, 80), "green").save(latest_source / "bottle_2.jpg")
        self.store.import_images(self.project, [latest_source])
        latest_records = latest_import_records(self.project)
        self.assertEqual(len(latest_records), 2)
        latest_records[0].annotations.append(Annotation.create_box(0, [1, 2, 30, 40]))
        latest_records[0].review_status = "reviewed"
        self.store.save(self.project)

        removed_images, removed_annotations = self.store.delete_images(self.project, latest_records)

        self.assertEqual((removed_images, removed_annotations), (2, 1))
        self.assertEqual([record.id for record in self.project.images], [first_record.id])
        self.assertEqual(self.project.last_import_batch, first_batch)
        self.assertTrue((latest_source / "bottle_1.jpg").exists())
        self.assertTrue((latest_source / "bottle_2.jpg").exists())
        loaded = self.store.load(self.project.id)
        self.assertEqual([record.id for record in loaded.images], [first_record.id])
        self.assertEqual(loaded.last_import_batch, first_batch)

    def test_new_project_templates_are_presets_not_saved_project_entries(self):
        self.assertEqual(
            set(PROJECT_TEMPLATE_LABELS.values()),
            {"deltax_bottle", "hydroponic_slot", "blank"},
        )
        self.assertEqual(set(PROJECT_TEMPLATE_HELP), set(PROJECT_TEMPLATE_LABELS.values()))
        self.assertTrue(all("project_" not in code for code in PROJECT_TEMPLATE_LABELS.values()))

    def test_project_page_actions_have_groups_and_detailed_hydro_help(self):
        self.assertEqual(set(PROJECT_ACTION_GROUPS), {"import", "cleanup", "settings"})
        self.assertIn("DỌN DỮ LIỆU NHẬP", PROJECT_ACTION_GROUPS["cleanup"][0])
        self.assertEqual(set(REVIEW_ACTION_GROUPS), {"checks", "triage"})
        self.assertIn("KIỂM TRA DATASET", REVIEW_ACTION_GROUPS["checks"][0])
        self.assertEqual(
            set(PROJECT_ACTION_TOOLTIPS),
            {
                "import_folder",
                "import_files",
                "capture_manifest",
                "import_video",
                "hydro_qa",
                "smart_filter",
                "delete_latest",
                "project_settings",
            },
        )
        for variants in PROJECT_ACTION_TOOLTIPS.values():
            self.assertEqual(set(variants), {"standard", "hydro"})
            self.assertGreater(len(variants["standard"]), 50)
            self.assertGreater(len(variants["hydro"]), 80)
        self.assertIn("đủ đúng 10 slot", PROJECT_ACTION_TOOLTIPS["capture_manifest"]["hydro"])
        self.assertIn("trang Kiểm duyệt", PROJECT_ACTION_TOOLTIPS["hydro_qa"]["hydro"])
        self.assertIn("không tự sửa hay xóa", PROJECT_ACTION_TOOLTIPS["hydro_qa"]["hydro"])
        self.assertIn("không thể hoàn tác", PROJECT_ACTION_TOOLTIPS["delete_latest"]["hydro"])
        self.assertIn("Cài đặt AI Camera", PROJECT_ACTION_TOOLTIPS["project_settings"]["hydro"])

    def test_tooltip_text_can_change_with_project_context(self):
        tooltip = object.__new__(ToolTip)
        tooltip.text = "standard"
        tooltip.after_id = None
        tooltip.window = None

        tooltip.set_text("hydro")

        self.assertEqual(tooltip.text, "hydro")

    def test_detailed_tooltip_prefers_side_without_covering_its_button(self):
        self.assertEqual(
            ToolTip._placement(60, 200, 220, 36, 360, 100, 1500, 900),
            (288, 200),
        )
        self.assertEqual(
            ToolTip._placement(1250, 820, 220, 36, 360, 100, 1500, 900),
            (882, 792),
        )

    def test_bulk_delete_and_video_frame_filter_keep_original_images(self):
        self.store.import_images(self.project, [self.source])
        original = self.project.images[0]
        video_source = self.root / "frame_source"
        video_source.mkdir()
        for index, color in enumerate(((10, 10, 10), (11, 11, 11), (230, 230, 230))):
            Image.new("RGB", (100, 80), color).save(video_source / f"clip_frame_{index:08d}.jpg")
        self.store.import_images(self.project, [video_source])
        video_records = self.project.images[1:]
        for record in video_records:
            record.source_path = str(self.root / "clip.mp4") + "#frame"
            record.capture_group = "video_clip"
        self.store.save(self.project)

        self.assertEqual(video_frame_records(self.project), video_records)
        decisions = analyze_video_frames(
            self.project,
            self.store,
            FrameFilterSettings(duplicate_similarity=0.995, negative_keep_percent=50),
            records=video_records,
        )
        self.assertEqual(len(decisions), 3)
        self.assertTrue(any(item.category == "duplicate" for item in decisions))

        removed_images, _ = self.store.delete_images(self.project, video_records)
        self.assertEqual(removed_images, 3)
        self.assertEqual([item.id for item in self.project.images], [original.id])
        self.assertTrue(self.store.image_path(self.project, original).exists())

        stale = self.store.project_dir(self.project) / "cache" / "video_extract_interrupted"
        stale.mkdir(parents=True)
        (stale / "orphan.jpg").write_bytes(b"orphan")
        removed_dirs, removed_files = self.store.cleanup_stale_video_cache(self.project)
        self.assertEqual((removed_dirs, removed_files), (1, 1))
        self.assertFalse(stale.exists())

    def test_smart_filter_supports_imported_images_and_protects_label_work(self):
        stills = self.root / "imported_stills"
        stills.mkdir()
        for index in range(3):
            image = Image.new("RGB", (160, 100), (35, 120, 65))
            for x in range(25, 135):
                for y in range(30, 70):
                    image.putpixel((x, y), (190, 205, 80))
            # Keep source hashes distinct while producing the same normalized
            # preview, as happens with re-encoded or copied camera images.
            image.putpixel((index, 0), (index + 1, 2, 3))
            image.save(stills / f"bottle_copy_{index}.png")
        Image.new("RGB", (160, 100), (15, 20, 170)).save(stills / "different.png")
        self.store.import_images(self.project, [stills])
        records = imported_image_records(self.project)
        self.assertEqual(len(records), 4)
        self.assertEqual(image_records_for_source(self.project, SOURCE_IMPORTED), records)
        self.assertEqual(image_records_for_source(self.project, SOURCE_VIDEO), [])
        self.assertEqual(image_records_for_source(self.project, SOURCE_ALL), self.project.images)

        copies = [record for record in records if "bottle_copy" in record.file_name]
        copies[0].annotations.append(Annotation.create_box(0, [20, 20, 120, 75]))
        copies[1].review_status = "reviewed"
        decisions = analyze_smart_images(
            self.project,
            self.store,
            FrameFilterSettings(duplicate_similarity=0.99),
            records=records,
        )
        by_id = {item.image_id: item for item in decisions}
        duplicate_decisions = [item for item in decisions if item.category == "duplicate"]
        self.assertTrue(duplicate_decisions)
        self.assertTrue(any(item.suggested_delete for item in duplicate_decisions))
        self.assertTrue(by_id[copies[0].id].protected)
        self.assertTrue(by_id[copies[1].id].protected)
        self.assertFalse(by_id[copies[0].id].suggested_delete)
        self.assertFalse(by_id[copies[1].id].suggested_delete)

    def test_dynamic_attribute_groups_persist_without_affecting_legacy_projects(self):
        self.project.attribute_schema = {
            "condition": ["nguyen_ven", "can_dep"],
            "quality_result": ["OK", "NG"],
        }
        self.project.attribute_settings = {
            "condition": {"title": "Tình trạng", "default": "", "required": False, "role": "classification"},
            "quality_result": {"title": "Kết quả", "default": "OK", "required": True, "role": "pass_fail"},
        }
        self.project.attribute_classification_enabled = True
        self.project.attribute_models = {"condition": "models/condition_best.pt"}
        self.project.attribute_model_bundle = "bundles/classification_models.zip"
        self.project.active_rknn_model = "deploy/detector.rknn"
        self.project.attribute_rknn_models = {"condition": "deploy/condition.rknn"}
        self.store.save(self.project)
        loaded = self.store.load(self.project.id)
        self.assertEqual(loaded.attribute_schema["quality_result"], ["OK", "NG"])
        self.assertEqual(loaded.attribute_settings["quality_result"]["default"], "OK")
        self.assertTrue(loaded.attribute_settings["quality_result"]["required"])
        self.assertTrue(loaded.attribute_classification_enabled)
        self.assertEqual(loaded.attribute_models["condition"], "models/condition_best.pt")
        self.assertEqual(loaded.attribute_model_bundle, "bundles/classification_models.zip")
        self.assertEqual(loaded.active_rknn_model, "deploy/detector.rknn")
        self.assertEqual(loaded.attribute_rknn_models["condition"], "deploy/condition.rknn")

    def test_classification_export_crops_objects_by_attribute(self):
        self.store.import_images(self.project, [self.source])
        self.project.attribute_schema = {"condition": ["nguyen_ven", "can_dep"]}
        self.project.attribute_settings = {
            "condition": {"title": "Tình trạng", "default": "", "required": True, "role": "classification"}
        }
        ann = Annotation.create_box(0, [10, 10, 50, 40])
        ann.attributes["condition"] = "can_dep"
        self.project.images[0].annotations.append(ann)
        exported = DatasetManager(self.store).export_classification(
            self.project,
            "condition",
            reviewed_only=False,
        )
        metadata = json.loads((exported / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["task"], "classify")
        self.assertEqual(metadata["attribute_key"], "condition")
        self.assertEqual(metadata["exported_crops"], 1)
        self.assertEqual(len(list((exported / "train" / "can_dep").glob("*.jpg"))), 1)

        final_export = DatasetManager(self.store).export_classification(
            self.project,
            "condition",
            reviewed_only=False,
            split_strategy=DatasetManager.STRATEGY_TRAIN_ALL,
        )
        final_metadata = json.loads((final_export / "export.json").read_text(encoding="utf-8"))
        self.assertFalse(final_metadata["validation_enabled"])
        self.assertFalse(final_metadata["independent_test"])
        self.assertEqual(final_metadata["exported_crops"], 1)
        self.assertEqual(final_metadata["physical_crops"], 2)
        self.assertEqual(len(list((final_export / "val" / "can_dep").glob("*.jpg"))), 1)

    def test_two_stage_bundle_manifest_keeps_detector_and_attributes_separate(self):
        self.project.attribute_schema = {"condition": ["nguyen_ven", "can_dep"]}
        self.project.attribute_settings = {
            "condition": {"title": "Tình trạng", "role": "classification"}
        }
        classifier = classifier_manifest_entry(
            self.project,
            attribute_key="condition",
            model_name="classifier_condition.rknn",
            metadata={
                "imgsz": [224, 224],
                "names": {"0": "can_dep", "1": "nguyen_ven"},
            },
        )
        manifest = build_vision_bundle_manifest(
            self.project,
            localization_model="localization_detector.rknn",
            localization_metadata={"task": "detect", "imgsz": [640, 640]},
            classifiers=[classifier],
        )
        self.assertEqual(manifest["pipeline"], "detection_then_classification")
        self.assertEqual(manifest["localization"]["task"], "detect")
        self.assertEqual(manifest["classifiers"][0]["attribute_key"], "condition")
        self.assertEqual(manifest["runtime_rules"]["result_field"], "attributes")

    def test_multiple_classifier_pt_models_are_packaged_with_separate_label_spaces(self):
        self.project.attribute_schema = {
            "condition": ["nguyen_ven", "can_dep"],
            "cap": ["co_nap", "mat_nap"],
        }
        self.project.attribute_settings = {
            "condition": {"title": "Tình trạng", "role": "classification"},
            "cap": {"title": "Nắp chai", "role": "classification"},
        }
        condition = self.root / "condition.pt"
        cap = self.root / "cap.pt"
        condition.write_bytes(b"condition-model")
        cap.write_bytes(b"cap-model")
        bundle = write_classifier_pt_bundle(
            self.project,
            self.root / "classification_models.zip",
            {"condition": condition, "cap": cap},
        )
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("classification_bundle.json").decode("utf-8"))
            self.assertEqual(manifest["model_count"], 2)
            self.assertEqual({item["attribute_key"] for item in manifest["models"]}, {"condition", "cap"})
            self.assertIn("models/classifier_condition.pt", archive.namelist())
            self.assertIn("models/classifier_cap.pt", archive.namelist())

    def test_yolo_and_coco_export(self):
        self.store.import_images(self.project, [self.source])
        record = self.project.images[0]
        record.annotations.append(Annotation.create_box(1, [10, 20, 30, 40]))
        record.review_status = "reviewed"
        self.store.save(self.project)
        manager = DatasetManager(self.store)
        yolo = manager.export_yolo(self.project)
        label = next((yolo / "labels").rglob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(label, "1 0.250000 0.500000 0.300000 0.500000")
        coco = json.loads(manager.export_coco(self.project).read_text(encoding="utf-8"))
        self.assertEqual(len(coco["annotations"]), 1)
        self.assertEqual(coco["annotations"][0]["category_id"], 1)

    def test_group_split_balances_image_count_without_leakage(self):
        groups = {"video": list(range(71))}
        groups.update({f"still_{index}": list(range(4)) for index in range(31)})
        split = DatasetManager.split_capture_groups(groups, seed=42)
        flattened = [key for keys in split.values() for key in keys]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), set(groups))
        counts = {name: sum(len(groups[key]) for key in keys) for name, keys in split.items()}
        self.assertLessEqual(abs(counts["train"] - 137), 7)
        self.assertLessEqual(abs(counts["val"] - 29), 7)
        self.assertLessEqual(abs(counts["test"] - 29), 7)

    def test_locked_split_keeps_old_groups_and_sends_new_groups_to_train(self):
        for index in range(8):
            Image.new("RGB", (100, 80), (index * 20, 10, 10)).save(self.source / f"locked_{index}.jpg")
        self.store.import_images(self.project, [self.source])
        manager = DatasetManager(self.store)
        first = manager.ensure_split_assignment(self.project, force_rebalance=True)["groups"]

        added_source = self.root / "added"
        added_source.mkdir()
        Image.new("RGB", (100, 80), "blue").save(added_source / "new_capture.jpg")
        self.store.import_images(self.project, [added_source])
        second = manager.ensure_split_assignment(self.project)["groups"]

        self.assertTrue(all(second[key] == value for key, value in first.items()))
        new_group = self.project.images[-1].capture_group or self.project.images[-1].id
        self.assertEqual(second[new_group], "train")
        manager.set_group_split(self.project, new_group, "test")
        self.assertEqual(manager.ensure_split_assignment(self.project)["groups"][new_group], "test")

    def test_final_split_strategies_preserve_or_consume_test(self):
        for index in range(11):
            path = self.source / f"strategy_{index}.jpg"
            Image.new("RGB", (100, 80), (index * 17 % 255, index * 11 % 255, 20)).save(path)
        self.store.import_images(self.project, [self.source])
        for record in self.project.images:
            record.review_status = "reviewed"
            record.annotations.append(Annotation.create_box(0, [10, 10, 30, 30]))
        manager = DatasetManager(self.store)
        locked = manager.ensure_split_assignment(self.project, force_rebalance=True)
        locked_counts = {split: 0 for split in ("train", "val", "test")}
        for record in self.project.images:
            locked_counts[locked["groups"][record.capture_group or record.id]] += 1

        final_dir = manager.export_yolo(
            self.project,
            split_strategy=DatasetManager.STRATEGY_FINAL_KEEP_TEST,
        )
        final_meta = json.loads((final_dir / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(final_meta["counts"]["train"], locked_counts["train"] + locked_counts["val"])
        self.assertEqual(final_meta["counts"]["test"], locked_counts["test"])
        self.assertFalse(final_meta["validation_enabled"])
        self.assertTrue(final_meta["independent_test"])
        self.assertIn("val: images/test", (final_dir / "data.yaml").read_text(encoding="utf-8"))

        all_dir = manager.export_yolo(
            self.project,
            split_strategy=DatasetManager.STRATEGY_TRAIN_ALL,
        )
        all_meta = json.loads((all_dir / "export.json").read_text(encoding="utf-8"))
        self.assertEqual(all_meta["counts"]["train"], len(self.project.images))
        self.assertEqual(all_meta["counts"]["test"], 0)
        self.assertFalse(all_meta["independent_test"])
        self.assertIn("val: images/train", (all_dir / "data.yaml").read_text(encoding="utf-8"))

    def test_quality_finds_invalid_box(self):
        self.store.import_images(self.project, [self.source])
        self.project.images[0].annotations.append(Annotation.create_box(0, [-2, 0, 20, 20]))
        issues = inspect_project(self.project)
        self.assertTrue(any("ngoài ảnh" in issue.message for issue in issues))

    def test_generic_quality_is_not_polluted_by_hydro_rules(self):
        self.store.import_images(self.project, [self.source])
        record = self.project.images[0]
        issues = inspect_project(self.project)
        messages = [issue.message for issue in issues]
        self.assertNotIn("Project chứa đường dẫn nguồn tuyệt đối", messages)
        self.assertNotIn("Nhãn condition mâu thuẫn với plant_presence", messages)

    def test_seg_annotation_can_still_export_as_detection_box(self):
        ann = Annotation.create_box(1, [10, 20, 30, 40])
        ann.kind = "polygon"
        ann.points = [[10, 20], [40, 20], [40, 60], [10, 60]]
        detection = DatasetManager._to_yolo(ann, 100, 80, segmentation=False)
        segmentation = DatasetManager._to_yolo(ann, 100, 80, segmentation=True)
        self.assertEqual(detection, "1 0.250000 0.500000 0.300000 0.500000")
        self.assertEqual(len(segmentation.split()), 9)

    def test_obb_and_orientation_export_formats(self):
        ann = Annotation.create_box(0, [10, 20, 30, 40])
        ann.obb = [[10, 20], [40, 20], [40, 60], [10, 60]]
        ann.orientation = [[25, 40], [40, 40]]
        obb = DatasetManager._to_yolo_task(ann, 100, 80, "obb")
        pose = DatasetManager._to_yolo_task(ann, 100, 80, "pose")
        self.assertEqual(len(obb.split()), 9)
        self.assertEqual(len(pose.split()), 11)
        self.assertTrue(pose.endswith("0.400000 0.500000 2"))
        self.store.import_images(self.project, [self.source])
        self.project.images[0].annotations.append(ann)
        self.project.images[0].review_status = "reviewed"
        manager = DatasetManager(self.store)
        obb_dir = manager.export_yolo(self.project, task="obb")
        pose_dir = manager.export_yolo(self.project, task="pose")
        self.assertEqual(json.loads((obb_dir / "export.json").read_text(encoding="utf-8"))["task"], "obb")
        self.assertIn("kpt_shape: [2, 3]", (pose_dir / "data.yaml").read_text(encoding="utf-8"))

    def test_auto_label_reads_segmentation_and_pose_outputs(self):
        import torch

        result = SimpleNamespace(
            obb=None,
            boxes=SimpleNamespace(
                xyxy=torch.tensor([[10.0, 20.0, 40.0, 60.0]]),
                cls=torch.tensor([1.0]),
                conf=torch.tensor([0.9]),
            ),
            masks=SimpleNamespace(xy=[[[10.0, 20.0], [40.0, 20.0], [40.0, 60.0], [10.0, 60.0]]]),
            keypoints=SimpleNamespace(xy=torch.tensor([[[25.0, 40.0], [40.0, 40.0]]])),
        )
        labeler = YoloAutoLabeler.__new__(YoloAutoLabeler)
        labeler.model_path = Path("pose-seg.pt")
        labeler.device = "cpu"
        labeler.model = SimpleNamespace(predict=lambda **_kwargs: [result])
        annotations = labeler.predict("image.jpg")
        self.assertEqual(len(annotations), 1)
        self.assertEqual(len(annotations[0].points), 4)
        self.assertEqual(len(annotations[0].orientation), 2)

    def test_sam2_config_is_discovered_from_installed_package(self):
        configs = Sam2Adapter.available_configs()
        if not configs:
            self.skipTest("SAM2 is optional")
        suggested = Sam2Adapter.suggest_config()
        self.assertIn(suggested, configs)
        self.assertEqual(Sam2Adapter.resolve_config(suggested, "sam2_hiera_small.pt"), suggested)
        with self.assertRaisesRegex(RuntimeError, "checkpoint|Checkpoint"):
            Sam2Adapter("", suggested, device="cpu")
        if not any("sam2.1" in item for item in configs):
            with self.assertRaisesRegex(RuntimeError, "SAM2.1"):
                Sam2Adapter.resolve_config(suggested, "sam2.1_hiera_s.pt")


if __name__ == "__main__":
    unittest.main()
