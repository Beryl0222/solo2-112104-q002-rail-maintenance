"""初始实体与别名（演练用种子数据）。实际使用时按现场台账维护。"""
from __future__ import annotations

from .aliases import AliasRegistry
from .models import Entity, EntityType

ENTITIES = [
    Entity("SEC-K17", EntityType.LINE, "K17区间（北段）"),
    Entity("SEC-K21", EntityType.LINE, "K21区间"),
    Entity("SEC-K30", EntityType.LINE, "K30区间"),
    Entity("EQ-SIG-K17", EntityType.EQUIPMENT, "K17信号箱", parent="SEC-K17"),
    Entity("EQ-RLY-K21", EntityType.EQUIPMENT, "K21继电器箱", parent="SEC-K21"),
    Entity("EQ-RLY-K30", EntityType.EQUIPMENT, "K30继电器箱", parent="SEC-K30"),
    Entity("EQ-SW-05", EntityType.EQUIPMENT, "5号道岔", parent="SEC-K30"),
]

# (写法, 实体, 备注)。DC-5 故意不登记，用于演练“未知写法 -> 补充映射”。
ALIASES = [
    ("K17区间", "SEC-K17", ""), ("K17 区间", "SEC-K17", ""), ("K17", "SEC-K17", ""),
    ("K-17", "SEC-K17", ""), ("北段", "SEC-K17", "昵称"),
    ("K21区间", "SEC-K21", ""), ("K21", "SEC-K21", ""),
    ("K30区间", "SEC-K30", ""), ("K30", "SEC-K30", ""),
    ("南二段", "SEC-K21", "昵称；演练中将被修订为 K30 区间"),
    ("K17信号箱", "EQ-SIG-K17", ""), ("K17 信号箱", "EQ-SIG-K17", ""),
    ("信号箱", "EQ-SIG-K17", ""), ("Box K17", "EQ-SIG-K17", "英文"),
    ("K17 box", "EQ-SIG-K17", "英文"),
    ("继电器箱", "EQ-RLY-K21", ""), ("K21继电器箱", "EQ-RLY-K21", ""),
    ("K30继电器箱", "EQ-RLY-K30", ""),
    ("5号道岔", "EQ-SW-05", ""), ("道岔5", "EQ-SW-05", ""),
]


def build_seed_registry() -> AliasRegistry:
    registry = AliasRegistry(entities=list(ENTITIES))
    for surface, entity_id, note in ALIASES:
        registry.add_alias(surface, entity_id, by="系统初始", confirm=True,
                           note=note, now="2026-11-01T00:00:00")
    return registry
