"""Shared test fixtures for probe scripts and eval harness."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.hashing import sha
from core.models import (
    NormalizedRecord, PipelineState, RawRecord, SourceFormat, WorkerOutput,
)


def make_raw(
    record_id: str = "PROBE-001",
    owner: str = "probe.user",
    deadline: str = "2026-07-30",
    category: str = "REPORT",
    notes: str = "Probe test record.",
    amount: float | None = 5000.0,
    source_hash_char: str = "c",
) -> RawRecord:
    return RawRecord(
        id=record_id,
        owner=owner,
        deadline=deadline,
        category=category,
        notes=notes,
        version=1,
        amount=amount,
        source_format=SourceFormat.FEED,
        source_hash="sha256:" + source_hash_char * 64,
    )


def make_normalized(
    record_id: str = "PROBE-001",
    owner: str = "probe.user",
    deadline: date = date(2026, 7, 30),
    category: str = "REPORT",
    notes: str = "Probe test record.",
    amount: float = 5000.0,
    source_hash_char: str = "c",
) -> NormalizedRecord:
    return NormalizedRecord(
        id=record_id,
        owner=owner,
        deadline=deadline,
        category=category,
        notes=notes,
        version=1,
        amount=amount,
        source_format=SourceFormat.FEED,
        source_hash="sha256:" + source_hash_char * 64,
    )


def make_state(
    amount: float = 5000.0,
    record_id: str = "PROBE-001",
    status: str = "held_for_approval",
    total_cost_usd: float = 0.0,
    category: str = "REPORT",
    notes: str = "Probe test record.",
    source_hash_char: str = "c",
) -> PipelineState:
    raw = make_raw(record_id=record_id, amount=amount, category=category,
                   notes=notes, source_hash_char=source_hash_char)
    normalized = make_normalized(record_id=record_id, amount=amount, category=category,
                                 notes=notes, source_hash_char=source_hash_char)
    return PipelineState(
        record_id=record_id, raw=raw, normalized=normalized,
        status=status, total_cost_usd=total_cost_usd,
    )


def make_worker_output(normalized: NormalizedRecord, fields: dict) -> WorkerOutput:
    return WorkerOutput(
        record_id=normalized.id,
        input_hash=sha(normalized.model_dump(mode="json")),
        delivered_fields=fields,
        confidence_score=0.95,
        model_used="claude-haiku-4-5-20251001",
        prompt_version="worker_v1",
        tokens_in=300,
        tokens_out=100,
        cost_usd=0.0004,
        latency_ms=500.0,
    )
