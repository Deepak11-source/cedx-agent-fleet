from datetime import date

import pytest

from core.approval import add_approval_entry, auto_approve_and_deliver, can_deliver, deliver
from core.models import (
    ApprovalState, NormalizedRecord, PipelineState, RawRecord, SourceFormat,
)


def _state(amount: float) -> PipelineState:
    raw = RawRecord(id="REC-X", owner="a.shah", deadline="2026-07-15", category="ONBOARDING",
                     notes="x", version=1, amount=amount, source_format=SourceFormat.FEED, source_hash="h")
    normalized = NormalizedRecord(id="REC-X", owner="a.shah", deadline=date(2026, 7, 15),
                                   category="ONBOARDING", notes="x", version=1, amount=amount,
                                   source_format=SourceFormat.FEED, source_hash="h")
    return PipelineState(record_id="REC-X", raw=raw, normalized=normalized, status="held_for_approval")


def test_can_deliver_false_with_no_approvals():
    ok, reason = can_deliver(_state(4800.0))
    assert not ok
    assert reason == "no_standard_approval"


def test_can_deliver_true_with_standard_approval_below_threshold():
    state = add_approval_entry(_state(4800.0), ApprovalState.APPROVED, "op.1", "operator")
    ok, reason = can_deliver(state)
    assert ok and reason is None


def test_can_deliver_false_above_threshold_without_legal_counsel():
    state = add_approval_entry(_state(32000.0), ApprovalState.APPROVED, "op.1", "operator")
    ok, reason = can_deliver(state)
    assert not ok
    assert reason == "amendment_approval_required:legal_counsel"


def test_can_deliver_true_above_threshold_with_legal_counsel():
    state = add_approval_entry(_state(32000.0), ApprovalState.APPROVED, "op.1", "operator")
    state = add_approval_entry(state, ApprovalState.APPROVED, "counsel.1", "legal_counsel")
    ok, reason = can_deliver(state)
    assert ok and reason is None


def test_deliver_raises_when_not_approved():
    with pytest.raises(PermissionError):
        deliver(_state(4800.0), actor="op.1")


def test_deliver_succeeds_when_approved():
    state = add_approval_entry(_state(4800.0), ApprovalState.APPROVED, "op.1", "operator")
    delivered = deliver(state, actor="op.1")
    assert delivered.status == "delivered"
    assert delivered.approval_trail[-1].state == ApprovalState.DELIVERED


def test_auto_approve_and_deliver_below_threshold_needs_only_one_approval():
    delivered = auto_approve_and_deliver(_state(4800.0))
    assert delivered.status == "delivered"
    states = [e.state for e in delivered.approval_trail]
    assert states == [ApprovalState.APPROVED, ApprovalState.DELIVERED]


def test_auto_approve_and_deliver_above_threshold_adds_legal_counsel():
    delivered = auto_approve_and_deliver(_state(32000.0))
    assert delivered.status == "delivered"
    roles = [e.actor_role for e in delivered.approval_trail]
    assert "operator" in roles
    assert "legal_counsel" in roles
