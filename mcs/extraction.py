"""从原始叙述中抽取结构化事件（中文 / 英文 / 拼音缩写混写）。

安全规则（不可绕过）：
- 只有来源为“调度通告”的文本能产生 限制开始 / 限制解除 事件；
- 承包商或现场记录中的恢复、解除类措辞一律记为“无授权表述”，
  只提示、不影响任何限制状态；
- 条件式 / 否定式表述（“待复核合格后另行解除”“方可解除”“未解除”等）
  不产生事件；
- “更换”“检查完成”“修好了”是不同事实，分别成事件，互不代表。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .aliases import AliasRegistry
from .models import (UNRESOLVED, EntityType, Event, EventKind, Record, SourceType)

CLAUSE_SPLIT = re.compile(r"[，。；;！？!?\n]+")
NOTICE_RE = re.compile(r"调字[〔\[]\d{4}[〕\]]\d+号")

FAULT_PATTERNS = [
    r"故障", r"异常", r"异响", r"漏油", r"渗油", r"过热", r"发热", r"进水", r"受潮",
    r"卡阻", r"卡涩", r"缺陷", r"报警", r"跳闸", r"破损", r"测温偏高", r"温度偏高",
    r"fault", r"defect", r"leak\w*", r"alarm\w*", r"trip(?:ped)?", r"abnormal", r"noise",
]
REPLACE_PATTERNS = [r"更换(?!后)", r"已换", r"换装", r"replac\w*", r"swap(?:ped)?"]
INSPECT_PATTERNS = [
    r"检查完成", r"检查完毕", r"完成检查", r"复测(?:正常|合格)", r"试验合格",
    r"复核[^，。]{0,6}(?:合格|正常|无误|通过)", r"现场确认",
    r"inspect\w*", r"verif\w*", r"tested",
]
REPAIR_PATTERNS = [r"修好\w*", r"修复", r"已修", r"处理完毕", r"fixed", r"repaired", r"mended"]
IMPOSE_PATTERNS = [
    r"临时限速", r"限速", r"限制运行", r"停运", r"降负荷", r"封锁", r"退出运行",
    r"out of service", r"derat\w*", r"restrict\w*", r"speed restriction",
]
LIFT_PATTERNS = [
    r"解除", r"允许恢复", r"恢复常速", r"恢复运行", r"恢复送电", r"复电", r"送电",
    r"lift\w*", r"releas\w*", r"restor\w*", r"resum\w*",
]

ACTIONS = [
    ("fault", FAULT_PATTERNS),
    ("replace", REPLACE_PATTERNS),
    ("inspect", INSPECT_PATTERNS),
    ("repair", REPAIR_PATTERNS),
    ("impose", IMPOSE_PATTERNS),
    ("lift", LIFT_PATTERNS),
]

# 条件/否定式“解除”：整句抑制 lift（如“收到调度确认后方可解除”）。
LIFT_GUARDS = [
    r"后方可?解除", r"待[^，。]{0,8}解除", r"另行解除", r"尚未解除", r"未解除",
    r"没有?收到[^，。]{0,4}解除", r"解除命令",
]
# 动作词前的否定/未然前缀（“待复核合格”“未修复”“拟更换”不算事实）。
NEG_PREFIXES = ("待", "需", "须", "应", "尚未", "未", "勿", "拟")

# 未登记写法的候选：拼音缩写/编号（如 DC-5）、“N号+中文部件”。
CANDIDATE_RES = [
    re.compile(r"[A-Za-z]{2,6}-?\d+"),
    re.compile(r"\d+号[一-鿿]{1,6}"),
]


@dataclass
class ExtractionResult:
    events: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - 2):start]
    return any(p in window for p in NEG_PREFIXES)


def _kind_for(action: str, source: SourceType) -> EventKind:
    if action == "impose":
        return EventKind.RESTRICTION_IMPOSED if source == SourceType.DISPATCH \
            else EventKind.UNAUTHORIZED_CLAIM
    if action == "lift":
        return EventKind.RESTRICTION_LIFTED if source == SourceType.DISPATCH \
            else EventKind.UNAUTHORIZED_CLAIM
    if action == "inspect":
        return EventKind.FIELD_VERIFIED if source == SourceType.FIELD_CHECK \
            else EventKind.WORK_INSPECTED
    if action == "replace":
        return EventKind.WORK_REPLACED
    if action == "repair":
        return EventKind.REPAIR_CLAIMED
    return EventKind.FAULT_REPORTED


class Extractor:
    def __init__(self, registry: AliasRegistry):
        self.registry = registry

    # ---------- 主入口 ----------
    def extract(self, record: Record) -> ExtractionResult:
        text = record.text
        notice_ids = NOTICE_RE.findall(text)
        notice_id = record.notice_id
        if not notice_id and record.source == SourceType.DISPATCH and notice_ids:
            notice_id = notice_ids[0]
        referenced = [n for n in notice_ids if n != notice_id]

        result = ExtractionResult()
        occurred_at = record.recorded_at or record.ingested_at
        last_target = None  # (entity_id, surface, alias_version)

        for clause in CLAUSE_SPLIT.split(text):
            clause = clause.strip()
            if not clause:
                continue
            mentions = self.registry.find_mentions(clause)
            actions = self._find_actions(clause)
            if not actions:
                if mentions:
                    m = self._pick(mentions, len(clause))
                    last_target = (m.entity_id, m.surface, m.version)
                continue
            # 同一小句中“解除……限速”类表述：解除优先，限制不再重复成事件。
            action_names = {a for a, _, _ in actions}
            if "lift" in action_names and "impose" in action_names:
                actions = [a for a in actions if a[0] != "impose"]

            for action, pos, keyword in actions:
                picked = self._pick(mentions, pos)
                if picked is not None:
                    target, surface, version = picked.entity_id, picked.surface, picked.version
                elif last_target is not None:
                    target, surface, version = last_target
                else:
                    candidate = self._unknown_candidate(clause)
                    if candidate:
                        target, surface, version = UNRESOLVED, candidate, None
                    else:
                        result.warnings.append(
                            f"{record.record_id}: 动作“{keyword}”找不到设备归属，已跳过（{clause}）")
                        continue
                kind = _kind_for(action, record.source)
                result.events.append(Event(
                    event_id="", record_id=record.record_id, source=record.source,
                    kind=kind, target=target, target_surface=surface,
                    occurred_at=occurred_at, ingested_at=record.ingested_at,
                    excerpt=clause, detail=keyword,
                    notice_id=notice_id if kind in (EventKind.RESTRICTION_IMPOSED,
                                                    EventKind.RESTRICTION_LIFTED) else None,
                    referenced_notices=referenced if kind == EventKind.RESTRICTION_LIFTED else [],
                    alias_version=version,
                ))
                last_target = (target, surface, version)

        result.events = self._dedupe(result.events)
        for cand in self._unknown_candidates(text):
            result.warnings.append(f"{record.record_id}: 未登记的设备写法“{cand}”，"
                                   f"请确认后补充别名映射")
        return result

    # ---------- 内部 ----------
    def _find_actions(self, clause: str):
        found = []
        lift_guarded = any(re.search(g, clause) for g in LIFT_GUARDS)
        for action, patterns in ACTIONS:
            for pat in patterns:
                m = re.search(pat, clause, re.IGNORECASE)
                if not m:
                    continue
                if action == "lift" and lift_guarded:
                    continue
                if action in ("fault", "replace", "inspect", "repair") \
                        and _negated(clause, m.start()):
                    continue
                found.append((action, m.start(), m.group(0)))
                break  # 每类动作取第一次出现
        return found

    def _pick(self, mentions, pos):
        """取离动作词最近的写法；距离相近时优先设备级而非线路级。"""
        if not mentions:
            return None

        def key(mention):
            center = (mention.span[0] + mention.span[1]) / 2
            ent = self.registry.entity(mention.entity_id)
            penalty = 0.0 if (ent and ent.type == EntityType.EQUIPMENT) else 0.5
            return abs(center - pos) + penalty

        return min(mentions, key=key)

    @staticmethod
    def _dedupe(events):
        seen, out = set(), []
        for e in events:
            key = (e.kind, e.target)
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    def _unknown_candidates(self, text):
        mention_spans = [m.span for m in self.registry.find_mentions(text)]
        notice_spans = [m.span() for m in NOTICE_RE.finditer(text)]

        def covered(span):
            return any(s < span[1] and span[0] < e
                       for s, e in mention_spans + notice_spans)

        found = []
        for rx in CANDIDATE_RES:
            for m in rx.finditer(text):
                if not covered(m.span()) and m.group(0) not in found:
                    found.append(m.group(0))
        return found

    @staticmethod
    def _unknown_candidate(clause):
        for rx in CANDIDATE_RES:
            m = rx.search(clause)
            if m:
                return m.group(0)
        return ""
