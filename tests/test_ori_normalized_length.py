"""ORI placement uses a box-relative endpoint, not the mouse-click radius."""
import math
import unittest

from smartlabel.annotation_geometry import direction, edit_obb, envelope, frame, translate


def box(width=240, height=120, angle=25, cx=400, cy=300):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [[cx+x*c-y*s, cy+x*s+y*c]
            for x, y in ((-width/2, -height/2), (width/2, -height/2),
                         (width/2, height/2), (-width/2, height/2))]


class NormalizedDirectionTests(unittest.TestCase):
    def assert_points_close(self, actual, expected):
        for a, b in zip(actual, expected):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=6)

    def assert_on_edge(self, corners, tip):
        self.assertTrue(any(
            abs((b[0]-a[0])*(tip[1]-a[1])-(b[1]-a[1])*(tip[0]-a[0])) < 1e-5
            and min(a[0], b[0])-1e-6 <= tip[0] <= max(a[0], b[0])+1e-6
            and min(a[1], b[1])-1e-6 <= tip[1] <= max(a[1], b[1])+1e-6
            for a, b in zip(corners, corners[1:]+corners[:1])))

    def test_snapped_tip_is_edge_midpoint_independent_of_click_distance(self):
        for angle in (0, 25, 90, 135, 179, 225, 300):
            for width, height in ((240, 120), (80, 180), (20, 20)):
                corners = box(width, height, angle)
                cx, cy, ux, uy, vx, vy, _, _ = frame(corners)
                for ax, ay, radius in ((ux, uy, width/2), (-ux, -uy, width/2),
                                       (vx, vy, height/2), (-vx, -vy, height/2)):
                    for distance in (2, 30, 1000):
                        with self.subTest(angle=angle, size=(width, height), axis=(ax, ay), distance=distance):
                            value = direction(envelope(corners), corners,
                                              (cx+distance*ax, cy+distance*ay), (800, 600))
                            self.assert_points_close(value, [[cx, cy], [cx+radius*ax, cy+radius*ay]])

    def test_free_angle_is_preserved_but_tip_is_on_box_boundary(self):
        for angle in (0, 25, 90, 135, 300):
            corners = box(angle=angle)
            for dx, dy in ((1, 0), (-2, 1), (0, -1), (4, 3), (-2, -5)):
                values = [direction(envelope(corners), corners, (400+dx*k, 300+dy*k),
                                    (800, 600), False) for k in (1, 10, 1000)]
                with self.subTest(angle=angle, vector=(dx, dy)):
                    self.assert_points_close(values[0], values[1])
                    self.assert_points_close(values[0], values[2])
                    center, tip = values[0]
                    self.assert_on_edge(corners, tip)
                    self.assertAlmostEqual((tip[0]-center[0])*dy-(tip[1]-center[1])*dx, 0)
                    self.assertGreater((tip[0]-center[0])*dx+(tip[1]-center[1])*dy, 0)

    def test_rect_fallback_has_same_rule_and_does_not_require_an_obb(self):
        bbox = [100, 100, 80, 60]
        self.assert_points_close(direction(bbox, [], (141, 130), (800, 600)),
                                 [[140, 130], [180, 130]])
        self.assert_points_close(direction(bbox, [], (141, 131), (800, 600), False),
                                 [[140, 130], [170, 160]])

    def test_free_ray_handles_corner_and_clockwise_vertex_order(self):
        corners = box(angle=0)
        for ordered in (corners, list(reversed(corners))):
            value = direction(envelope(ordered), ordered, (402, 301), (800, 600), False)
            self.assert_points_close(value, [[400, 300], [520, 360]])

    def test_legacy_affine_parallelogram_still_intersects_actual_edge(self):
        corners = [[200, 150], [500, 210], [450, 350], [150, 290]]
        for snap in (False, True):
            value = direction(envelope(corners), corners, (700, 400), (800, 600), snap)
            self.assert_on_edge(corners, value[1])

    def test_image_edge_clips_ray_without_changing_free_angle(self):
        corners = box(100, 80, 0, 10, 10)
        value = direction(envelope(corners), corners, (-30, -10), (800, 600), False)
        self.assert_points_close(value, [[10, 10], [0, 5]])

    def test_invalid_or_zero_direction_is_rejected(self):
        for bbox, corners, point, size in (
                ([100, 100, 0, 20], [], (120, 120), (800, 600)),
                ([100, 100, 40, 20], [], (120, 110), (800, 600)),
                ([100, 100, 40, 20], [], (float('nan'), 110), (800, 600)),
                ([100, 100, 40, 20], [], (float('inf'), 110), (800, 600)),
                ([100, 100, 40, 20], [], (150, 110), (0, 600)),
                ([100, 100, 40, 20], [], (150, 110), (800, float('nan'))),
                ([-300, 100, 40, 20], [], (150, 110), (800, 600))):
            with self.subTest(bbox=bbox, point=point, size=size):
                self.assertIsNone(direction(bbox, corners, point, size))

    def test_normalized_tip_follows_all_resize_handles_and_rotation(self):
        corners = box()
        for snap in (True, False):
            ori = direction(envelope(corners), corners, (500, 330), (800, 600), snap)
            snapshot = {'bbox': envelope(corners), 'obb': corners, 'points': [], 'orientation': ori}
            for handle in ('nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w', 'rotate'):
                with self.subTest(snap=snap, handle=handle):
                    value = edit_obb(snapshot, handle, (400, 200), (430, 310), (800, 600))
                    self.assertIsNotNone(value)
                    self.assert_on_edge(value['obb'], value['orientation'][1])
                    cx, cy, *_ = frame(value['obb'])
                    self.assert_points_close([value['orientation'][0]], [[cx, cy]])
            value = translate(snapshot, 20, 10, (800, 600))
            self.assert_on_edge(value['obb'], value['orientation'][1])
