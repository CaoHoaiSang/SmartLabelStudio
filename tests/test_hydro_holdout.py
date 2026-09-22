from copy import deepcopy
from types import SimpleNamespace
import unittest
from smartlabel.hydro_holdout import holdout_diagnostics, describe_holdout


class HoldoutDiagnosticsTests(unittest.TestCase):
    def project(self, rows):
        return SimpleNamespace(images=[SimpleNamespace(id=str(i), capture_group=str(i),
            metadata={"cropCycleId": cycle}) for i, cycle in enumerate(rows)])

    def test_two_seasons_with_new_season_in_train_explains_real_blocker(self):
        project = self.project(["vụ 1", "vụ 1", "vụ 1", "vụ 2"])
        assignment = {"0": "train", "1": "val", "2": "test", "3": "train"}
        before = deepcopy(assignment)
        report = holdout_diagnostics(project, assignment)
        self.assertFalse(report["independent"])
        self.assertEqual(report["overlappingCycles"], ["vụ 1"])
        text = describe_holdout({"holdout": report})
        self.assertIn("vụ 2: TRAIN 1 · VAL 0 · TEST 0", text)
        self.assertIn("đã dùng để học không trở thành holdout", text)
        self.assertIn("không tự hạ chế độ", text)
        self.assertEqual(assignment, before)

    def test_disjoint_test_cycle_remains_valid(self):
        report = holdout_diagnostics(self.project(["a", "a", "b"]), {"0": "train", "1": "val", "2": "test"})
        self.assertTrue(report["independent"])
        self.assertEqual(report["overlappingCycles"], [])

    def test_unknown_test_cycle_is_never_independent(self):
        for unknown in (None, "", "   ", "unknown"):
            with self.subTest(unknown=unknown):
                report = holdout_diagnostics(self.project(["a", unknown]), {"0": "train", "1": "test"})
                self.assertFalse(report["independent"])
                self.assertIn("chưa xác định được vụ", describe_holdout({"holdout": report}))

    def test_no_test_and_unassigned_are_explicit(self):
        report = holdout_diagnostics(self.project(["a", "b"]), {"0": "train"})
        self.assertFalse(report["independent"])
        text = describe_holdout({"holdout": report})
        self.assertIn("chưa chia 1", text)
        self.assertIn("chưa có ảnh được dành cho TEST", text)

    def test_legacy_report_has_action_not_fabricated_counts(self):
        self.assertIn("Chưa có thống kê", describe_holdout({}))
        self.assertNotIn("TRAIN 0", describe_holdout({}))
