#!/usr/bin/env python3
"""端到端演练：乱序到达的多来源材料 -> 状态归算 -> 归属纠错。

运行（仓库根目录）：python3 examples/demo.py
演练数据为合成记录（data/shift_handover.jsonl），仅用于练习文本整理。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcs import (Extractor, Query, Record, Store, build_seed_registry)

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "shift_handover.jsonl"


def load_records():
    import json
    return [Record.from_dict(json.loads(line))
            for line in DATA_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def show_pending(query, title):
    print(f"\n=== {title} ===")
    groups = query.pending_by_line()
    if not groups:
        print("  （无待处理事项）")
    for line, items in groups.items():
        label = query.entity_label(line) if line != "其他/未归属" else line
        print(f"■ {label}")
        for item in items:
            print(f"    [{item.kind}] {item.summary}")
            print(f"        需要确认：{item.needed}；依据：{', '.join(item.evidence)}")


def main():
    data_dir = Path(tempfile.mkdtemp(prefix="mcs_demo_"))
    try:
        registry = build_seed_registry()
        store = Store(data_dir)
        extractor = Extractor(registry)
        query = Query(store, registry)

        print("演练：检修文本整理与检修状态查询（合成数据）")
        print("材料到达顺序已打乱；状态按发生时间归算，与到达顺序无关。")

        # 1) 逐条入库，观察待处理事项如何随证据到达而变化
        for record in load_records():
            report = store.ingest_record(record, extractor)
            kinds = "、".join(e.kind.value for e in report.events) or "无事件"
            print(f"\n>> 入库 {record.record_id}（{record.source.value}，"
                  f"发生于 {record.recorded_at}）-> {kinds}")
            for w in report.warnings:
                print(f"   ! {w}")
            if record.record_id == "SH-003":
                show_pending(query, "承包商称“修好了、可以申请恢复常速”之后")
                print("  注意：修复声明与申请均不构成运行许可；"
                      "且此时限制通告尚未到达，系统不臆造限制。")
            if record.record_id == "SH-002":
                show_pending(query, "限制通告（调字118号）到达后")

        show_pending(query, "全部材料入库后（SH-005 解除通告已生效）")

        # 2) 回看 K17 区间限制为何开始、为何解除
        print("\n=== K17区间 限制始末 ===")
        for view in query.restriction_history("SEC-K17"):
            imp = view.imposed_by
            print(f"  {view.restriction_id} [{view.level}] "
                  f"{'生效中' if view.active else '已解除'}")
            print(f"    开始 {imp.occurred_at} 依据 {imp.record_id}"
                  f"（{imp.notice_id}）：{imp.excerpt}")
            if view.lifted_by:
                print(f"    解除 {view.lifted_by.occurred_at} 依据 "
                      f"{view.lifted_by.record_id}（{view.lifted_by.notice_id}）："
                      f"{view.lifted_by.excerpt}")

        # 3) 归属纠错：SH-007 现场核对表明“南二段继电器箱”实际在 K30 区间
        print("\n=== 归属纠错（依据 SH-007 现场核对） ===")
        moved = [e for e in store.events()
                 if e.record_id == "SH-006" and e.target == "EQ-RLY-K21"]
        for e in moved:
            ra = store.propose_reattribution(
                e.event_id, "EQ-RLY-K30",
                reason="SH-007 现场核对：实际位于K30区间", by="值班员A")
            store.confirm_reattribution(ra.ra_id, by="值班长B")
            print(f"  {e.event_id}（{e.kind.value}）EQ-RLY-K21 -> EQ-RLY-K30，"
                  f"原归属保留于历史")
        registry.revise_alias("南二段", "SEC-K30", by="值班长B",
                              note="SH-007 核对结论；此后新文本按新映射解析")
        print("  别名“南二段”已修订 -> SEC-K30（历史事件归属不变）")

        # 4) 未知写法：补充映射并纠正已入库事件
        print("\n=== 未知写法 DC-5 的处理 ===")
        registry.add_alias("DC-5", "EQ-SW-05", by="值班员A", confirm=True,
                           note="确认为5号道岔")
        for e in store.events():
            if e.record_id == "SH-008" and e.target == "UNRESOLVED":
                ra = store.propose_reattribution(
                    e.event_id, "EQ-SW-05", reason="DC-5 已确认为5号道岔",
                    by="值班员A")
                store.confirm_reattribution(ra.ra_id, by="值班长B")
                print(f"  {e.event_id}（{e.kind.value}）UNRESOLVED -> EQ-SW-05")

        show_pending(query, "纠错完成后（当前真实待办）")

        # 5) 抽看一个被改属事件的完整历史
        print("\n=== 事件归属历史示例 ===")
        history = store.event_history(moved[0].event_id)
        print(f"  {moved[0].event_id} 入库归属 {history['original_target']}，"
              f"当前有效归属 {history['effective_target']}")
        for ra in history["chain"]:
            print(f"    {ra.ra_id} [{ra.status}] {ra.old_entity} -> {ra.new_entity}"
                  f"（{ra.reason}）")
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
