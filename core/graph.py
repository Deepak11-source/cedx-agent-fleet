from __future__ import annotations
from datetime import date
from pathlib import Path

from agents.orchestrator import dedupe_versions, orchestrate
from agents.verifier import verify
from agents.worker import worker_draft
from core.config import get_max_steps_per_record
from core.models import (
    AgentStatus, AgentTrace, ExceptionRecord, PipelineState, RawRecord,
    ReasonClass, ReasonCode,
)
from intake import load_all_records


def _kill_for_loop(state: PipelineState) -> PipelineState:
    max_steps = get_max_steps_per_record()
    trace = AgentTrace(agent="orchestrator", status=AgentStatus.KILLED)
    return state.model_copy(update={
        "exception": ExceptionRecord(
            record_id=state.record_id, reason_code=ReasonCode.AGENT_LOOP, reason_class=ReasonClass.A,
            detail=f"Record exceeded MAX_STEPS_PER_RECORD ({max_steps}) steps",
            raw_snapshot=state.raw.model_dump(mode="json"),
        ),
        "audit_trail": state.audit_trail + [trace],
        "status": "exception",
    })


def process_record(raw: RawRecord, batch_amounts: list[float], pipeline_now: date) -> PipelineState:
    """Run one record through orchestrator -> worker -> verifier, honoring
    the per-record step ceiling (AGENT_LOOP) after every stage."""
    state = PipelineState(record_id=raw.id, raw=raw)
    max_steps = get_max_steps_per_record()

    state = orchestrate(state, batch_amounts, pipeline_now)
    if state.step_count > max_steps:
        return _kill_for_loop(state)
    if state.exception is not None:
        return state

    state = worker_draft(state)
    if state.step_count > max_steps:
        return _kill_for_loop(state)
    if state.exception is not None:
        return state

    state = verify(state)
    if state.step_count > max_steps:
        return _kill_for_loop(state)
    if state.exception is not None:
        return state

    return state.model_copy(update={"status": "held_for_approval"})


def run_pipeline(seed_dir: Path, pipeline_now: date) -> list[PipelineState]:
    """Load every seed record, dedupe superseded versions, and run the
    remaining records through the full agent pipeline."""
    raw_records = load_all_records(seed_dir)
    kept, superseded_exceptions = dedupe_versions(raw_records)
    batch_amounts = [r.amount for r in kept if r.amount is not None]

    states: list[PipelineState] = []
    for exc in superseded_exceptions:
        raw = RawRecord.model_validate(exc.raw_snapshot)
        states.append(PipelineState(record_id=raw.id, raw=raw, exception=exc, status="superseded"))

    for raw in kept:
        states.append(process_record(raw, batch_amounts, pipeline_now))

    return states
