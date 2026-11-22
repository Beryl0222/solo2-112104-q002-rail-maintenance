"""事件库：只追加存储原始记录与结构化事件，管理归属修订。

- 记录按 record_id 去重，重复入库自动跳过（材料可安全重复导入）。
- 归属修订（Reattribution）提议后需确认才生效；事件的原始入库归属
  永远保留，查询时按“最新已确认修订”计算有效归属。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .extraction import Extractor
from .models import Event, Reattribution, Record


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class IngestReport:
    record_id: str
    skipped: bool = False
    events: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.data_dir / "records.jsonl"
        self.events_path = self.data_dir / "events.jsonl"
        self.reattr_path = self.data_dir / "reattributions.jsonl"

    # ---------- 读取 ----------
    @staticmethod
    def _read_jsonl(path):
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _append_jsonl(path, obj):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def records(self) -> list[Record]:
        return [Record.from_dict(d) for d in self._read_jsonl(self.records_path)]

    def events(self) -> list[Event]:
        return [Event.from_dict(d) for d in self._read_jsonl(self.events_path)]

    def reattributions(self) -> list[Reattribution]:
        return [Reattribution.from_dict(d) for d in self._read_jsonl(self.reattr_path)]

    def event(self, event_id: str) -> Event:
        for e in self.events():
            if e.event_id == event_id:
                return e
        raise KeyError(f"未知事件：{event_id}")

    # ---------- 入库 ----------
    def ingest_record(self, record: Record, extractor: Extractor, now: str = "") -> IngestReport:
        now = now or _now()
        report = IngestReport(record_id=record.record_id)
        if any(r.record_id == record.record_id for r in self.records()):
            report.skipped = True
            report.warnings.append(f"{record.record_id}: 已入库，跳过重复记录")
            return report
        record.ingested_at = now
        if not record.recorded_at:
            record.recorded_at = now
        self._append_jsonl(self.records_path, record.to_dict())

        result = extractor.extract(record)
        seq = len(self.events())
        for event in result.events:
            seq += 1
            event.event_id = f"EV-{seq:05d}"
            event.ingested_at = now
            self._append_jsonl(self.events_path, event.to_dict())
            report.events.append(event)
        report.warnings.extend(result.warnings)
        return report

    # ---------- 归属修订 ----------
    def propose_reattribution(self, event_id, new_entity, reason, by, now="") -> Reattribution:
        event = self.event(event_id)  # 不存在则抛 KeyError
        ra = Reattribution(
            ra_id=f"RA-{len(self.reattributions()) + 1:04d}",
            event_id=event_id, old_entity=self.effective_target(event),
            new_entity=new_entity, reason=reason, proposed_by=by,
            created_at=now or _now(),
        )
        self._append_jsonl(self.reattr_path, ra.to_dict())
        return ra

    def confirm_reattribution(self, ra_id, by, now="") -> Reattribution:
        all_ra = self.reattributions()
        for ra in all_ra:
            if ra.ra_id == ra_id:
                if ra.status != "proposed":
                    raise ValueError(f"{ra_id} 已处理过，不能重复确认")
                ra.status = "confirmed"
                ra.confirmed_by = by
                ra.confirmed_at = now or _now()
                self.reattr_path.write_text(
                    "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in all_ra),
                    encoding="utf-8")
                return ra
        raise KeyError(f"未知归属修订：{ra_id}")

    def effective_target(self, event: Event) -> str:
        """事件的有效归属：最新已确认修订，否则为入库时的归属。"""
        confirmed = [r for r in self.reattributions()
                     if r.event_id == event.event_id and r.status == "confirmed"]
        return confirmed[-1].new_entity if confirmed else event.target

    def event_history(self, event_id: str) -> dict:
        """事件的归属历史：原始归属 + 全部修订链。"""
        event = self.event(event_id)
        chain = [r for r in self.reattributions() if r.event_id == event_id]
        return {"event": event, "original_target": event.target,
                "effective_target": self.effective_target(event), "chain": chain}
