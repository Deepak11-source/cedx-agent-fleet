from __future__ import annotations
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from agents.delivery import assemble_package, compute_package_hash
from core.approval import add_approval_entry, auto_approve_and_deliver, can_deliver, deliver
from core.audit_store import append_event, build_audit_json, write_audit_json, write_exception_queue
from core.config import AMENDMENT_ROLE, AMENDMENT_THRESHOLD, get_case_id, get_pipeline_now, get_seed_dir
from core.graph import run_pipeline
from core.models import ApprovalState, PipelineState
from core.state_store import record_processed

OUT_DIR = Path("out")
PACKAGE_DIR = OUT_DIR / "package"
RECORDS_STORE_PATH = OUT_DIR / ".state" / "records.json"

AGENTS_ROSTER = [
    {"name": "orchestrator", "role": "orchestrator", "models": [], "can_call": ["worker"]},
    {"name": "worker", "role": "worker",
     "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"], "can_call": ["verifier"]},
    {"name": "verifier", "role": "verifier", "models": ["claude-sonnet-4-6"], "can_call": []},
]


def _load_records_store() -> dict[str, PipelineState]:
    if not RECORDS_STORE_PATH.exists():
        return {}
    raw = json.loads(RECORDS_STORE_PATH.read_text(encoding="utf-8"))
    return {rid: PipelineState.model_validate(data) for rid, data in raw.items()}


