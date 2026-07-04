from datetime import date
from pathlib import Path

import pytest

import core.audit_store as audit_store_mod
from core.audit_store import (
    append_event, build_audit_json, load_events, verify_chain,
    write_audit_json, write_exception_queue,
)
from core.hashing import sha
from core.models import (
    AgentStatus, AgentTrace, ApprovalEntry, ApprovalState, ExceptionRecord,
    NormalizedRecord, PipelineState, RawRecord, ReasonClass, ReasonCode,
    SourceFormat, WorkerOutput,
)


@pytest.fixture
def events_path(tmp_path, monkeypatch):
    path = tmp_path / "events.json"
    monkeypatch.setattr(audit_store_mod, "EVENTS_PATH", path)
    return path


def test_append_event_builds_hash_chain(events_path):
    e0 = append_event("system", "pipeline_start", None, path=events_path)
    e1 = append_event("orchestrator", "record_ingested", "REC-001", path=events_path)
    assert e0["seq"] == 0 and e1["seq"] == 1
    assert e1["prev_hash"] == e0["event_hash"]
    events = load_events(events_path)
    assert verify_chain(events)


def test_verify_chain_detects_tampering(events_path):
    append_event("system", "pipeline_start", None, path=events_path)
    append_event("orchestrator", "record_ingested", "REC-001", path=events_path)
    events = load_events(events_path)
    events[0]["actor"] = "tampered"
    assert not verify_chain(events)


def test_append_event_refuses_after_tampering(events_path):
    append_event("system", "pipeline_start", None, path=events_path)
    raw_events = load_events(events_path)
    raw_events[0]["actor"] = "tampered"
    events_path.write_text(
        __import__("json").dumps([e for e in raw_events], indent=2), encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        append_event("system", "second_event", None, path=events_path)


def _delivered_state() -> PipelineState:
    raw = RawRecord(id="REC-001", owner="a.shah", deadline="2026-07-15", category="ONBOARDING",
                     notes="x", version=1, amount=4800.0, source_format=SourceFormat.FEED, source_hash="h1")
    normalized = NormalizedRecord(id="REC-001", owner="a.shah", deadline=date(2026, 7, 15),
                                   category="ONBOARDING", notes="x", version=1, amount=4800.0,
                                   source_format=SourceFormat.FEED, source_hash="h1")
    delivered_fields = {"summary": "x", "formatted_amount": "$4,800.00"}
    worker_output = WorkerOutput(
        record_id="REC-001", input_hash="ih1", delivered_fields=delivered_fields,
        confidence_score=0.9, model_used="claude-haiku-4-5-20251001", prompt_version="worker_v1",
        tokens_in=300, tokens_out=100, cost_usd=0.0005, latency_ms=500.0, transcript_hash="sha256:abc",
    )
    trace_o = AgentTrace(agent="orchestrator", status=AgentStatus.OK, latency_ms=10.0)
    trace_w = AgentTrace(agent="worker", model="claude-haiku-4-5-20251001", status=AgentStatus.OK,
                          cost_usd=0.0005, latency_ms=500.0)
    trace_v = AgentTrace(agent="verifier", model="claude-sonnet-4-6", status=AgentStatus.OK,
                          verdict="pass", cost_usd=0.001, latency_ms=800.0)
    approval = ApprovalEntry(state=ApprovalState.APPROVED, actor="demo-auto-operator",
                              actor_role="operator", ts="2026-07-02T10:00:00Z")
    return PipelineState(
        record_id="REC-001", raw=raw, normalized=normalized, worker_output=worker_output,
        audit_trail=[trace_o, trace_w, trace_v], approval_trail=[approval],
        total_cost_usd=0.0015, status="delivered",
    )


def _exception_state() -> PipelineState:
    raw = RawRecord(id="REC-011", owner="k.banerjee", deadline="2026-06-01", category="REVIEW",
                     notes="x", version=1, amount=4900.0, source_format=SourceFormat.FEED, source_hash="h2")
    exc = ExceptionRecord(record_id="REC-011", reason_code=ReasonCode.STALE, reason_class=ReasonClass.A,
                           detail="stale", raw_snapshot={"id": "REC-011"})
    trace = AgentTrace(agent="orchestrator", status=AgentStatus.ROUTED)
    return PipelineState(record_id="REC-011", raw=raw, exception=exc, audit_trail=[trace], status="exception")


AGENTS_ROSTER = [
    {"name": "orchestrator", "role": "orchestrator", "models": [], "can_call": ["worker"]},
    {"name": "worker", "role": "worker", "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"], "can_call": ["verifier"]},
    {"name": "verifier", "role": "verifier", "models": ["claude-sonnet-4-6"], "can_call": []},
]


def test_build_audit_json_has_required_top_level_keys(events_path):
    states = [_delivered_state(), _exception_state()]
    audit = build_audit_json(states, AGENTS_ROSTER, "CEDX-DCB8F2", "seed", "2026-06-26", "sha256:" + "0" * 64)
    for key in ["case_id", "pipeline_version", "generated_at", "seed_dir", "amendment",
                "agents", "cost", "output_package_hash", "records", "events"]:
        assert key in audit
    assert audit["amendment"] == {"role": "legal_counsel", "threshold": 32000}
    assert audit["cost"]["records"] == 2


def test_build_audit_json_delivered_record_has_hashes():
    states = [_delivered_state()]
    audit = build_audit_json(states, AGENTS_ROSTER, "CEDX-DCB8F2", "seed", "2026-06-26", "sha256:" + "0" * 64)
    rec = audit["records"][0]
    assert rec["status"] == "delivered"
    assert rec["delivered_fields_hash"] == sha(rec["delivered_fields"])
    assert rec["transcript_hash"] == "sha256:abc"


def test_build_audit_json_exception_record_has_no_delivered_fields():
    states = [_exception_state()]
    audit = build_audit_json(states, AGENTS_ROSTER, "CEDX-DCB8F2", "seed", "2026-06-26", "sha256:" + "0" * 64)
    rec = audit["records"][0]
    assert rec["status"] == "exception"
    assert rec["reason_code"] == "STALE"
    assert rec["delivered_fields"] is None


def test_build_audit_json_reports_schema_drift_on_a_delivered_record():
    state = _delivered_state()
    state = state.model_copy(update={
        "normalized": state.normalized.model_copy(update={"schema_drifts": ["value→amount"]}),
    })
    audit = build_audit_json([state], AGENTS_ROSTER, "CEDX-DCB8F2", "seed", "2026-06-26", "sha256:" + "0" * 64)
    rec = audit["records"][0]
    assert rec["status"] == "delivered"
    assert rec["reason_code"] == "SCHEMA_DRIFT"
    assert rec["reason_class"] == "B"
    # Class B is non-blocking -- delivered_fields must still be populated.
    assert rec["delivered_fields"] is not None


def test_write_audit_json_and_exception_queue(tmp_path):
    audit_path = tmp_path / "audit.json"
    exc_path = tmp_path / "exception_queue.json"
    audit = build_audit_json([_delivered_state()], AGENTS_ROSTER, "CEDX-DCB8F2", "seed", "2026-06-26", "sha256:" + "0" * 64)
    write_audit_json(audit, audit_path)
    write_exception_queue([_exception_state()], exc_path)
    assert audit_path.exists()
    assert exc_path.exists()
    import json
    written = json.loads(audit_path.read_text(encoding="utf-8"))
    assert written["case_id"] == "CEDX-DCB8F2"
    exceptions = json.loads(exc_path.read_text(encoding="utf-8"))
    assert exceptions[0]["reason_code"] == "STALE"
