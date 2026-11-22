"""设备别名注册表：中文 / 英文 / 拼音缩写 / 昵称 -> 规范实体。

规则：
- 只有 confirmed（已确认）的映射参与文本解析；proposed 仅作候选。
- 映射可经确认后新增或修订（revise）。修订只影响之后入库的文本；
  已入库事件保存了当时解析到的实体与映射版本，历史不被改写。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import AliasMapping, Entity, EntityType


@dataclass
class Mention:
    surface: str
    entity_id: str
    span: tuple
    version: int


class AliasRegistry:
    def __init__(self, entities=None, mappings=None):
        self.entities: dict[str, Entity] = {e.entity_id: e for e in (entities or [])}
        self.mappings: list[AliasMapping] = list(mappings or [])

    # ---------- 实体 ----------
    def add_entity(self, entity: Entity):
        self.entities[entity.entity_id] = entity

    def entity(self, entity_id: str) -> Optional[Entity]:
        return self.entities.get(entity_id)

    def entity_name(self, entity_id: str) -> str:
        ent = self.entities.get(entity_id)
        return ent.name if ent else entity_id

    def line_of(self, entity_id: str) -> Optional[str]:
        """实体所属线路：线路返回自身，设备返回其 parent。"""
        ent = self.entities.get(entity_id)
        if ent is None:
            return None
        return ent.entity_id if ent.type == EntityType.LINE else ent.parent

    # ---------- 映射 ----------
    def _norm(self, surface: str) -> str:
        return surface.strip().lower()

    def mapping_for(self, surface: str) -> Optional[AliasMapping]:
        """当前生效（confirmed）的映射。"""
        key = self._norm(surface)
        confirmed = [m for m in self.mappings
                     if self._norm(m.surface) == key and m.status == "confirmed"]
        return max(confirmed, key=lambda m: m.version) if confirmed else None

    def _next_version(self, surface: str) -> int:
        key = self._norm(surface)
        versions = [m.version for m in self.mappings if self._norm(m.surface) == key]
        return (max(versions) + 1) if versions else 1

    def add_alias(self, surface, entity_id, by, confirm=False, note="", now=""):
        """新增映射。confirm=True 时直接生效并废止同写法的旧映射。"""
        if entity_id not in self.entities:
            raise KeyError(f"未知实体：{entity_id}")
        mapping = AliasMapping(
            surface=surface.strip(), entity_id=entity_id,
            version=self._next_version(surface),
            status="confirmed" if confirm else "proposed",
            created_by=by, confirmed_by=by if confirm else "",
            note=note, created_at=now,
        )
        if confirm:
            self._deprecate_others(mapping)
        self.mappings.append(mapping)
        return mapping

    def confirm_alias(self, surface, by, now=""):
        """确认待确认的映射（取该写法最新版本）。"""
        key = self._norm(surface)
        proposed = [m for m in self.mappings
                    if self._norm(m.surface) == key and m.status == "proposed"]
        if not proposed:
            raise KeyError(f"没有待确认的映射：{surface}")
        mapping = max(proposed, key=lambda m: m.version)
        mapping.status = "confirmed"
        mapping.confirmed_by = by
        self._deprecate_others(mapping)
        return mapping

    def revise_alias(self, surface, entity_id, by, note="", now=""):
        """修订映射：旧映射废止，新映射直接生效。历史事件不受影响。"""
        return self.add_alias(surface, entity_id, by, confirm=True,
                              note=note or "映射修订", now=now)

    def _deprecate_others(self, active: AliasMapping):
        key = self._norm(active.surface)
        for m in self.mappings:
            if m is not active and self._norm(m.surface) == key and m.status == "confirmed":
                m.status = "deprecated"

    # ---------- 文本解析 ----------
    def find_mentions(self, text: str) -> list[Mention]:
        """在文本中查找设备写法（最长匹配优先，拉丁字符忽略大小写）。"""
        current = {}
        for m in self.mappings:
            if m.status == "confirmed":
                key = self._norm(m.surface)
                if key not in current or m.version > current[key].version:
                    current[key] = m
        if not current:
            return []
        surfaces = sorted(current, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(s) for s in surfaces), re.IGNORECASE)
        mentions = []
        for match in pattern.finditer(text):
            mapping = current[self._norm(match.group(0))]
            mentions.append(Mention(surface=match.group(0), entity_id=mapping.entity_id,
                                    span=match.span(), version=mapping.version))
        return mentions

    # ---------- 持久化 ----------
    def save(self, path):
        data = {
            "entities": [e.to_dict() for e in self.entities.values()],
            "mappings": [m.to_dict() for m in self.mappings],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(entities=[Entity.from_dict(d) for d in data.get("entities", [])],
                   mappings=[AliasMapping.from_dict(d) for d in data.get("mappings", [])])
