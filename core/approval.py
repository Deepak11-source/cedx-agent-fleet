from __future__ import annotations

from core.config import AMENDMENT_ROLE, AMENDMENT_THRESHOLD
from core.models import ApprovalEntry, ApprovalState, PipelineState
from core.timeutil import now_iso


def add_approval_entry(
    state: PipelineState, new_state: ApprovalState, actor: str, actor_role: str,
    reason: str | None = None,
) -> PipelineState:
    entry = ApprovalEntry(state=new_state, actor=actor, actor_role=actor_role, ts=now_iso(), reason=reason)
    return state.model_copy(update={
        "approval_trail": state.approval_trail + [entry],
        "approval_status": new_state,
    })


def can_deliver(state: PipelineState) -> tuple[bool, str | None]:
    """The single shared delivery gate -- every caller (CLI, probes, any
    future API) must go through this function. Not just a CLI warning:
    this is the actual enforcement point."""
    approvals = state.approval_trail
    has_standard = any(a.state == ApprovalState.APPROVED for a in approvals)
    if not has_standard:
        return False, "no_standard_approval"

    amount = state.normalized.amount if state.normalized else None
    if amount is not None and amount >= AMENDMENT_THRESHOLD:
        has_amendment = any(
            a.state == ApprovalState.APPROVED and a.actor_role == AMENDMENT_ROLE
            for a in approvals
        )
        if not has_amendment:
            return False, f"amendment_approval_required:{AMENDMENT_ROLE}"

    return True, None


def deliver(state: PipelineState, actor: str) -> PipelineState:
    ok, reason = can_deliver(state)
    if not ok:
        raise PermissionError(f"delivery refused for {state.record_id}: {reason}")
    delivered_state = add_approval_entry(state, ApprovalState.DELIVERED, actor, "system")
    return delivered_state.model_copy(update={"status": "delivered", "delivered": True})


def auto_approve_and_deliver(state: PipelineState) -> PipelineState:
    """Drive a held_for_approval record to delivered using a distinguishable
    'demo-auto-operator' actor, for the one-command `make demo` path. Goes
    through the exact same can_deliver() gate a human CLI approval would."""
    state = add_approval_entry(state, ApprovalState.APPROVED, "demo-auto-operator", "operator")
    if state.normalized is not None and state.normalized.amount >= AMENDMENT_THRESHOLD:
        state = add_approval_entry(state, ApprovalState.APPROVED, "demo-legal-counsel", AMENDMENT_ROLE)
    return deliver(state, "demo-auto-operator")
