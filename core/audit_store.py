from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.config import AMENDMENT_ROLE, AMENDMENT_THRESHOLD
from core.hashing import sha
from core.models import AgentTrace, ApprovalEntry, PipelineState
from core.timeutil import now_iso

EVENTS_PATH = Path("out/.state/events.json")


def _atomic_write(path: Path, data: Any) -> None:
    """Write via a temp file + os.replace -- atomic AND overwrites an
    existing destination on both POSIX and Windows (shutil.move does not
    reliably overwrite on Windows; os.replace is the documented-atomic,
    cross-platform-overwriting primitive)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def load_events(path: Path | None = None) -> list[dict]:
    path = path if path is not None else EVENTS_PATH
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def verify_chain(events: list[dict]) -> bool:
    prev_hash = None
    for i, event in enumerate(events):
        if event.get("seq") != i:
            return False
        if event.get("prev_hash") != prev_hash:
            return False
        payload_for_hash = {k: v for k, v in event.items() if k != "event_hash"}
        if sha(payload_for_hash) != event.get("event_hash"):
            return False
        prev_hash = event.get("event_hash")
    return True


def append_event(
    actor: str, action: str, record_id: str | None, payload: dict | None = None,
    path: Path | None = None,
) -> dict:
    path = path if path is not None else EVENTS_PATH
    events = load_events(path)
    if events and not verify_chain(events):
        raise RuntimeError("audit event log hash chain is broken -- refusing to append (tamper detected)")
    prev_hash = events[-1]["event_hash"] if events else None
    event = {
        "seq": len(events),
        "ts": now_iso(),
        "actor": actor,
        "action": action,
        "record_id": record_id,
        "payload": payload or {},
        "prev_hash": prev_hash,
    }
    event["event_hash"] = sha(event)
    events.append(event)
    _atomic_write(path, events)
    return event


def _trace_to_dict(t: AgentTrace) -> dict:
    return {
        "agent": t.agent, "model": t.model, "prompt_version": t.prompt_version,
        "tokens_in": t.tokens_in, "tokens_out": t.tokens_out, "cost_usd": t.cost_usd,
        "latency_ms": t.latency_ms, "retries": t.retries, "transcript_hash": t.transcript_hash,
        "status": t.status.value if hasattr(t.status, "value") else t.status,
        "verdict": (t.verdict.value if hasattr(t.verdict, "value") else t.verdict) if t.verdict else None,
    }


def _approval_to_dict(a: ApprovalEntry) -> dict:
    return {
        "state": a.state.value, "actor": a.actor, "actor_role": a.actor_role,
        "ts": a.ts, "reason": a.reason,
    }


def _record_to_audit_dict(state: PipelineState) -> dict:
    version = state.normalized.version if state.normalized else state.raw.version
    reason_code = state.exception.reason_code.value if state.exception else None
    reason_class = state.exception.reason_class.value if state.exception else None
    if reason_code is None and state.normalized is not None and state.normalized.schema_drifts:
        # SCHEMA_DRIFT is Class B (auto-resolved, non-blocking) -- the record
        # still proceeds to delivery, but the drift must still be visible as
        # a reason_code in the audit bundle (verify_audit.py requires it).
        reason_code = "SCHEMA_DRIFT"
        reason_class = "B"
    record: dict[str, Any] = {
        "id": state.record_id,
        "version": version,
        "source_format": state.raw.source_format.value,
        "source_version_hash": state.raw.source_hash,
        "status": state.status,
        "reason_code": reason_code,
        "reason_class": reason_class,
        "transcript_hash": None,
        "delivered_fields": None,
        "delivered_fields_hash": None,
        "agent_trace": [_trace_to_dict(t) for t in state.audit_trail],
        "approval_trail": [_approval_to_dict(a) for a in state.approval_trail],
    }
    if state.status == "delivered" and state.worker_output is not None:
        record["delivered_fields"] = state.worker_output.delivered_fields
        record["delivered_fields_hash"] = sha(state.worker_output.delivered_fields)
        record["transcript_hash"] = state.worker_output.transcript_hash
    return record


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def build_audit_json(
    states: list[PipelineState], agents_roster: list[dict], case_id: str,
    seed_dir: str, pipeline_now: str, output_package_hash: str,
) -> dict:
    records = [_record_to_audit_dict(s) for s in states]
    total_cost = sum(s.total_cost_usd for s in states)
    n_records = len(states)
    latencies = [t.latency_ms for s in states for t in s.audit_trail if t.latency_ms is not None]
    avg = total_cost / n_records if n_records else 0.0
    cost = {
        "total_usd": round(total_cost, 6),
        "avg_usd_per_record": round(avg, 6),
        "p95_latency_ms": round(_percentile(latencies, 95), 2),
        "records": n_records,
        "projected_usd_per_10k": round(avg * 10_000, 2),
    }
    return {
        "case_id": case_id,
        "pipeline_version": "v1",
        "generated_at": now_iso(),
        "seed_dir": seed_dir,
        "pipeline_now": pipeline_now,
        "amendment": {"role": AMENDMENT_ROLE, "threshold": AMENDMENT_THRESHOLD},
        "agents": agents_roster,
        "cost": cost,
        "output_package_hash": output_package_hash,
        "records": records,
        "events": load_events(),
    }


def write_audit_json(audit: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")


def write_exception_queue(states: list[PipelineState], path: Path) -> None:
    exceptions = [
        {
            "record_id": s.exception.record_id,
            "reason_code": s.exception.reason_code.value,
            "reason_class": s.exception.reason_class.value,
            "detail": s.exception.detail,
        }
        for s in states if s.exception is not None
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(exceptions, indent=2, sort_keys=True), encoding="utf-8")
