"""测试公共工具：构造种子注册表、临时事件库与记录。"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcs import Extractor, Record, SourceType, Store, build_seed_registry  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SHIFT_FILE = DATA_DIR / "shift_handover.jsonl"


def make_env(tmpdir):
    registry = build_seed_registry()
    store = Store(tmpdir)
    return registry, store, Extractor(registry)


def rec(rid, kind, text, recorded_at="2026-11-20T08:00:00", notice_id=None):
    return Record(record_id=rid, source=SourceType(kind), text=text,
                  recorded_at=recorded_at, notice_id=notice_id)


def load_shift_records(chronological=False):
    records = [Record.from_dict(json.loads(line))
               for line in SHIFT_FILE.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    if chronological:
        records.sort(key=lambda r: r.recorded_at)
    return records


def ingest_all(store, extractor, records):
    for record in records:
        store.ingest_record(record, extractor)


class TempEnvMixin:
    """每个用例一个独立的临时数据目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.registry, self.store, self.extractor = make_env(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
