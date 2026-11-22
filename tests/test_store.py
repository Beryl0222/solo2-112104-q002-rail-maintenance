"""事件库：归属修订的提议/确认、历史保留、记录去重。"""
import unittest

import helpers


class ReattributionTests(helpers.TempEnvMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store.ingest_record(helpers.rec(
            "S-1", "contractor", "南二段继电器箱进水，已更换受潮端子。",
            "2026-11-19T08:10:00"), self.extractor)
        self.event = self.store.events()[0]

    def test_proposal_does_not_change_effective_target(self):
        ra = self.store.propose_reattribution(
            self.event.event_id, "EQ-RLY-K30", reason="现场核对", by="值班员")
        self.assertEqual(ra.status, "proposed")
        self.assertEqual(self.store.effective_target(self.event), "EQ-RLY-K21")

    def test_confirmation_changes_effective_target_but_not_history(self):
        ra = self.store.propose_reattribution(
            self.event.event_id, "EQ-RLY-K30", reason="现场核对", by="值班员")
        self.store.confirm_reattribution(ra.ra_id, by="值班长")
        self.assertEqual(self.store.effective_target(self.event), "EQ-RLY-K30")
        stored = self.store.event(self.event.event_id)
        self.assertEqual(stored.target, "EQ-RLY-K21", "入库归属必须原样保留")
        history = self.store.event_history(self.event.event_id)
        self.assertEqual(history["original_target"], "EQ-RLY-K21")
        self.assertEqual(history["effective_target"], "EQ-RLY-K30")
        self.assertEqual(len(history["chain"]), 1)

    def test_double_confirmation_rejected(self):
        ra = self.store.propose_reattribution(
            self.event.event_id, "EQ-RLY-K30", reason="r", by="a")
        self.store.confirm_reattribution(ra.ra_id, by="b")
        with self.assertRaises(ValueError):
            self.store.confirm_reattribution(ra.ra_id, by="b")

    def test_unknown_event_rejected(self):
        with self.assertRaises(KeyError):
            self.store.propose_reattribution("EV-99999", "EQ-RLY-K30",
                                             reason="r", by="a")


class IngestTests(helpers.TempEnvMixin, unittest.TestCase):
    def test_duplicate_record_is_skipped(self):
        record = helpers.rec("S-2", "contractor", "北段K17信号箱进水。")
        first = self.store.ingest_record(record, self.extractor)
        second = self.store.ingest_record(record, self.extractor)
        self.assertFalse(first.skipped)
        self.assertTrue(second.skipped)
        self.assertEqual(len(self.store.events()), len(first.events))

    def test_event_ids_are_sequential(self):
        self.store.ingest_record(helpers.rec(
            "S-3", "contractor", "北段K17信号箱进水，已更换端子。"), self.extractor)
        ids = [e.event_id for e in self.store.events()]
        self.assertEqual(ids, [f"EV-{i + 1:05d}" for i in range(len(ids))])


if __name__ == "__main__":
    unittest.main()
