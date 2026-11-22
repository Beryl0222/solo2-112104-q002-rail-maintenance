"""文本抽取：三语别名解析、事件分类、授权门槛、未知写法提示。"""
import unittest

import helpers


class AliasResolutionTests(helpers.TempEnvMixin, unittest.TestCase):
    def extract_targets(self, text):
        record = helpers.rec("T-1", "contractor", text)
        return self.extractor.extract(record).events

    def test_chinese_english_and_mixed_surfaces_resolve(self):
        for text in ("K17信号箱进水", "Box K17 water ingress fault",
                     "K17 box replaced"):
            events = self.extract_targets(text)
            self.assertTrue(events, text)
            self.assertEqual(events[0].target, "EQ-SIG-K17", text)

    def test_longest_match_prefers_equipment_over_line(self):
        mentions = self.registry.find_mentions("北段K17信号箱夜间进水")
        by_entity = {m.entity_id for m in mentions}
        self.assertIn("EQ-SIG-K17", by_entity)
        self.assertIn("SEC-K17", by_entity)  # “北段”
        # 故障挂在离动作词最近的设备级写法上
        events = self.extract_targets("北段K17信号箱夜间进水")
        self.assertEqual(events[0].target, "EQ-SIG-K17")

    def test_proposed_alias_not_used_until_confirmed(self):
        self.registry.add_alias("DC-5", "EQ-SW-05", by="测试")
        self.assertEqual(self.registry.find_mentions("DC-5 卡阻"), [])
        self.registry.confirm_alias("DC-5", by="值班长")
        self.assertEqual(self.registry.find_mentions("DC-5 卡阻")[0].entity_id,
                         "EQ-SW-05")


class EventKindTests(helpers.TempEnvMixin, unittest.TestCase):
    def kinds(self, record):
        return [e.kind for e in self.extractor.extract(record).events]

    def test_replace_inspect_repair_are_distinct_facts(self):
        kinds = self.kinds(helpers.rec(
            "T-2", "contractor", "K17信号箱已更换端子，检查完成，修好了。"))
        self.assertIn("work_replaced", kinds)
        self.assertIn("work_inspected", kinds)
        self.assertIn("repair_claimed", kinds)

    def test_contractor_lift_wording_is_unauthorized_only(self):
        events = self.extractor.extract(helpers.rec(
            "T-3", "contractor", "K17区间修好了，可以申请恢复常速。")).events
        kinds = [e.kind for e in events]
        self.assertIn("unauthorized_claim", kinds)
        self.assertNotIn("restriction_lifted", kinds)

    def test_field_check_lift_wording_is_unauthorized_only(self):
        kinds = self.kinds(helpers.rec(
            "T-4", "field_check", "现场认为K17区间可以恢复常速。"))
        self.assertNotIn("restriction_lifted", kinds)

    def test_conditional_lift_produces_no_event(self):
        for text in ("K17区间临时限速保持，收到调度确认后方可解除。",
                     "K17区间临时限速，待复核合格后另行解除。"):
            kinds = self.kinds(helpers.rec("T-5", "dispatch", text,
                                           notice_id="调字〔2026〕118号"))
            self.assertIn("restriction_imposed", kinds)
            self.assertNotIn("restriction_lifted", kinds)

    def test_dispatch_lift_carries_notice_reference(self):
        events = self.extractor.extract(helpers.rec(
            "T-6", "dispatch",
            "调字〔2026〕121号：解除调字〔2026〕118号对K17区间的临时限速。",
            notice_id="调字〔2026〕121号")).events
        lifts = [e for e in events if e.kind == "restriction_lifted"]
        self.assertEqual(len(lifts), 1)
        self.assertEqual(lifts[0].target, "SEC-K17")
        self.assertIn("调字〔2026〕118号", lifts[0].referenced_notices)
        # 同句中的“临时限速”不得再生成一条限制开始事件
        self.assertNotIn("restriction_imposed", [e.kind for e in events])

    def test_field_check_inspection_counts_as_verified(self):
        kinds = self.kinds(helpers.rec(
            "T-7", "field_check", "现场复核：K17信号箱复测正常。"))
        self.assertIn("field_verified", kinds)
        kinds = self.kinds(helpers.rec(
            "T-8", "contractor", "K17信号箱试验合格。"))
        self.assertIn("work_inspected", kinds)
        self.assertNotIn("field_verified", kinds)

    def test_negated_or_planned_work_produces_no_event(self):
        kinds = self.kinds(helpers.rec(
            "T-9", "contractor", "K17信号箱待更换端子，尚未修复。"))
        self.assertNotIn("work_replaced", kinds)
        self.assertNotIn("repair_claimed", kinds)


class UnknownSurfaceTests(helpers.TempEnvMixin, unittest.TestCase):
    def test_unknown_surface_creates_unresolved_event_and_warning(self):
        result = self.extractor.extract(helpers.rec(
            "T-10", "contractor", "DC-5 转换器卡阻，已检查完成。"))
        targets = {e.target for e in result.events}
        self.assertEqual(targets, {"UNRESOLVED"})
        self.assertTrue(any("DC-5" in w for w in result.warnings))

    def test_notice_numbers_are_not_reported_as_unknown(self):
        result = self.extractor.extract(helpers.rec(
            "T-11", "dispatch",
            "调字〔2026〕121号：解除调字〔2026〕118号对K17区间的临时限速。",
            notice_id="调字〔2026〕121号"))
        self.assertFalse(any("118号" in w or "121号" in w
                             for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