def _save_records_store(records: dict[str, PipelineState]) -> None:
    RECORDS_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORDS_STORE_PATH.write_text(
        json.dumps({rid: s.model_dump(mode="json") for rid, s in records.items()}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resolve_seed_and_now(args: argparse.Namespace) -> tuple[Path, date]:
    seed_dir = Path(args.seed_dir or get_seed_dir())
    pipeline_now = date.fromisoformat(args.pipeline_now or get_pipeline_now())
    return seed_dir, pipeline_now


def cmd_run(args: argparse.Namespace) -> int:
    print(f"AMENDMENT: role={AMENDMENT_ROLE} threshold={AMENDMENT_THRESHOLD}")
    seed_dir, pipeline_now = _resolve_seed_and_now(args)

    append_event("system", "pipeline_start", None)
    states = run_pipeline(seed_dir, pipeline_now)
    for state in states:
        agent = state.audit_trail[-1].agent if state.audit_trail else "system"
        append_event(agent, "record_processed", state.record_id, {"status": state.status})
        record_processed(state.raw.source_hash, "v1", state.record_id, state.status)

    _save_records_store({s.record_id: s for s in states})
    n_held = sum(1 for s in states if s.status == "held_for_approval")
    n_exception = sum(1 for s in states if s.status == "exception")
    n_superseded = sum(1 for s in states if s.status == "superseded")
    print(f"Processed {len(states)} records: {n_held} awaiting approval, "
          f"{n_exception} exceptions, {n_superseded} superseded.")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    records = _load_records_store()
    if args.record_id not in records:
        print(f"Unknown record: {args.record_id}", file=sys.stderr)
        return 1
    state = add_approval_entry(records[args.record_id], ApprovalState.APPROVED, args.actor, args.role, args.reason)
    records[args.record_id] = state
    _save_records_store(records)
    append_event(args.actor, "approved", args.record_id, {"role": args.role})
    print(f"{args.record_id}: approved by {args.actor} ({args.role})")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    records = _load_records_store()
    if args.record_id not in records:
        print(f"Unknown record: {args.record_id}", file=sys.stderr)
        return 1
    state = add_approval_entry(records[args.record_id], ApprovalState.CHANGES_REQUESTED, args.actor, args.role, args.reason)
    records[args.record_id] = state
    _save_records_store(records)
    append_event(args.actor, "changes_requested", args.record_id, {"reason": args.reason})
    print(f"{args.record_id}: changes requested by {args.actor}")
    return 0


def cmd_deliver(args: argparse.Namespace) -> int:
    records = _load_records_store()
    if args.record_id not in records:
        print(f"Unknown record: {args.record_id}", file=sys.stderr)
        return 1
    state = records[args.record_id]
    ok, reason = can_deliver(state)
    if not ok:
        append_event("system", "delivery_refused", args.record_id, {"reason": reason})
        print(f"{args.record_id}: delivery refused ({reason})", file=sys.stderr)
        return 1
    delivered = deliver(state, args.actor)
    assemble_package(delivered, PACKAGE_DIR, get_case_id())
    records[args.record_id] = delivered
    _save_records_store(records)
    append_event(args.actor, "delivered", args.record_id, {})
    print(f"{args.record_id}: delivered")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    print(f"AMENDMENT: role={AMENDMENT_ROLE} threshold={AMENDMENT_THRESHOLD}")
    seed_dir, pipeline_now = _resolve_seed_and_now(args)

    append_event("system", "pipeline_start", None)
    states = run_pipeline(seed_dir, pipeline_now)

    final_states: list[PipelineState] = []
    for state in states:
        agent = state.audit_trail[-1].agent if state.audit_trail else "system"
        append_event(agent, "record_processed", state.record_id, {"status": state.status})
        if state.status == "held_for_approval":
            state = auto_approve_and_deliver(state)
            append_event("demo-auto-operator", "delivered", state.record_id, {})
        final_states.append(state)
        record_processed(state.raw.source_hash, "v1", state.record_id, state.status)

    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    for state in final_states:
        if state.status == "delivered":
            assemble_package(state, PACKAGE_DIR, get_case_id())
    package_hash = (
        compute_package_hash(PACKAGE_DIR)
        if any(s.status == "delivered" for s in final_states)
        else "sha256:" + "0" * 64
    )

    audit = build_audit_json(
        final_states, AGENTS_ROSTER, get_case_id(), str(seed_dir), pipeline_now.isoformat(), package_hash,
    )
    write_audit_json(audit, OUT_DIR / "audit.json")
    write_exception_queue(final_states, OUT_DIR / "exception_queue.json")
    _save_records_store({s.record_id: s for s in final_states})

    n_delivered = sum(1 for s in final_states if s.status == "delivered")
    n_exception = sum(1 for s in final_states if s.status == "exception")
    n_superseded = sum(1 for s in final_states if s.status == "superseded")
    print(f"Wrote out/audit.json, out/exception_queue.json, out/package/ -- "
          f"{n_delivered} delivered, {n_exception} exceptions, {n_superseded} superseded.")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    audit = json.loads((OUT_DIR / "audit.json").read_text(encoding="utf-8"))
    record = next((r for r in audit["records"] if r["id"] == args.record_id), None)
    if record is None:
        print(f"No such record in audit.json: {args.record_id}", file=sys.stderr)
        return 1
    print(f"Record {record['id']} -- status={record['status']} reason_code={record['reason_code']}")
    for span in record["agent_trace"]:
        print(f"  [{span['agent']}] model={span.get('model')} status={span['status']} "
              f"verdict={span.get('verdict')} cost=${span.get('cost_usd') or 0:.6f} "
              f"latency={span.get('latency_ms')}ms retries={span.get('retries')}")
    for entry in record["approval_trail"]:
        print(f"  [approval] {entry['state']} by {entry['actor']} at {entry['ts']}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    audit = json.loads((OUT_DIR / "audit.json").read_text(encoding="utf-8"))
    record = next((r for r in audit["records"] if r["id"] == args.record_id), None)
    if record is None:
        print(f"No such record in audit.json: {args.record_id}", file=sys.stderr)
        return 1
    print(f"Lineage for {record['id']}:")
    print(f"  source_format={record['source_format']} source_version_hash={record['source_version_hash']}")
    for span in record["agent_trace"]:
        print(f"  -> {span['agent']} (status={span['status']}, transcript_hash={span.get('transcript_hash')})")
    print(f"  final status: {record['status']} (reason_code={record['reason_code']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cedx")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run the pipeline, hold records for approval")
    p_run.add_argument("--seed-dir", dest="seed_dir", default=None)
    p_run.add_argument("--pipeline-now", dest="pipeline_now", default=None)
    p_run.set_defaults(func=cmd_run)

    p_demo = sub.add_parser("demo", help="run + auto-approve + deliver + write audit bundle")
    p_demo.add_argument("--seed-dir", dest="seed_dir", default=None)
    p_demo.add_argument("--pipeline-now", dest="pipeline_now", default=None)
    p_demo.set_defaults(func=cmd_demo)

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("record_id")
    p_approve.add_argument("--actor", required=True)
    p_approve.add_argument("--role", required=True)
    p_approve.add_argument("--reason", default=None)
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject")
    p_reject.add_argument("record_id")
    p_reject.add_argument("--actor", required=True)
    p_reject.add_argument("--role", required=True)
    p_reject.add_argument("--reason", default=None)
    p_reject.set_defaults(func=cmd_reject)

    p_deliver = sub.add_parser("deliver")
    p_deliver.add_argument("record_id")
    p_deliver.add_argument("--actor", required=True)
    p_deliver.set_defaults(func=cmd_deliver)

    p_trace = sub.add_parser("trace")
    p_trace.add_argument("record_id")
    p_trace.set_defaults(func=cmd_trace)

    p_replay = sub.add_parser("replay")
    p_replay.add_argument("record_id")
    p_replay.set_defaults(func=cmd_replay)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
