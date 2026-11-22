"""值班查询接口：待处理事项、限制始末、设备时间线。"""
from __future__ import annotations

from .aliases import AliasRegistry
from .models import (EVENT_KIND_LABELS, SOURCE_LABELS, UNRESOLVED, EntityType)
from .state import (PendingItem, RestrictionView, compute_pending,
                    compute_restrictions, effective_events)
from .store import Store


class Query:
    def __init__(self, store: Store, registry: AliasRegistry):
        self.store = store
        self.registry = registry

    # ---------- 待处理事项 ----------
    def pending(self, line: str = None, entity: str = None) -> list[PendingItem]:
        items = compute_pending(self.store, self.registry)
        if entity:
            items = [i for i in items if i.entity == entity]
        if line:
            items = [i for i in items
                     if i.entity == line or self.registry.line_of(i.entity) == line]
        return items

    def pending_by_line(self) -> dict:
        """按线路分组；未归属与站级对象归入“其他”。"""
        groups: dict[str, list[PendingItem]] = {}
        for item in compute_pending(self.store, self.registry):
            key = self.registry.line_of(item.entity) or "其他/未归属"
            groups.setdefault(key, []).append(item)
        return groups

    # ---------- 限制始末 ----------
    def restriction_history(self, scope: str) -> list[RestrictionView]:
        """某线路/设备上全部限制（含已解除），可看为何开始、为何解除。"""
        events = effective_events(self.store)
        restrictions, _ = compute_restrictions(events)
        return [r for r in restrictions
                if r.scope == scope or self.registry.line_of(r.scope) == scope]

    # ---------- 设备时间线 ----------
    def timeline(self, entity: str) -> list[dict]:
        """与实体相关的全部事件；归属被修订过的事件标注原归属与修订号。"""
        rows = []
        for e in effective_events(self.store):
            original = self.store.event(e.event_id).target
            if e.target != entity and original != entity:
                continue
            note = ""
            if original != e.target:
                ra = [r for r in self.store.reattributions()
                      if r.event_id == e.event_id and r.status == "confirmed"]
                ref = ra[-1].ra_id if ra else ""
                if e.target == entity:
                    note = f"原归属 {original}，经 {ref} 改属本对象"
                else:
                    note = f"经 {ref} 已改属 {e.target}"
            rows.append({
                "event_id": e.event_id, "occurred_at": e.occurred_at,
                "kind": EVENT_KIND_LABELS[e.kind], "source": SOURCE_LABELS[e.source],
                "excerpt": e.excerpt, "surface": e.target_surface,
                "notice_id": e.notice_id, "note": note,
            })
        return rows

    # ---------- 辅助 ----------
    def resolve_entity(self, text: str):
        """把任意写法（昵称/缩写/编号）解析为规范实体 id。"""
        mentions = self.registry.find_mentions(text)
        return mentions[0].entity_id if mentions else None

    def entity_label(self, entity_id: str) -> str:
        if entity_id == UNRESOLVED:
            return "未归属"
        ent = self.registry.entity(entity_id)
        if not ent:
            return entity_id
        kind = "线路" if ent.type == EntityType.LINE else "设备"
        return f"{ent.name}（{kind} {ent.entity_id}）"
