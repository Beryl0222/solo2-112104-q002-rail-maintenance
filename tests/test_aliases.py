"""别名映射：修订不影响历史事件，确认流程。"""
import unittest

import helpers


class AliasRevisionTests(helpers.TempEnvMixin, unittest.TestCase):
    def test_revision_keeps_historical_events_unchanged(self):
        self.store.ingest_record(helpers.rec(
            "A-1", "contractor", "南二段继电器箱进水。",
            "2026-11-19T08:00:00"), self.extractor)
        old_event = self.store.events()[0]
        self.assertEqual(old_event.target, "EQ-RLY-K21")
        old_version = old_event.alias_version

        self.registry.revise_alias("南二段", "SEC-K30", by="值班长",
                                   note="现场核对结论")
        self.store.ingest_record(helpers.rec(
            "A-2", "dispatch", "调字〔2026〕210号：南二段临时限速。",
            "2026-11-20T09:00:00", "调字〔2026〕210号"), self.extractor)

        events = self.store.events()
        self.assertEqual(events[0].target, "EQ-RLY-K21",
                         "历史事件必须保留入库时的归属")
        self.assertEqual(events[0].alias_version, old_version)
        impose = [e for e in events if e.kind == "restriction_imposed"][0]
        self.assertEqual(impose.target, "SEC-K30",
                         "修订后入库的文本按新映射解析")

    def test_old_mapping_is_deprecated_after_revision(self):
        self.registry.revise_alias("南二段", "SEC-K30", by="值班长")
        statuses = {(m.surface, m.status) for m in self.registry.mappings
                    if m.surface == "南二段"}
        self.assertEqual(statuses,
                         {("南二段", "deprecated"), ("南二段", "confirmed")})

    def test_revision_requires_known_entity(self):
        with self.assertRaises(KeyError):
            self.registry.revise_alias("南二段", "SEC-XXX", by="值班长")


if __name__ == "__main__":
    unittest.main()
