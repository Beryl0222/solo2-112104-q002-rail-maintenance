"""值班员命令行：文本入库、待处理事项查询、限制始末回看、别名与归属维护。

用法示例：
    python3 -m mcs init --data-dir mcs_state
    python3 -m mcs ingest data/shift_handover.jsonl --data-dir mcs_state
    python3 -m mcs pending --data-dir mcs_state
    python3 -m mcs pending --line SEC-K17 --data-dir mcs_state
    python3 -m mcs restrictions --entity SEC-K17 --data-dir mcs_state
    python3 -m mcs timeline --entity EQ-SIG-K17 --data-dir mcs_state
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .aliases import AliasRegistry
from .extraction import Extractor
from .models import (EVENT_KIND_LABELS, SOURCE_LABELS, Record, SourceType)
from .query import Query
from .seed import build_seed_registry
from .store import Store

REGISTRY_FILE = "registry.json"


# ---------- 通用 ----------
def _load_registry(data_dir: Path) -> AliasRegistry:
    path = data_dir / REGISTRY_FILE
    if not path.exists():
        raise SystemExit(f"未找到别名注册表 {path}，请先运行：python3 -m mcs init --data-dir {data_dir}")
    return AliasRegistry.load(path)


def _save_registry(registry: AliasRegistry, data_dir: Path):
    registry.save(data_dir / REGISTRY_FILE)


def _load_records(path: Path) -> list[Record]:
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return [Record.from_dict(d) for d in json.loads(text)]
    return [Record.from_dict(json.loads(line))
            for line in text.splitlines() if line.strip()]


def _print_item(query: Query, item, indent="  "):
    print(f"{indent}[{item.kind}] {item.summary}")
    print(f"{indent}    需要确认：{item.needed}")
    print(f"{indent}    依据事件：{', '.join(item.evidence)}（自 {item.since}）")
    if item.detail:
        print(f"{indent}    说明：{item.detail}")


# ---------- 子命令 ----------
def cmd_init(args):
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / REGISTRY_FILE
    if path.exists() and not args.force:
        print(f"注册表已存在：{path}（--force 可重置为种子数据）")
        return
    build_seed_registry().save(path)
    Store(data_dir)
    print(f"已初始化数据目录 {data_dir}（含种子实体与别名映射）")


def cmd_ingest(args):
    data_dir = Path(args.data_dir)
    registry = _load_registry(data_dir)
    store = Store(data_dir)
    extractor = Extractor(registry)
    for record in _load_records(Path(args.file)):
        report = store.ingest_record(record, extractor)
        if report.skipped:
            print(f"{record.record_id}: 跳过（已入库）")
            continue
        kinds = "、".join(EVENT_KIND_LABELS[e.kind] for e in report.events) or "无事件"
        print(f"{record.record_id}（{SOURCE_LABELS[record.source]}）: {kinds}")
        for warning in report.warnings:
            print(f"    ! {warning}")


def cmd_pending(args):
    data_dir = Path(args.data_dir)
    query = Query(Store(data_dir), _load_registry(data_dir))
    if args.line or args.entity:
        items = query.pending(line=args.line, entity=args.entity)
        scope = args.line or args.entity
        print(f"待处理事项（{query.entity_label(scope)}）：{len(items)} 项")
        for item in items:
            _print_item(query, item)
        return
    groups = query.pending_by_line()
    if not groups:
        print("当前无待处理事项。")
        return
    for line, items in groups.items():
        print(f"■ {query.entity_label(line) if line != '其他/未归属' else line}"
              f" — {len(items)} 项")
        for item in items:
            _print_item(query, item)


def cmd_restrictions(args):
    data_dir = Path(args.data_dir)
    query = Query(Store(data_dir), _load_registry(data_dir))
    history = query.restriction_history(args.entity)
    if not history:
        print(f"{query.entity_label(args.entity)} 没有调度限制记录。")
        return
    print(f"调度限制始末（{query.entity_label(args.entity)}）：")
    for view in history:
        imp = view.imposed_by
        print(f"  {view.restriction_id} [{view.level}] "
              f"{'生效中' if view.active else '已解除'}")
        print(f"    开始：{imp.occurred_at} 依据 {imp.record_id}"
              f"（{imp.notice_id or '无编号'}）“{imp.excerpt}”")
        if view.lifted_by:
            lift = view.lifted_by
            print(f"    解除：{lift.occurred_at} 依据 {lift.record_id}"
                  f"（{lift.notice_id or '无编号'}）“{lift.excerpt}”")
        else:
            print(f"    解除：尚未解除（只能由调度通告解除）")


def cmd_timeline(args):
    data_dir = Path(args.data_dir)
    query = Query(Store(data_dir), _load_registry(data_dir))
    rows = query.timeline(args.entity)
    print(f"设备时间线（{query.entity_label(args.entity)}）：{len(rows)} 条")
    for row in rows:
        note = f"〔{row['note']}〕" if row["note"] else ""
        notice = f"（{row['notice_id']}）" if row["notice_id"] else ""
        print(f"  {row['occurred_at']} [{row['kind']}]{notice} "
              f"{row['source']} {row['event_id']}{note}")
        print(f"      “{row['excerpt']}”")


def cmd_event(args):
    data_dir = Path(args.data_dir)
    store = Store(data_dir)
    history = store.event_history(args.event_id)
    event = history["event"]
    print(f"{event.event_id} [{EVENT_KIND_LABELS[event.kind]}] 来源 {event.record_id}")
    print(f"  入库归属：{history['original_target']}（原文写法 {event.target_surface or '无'}）")
    print(f"  当前有效归属：{history['effective_target']}")
    for ra in history["chain"]:
        print(f"  修订 {ra.ra_id} [{ra.status}] {ra.old_entity} -> {ra.new_entity}"
              f"（{ra.reason}；提议 {ra.proposed_by}，确认 {ra.confirmed_by or '—'}）")


def cmd_aliases(args):
    registry = _load_registry(Path(args.data_dir))
    for m in registry.mappings:
        if not args.all and m.status != "confirmed":
            continue
        print(f"  {m.surface} -> {m.entity_id} [v{m.version} {m.status}]"
              f"（{m.created_by}{'；' + m.note if m.note else ''}）")


def cmd_alias_add(args):
    data_dir = Path(args.data_dir)
    registry = _load_registry(data_dir)
    m = registry.add_alias(args.surface, args.entity, by=args.by,
                           confirm=args.confirm, note=args.note)
    _save_registry(registry, data_dir)
    print(f"已新增映射 {m.surface} -> {m.entity_id} [v{m.version} {m.status}]")


def cmd_alias_confirm(args):
    data_dir = Path(args.data_dir)
    registry = _load_registry(data_dir)
    m = registry.confirm_alias(args.surface, by=args.by)
    _save_registry(registry, data_dir)
    print(f"已确认映射 {m.surface} -> {m.entity_id} [v{m.version}]")


def cmd_alias_revise(args):
    data_dir = Path(args.data_dir)
    registry = _load_registry(data_dir)
    m = registry.revise_alias(args.surface, args.entity, by=args.by, note=args.note)
    _save_registry(registry, data_dir)
    print(f"已修订映射 {m.surface} -> {m.entity_id} [v{m.version}]（历史事件归属不变）")


def cmd_reattribute(args):
    store = Store(Path(args.data_dir))
    registry = _load_registry(Path(args.data_dir))
    if registry.entity(args.entity) is None:
        raise SystemExit(f"未知实体：{args.entity}")
    ra = store.propose_reattribution(args.event_id, args.entity,
                                     reason=args.reason, by=args.by)
    print(f"已提议归属修订 {ra.ra_id}：{ra.event_id} {ra.old_entity} -> {ra.new_entity}"
          f"（待确认，确认后才生效）")


def cmd_reattr_confirm(args):
    store = Store(Path(args.data_dir))
    ra = store.confirm_reattribution(args.ra_id, by=args.by)
    print(f"已确认 {ra.ra_id}：{ra.event_id} 现归属 {ra.new_entity}（原归属保留在历史中）")


def cmd_reattr_list(args):
    store = Store(Path(args.data_dir))
    for ra in store.reattributions():
        print(f"  {ra.ra_id} [{ra.status}] {ra.event_id}: "
              f"{ra.old_entity} -> {ra.new_entity}（{ra.reason}）")


def cmd_entities(args):
    registry = _load_registry(Path(args.data_dir))
    for ent in registry.entities.values():
        parent = f"，所属 {ent.parent}" if ent.parent else ""
        print(f"  {ent.entity_id} [{ent.type.value}] {ent.name}{parent}")


# ---------- 入口 ----------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default="mcs_state",
                        help="数据目录（默认 mcs_state）")
    parser = argparse.ArgumentParser(prog="mcs", description="检修文本整理与检修状态查询")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, **kwargs):
        return sub.add_parser(name, parents=[common], **kwargs)

    p = add("init", help="初始化数据目录（写入种子实体与别名）")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = add("ingest", help="导入记录文件（JSON 数组或 JSONL）")
    p.add_argument("file")
    p.set_defaults(func=cmd_ingest)

    p = add("pending", help="查看当前待处理事项")
    p.add_argument("--line")
    p.add_argument("--entity")
    p.set_defaults(func=cmd_pending)

    p = add("restrictions", help="回看某线路/设备的限制始末")
    p.add_argument("--entity", required=True)
    p.set_defaults(func=cmd_restrictions)

    p = add("timeline", help="查看设备相关全部事件")
    p.add_argument("--entity", required=True)
    p.set_defaults(func=cmd_timeline)

    p = add("event", help="查看事件详情与归属历史")
    p.add_argument("event_id")
    p.set_defaults(func=cmd_event)

    p = add("aliases", help="列出别名映射")
    p.add_argument("--all", action="store_true", help="含待确认与已废止")
    p.set_defaults(func=cmd_aliases)

    p = add("alias-add", help="新增别名映射")
    p.add_argument("surface")
    p.add_argument("entity")
    p.add_argument("--confirm", action="store_true", help="直接确认生效")
    p.add_argument("--by", default="值班员")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_alias_add)

    p = add("alias-confirm", help="确认待确认的别名映射")
    p.add_argument("surface")
    p.add_argument("--by", default="值班员")
    p.set_defaults(func=cmd_alias_confirm)

    p = add("alias-revise", help="修订别名映射（历史事件归属不变）")
    p.add_argument("surface")
    p.add_argument("entity")
    p.add_argument("--by", default="值班员")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_alias_revise)

    p = add("reattribute", help="提议修改某事件的设备归属")
    p.add_argument("event_id")
    p.add_argument("entity")
    p.add_argument("--reason", required=True)
    p.add_argument("--by", default="值班员")
    p.set_defaults(func=cmd_reattribute)

    p = add("reattr-confirm", help="确认归属修订")
    p.add_argument("ra_id")
    p.add_argument("--by", default="值班员")
    p.set_defaults(func=cmd_reattr_confirm)

    p = add("reattr-list", help="列出归属修订")
    p.set_defaults(func=cmd_reattr_list)

    p = add("entities", help="列出规范实体")
    p.set_defaults(func=cmd_entities)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
