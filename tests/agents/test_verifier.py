from datetime import date
from pathlib import Path

from agents.orchestrator import dedupe_versions, orchestrate
from agents.worker import worker_draft
from agents.verifier import verify
from core.models import PipelineState, ReasonCode, VerifierVerdict, WorkerOutput
from intake import load_all_records

SEED_DIR = Path("seed")
PIPELINE_NOW = date(2026, 6, 26)


def _through_worker(record_id: str) -> PipelineState:
    kept, _ = dedupe_versions(load_all_records(SEED_DIR))
    batch_amounts = [r.amount for r in kept if r.amount is not None]
    raw = next(r for r in kept if r.id == record_id)
    state = orchestrate(PipelineState(record_id=raw.id, raw=raw), batch_amounts, PIPELINE_NOW)
    return worker_draft(state)


def test_verify_passes_clean_record_rec_001():
    state = verify(_through_worker("REC-001"))
    assert state.exception is None
    assert state.verifier_decision.verdict == VerifierVerdict.PASS
    assert state.audit_trail[-1].agent == "verifier"


def test_verify_overrules_hallucinated_field_rec_002():
    state = verify(_through_worker("REC-002"))
    assert state.exception is not None
    assert state.exception.reason_code == ReasonCode.AGENT_HALLUCINATION
    assert "internal_risk_score" in state.verifier_decision.hallucinated_fields
    assert state.verifier_decision.verdict == VerifierVerdict.FAIL


def test_verify_catches_formatted_amount_value_mismatch():
    state = _through_worker("REC-001")
    tampered = state.worker_output.model_copy(update={
        "delivered_fields": {**state.worker_output.delivered_fields, "formatted_amount": "$999,999.00"},
    })
    state = state.model_copy(update={"worker_output": tampered})
    result = verify(state)
    assert result.exception is not None
    assert result.exception.reason_code == ReasonCode.AGENT_HALLUCINATION
    assert any("formatted_amount" in f for f in result.verifier_decision.hallucinated_fields)
