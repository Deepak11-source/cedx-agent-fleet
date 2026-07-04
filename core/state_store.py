from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from core.models import ProcessingLedgerEntry

LEDGER_PATH = Path("out/.state/ledger.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(path: Path | None = None) -> list[ProcessingLedgerEntry]:
    path = path if path is not None else LEDGER_PATH
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ProcessingLedgerEntry.model_validate(e) for e in raw]


def is_already_processed(source_hash: str, pipeline_version: str, path: Path | None = None) -> bool:
    path = path if path is not None else LEDGER_PATH
    return any(
        e.source_hash == source_hash and e.pipeline_version == pipeline_version
        for e in load_ledger(path)
    )


def record_processed(
    source_hash: str, pipeline_version: str, record_id: str, completed_stage: str,
    path: Path | None = None,
) -> ProcessingLedgerEntry:
    """Upsert a ledger entry keyed by (source_hash, pipeline_version).

    Calling this twice for the same key replaces the entry rather than
    appending a duplicate -- this is what keeps `make demo` idempotent
    across repeated runs. `path` defaults to `None` (resolved to
    `LEDGER_PATH` inside the function body, not as the literal parameter
    default) so tests can monkeypatch the module-level `LEDGER_PATH` and
    have callers that omit `path=` still pick up the override.
    """
    path = path if path is not None else LEDGER_PATH
    entries = load_ledger(path)
    entry = ProcessingLedgerEntry(
        source_hash=source_hash, pipeline_version=pipeline_version,
        record_id=record_id, completed_stage=completed_stage, ts=_now_iso(),
    )
    entries = [
        e for e in entries
        if not (e.source_hash == source_hash and e.pipeline_version == pipeline_version)
    ]
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([e.model_dump(mode="json") for e in entries], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return entry
