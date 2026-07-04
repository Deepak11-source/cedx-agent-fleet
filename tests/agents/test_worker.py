import json
from datetime import date
from pathlib import Path

import pytest

import core.transcripts as transcripts_mod
from agents.orchestrator import dedupe_versions, orchestrate
from agents.worker import worker_draft
from core.models import PipelineState, ReasonCode
from core.transcripts import save_transcript
from intake import load_all_records

SEED_DIR = Path("seed")
PIPELINE_NOW = date(2026, 6, 26)


def _normalized_state(record_id: str) -> PipelineState:
    kept, _ = dedupe_versions(load_all_records(SEED_DIR))
    batch_amounts = [r.amount for r in kept if r.amount is not None]
    raw = next(r for r in kept if r.id == record_id)
    state = orchestrate(PipelineState(record_id=raw.id, raw=raw), batch_amounts, PIPELINE_NOW)
    assert state.normalized is not None, f"{record_id} unexpectedly blocked at orchestrator"
    return state


def test_worker_draft_clean_record_rec_001():
    # Uses the transcripts committed in Task 7 -- REC-001 is a clean record.
    state = worker_draft(_normalized_state("REC-001"))
    assert state.exception is None
    assert state.worker_output is not None
    assert state.worker_output.abstained is False
    assert state.worker_output.confidence_score >= 0.5
    assert "formatted_amount" in state.worker_output.delivered_fields
    assert state.audit_trail[-1].agent == "worker"


def test_worker_draft_abstains_on_low_confidence_rec_021():
    state = worker_draft(_normalized_state("REC-021"))
    assert state.worker_output.abstained is True
    assert state.exception is not None
    assert state.exception.reason_code == ReasonCode.LOW_CONFIDENCE


def test_worker_draft_does_not_self_police_hallucination_rec_002():
    # Worker isn't responsible for catching hallucinated fields -- the
    # Verifier is (Task 9). The Worker just returns whatever valid JSON it drafted.
    state = worker_draft(_normalized_state("REC-002"))
    assert state.exception is None
    assert "internal_risk_score" in state.worker_output.delivered_fields


def test_worker_draft_malformed_json_raises_agent_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts_mod, "TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(transcripts_mod, "INDEX_PATH", tmp_path / "index.json")
    save_transcript(
        record_id="REC-FAKE", agent="worker", prompt_version="worker_v1",
        response={"content": [{"type": "text", "text": "not valid json"}],
                  "usage": {"input_tokens": 10, "output_tokens": 5}},
        delivered_fields=None, model="claude-haiku-4-5-20251001",
        tokens_in=10, tokens_out=5, latency_ms=10.0,
    )
    state = _normalized_state("REC-001")
    state = state.model_copy(update={"record_id": "REC-FAKE",
                                      "normalized": state.normalized.model_copy(update={"id": "REC-FAKE"})})
    result = worker_draft(state)
    assert result.exception is not None
    assert result.exception.reason_code == ReasonCode.AGENT_MALFORMED


def test_worker_draft_budget_exceeded(monkeypatch):
    monkeypatch.setenv("MAX_COST_PER_RECORD", "0.0000001")
    state = worker_draft(_normalized_state("REC-001"))
    assert state.exception is not None
    assert state.exception.reason_code == ReasonCode.BUDGET_EXCEEDED
