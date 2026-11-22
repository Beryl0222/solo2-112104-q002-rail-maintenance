"""数据模型：原始记录、结构化事件、设备实体、别名映射、归属修订。

设计约定：
- 事件一旦入库即不可改写（只追加）。事件上的 target 保存“入库时”
  解析到的规范实体，之后别名映射修订不影响历史事件。
- 归属错误通过 Reattribution（归属修订）纠正：提议 -> 确认后生效，
  原归属保留在修订链中，可随时回看。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import Optional


class SourceType(str, enum.Enum):
    CONTRACTOR = "contractor"    # 承包商交班记录
    DISPATCH = "dispatch"        # 调度通告
    FIELD_CHECK = "field_check"  # 现场复核记录


SOURCE_LABELS = {
    SourceType.CONTRACTOR: "承包商交班",
    SourceType.DISPATCH: "调度通告",
    SourceType.FIELD_CHECK: "现场复核",
}


class EntityType(str, enum.Enum):
    LINE = "line"            # 线路/区间
    EQUIPMENT = "equipment"  # 设备/部件


class EventKind(str, enum.Enum):
    FAULT_REPORTED = "fault_reported"             # 故障/缺陷报告
    WORK_REPLACED = "work_replaced"               # 更换
    WORK_INSPECTED = "work_inspected"             # 检查完成
    REPAIR_CLAIMED = "repair_claimed"             # 承包方声称已修复（不等于运行许可）
    FIELD_VERIFIED = "field_verified"             # 现场复核合格
    RESTRICTION_IMPOSED = "restriction_imposed"   # 调度限制开始（仅调度通告）
    RESTRICTION_LIFTED = "restriction_lifted"     # 调度限制解除（仅调度通告）
    UNAUTHORIZED_CLAIM = "unauthorized_claim"     # 无授权的恢复/解除表述（仅提示，不生效）


EVENT_KIND_LABELS = {
    EventKind.FAULT_REPORTED: "故障报告",
    EventKind.WORK_REPLACED: "更换",
    EventKind.WORK_INSPECTED: "检查完成",
    EventKind.REPAIR_CLAIMED: "修复声明(承包方)",
    EventKind.FIELD_VERIFIED: "现场复核合格",
    EventKind.RESTRICTION_IMPOSED: "调度限制开始",
    EventKind.RESTRICTION_LIFTED: "调度限制解除",
    EventKind.UNAUTHORIZED_CLAIM: "无授权恢复表述",
}

UNRESOLVED = "UNRESOLVED"  # 未能归属的对象（等待补充别名映射）


@dataclass
class Entity:
    entity_id: str
    type: EntityType
    name: str
    parent: Optional[str] = None  # 设备所属线路/区间

    def to_dict(self):
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(entity_id=d["entity_id"], type=EntityType(d["type"]),
                   name=d["name"], parent=d.get("parent"))


@dataclass
class Record:
    """一条原始材料（交班记录 / 调度通告 / 现场复核）。"""
    record_id: str
    source: SourceType
    text: str
    recorded_at: str = ""            # 材料形成时间（可空，空则用入库时间）
    author: str = ""
    notice_id: Optional[str] = None  # 调度通告编号，如 调字〔2026〕118号
    lang: str = ""
    ingested_at: str = ""            # 入库时间（到达顺序）

    def to_dict(self):
        d = asdict(self)
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            record_id=d.get("record_id") or d.get("id"),
            source=SourceType(d.get("source") or d.get("kind")),
            text=d["text"],
            recorded_at=d.get("recorded_at", ""),
            author=d.get("author", ""),
            notice_id=d.get("notice_id"),
            lang=d.get("lang", ""),
            ingested_at=d.get("ingested_at", ""),
        )


@dataclass
class Event:
    """从原始记录中抽取的一条结构化事实。入库后不可改写。"""
    event_id: str
    record_id: str
    source: SourceType
    kind: EventKind
    target: str                      # 入库时解析到的规范实体（历史保留）
    target_surface: str              # 原文写法（昵称/缩写原样保留）
    occurred_at: str
    ingested_at: str
    excerpt: str                     # 依据原文片段
    detail: str = ""                 # 命中的关键词（如 限制方式：临时限速）
    notice_id: Optional[str] = None
    referenced_notices: list = field(default_factory=list)  # 文中引用的其他通告编号
    alias_version: Optional[int] = None  # 解析时使用的别名映射版本

    def to_dict(self):
        d = asdict(self)
        d["source"] = self.source.value
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            event_id=d["event_id"], record_id=d["record_id"],
            source=SourceType(d["source"]), kind=EventKind(d["kind"]),
            target=d["target"], target_surface=d.get("target_surface", ""),
            occurred_at=d["occurred_at"], ingested_at=d.get("ingested_at", ""),
            excerpt=d.get("excerpt", ""), detail=d.get("detail", ""),
            notice_id=d.get("notice_id"),
            referenced_notices=list(d.get("referenced_notices", [])),
            alias_version=d.get("alias_version"),
        )


@dataclass
class AliasMapping:
    """一条别名映射。status: proposed(待确认) / confirmed(已确认) / deprecated(已废止)。"""
    surface: str
    entity_id: str
    version: int
    status: str = "proposed"
    created_by: str = ""
    confirmed_by: str = ""
    note: str = ""
    created_at: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(surface=d["surface"], entity_id=d["entity_id"],
                   version=d["version"], status=d.get("status", "proposed"),
                   created_by=d.get("created_by", ""),
                   confirmed_by=d.get("confirmed_by", ""),
                   note=d.get("note", ""), created_at=d.get("created_at", ""))


@dataclass
class Reattribution:
    """归属修订：把某事件当时归属的对象改为另一对象。确认后才生效。"""
    ra_id: str
    event_id: str
    old_entity: str
    new_entity: str
    reason: str
    proposed_by: str
    status: str = "proposed"  # proposed / confirmed
    created_at: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(ra_id=d["ra_id"], event_id=d["event_id"],
                   old_entity=d["old_entity"], new_entity=d["new_entity"],
                   reason=d.get("reason", ""), proposed_by=d.get("proposed_by", ""),
                   status=d.get("status", "proposed"),
                   created_at=d.get("created_at", ""),
                   confirmed_by=d.get("confirmed_by", ""),
                   confirmed_at=d.get("confirmed_at", ""))
