from datetime import date
from pathlib import Path

from agents.orchestrator import dedupe_versions
from core.graph import process_record, run_pipeline
from core.models import ReasonCode
from intake import load_all_records

SEED_DIR = Path("seed")
PIPELINE_NOW = date(2026, 6, 26)


def test_process_record_clean_record_reaches_held_for_approval():
    kept, _ = dedupe_versions(load_all_records(SEED_DIR))
    batch_amounts = [r.amount for r in kept if r.amount is not None]
    raw = next(r for r in kept if r.id == "REC-001")
    state = process_record(raw, batch_amounts, PIPELINE_NOW)
    assert state.status == "held_for_approval"
    assert state.exception is None
    assert [t.agent for t in state.audit_trail] == ["orchestrator", "worker", "verifier"]


def test_process_record_kills_on_step_budget_exceeded(monkeypatch):
    monkeypatch.setenv("MAX_STEPS_PER_RECORD", "1")
    kept, _ = dedupe_versions(load_all_records(SEED_DIR))
    batch_amounts = [r.amount for r in kept if r.amount is not None]
    raw = next(r for r in kept if r.id == "REC-001")
    state = process_record(raw, batch_amounts, PIPELINE_NOW)
    assert state.exception is not None
    assert state.exception.reason_code == ReasonCode.AGENT_LOOP


def test_run_pipeline_covers_all_reason_codes():
    states = run_pipeline(SEED_DIR, PIPELINE_NOW)
    by_id = {s.record_id: s for s in states if s.status != "superseded"}
    superseded_ids = {s.record_id for s in states if s.status == "superseded"}

    assert by_id["REC-011"].exception.reason_code == ReasonCode.STALE
    assert by_id["REC-012"].exception.reason_code == ReasonCode.MISSING_INPUT
    assert by_id["REC-013"].exception.reason_code == ReasonCode.OUTLIER
    assert by_id["REC-014"].exception.reason_code == ReasonCode.INJECTION_BLOCKED
    assert by_id["REC-021"].exception.reason_code == ReasonCode.LOW_CONFIDENCE
    assert by_id["REC-002"].exception.reason_code == ReasonCode.AGENT_HALLUCINATION
    assert "REC-017" in superseded_ids
    assert by_id["REC-017"].status == "held_for_approval"
    assert by_id["REC-016"].status == "held_for_approval"
    assert by_id["REC-016"].normalized.schema_drifts == ["value→amount"]
    assert by_id["REC-001"].status == "held_for_approval"
