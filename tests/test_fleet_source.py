import unittest
from smartlabel.fleet_source import qualification, source_caption
from smartlabel.fleet_intake import FleetIntakeError


class FleetSourceTests(unittest.TestCase):
    def row(self, source="hydro_camera"):
        return {"source": source, "groupId": "a" * 64, "qualification": {
            "schemaVersion": "FleetSourceQualificationV1", "trainAllowed": False, "evaluationEligible": False,
            "sourceClass": "hydro_slot" if source == "hydro_camera" else "customer_phone", "issues": [],
            "groupId": "a" * 64, "parentStatus": "not_shared" if source == "hydro_camera" else "not_applicable",
            "splitPolicy": "TRAIN_ONLY" if source == "phone" else "CROP_CYCLE_GROUPED_PENDING_QA"}}

    def test_distinct_sources_no_parent_fabrication_or_train_claim(self):
        self.assertIn("Giàn", source_caption(self.row()))
        self.assertIn("ảnh cha không chia sẻ", source_caption(self.row()))
        self.assertIn("Bổ trợ", source_caption(self.row("phone")))
        self.assertIn("chưa đưa", source_caption(self.row()))

    def test_old_receiver_and_unknown_issue_fail_closed_without_crashing_drafts(self):
        self.assertEqual(qualification({})["sourceClass"], "unqualified")
        row = self.row(); row["qualification"].update(sourceClass="unqualified", issues=["crop_mismatch", "future_issue"])
        self.assertIn("Giống cây khác", source_caption(row)); self.assertIn("Cần kiểm tra", source_caption(row))

    def test_untrusted_qualification_cannot_enable_train_or_holdout(self):
        for field, value in [("trainAllowed", True), ("evaluationEligible", True), ("groupId", "different"),
                             ("sourceClass", "unknown"), ("issues", ["crop_mismatch"]), ("issues", "bad")]:
            row = self.row(); row["qualification"][field] = value
            with self.assertRaises(FleetIntakeError): qualification(row)
        row = self.row("phone"); row["qualification"]["splitPolicy"] = "VAL_TEST"
        with self.assertRaises(FleetIntakeError): qualification(row)
