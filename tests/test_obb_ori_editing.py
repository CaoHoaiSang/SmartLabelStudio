"""Object-geometry regressions; never edit operator projects or load SAM weights."""
import copy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
import unittest

from PIL import Image

from smartlabel.annotation_canvas import AnnotationCanvas
from smartlabel.models import Annotation, ImageRecord, LabelClass, Project
from smartlabel.annotation_geometry import direction, edit_obb, frame


def rotated_box(cx=400, cy=300, width=240, height=120, angle=25):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [[cx + x*c - y*s, cy + x*s + y*c]
            for x, y in ((-width/2, -height/2), (width/2, -height/2),
                         (width/2, height/2), (-width/2, height/2))]


def envelope(points):
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)]


class ObbOriCanvasTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.changes = []
        self.canvas = AnnotationCanvas(self.root, lambda: self.changes.append(True), lambda _id: None)
        self.ann = Annotation.create_box(0, envelope(rotated_box()), source="sam2-point", confidence=.9)
        self.ann.kind = "obb"
        self.ann.obb = rotated_box()
        self.ann.points = [[330, 290], [420, 280], [410, 340]]
        self.ann.orientation = [[400, 300], [490, 342]]
        self.ann.approved = True
        self.record = ImageRecord("r", "r.png", 800, 600, annotations=[self.ann], review_status="reviewed")
        self.project = Project.create("Noodles fixture")
        self.project.classes = [LabelClass(0, "noodles")]
        self.project.images = [self.record]
        self.canvas.project = self.project
        self.canvas.record = self.record
        self.canvas.image = Image.new("RGB", (800, 600))
        self.canvas.selected_id = self.ann.id
        self.canvas.geometry_mode = "obb"
        self.canvas.mode = "select"

    def drag(self, start, end, state=0):
        self.canvas._press(SimpleNamespace(x=start[0], y=start[1], state=state))
        self.canvas._drag(SimpleNamespace(x=end[0], y=end[1], state=state))
        self.canvas._release(SimpleNamespace(x=end[0], y=end[1], state=state))

    def assert_points_close(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for point, wanted in zip(actual, expected):
            for value, target in zip(point, wanted):
                self.assertAlmostEqual(value, target, places=5)

    def test_ori_view_preserves_obb_outline(self):
        self.canvas.set_geometry_mode("ori")
        polygons = [self.canvas.coords(i) for i in self.canvas.find_withtag(self.ann.id)
                    if self.canvas.type(i) == "polygon"]
        self.assertIn([coord for p in self.ann.obb for coord in p], polygons)

    def test_obb_view_shows_direction_and_edit_handles(self):
        self.canvas.redraw()
        self.assertTrue(any(self.canvas.itemcget(i, "arrow") == "last"
                            for i in self.canvas.find_withtag(self.ann.id)
                            if self.canvas.type(i) == "line"))
        self.assertEqual(len(self.canvas._obb_handles(self.ann)), 9)

    def test_move_translates_all_geometry_and_revokes_approval(self):
        before = copy.deepcopy(self.ann)
        self.drag((400, 300), (425, 315))
        self.assert_points_close(self.ann.obb, [[x+25, y+15] for x, y in before.obb])
        self.assert_points_close(self.ann.points, [[x+25, y+15] for x, y in before.points])
        self.assert_points_close(self.ann.orientation, [[x+25, y+15] for x, y in before.orientation])
        self.assertEqual(self.record.review_status, "draft")
        self.assertFalse(self.ann.approved)
        self.assertIsNone(self.ann.confidence)
        self.assertEqual(self.ann.source, "manual")
        self.assertEqual(len(self.changes), 1)

    def test_resize_obb_corner_keeps_right_angles_and_opposite_corner(self):
        before = copy.deepcopy(self.ann.obb)
        c, s = math.cos(math.radians(25)), math.sin(math.radians(25))
        self.drag(before[2], (before[2][0]+30*c-15*s, before[2][1]+30*s+15*c))
        self.assertNotEqual(self.ann.obb, before)
        self.assert_points_close([self.ann.obb[0]], [before[0]])
        p = self.ann.obb
        u = [p[1][i]-p[0][i] for i in (0, 1)]
        v = [p[3][i]-p[0][i] for i in (0, 1)]
        self.assertAlmostEqual(sum(a*b for a, b in zip(u, v)), 0, places=5)
        for actual, wanted in zip(self.ann.bbox, envelope(p)):
            self.assertAlmostEqual(actual, wanted)

    def test_rotate_obb_rotates_direction_and_is_undoable(self):
        before = copy.deepcopy(self.ann)
        handle = next((x, y) for name, x, y in self.canvas._obb_handles(self.ann) if name == "rotate")
        delta = math.radians(30)
        dx, dy = handle[0]-400, handle[1]-300
        end = (400+dx*math.cos(delta)-dy*math.sin(delta),
               300+dx*math.sin(delta)+dy*math.cos(delta))
        self.drag(handle, end)
        expected = [[400+(x-400)*math.cos(delta)-(y-300)*math.sin(delta),
                     300+(x-400)*math.sin(delta)+(y-300)*math.cos(delta)] for x, y in before.obb]
        self.assert_points_close(self.ann.obb, expected)
        self.assertNotEqual(self.ann.orientation, before.orientation)
        self.canvas.undo()
        self.assertEqual(self.record.annotations[0].to_dict(), before.to_dict())
        self.canvas.redo()
        self.assert_points_close(self.record.annotations[0].obb, expected)

    def test_direction_tip_drag_snaps_parallel_without_changing_box(self):
        self.canvas.geometry_mode = "ori"
        before = copy.deepcopy(self.ann.obb)
        self.drag(self.canvas._direction_handle(self.ann), (500, 330))
        self.assertEqual(self.ann.obb, before)
        tip = self.ann.orientation[1]
        u = [before[1][i]-before[0][i] for i in (0, 1)]
        self.assertAlmostEqual((tip[0]-400)*u[1]-(tip[1]-300)*u[0], 0, places=5)

    def test_direction_can_be_reversed_and_free_mode_keeps_clicked_angle(self):
        self.canvas.mode = "orientation"
        self.canvas._press(SimpleNamespace(x=300, y=270, state=0))
        self.assertLess(self.ann.orientation[1][0], 400)
        self.assertEqual(self.canvas.mode, "select")
        self.canvas.orientation_snap = False
        self.canvas.mode = "orientation"
        self.canvas._press(SimpleNamespace(x=490, y=320, state=0))
        center, tip = self.ann.orientation
        self.assertEqual(center, [400, 300])
        self.assertAlmostEqual((tip[0]-400)*20-(tip[1]-300)*90, 0)
        self.assertNotEqual(tip, [490, 320])
        expected = direction(self.ann.bbox, self.ann.obb, (1300, 500), (800, 600), False)
        self.assert_points_close(self.ann.orientation, expected)

    def test_existing_arbitrary_length_is_not_changed_by_viewing(self):
        before = self.ann.to_dict()
        for mode in ("ori", "rect", "obb", "seg"):
            self.canvas.set_geometry_mode(mode)
        self.assertEqual(self.ann.to_dict(), before)
        self.assertFalse(self.changes)
        self.assertFalse(self.canvas.history)

    def test_replacing_legacy_direction_normalizes_and_undo_restores_old_length(self):
        before = self.ann.to_dict()
        self.canvas.set_mode("orientation")
        self.canvas._press(SimpleNamespace(x=401, y=301, state=0))
        normalized = self.ann.to_dict()
        expected = [(self.ann.obb[1][i]+self.ann.obb[2][i])/2 for i in (0, 1)]
        self.assert_points_close([self.ann.orientation[1]], [expected])
        self.assertEqual(len(self.changes), 1)
        self.assertFalse(self.ann.approved)
        self.canvas.undo()
        self.assertEqual(self.record.annotations[0].to_dict(), before)
        self.canvas.redo()
        self.assertEqual(self.record.annotations[0].to_dict(), normalized)

    def test_same_direction_near_far_click_is_noop_and_leaves_select_mode(self):
        for snap in (True, False):
            self.canvas.orientation_snap = snap
            self.canvas.set_mode("orientation")
            self.canvas._press(SimpleNamespace(x=403, y=301, state=0))
            before = self.ann.to_dict()
            changes, history = len(self.changes), len(self.canvas.history)
            self.canvas.set_mode("orientation")
            self.canvas._press(SimpleNamespace(x=700, y=400, state=0))
            self.assertEqual(self.ann.to_dict(), before)
            self.assertEqual(len(self.changes), changes)
            self.assertEqual(len(self.canvas.history), history)
            self.assertEqual(self.canvas.mode, "select")

    def test_outside_image_click_and_drag_choose_unclamped_free_angle(self):
        self.canvas.orientation_snap = False
        self.canvas.set_mode("orientation")
        self.canvas._press(SimpleNamespace(x=1400, y=800, state=0))
        self.assert_points_close(self.ann.orientation,
                                 direction(self.ann.bbox, self.ann.obb, (1400, 800), (800, 600), False))
        self.drag(self.canvas._direction_handle(self.ann), (-600, -200))
        self.assert_points_close(self.ann.orientation,
                                 direction(self.ann.bbox, self.ann.obb, (-600, -200), (800, 600), False))

    def test_normalized_tip_does_not_hide_resize_or_rotate_handles_at_any_zoom(self):
        # Include all edge midpoints and the exact corner in free mode.
        for target in ((600, 393), (200, 207), (350, 407), (450, 193), self.ann.obb[2]):
            self.ann.orientation = direction(self.ann.bbox, self.ann.obb, target,
                                             (800, 600), target != self.ann.obb[2])
            for scale in (.15, .25, 1, 4):
                self.canvas.scale = scale
                self.canvas.offset_x, self.canvas.offset_y = 30, 50
                self.canvas.redraw()
                for name, x, y in self.canvas._obb_handles(self.ann):
                    self.assertEqual(self.canvas._handle_at(x, y), name)
                x, y = self.canvas._direction_handle(self.ann)
                self.assertEqual(self.canvas._handle_at(x, y), "direction")

    def test_normalized_rect_tip_does_not_hide_resize_handles(self):
        self.ann.obb = []
        self.ann.bbox = [100, 100, 80, 60]
        self.canvas.geometry_mode = "ori"
        self.ann.orientation = direction(self.ann.bbox, [], (200, 130), (800, 600))
        for name, x, y in self.canvas._rect_handles(self.ann):
            self.assertEqual(self.canvas._handle_at(x, y), name)
        self.assertEqual(self.canvas._handle_at(*self.canvas._direction_handle(self.ann)), "direction")

    def test_radial_drag_of_normalized_arrow_does_not_create_edit(self):
        self.canvas.orientation_snap = False
        self.ann.orientation = direction(self.ann.bbox, self.ann.obb, (500, 330), (800, 600), False)
        before = self.ann.to_dict()
        self.drag(self.canvas._direction_handle(self.ann), (700, 390))
        self.assertEqual(self.ann.to_dict(), before)
        self.assertFalse(self.changes)
        self.assertFalse(self.canvas.history)

    def test_cancel_direction_drag_restores_legacy_arrow_without_saving(self):
        before = self.ann.to_dict()
        x, y = self.canvas._direction_handle(self.ann)
        self.canvas._press(SimpleNamespace(x=x, y=y, state=0))
        self.canvas._drag(SimpleNamespace(x=300, y=300, state=0))
        self.assertNotEqual(self.ann.to_dict(), before)
        self.canvas.cancel_action()
        self.assertEqual(self.ann.to_dict(), before)
        self.assertFalse(self.changes)
        self.assertFalse(self.canvas.history)

    def test_obb_hit_test_ignores_empty_envelope_corner(self):
        x, y, _, _ = self.ann.bbox
        self.canvas.selected_id = None
        self.canvas._press(SimpleNamespace(x=x+1, y=y+1, state=0))
        self.assertIsNone(self.canvas.selected_id)

    def test_readonly_does_not_mutate(self):
        before = self.ann.to_dict()
        self.canvas.read_only = True
        self.drag((400, 300), (430, 330))
        self.assertEqual(self.ann.to_dict(), before)
        self.assertFalse(self.changes)

    def test_rotation_outside_image_is_rejected_without_history_or_changes(self):
        self.ann.obb = rotated_box(cx=400, cy=68, height=120, angle=0)
        self.ann.bbox = envelope(self.ann.obb)
        self.ann.points = []
        self.ann.orientation = [[400, 68], [460, 68]]
        before = self.ann.to_dict()
        handle = next((x, y) for name, x, y in self.canvas._obb_handles(self.ann) if name == "rotate")
        self.assertLess(handle[1], 0)  # Handle can extend beyond the image.
        self.drag(handle, (488, 68))  # A 90-degree turn would cross the image edge.
        self.assertEqual(self.ann.to_dict(), before)
        self.assertFalse(self.canvas.history)
        self.assertFalse(self.changes)

    def test_space_drag_on_a_handle_pans_instead_of_editing(self):
        before = self.ann.to_dict()
        self.canvas.space_pressed = True
        self.drag(self.ann.obb[0], (self.ann.obb[0][0]+15, self.ann.obb[0][1]+10))
        self.assertEqual(self.ann.to_dict(), before)
        self.assertEqual((self.canvas.offset_x, self.canvas.offset_y), (15, 10))

    def test_ori_outline_and_snapped_direction_survive_view_switches(self):
        self.canvas.set_mode("orientation")
        self.canvas._press(SimpleNamespace(x=490, y=330))
        before = self.ann.to_dict()
        for geometry in ("rect", "seg", "obb", "ori", "obb"):
            self.canvas.set_geometry_mode(geometry)
            self.assertEqual(self.ann.to_dict(), before)

    def test_rotate_handle_is_screen_sized_at_different_zoom_levels(self):
        for scale in (.25, 1, 4):
            self.canvas.scale = scale
            handle = next((x, y) for name, x, y in self.canvas._obb_handles(self.ann) if name == "rotate")
            a, b = self.ann.obb[0], self.ann.obb[1]
            midpoint = self.canvas.to_canvas((a[0]+b[0])/2, (a[1]+b[1])/2)
            self.assertAlmostEqual(math.dist(handle, midpoint), 28)

    def test_click_without_motion_does_not_pollute_undo(self):
        self.drag((400, 300), (400, 300))
        self.assertFalse(self.canvas.history)
        self.assertFalse(self.changes)

    def test_cancel_drag_restores_original_geometry(self):
        before = self.ann.to_dict()
        self.canvas._press(SimpleNamespace(x=400, y=300, state=0))
        self.canvas._drag(SimpleNamespace(x=440, y=320, state=0))
        self.canvas.cancel_action()
        self.assertEqual(self.ann.to_dict(), before)
        self.assertFalse(self.changes)

    def test_cancel_drag_preserves_full_history_and_redo(self):
        self.canvas.history = [[self.ann.to_dict()] for _ in range(50)]
        self.canvas.future = [[self.ann.to_dict()]]
        history, future = copy.deepcopy(self.canvas.history), copy.deepcopy(self.canvas.future)
        self.canvas._press(SimpleNamespace(x=400, y=300, state=0))
        self.canvas._drag(SimpleNamespace(x=440, y=320, state=0))
        self.canvas.cancel_action()
        self.assertEqual(self.canvas.history, history)
        self.assertEqual(self.canvas.future, future)

    def test_undo_during_drag_cancels_unreleased_edit_before_undo(self):
        self.drag((400, 300), (420, 310))
        self.canvas._press(SimpleNamespace(x=420, y=310, state=0))
        self.canvas._drag(SimpleNamespace(x=450, y=340, state=0))
        self.canvas.undo()
        self.assertIsNone(self.canvas.edit_state)
        self.assert_points_close(self.record.annotations[0].obb, rotated_box())

    def test_rect_editing_and_ori_without_obb_still_work(self):
        self.ann.obb = []
        self.ann.orientation = []
        self.ann.points = []
        self.ann.bbox = [100, 100, 80, 60]
        self.canvas.geometry_mode = "ori"
        self.drag((140, 130), (150, 150))
        self.assertEqual(self.ann.bbox, [110, 120, 80, 60])
        self.canvas.geometry_mode = "rect"
        self.drag((190, 180), (210, 200))
        self.assertEqual(self.ann.bbox, [110, 120, 100, 80])


class ObbOriAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from smartlabel import app as app_module
        from smartlabel.project_store import ProjectStore
        cls.module = app_module
        cls.temp = TemporaryDirectory()
        cls.workspace = Path(cls.temp.name) / "workspace"
        cls.store = ProjectStore(cls.workspace)
        cls.project = cls.store.create_project("Noodles temporary", classes=["noodles"])
        Image.new("RGB", (800, 600)).save(cls.store.project_dir(cls.project) / "images" / "r.png")
        cls.project.images = [ImageRecord("r", "r.png", 800, 600)]
        cls.store.save(cls.project)
        cls.patches = [patch.object(app_module, "WORKSPACE", cls.workspace),
                       patch.object(app_module.SmartLabelApp, "_refresh_hardware")]
        for item in cls.patches:
            item.start()
        cls.app = app_module.SmartLabelApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.supplement_view.warm_stop.set()
        for timer in cls.app.tk.splitlist(cls.app.tk.call("after", "info")):
            cls.app.tk.call("after", "cancel", timer)
        cls.app.destroy()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.app._change_project_context(self.store.load(self.project.id))
        self.ann = Annotation.create_box(0, envelope(rotated_box()))
        self.ann.obb = rotated_box()
        self.ann.kind = "obb"
        self.app.canvas.record.annotations = [self.ann]
        self.app.canvas.selected_id = self.ann.id
        self.app._annotation_selected(self.ann.id)
        self.app.sam_click_enabled.set(False)
        self.app.geometry_selector.set("OBB")
        self.app._geometry_changed("OBB")

    def test_start_orientation_keeps_obb_view_and_disables_sam(self):
        before = self.ann.to_dict()
        self.app.sam_click_enabled.set(True)
        version = self.app.sam_click_request_version
        self.app._start_orientation()
        self.assertEqual(self.app.annotation_geometry.get(), "OBB")
        self.assertEqual(self.app.canvas.geometry_mode, "obb")
        self.assertEqual(self.app.canvas.mode, "orientation")
        self.assertFalse(self.app.sam_click_enabled.get())
        self.assertGreater(self.app.sam_click_request_version, version)
        self.assertEqual(self.ann.to_dict(), before)

    def test_late_sam_result_cannot_override_manual_orientation(self):
        version = self.app.sam_click_request_version
        self.app.sam_click_enabled.set(True)
        self.app._start_orientation()
        self.app.event_queue.put(("sam_click_done", (
            "r", version, 0, "rect", {}, {"bbox": [10, 10, 30, 40]}, .9)))
        self.app._drain_events()
        self.assertEqual(len(self.app.canvas.record.annotations), 1)
        self.assertEqual(self.app.canvas.mode, "orientation")
        self.assertEqual(self.app.annotation_geometry.get(), "OBB")

    def test_late_sam_refinement_is_discarded_after_entering_manual(self):
        self.app.sam_request_versions[self.ann.id] = 42
        before = self.ann.to_dict()
        self.app._start_orientation()
        self.app.event_queue.put(("sam_done", ("r", self.ann.id, 42, [[1, 1], [2, 2], [3, 3]], .5)))
        self.app._drain_events()
        self.assertEqual(self.ann.to_dict(), before)
        self.assertEqual(self.app.canvas.mode, "orientation")

    def test_select_tool_exits_sam_even_when_geometry_changes(self):
        self.app.sam_click_enabled.set(True)
        self.app._set_tool("select")
        self.app._geometry_changed("ORI")
        self.assertEqual(self.app.canvas.mode, "select")
        self.assertFalse(self.app.sam_click_enabled.get())

    def test_sam_click_on_existing_object_enters_editing_without_duplicate(self):
        self.app.canvas.active_class_id = 0
        self.app.sam_click_enabled.set(True)
        self.app.canvas.set_mode("sam_click")
        self.app._run_sam_click_create(400, 300)
        self.assertFalse(self.app.sam_click_enabled.get())
        self.assertEqual(self.app.canvas.mode, "select")
        self.assertEqual(self.app.canvas.selected_id, self.ann.id)
        self.assertEqual(len(self.app.canvas.record.annotations), 1)

    def test_sam_selection_uses_obb_not_empty_envelope_corners(self):
        x, y, _, _ = self.ann.bbox
        self.assertIsNone(self.app._annotation_at_point(x+1, y+1))
        self.assertIs(self.app._annotation_at_point(400, 300), self.ann)

    def test_sam_ori_result_keeps_rotated_shape_for_direction_step(self):
        self.app.canvas.record.annotations = []
        self.app.sam_click_enabled.set(True)
        version = self.app.sam_click_request_version
        self.app.event_queue.put(("sam_click_done", (
            "r", version, 0, "ori", {}, {"bbox": envelope(rotated_box()),
            "points": [[300, 300], [400, 200], [500, 300]], "obb": rotated_box()}, .9)))
        self.app._drain_events()
        ann = self.app.canvas.record.annotations[0]
        self.assertEqual(ann.obb, rotated_box())
        self.assertEqual(self.app.canvas.mode, "orientation")
        self.assertFalse(self.app.sam_click_enabled.get())

    def test_sam_obb_then_ori_persists_both_and_exports_existing_formats(self):
        from smartlabel.dataset_manager import DatasetManager
        self.app.canvas.record.annotations = []
        self.app.sam_click_enabled.set(True)
        version = self.app.sam_click_request_version
        data = {"bbox": envelope(rotated_box()), "points": [[300, 300], [400, 200], [500, 300]],
                "obb": rotated_box()}
        self.app.event_queue.put(("sam_click_done", ("r", version, 0, "obb", {}, data, .9)))
        self.app._drain_events()
        ann = self.app.canvas.record.annotations[0]
        before = copy.deepcopy(ann.obb)
        self.app._start_orientation()
        x, y = self.app.canvas.to_canvas(490, 330)
        self.app.canvas._press(SimpleNamespace(x=x, y=y, state=0))
        self.assertEqual(ann.obb, before)
        self.assertEqual(self.app.canvas.mode, "select")
        loaded = self.store.load(self.project.id).images[0].annotations[0]
        self.assertEqual(loaded.obb, ann.obb)
        self.assertEqual(loaded.orientation, ann.orientation)
        self.assertEqual(len(DatasetManager._to_yolo_task(loaded, 800, 600, "obb").split()), 9)
        self.assertEqual(len(DatasetManager._to_yolo_task(loaded, 800, 600, "pose").split()), 11)
        expected_tip = [(before[1][i]+before[2][i])/2 for i in (0, 1)]
        for value, wanted in zip(loaded.orientation[1], expected_tip):
            self.assertAlmostEqual(value, wanted)
        pose = DatasetManager._to_yolo_task(loaded, 800, 600, "pose").split()
        self.assertAlmostEqual(float(pose[8]), expected_tip[0]/800, places=6)
        self.assertAlmostEqual(float(pose[9]), expected_tip[1]/600, places=6)

    def test_snap_preference_is_applied_and_persisted_without_geometry_changes(self):
        import json
        self.ann.orientation = [[400, 300], [420, 315]]  # Old arbitrary length.
        before = self.ann.to_dict()
        self.app.orientation_snap.set(False)
        self.app._orientation_snap_changed()
        self.assertFalse(self.app.canvas.orientation_snap)
        self.assertFalse(json.loads(self.app.settings_path.read_text(encoding="utf-8"))["orientation_snap"])
        self.assertEqual(self.ann.to_dict(), before)
        self.app.orientation_snap.set(True)
        self.app._orientation_snap_changed()

    def test_orientation_from_rect_uses_ori_view_without_creating_an_obb(self):
        self.ann.obb = []
        self.app.geometry_selector.set("RECT")
        self.app._geometry_changed("RECT")
        before = self.ann.to_dict()
        self.app._start_orientation()
        self.assertEqual(self.app.canvas.geometry_mode, "ori")
        self.assertEqual(self.ann.to_dict(), before)


class OrientedGeometryMathTests(unittest.TestCase):
    def test_snap_covers_both_axes_both_signs_for_many_box_angles(self):
        for angle in (0, 25, 70, 90, 135, 179, 225, 300):
            box = rotated_box(angle=angle)
            cx, cy, ux, uy, vx, vy, _, _ = frame(box)
            for ax, ay in ((ux, uy), (-ux, -uy), (vx, vy), (-vx, -vy)):
                with self.subTest(angle=angle, axis=(ax, ay)):
                    tip = direction(envelope(box), box, (cx+70*ax+.5, cy+70*ay+.5), (800, 600))[1]
                    self.assertAlmostEqual((tip[0]-cx)*ay-(tip[1]-cy)*ax, 0, places=6)
                    self.assertGreater((tip[0]-cx)*ax+(tip[1]-cy)*ay, 0)

    def test_center_click_cannot_create_zero_direction(self):
        self.assertIsNone(direction([100, 100, 80, 60], [], (140, 130), (800, 600)))

    def test_direction_clipping_preserves_axis_at_image_boundary(self):
        box = rotated_box(cx=10, cy=10, width=40, height=20, angle=25)
        center, tip = direction(envelope(box), box, (-100, -20), (800, 600))
        self.assertAlmostEqual((tip[0]-center[0])*math.sin(math.radians(25))
                               -(tip[1]-center[1])*math.cos(math.radians(25)), 0)
        self.assertGreaterEqual(min(tip), -1e-9)
        self.assertAlmostEqual(min(tip), 0)

    def test_all_resize_handles_keep_rectangularity_and_minimum_dimensions(self):
        box = rotated_box()
        snapshot = {"bbox": envelope(box), "obb": box, "points": [], "orientation": []}
        for handle in ("nw", "n", "ne", "e", "se", "s", "sw", "w"):
            with self.subTest(handle=handle):
                value = edit_obb(snapshot, handle, (0, 0), (400, 300), (800, 600))
                self.assertIsNotNone(value)
                _, _, ux, uy, vx, vy, w, h = frame(value["obb"])
                self.assertAlmostEqual(ux*vx+uy*vy, 0)
                self.assertGreaterEqual(min(w, h), 3-1e-6)

    def test_shift_rotation_snaps_absolute_box_angle_to_15_degrees(self):
        box = rotated_box(angle=25)
        snapshot = {"bbox": envelope(box), "obb": box, "points": [], "orientation": []}
        value = edit_obb(snapshot, "rotate", (400, 200), (440, 210), (800, 600), True)
        _, _, ux, uy, _, _, _, _ = frame(value["obb"])
        angle = math.degrees(math.atan2(uy, ux))
        self.assertAlmostEqual(angle/15, round(angle/15))


