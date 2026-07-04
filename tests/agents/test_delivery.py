import json
from datetime import date

import pytest

from agents.delivery import assemble_package, compute_package_hash
from core.models import (
    AgentStatus, AgentTrace, NormalizedRecord, PipelineState, RawRecord,
    SourceFormat, WorkerOutput,
)


def _delivered_state(record_id="REC-001", amount=4800.0) -> PipelineState:
    raw = RawRecord(id=record_id, owner="a.shah", deadline="2026-07-15", category="ONBOARDING",
                     notes="x", version=1, amount=amount, source_format=SourceFormat.FEED, source_hash="h")
    normalized = NormalizedRecord(id=record_id, owner="a.shah", deadline=date(2026, 7, 15),
                                   category="ONBOARDING", notes="x", version=1, amount=amount,
                                   source_format=SourceFormat.FEED, source_hash="h")
    worker_output = WorkerOutput(
        record_id=record_id, input_hash="ih", delivered_fields={"summary": "s", "formatted_amount": f"${amount:,.2f}"},
        confidence_score=0.9, model_used="claude-haiku-4-5-20251001", prompt_version="worker_v1",
        tokens_in=1, tokens_out=1, cost_usd=0.0001, latency_ms=1.0,
    )
    trace = AgentTrace(agent="orchestrator", status=AgentStatus.OK)
    return PipelineState(record_id=record_id, raw=raw, normalized=normalized,
                          worker_output=worker_output, audit_trail=[trace], status="delivered")


def test_assemble_package_writes_branded_json(tmp_path):
    path = assemble_package(_delivered_state(), tmp_path, case_id="CEDX-DCB8F2")
    assert path.exists()
    content = json.loads(path.read_text(encoding="utf-8"))
    assert content["record_id"] == "REC-001"
    assert content["case_id"] == "CEDX-DCB8F2"
    assert content["owner"] == "a.shah"
    assert content["summary"] == "s"


def test_assemble_package_rejects_non_delivered_state(tmp_path):
    state = _delivered_state().model_copy(update={"status": "exception"})
    with pytest.raises(AssertionError):
        assemble_package(state, tmp_path, case_id="CEDX-DCB8F2")


def test_compute_package_hash_is_deterministic(tmp_path):
    assemble_package(_delivered_state("REC-001"), tmp_path, case_id="CEDX-DCB8F2")
    assemble_package(_delivered_state("REC-002"), tmp_path, case_id="CEDX-DCB8F2")
    h1 = compute_package_hash(tmp_path)
    h2 = compute_package_hash(tmp_path)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_compute_package_hash_changes_when_content_changes(tmp_path):
    assemble_package(_delivered_state("REC-001", amount=4800.0), tmp_path, case_id="CEDX-DCB8F2")
    h1 = compute_package_hash(tmp_path)
    assemble_package(_delivered_state("REC-001", amount=5000.0), tmp_path, case_id="CEDX-DCB8F2")
    h2 = compute_package_hash(tmp_path)
    assert h1 != h2
