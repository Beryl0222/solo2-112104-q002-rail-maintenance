"""值班查询：按线路聚合待办、限制始末、设备时间线。"""
import unittest

import helpers
from mcs import Query


class PendingViewTests(helpers.TempEnvMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.query = Query(self.store, self.registry)
        helpers.ingest_all(self.store, self.extractor, [
            helpers.rec("Q-1", "contractor", "北段K17信号箱进水，已报缺陷。",
                        "2026-11-20T07:50:00"),
            helpers.rec("Q-2", "dispatch", "调字〔2026〕118号：K17区间临时限速。",
                        "2026-11-20T09:00:00", "调字〔2026〕118号"),
        ])

    def test_line_view_aggregates_equipment_items(self):
        items = self.query.pending(line="SEC-K17")
        kinds = {(i.kind, i.entity) for i in items}
        self.assertIn(("open_fault", "EQ-SIG-K17"), kinds)
        self.assertIn(("restriction", "SEC-K17"), kinds)

    def test_equipment_view_isolates_single_entity(self):
        items = self.query.pending(entity="EQ-SIG-K17")
        self.assertTrue(items)
        self.assertTrue(all(i.entity == "EQ-SIG-K17" for i in items))

    def test_pending_item_carries_evidence_and_needed_confirmation(self):
        items = self.query.pending(entity="SEC-K17")
        restriction = [i for i in items if i.kind == "restriction"][0]
        self.assertEqual(restriction.needed, "调度通告解除")
        self.assertTrue(restriction.evidence)


class RestrictionHistoryTests(helpers.TempEnvMixin, unittest.TestCase):
    def test_history_explains_start_and_end(self):
        helpers.ingest_all(self.store, self.extractor,
                           helpers.load_shift_records())
        query = Query(self.store, self.registry)
        history = query.restriction_history("SEC-K17")
        self.assertEqual(len(history), 1)
        view = history[0]
        self.assertEqual(view.imposed_by.notice_id, "调字〔2026〕118号")
        self.assertIn("临时限速", view.imposed_by.excerpt)
        self.assertEqual(view.lifted_by.notice_id, "调字〔2026〕121号")
        self.assertIn("解除", view.lifted_by.excerpt)


class TimelineTests(helpers.TempEnvMixin, unittest.TestCase):
    def test_reattributed_event_visible_on_both_sides_with_notes(self):
        helpers.ingest_all(self.store, self.extractor, [
            helpers.rec("Q-3", "contractor", "南二段继电器箱进水，已更换受潮端子。",
                        "2026-11-19T08:10:00"),
        ])
        query = Query(self.store, self.registry)
        event = self.store.events()[0]
        ra = self.store.propose_reattribution(
            event.event_id, "EQ-RLY-K30", reason="现场核对：实际位于K30区间",
            by="值班员")
        self.store.confirm_reattribution(ra.ra_id, by="值班长")

        new_side = query.timeline("EQ-RLY-K30")
        self.assertTrue(any(r["event_id"] == event.event_id and "原归属" in r["note"]
                            for r in new_side))
        old_side = query.timeline("EQ-RLY-K21")
        self.assertTrue(any(r["event_id"] == event.event_id and "已改属" in r["note"]
                            for r in old_side))


if __name__ == "__main__":
    unittest.main()
