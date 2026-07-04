from datetime import date

from core.models import (
    AgentStatus, AgentTrace, ApprovalEntry, ApprovalState, ExceptionRecord,
    NormalizedRecord, PipelineState, ProcessingLedgerEntry, RawRecord,
    ReasonClass, ReasonCode, SourceFormat, VerifierDecision, VerifierVerdict,
    WorkerOutput,
)

# The exact string values audit.schema.json declares for reason_code.
SCHEMA_REASON_CODES = {
    "STALE", "MISSING_INPUT", "OUTLIER", "INJECTION_BLOCKED", "LOW_CONFIDENCE",
    "UNVERIFIED_ANOMALY", "AGENT_HALLUCINATION", "AGENT_LOOP", "AGENT_MALFORMED",
    "BUDGET_EXCEEDED", "SCHEMA_DRIFT", "SUPERSEDED_VERSION",
}
SCHEMA_APPROVAL_STATES = {"draft", "in_review", "changes_requested", "approved", "delivered", "blocked"}
SCHEMA_AGENT_STATUSES = {"ok", "retried", "rejected", "overruled", "routed", "abstained", "killed"}


def test_reason_code_matches_audit_schema_enum():
    assert {c.value for c in ReasonCode} == SCHEMA_REASON_CODES


def test_approval_state_matches_audit_schema_enum():
    assert {s.value for s in ApprovalState} == SCHEMA_APPROVAL_STATES


def test_agent_status_matches_audit_schema_enum():
    assert {s.value for s in AgentStatus} == SCHEMA_AGENT_STATUSES


def _make_raw() -> RawRecord:
    return RawRecord(
        id="REC-001", owner="a.shah", deadline="2026-07-15", category="ONBOARDING",
        notes="Standard new-client setup.", version=1, amount=4800.0,
        source_format=SourceFormat.FEED, source_hash="abc123",
    )


def test_pipeline_state_updates_are_immutable_copies():
    raw = _make_raw()
    state = PipelineState(record_id="REC-001", raw=raw)
    normalized = NormalizedRecord(
        id="REC-001", owner="a.shah", deadline=date(2026, 7, 15), category="ONBOARDING",
        notes="Standard new-client setup.", version=1, amount=4800.0,
        source_format=SourceFormat.FEED, source_hash="abc123",
    )
    trace = AgentTrace(agent="orchestrator", status=AgentStatus.OK, latency_ms=1.0)
    updated = state.model_copy(update={
        "normalized": normalized,
        "audit_trail": state.audit_trail + [trace],
        "step_count": state.step_count + 1,
    })
    assert state.normalized is None
    assert state.step_count == 0
    assert updated.normalized == normalized
    assert updated.audit_trail == [trace]
    assert updated.step_count == 1


def test_exception_record_requires_reason_class():
    exc = ExceptionRecord(
        record_id="REC-011", reason_code=ReasonCode.STALE, reason_class=ReasonClass.A,
        detail="Deadline 2026-06-01 is before today 2026-06-26", raw_snapshot={"id": "REC-011"},
    )
    assert exc.reason_class == ReasonClass.A


def test_worker_output_confidence_bounds():
    output = WorkerOutput(
        record_id="REC-001", input_hash="h1", delivered_fields={"summary": "x"},
        confidence_score=0.9, model_used="claude-haiku-4-5-20251001", prompt_version="worker_v1",
        tokens_in=100, tokens_out=50, cost_usd=0.0001, latency_ms=500.0,
    )
    assert 0.0 <= output.confidence_score <= 1.0


def test_verifier_decision_verdict_enum():
    decision = VerifierDecision(
        record_id="REC-001", verdict=VerifierVerdict.PASS, worker_output_hash="h2",
        reasoning="Consistent with source.", prompt_version="verifier_v1",
    )
    assert decision.verdict == VerifierVerdict.PASS


def test_approval_entry_has_actor_role():
    entry = ApprovalEntry(state=ApprovalState.APPROVED, actor="operator.1", actor_role="operator", ts="2026-07-02T10:00:00Z")
    assert entry.actor_role == "operator"


def test_processing_ledger_entry_fields():
    entry = ProcessingLedgerEntry(
        source_hash="abc123", pipeline_version="v1", record_id="REC-001",
        completed_stage="delivered", ts="2026-07-02T10:00:00Z",
    )
    assert entry.completed_stage == "delivered"
