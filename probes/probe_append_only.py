#!/usr/bin/env python3
"""probe_append_only.py — verify the audit event log is append-only.

Exit 0 = append-only enforced (mutation attempt refused).
Exit 1 = append-only broken (mutation succeeded silently).

Checks:
  A) Writing valid sequential events succeeds and passes verify_chain().
  B) Mutating an event's payload and calling verify_chain() returns False.
  C) Calling append_event() after chain is broken raises RuntimeError.
  D) Deleting an event and calling verify_chain() returns False.
"""
from __future__ import annotations
import copy
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.audit_store import append_event, load_events, verify_chain


def check_a_valid_chain() -> bool:
    """append_event() builds a valid chain that verify_chain() confirms."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state" / "events.json"
        append_event("system", "pipeline_start", None, path=path)
        append_event("orchestrator", "record_processed", "REC-001", {"status": "delivered"}, path=path)
        append_event("worker", "draft_created", "REC-001", {}, path=path)

        events = load_events(path=path)
        if len(events) != 3:
            print(f"FAIL check-A: expected 3 events, got {len(events)}")
            return False
        if not verify_chain(events):
            print("FAIL check-A: verify_chain returned False on a freshly built chain")
            return False
        # Verify seq is strictly 0, 1, 2
        seqs = [e["seq"] for e in events]
        if seqs != [0, 1, 2]:
            print(f"FAIL check-A: seq values wrong: {seqs}")
            return False

    print("PASS check-A: valid chain builds and verifies correctly")
    return True


def check_b_mutation_detected() -> bool:
    """Mutating an event payload breaks verify_chain()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state" / "events.json"
        append_event("system", "pipeline_start", None, path=path)
        append_event("orchestrator", "record_processed", "REC-001", {"status": "delivered"}, path=path)

        events = load_events(path=path)
        # Mutate: change the action field of event 0
        tampered = copy.deepcopy(events)
        tampered[0]["action"] = "TAMPERED_ACTION"
        # Write tampered events directly (bypassing append_event)
        path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

        tampered_loaded = load_events(path=path)
        if verify_chain(tampered_loaded):
            print("FAIL check-B: verify_chain returned True on tampered chain")
            return False

    print("PASS check-B: payload mutation detected by verify_chain()")
    return True


def check_c_append_after_broken_chain_raises() -> bool:
    """append_event() refuses to append when chain is broken."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state" / "events.json"
        append_event("system", "pipeline_start", None, path=path)

        events = load_events(path=path)
        tampered = copy.deepcopy(events)
        tampered[0]["payload"] = {"injected": "data"}
        path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

        try:
            append_event("attacker", "malicious_action", "REC-X", path=path)
            print("FAIL check-C: append_event succeeded on broken chain (should have raised)")
            return False
        except RuntimeError as e:
            if "tamper" not in str(e).lower() and "broken" not in str(e).lower():
                print(f"FAIL check-C: raised RuntimeError but wrong message: {e}")
                return False

    print("PASS check-C: append_event raises RuntimeError on broken chain")
    return True


def check_d_deletion_detected() -> bool:
    """Deleting an event from the middle breaks verify_chain()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state" / "events.json"
        append_event("system", "pipeline_start", None, path=path)
        append_event("orchestrator", "record_processed", "REC-001", {}, path=path)
        append_event("worker", "draft_created", "REC-001", {}, path=path)

        events = load_events(path=path)
        # Delete middle event
        deleted = [events[0], events[2]]  # skip index 1
        path.write_text(json.dumps(deleted, indent=2), encoding="utf-8")

        loaded = load_events(path=path)
        if verify_chain(loaded):
            print("FAIL check-D: verify_chain returned True after event deletion")
            return False

    print("PASS check-D: event deletion detected by verify_chain()")
    return True


def main() -> int:
    print("probe-append-only: verifying audit log append-only enforcement")
    checks = [check_a_valid_chain, check_b_mutation_detected,
              check_c_append_after_broken_chain_raises, check_d_deletion_detected]
    results = [fn() for fn in checks]
    if all(results):
        print("probe-append-only: PASS")
        return 0
    else:
        failed = sum(1 for r in results if not r)
        print(f"probe-append-only: FAIL ({failed}/{len(checks)} checks failed)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
