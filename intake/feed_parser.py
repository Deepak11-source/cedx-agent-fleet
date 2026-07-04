from __future__ import annotations
import hashlib
import json
from pathlib import Path

from core.models import RawRecord, SourceFormat
from intake.common import build_raw_record


def parse_feed(path: Path) -> list[RawRecord]:
    records_json = json.loads(path.read_text(encoding="utf-8"))
    result: list[RawRecord] = []
    for rec in records_json:
        rec_hash = hashlib.sha256(
            json.dumps(rec, sort_keys=True).encode("utf-8")
        ).hexdigest()
        fields = {k: ("" if v is None else v) for k, v in rec.items()}
        raw = build_raw_record(fields, SourceFormat.FEED, rec_hash)
        result.append(raw)
    return result
