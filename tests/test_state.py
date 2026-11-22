"""状态归算：限制只能由调度通告解除、到达顺序无关、待办确认类型。"""
import unittest

import helpers
from mcs import Query
from mcs.state import compute_pending, compute_restrictions, effective_events


def restriction_snapshot(store):
    restrictions, unmatched = compute_restrictions(effective_events(store))
    snap = sorted((r.scope, r.level, r.active,
                   r.imposed_by.notice_id,
                   r.lifted_by.notice_id if r.lifted_by else None)
                  for r in restrictions)
    return snap, len(unmatched)


def pending_signature(store, registry):
    return sorted((i.kind, i.entity, i.needed)
                  for i in compute_pending(store, registry))


class RestrictionLifecycleTests(helpers.TempEnvMixin, unittest.TestCase):
    def ingest(self, *records):
        helpers.ingest_all(self.store, self.extractor, records)

    def test_repair_claim_does_not_lift_restriction(self):
        self.ingest(
            helpers.rec("R-1", "contractor", "北段K17信号箱进水，已报缺陷。",
                        "2026-11-20T07:50:00"),
            helpers.rec("R-2", "dispatch", "调字〔2026〕118号：K17区间临时限速。",
                        "2026-11-20T09:00:00", "调字〔2026〕118号"),
            helpers.rec("R-3", "contractor",
                        "K17 box replaced，试验合格。K17区间修好了，可以申请恢复常速。",
                        "2026-11-20T15:20:00"),
            helpers.rec("R-4", "field_check",
                        "现场复核：K17信号箱复测正常，具备运行条件。",
                        "2026-11-21T10:00:00"),
        )
        snap, _ = restriction_snapshot(self.store)
        self.assertEqual(len(snap), 1)
        self.assertTrue(snap[0][2], "限制必须仍然生效：修好了/复核合格都不解除限制")
        items = compute_pending(self.store, self.registry)
        restriction_items = [i for i in items if i.kind == "restriction"]
        self.assertEqual(len(restriction_items), 1)
        self.assertEqual(restriction_items[0].needed, "调度通告解除")

    def test_only_dispatch_notice_lifts(self):
        records = helpers.load_shift_records()
        self.ingest(*records)
        snap, unmatched = restriction_snapshot(self.store)
        k17 = [s for s in snap if s[0] == "SEC-K17"]
        self.assertEqual(len(k17), 1)
        self.assertFalse(k17[0][2], "调字121号到达后限制应已解除")
        self.assertEqual(k17[0][4], "调字〔2026〕121号")
        self.assertEqual(unmatched, 0)

    def test_lift_prefers_referenced_notice(self):
        self.ingest(
            helpers.rec("D-1", "dispatch", "调字〔2026〕201号：K21区间临时限速。",
                        "2026-11-20T10:00:00", "调字〔2026〕201号"),
            helpers.rec("D-2", "dispatch", "调字〔2026〕202号：K21区间封锁。",
                        "2026-11-20T11:00:00", "调字〔2026〕202号"),
            helpers.rec("D-3", "dispatch",
                        "调字〔2026〕203号：解除调字〔2026〕202号对K21区间的封锁。",
                        "2026-11-20T12:00:00", "调字〔2026〕203号"),
        )
        restrictions, _ = compute_restrictions(effective_events(self.store))
        by_notice = {r.imposed_by.notice_id: r for r in restrictions}
        self.assertTrue(by_notice["调字〔2026〕201号"].active)
        self.assertFalse(by_notice["调字〔2026〕202号"].active)


class ArrivalOrderTests(unittest.TestCase):
    def test_out_of_order_arrival_yields_same_final_state(self):
        import tempfile
        results = []
        for chronological in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                registry, store, extractor = helpers.make_env(tmp)
                helpers.ingest_all(store, extractor,
                                   helpers.load_shift_records(chronological))
                results.append((restriction_snapshot(store),
                                pending_signature(store, registry)))
        self.assertEqual(results[0], results[1],
                         "最终状态不得依赖材料到达顺序")


class PendingStageTests(helpers.TempEnvMixin, unittest.TestCase):
    def items_for(self, entity):
        return [i for i in compute_pending(self.store, self.registry)
                if i.entity == entity]

    def test_fault_work_verify_progression(self):
        self.store.ingest_record(helpers.rec(
            "P-1", "contractor", "北段K17信号箱进水。",
            "2026-11-20T08:00:00"), self.extractor)
        items = self.items_for("EQ-SIG-K17")
        self.assertEqual([(i.kind, i.needed) for i in items],
                         [("open_fault", "检修处理")])

        self.store.ingest_record(helpers.rec(
            "P-2", "contractor", "K17信号箱已更换端子。",
            "2026-11-20T12:00:00"), self.extractor)
        items = self.items_for("EQ-SIG-K17")
        self.assertEqual([(i.kind, i.needed) for i in items],
                         [("open_fault", "现场复核")])

        self.store.ingest_record(helpers.rec(
            "P-3", "field_check", "现场复核：K17信号箱复测正常。",
            "2026-11-21T09:00:00"), self.extractor)
        self.assertEqual(self.items_for("EQ-SIG-K17"), [])

    def test_unresolved_surface_appears_in_pending(self):
        self.store.ingest_record(helpers.rec(
            "P-4", "contractor", "DC-5 转换器卡阻，已检查完成。"), self.extractor)
        items = compute_pending(self.store, self.registry)
        unresolved = [i for i in items if i.kind == "unresolved"]
        self.assertEqual(len(unresolved), 1)
        self.assertIn("别名", unresolved[0].needed)

    def test_unauthorized_claim_is_warning_not_permission(self):
        self.store.ingest_record(helpers.rec(
            "P-5", "contractor", "K17区间修好了，可以申请恢复常速。"), self.extractor)
        items = compute_pending(self.store, self.registry)
        warnings = [i for i in items if i.kind == "warning"]
        self.assertTrue(any("不构成运行许可" in i.needed for i in warnings))
        # 不得因此出现任何“已解除”的限制
        restrictions, _ = compute_restrictions(effective_events(self.store))
        self.assertEqual(restrictions, [])


if __name__ == "__main__":
    unittest.main()
