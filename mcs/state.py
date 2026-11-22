"""由事件流归算当前状态：调度限制生命周期、待处理事项。

归算只依赖事件的“发生时间”，与材料到达（入库）顺序无关：
晚到的材料会自然并入既有时间线，补足证据或暴露归属问题。

核心不变量：
- 限制只能由调度通告事件开启，也只能由调度通告事件关闭；
  承包商的“修好了”、现场复核合格都不改变限制状态。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .aliases import AliasRegistry
from .models import (UNRESOLVED, Event, EventKind)
from .store import Store

WORK_KINDS = (EventKind.WORK_REPLACED, EventKind.WORK_INSPECTED, EventKind.REPAIR_CLAIMED)


@dataclass
class RestrictionView:
    restriction_id: str
    scope: str                 # 限制作用的规范实体（线路或设备）
    level: str                 # 限制方式（原文关键词，如 临时限速）
    imposed_by: Event
    lifted_by: Event = None

    @property
    def active(self) -> bool:
        return self.lifted_by is None


@dataclass
class PendingItem:
    kind: str                  # restriction / open_fault / work_unverified / unresolved / warning
    entity: str
    summary: str
    needed: str                # 需要的确认类型
    evidence: list = field(default_factory=list)  # 依据事件 id
    since: str = ""
    detail: str = ""


def effective_events(store: Store) -> list[Event]:
    """全部事件按有效归属 + 发生时间归算后的序列。"""
    events = store.events()
    for e in events:
        e.target = store.effective_target(e)
    return sorted(events, key=lambda e: (e.occurred_at, e.event_id))


def compute_restrictions(events: list[Event]):
    """归算限制生命周期。返回 (全部限制, 无对应限制的解除通告)。"""
    flow = [e for e in events if e.kind in (EventKind.RESTRICTION_IMPOSED,
                                            EventKind.RESTRICTION_LIFTED)]
    restrictions, unmatched_lifts = [], []
    open_by_scope: dict[str, list[RestrictionView]] = {}
    for e in flow:
        if e.kind == EventKind.RESTRICTION_IMPOSED:
            view = RestrictionView(
                restriction_id=f"RST-{len(restrictions) + 1:04d}",
                scope=e.target, level=e.detail, imposed_by=e)
            restrictions.append(view)
            open_by_scope.setdefault(e.target, []).append(view)
            continue
        candidates = open_by_scope.get(e.target, [])
        chosen = None
        if e.referenced_notices:  # 解除通告指明原通告编号时优先对应
            for view in candidates:
                if view.imposed_by.notice_id and \
                        view.imposed_by.notice_id in e.referenced_notices:
                    chosen = view
                    break
        if chosen is None and candidates:
            chosen = candidates[0]  # 否则关闭该对象上最早未解除的限制
        if chosen is None:
            unmatched_lifts.append(e)
        else:
            chosen.lifted_by = e
            candidates.remove(chosen)
    return restrictions, unmatched_lifts


def compute_pending(store: Store, registry: AliasRegistry) -> list[PendingItem]:
    events = effective_events(store)
    restrictions, unmatched_lifts = compute_restrictions(events)
    items: list[PendingItem] = []

    by_entity: dict[str, list[Event]] = {}
    for e in events:
        by_entity.setdefault(e.target, []).append(e)

    # 1) 故障闭环：故障报告 -> （检修处理）-> 现场复核合格 才算闭环；
    #    同一未闭环时段内多来源的重复报告合并为同一事项的证据。
    fault_open_entities = set()
    for entity, evs in by_entity.items():
        if entity == UNRESOLVED:
            continue
        verifs = sorted((e for e in evs if e.kind == EventKind.FIELD_VERIFIED),
                        key=lambda e: (e.occurred_at, e.event_id))
        works = [e for e in evs if e.kind in WORK_KINDS]
        faults = sorted((e for e in evs if e.kind == EventKind.FAULT_REPORTED),
                        key=lambda e: (e.occurred_at, e.event_id))
        chains: list[list[Event]] = []
        for fault in faults:
            if chains and not any(v.occurred_at >= chains[-1][0].occurred_at
                                  for v in verifs):
                chains[-1].append(fault)  # 前一条故障未闭环，视为同一事项
            else:
                chains.append([fault])
        for chain in chains:
            first = chain[0]
            if any(v.occurred_at >= first.occurred_at for v in verifs):
                continue  # 已复核闭环
            after = [w for w in works if w.occurred_at >= first.occurred_at]
            needed = "现场复核" if after else "检修处理"
            evidence = [f.event_id for f in chain] + [w.event_id for w in after]
            items.append(PendingItem(
                kind="open_fault", entity=entity,
                summary=f"{registry.entity_name(entity)} 故障未闭环（{first.detail}）",
                needed=needed, evidence=evidence, since=first.occurred_at,
                detail=first.excerpt))
            fault_open_entities.add(entity)
        # 无对应故障的已完成工作：仍需现场复核确认
        if works and entity not in fault_open_entities:
            latest = max(works, key=lambda w: (w.occurred_at, w.event_id))
            if not any(v.occurred_at >= latest.occurred_at for v in verifs):
                items.append(PendingItem(
                    kind="work_unverified", entity=entity,
                    summary=f"{registry.entity_name(entity)} 有已完成工作未经现场复核",
                    needed="现场复核", evidence=[w.event_id for w in works],
                    since=latest.occurred_at, detail=latest.excerpt))

    # 2) 生效中的调度限制：只有调度通告能解除
    for view in restrictions:
        if not view.active:
            continue
        related = [ent for ent in by_entity
                   if ent != UNRESOLVED and
                   (ent == view.scope or registry.line_of(ent) == view.scope)]
        open_field = [i for i in items
                      if i.kind in ("open_fault", "work_unverified") and i.entity in related]
        readiness = ("现场尚有未闭环事项：" + "、".join(sorted({i.entity for i in open_field}))) \
            if open_field else "现场事项已闭环，仅待调度解除通告"
        items.append(PendingItem(
            kind="restriction", entity=view.scope,
            summary=f"{registry.entity_name(view.scope)} 调度限制生效中（{view.level}）",
            needed="调度通告解除", evidence=[view.imposed_by.event_id],
            since=view.imposed_by.occurred_at, detail=readiness))

    # 3) 未归属对象：等待补充/修订别名映射
    unresolved = by_entity.get(UNRESOLVED, [])
    if unresolved:
        surfaces = sorted({e.target_surface for e in unresolved if e.target_surface})
        items.append(PendingItem(
            kind="unresolved", entity=UNRESOLVED,
            summary=f"存在未归属的设备写法：{'、'.join(surfaces) or '（无写法）'}",
            needed="确认设备归属（补充或修订别名映射）",
            evidence=[e.event_id for e in unresolved],
            since=unresolved[0].occurred_at))

    # 4) 提示类：无授权表述、无对应限制的解除通告
    for e in events:
        if e.kind == EventKind.UNAUTHORIZED_CLAIM:
            items.append(PendingItem(
                kind="warning", entity=e.target,
                summary=f"{registry.entity_name(e.target)} 出现无授权恢复表述"
                        f"（{e.target_surface or e.detail}）",
                needed="无需操作：该表述不构成运行许可；如属实应等待调度通告",
                evidence=[e.event_id], since=e.occurred_at, detail=e.excerpt))
    for e in unmatched_lifts:
        items.append(PendingItem(
            kind="warning", entity=e.target,
            summary=f"解除通告 {e.notice_id or ''} 找不到对应的生效限制",
            needed="核对解除通告与既有限制的对应关系",
            evidence=[e.event_id], since=e.occurred_at, detail=e.excerpt))
    return items
