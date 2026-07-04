#!/usr/bin/env python3
"""probe_approval.py — verify delivery gate refuses unapproved records.

Exit 0 = gate works correctly (all checks pass).
Exit 1 = gate is broken (delivery allowed without proper approval).

Checks:
  A) Delivering a record with NO approval is refused.
  B) Delivering an amendment-threshold record without legal_counsel is refused
     even when standard operator approval exists.
  C) delivery_refused event is logged to the audit trail on refusal.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from _fixtures import make_state

from core.approval import add_approval_entry, can_deliver, deliver
from core.audit_store import append_event, load_events
from core.models import ApprovalState


def check_a_no_approval_refused() -> bool:
    state = make_state(amount=5000.0)
    ok, reason = can_deliver(state)
    if ok:
        print("FAIL check-A: can_deliver() returned True with zero approvals")
        return False
    if reason != "no_standard_approval":
        print(f"FAIL check-A: expected reason 'no_standard_approval', got {reason!r}")
        return False
    try:
        deliver(state, actor="probe-actor")
        print("FAIL check-A: deliver() did not raise PermissionError")
        return False
    except PermissionError:
        pass
    print("PASS check-A: delivery refused with no approval")
    return True


def check_b_amendment_gate() -> bool:
    state = make_state(amount=35000.0)
    state = add_approval_entry(state, ApprovalState.APPROVED, "probe-operator", "operator")

    ok, reason = can_deliver(state)
    if ok:
        print("FAIL check-B: can_deliver() returned True without legal_counsel approval")
        return False
    if "amendment_approval_required" not in (reason or ""):
        print(f"FAIL check-B: expected 'amendment_approval_required' in reason, got {reason!r}")
        return False

    state = add_approval_entry(state, ApprovalState.APPROVED, "probe-counsel", "legal_counsel")
    ok2, reason2 = can_deliver(state)
    if not ok2:
        print(f"FAIL check-B: refused after legal_counsel approval: {reason2}")
        return False

    print("PASS check-B: amendment gate enforced — refused without legal_counsel, passed with it")
    return True


def check_c_delivery_refused_logged() -> bool:
    with tempfile.TemporaryDirectory() as tmpdir:
        events_path = Path(tmpdir) / "state" / "events.json"
        state = make_state(amount=5000.0)
        ok, reason = can_deliver(state)
        if ok:
            print("FAIL check-C: expected refusal but can_deliver returned True")
            return False
        append_event("system", "delivery_refused", state.record_id, {"reason": reason},
                     path=events_path)
        events = load_events(path=events_path)
        refusals = [e for e in events if e.get("action") == "delivery_refused"]
        if not refusals or refusals[0].get("record_id") != state.record_id:
            print("FAIL check-C: delivery_refused event missing or has wrong record_id")
            return False
    print("PASS check-C: delivery_refused event correctly logged")
    return True


def main() -> int:
    print("probe-approval: verifying delivery gate enforcement")
    checks = [check_a_no_approval_refused, check_b_amendment_gate, check_c_delivery_refused_logged]
    results = [fn() for fn in checks]
    if all(results):
        print("probe-approval: PASS")
        return 0
    print(f"probe-approval: FAIL ({sum(1 for r in results if not r)}/{len(checks)} checks failed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
