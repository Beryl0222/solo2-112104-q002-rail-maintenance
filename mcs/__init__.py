"""检修控制室文本整理与检修状态查询。

- extraction：中/英/拼音缩写混写文本 -> 结构化事件
- store：只追加事件库 + 归属修订（确认后生效，历史保留）
- state：限制生命周期与待处理事项归算（与到达顺序无关）
- query：值班查询（按线路/设备、依据、所需确认、限制始末）

安全不变量：调度限制只能由调度通告开启与解除；任何“修好了”
类表述都不会被系统转成运行许可。
"""
from .aliases import AliasRegistry
from .extraction import Extractor
from .models import (Entity, EntityType, Event, EventKind, Record, SourceType,
                     UNRESOLVED)
from .query import Query
from .seed import build_seed_registry
from .state import compute_pending, compute_restrictions
from .store import Store

__all__ = [
    "AliasRegistry", "Extractor", "Entity", "EntityType", "Event", "EventKind",
    "Record", "SourceType", "UNRESOLVED", "Query", "Store",
    "build_seed_registry", "compute_pending", "compute_restrictions",
]
