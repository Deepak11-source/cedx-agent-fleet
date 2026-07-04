#!/usr/bin/env python3
"""probe_budget.py — verify BUDGET_EXCEEDED is raised when cost ceiling is hit.

Exit 0 = budget gate works (overspend blocked).
Exit 1 = budget gate broken (overspend allowed silently).

Checks:
  A) would_exceed_budget() returns True when projected cost > ceiling.
  B) would_exceed_budget() returns False when safely under ceiling.
  C) worker_draft() raises BUDGET_EXCEEDED when ceiling is pre-exhausted.
"""
from __future__ import annotations
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from _fixtures import make_state


def _reload_modules():
    """Reload config-dependent modules so env-var changes take effect."""
    import core.config as cfg
    import core.model_router as mr
    import agents.worker as aw
    importlib.reload(cfg)
    importlib.reload(mr)
    importlib.reload(aw)
    return aw


def check_a_exceeds_budget() -> bool:
    os.environ["MAX_COST_PER_RECORD"] = "0.001"
    try:
        _reload_modules()
        from core.model_router import would_exceed_budget
        if not would_exceed_budget(0.0, 0.002):
            print("FAIL check-A: would_exceed_budget returned False when projected > ceiling")
            return False
        print("PASS check-A: would_exceed_budget correctly detected overspend")
        return True
    finally:
        del os.environ["MAX_COST_PER_RECORD"]


def check_b_within_budget() -> bool:
    os.environ["MAX_COST_PER_RECORD"] = "0.05"
    try:
        _reload_modules()
        from core.model_router import would_exceed_budget
        if would_exceed_budget(0.01, 0.001):
            print("FAIL check-B: would_exceed_budget returned True when well under ceiling")
            return False
        print("PASS check-B: would_exceed_budget correctly returned False under ceiling")
        return True
    finally:
        del os.environ["MAX_COST_PER_RECORD"]


def check_c_worker_raises_budget_exceeded() -> bool:
    os.environ["MAX_COST_PER_RECORD"] = "0.0001"
    os.environ["REPLAY_LLM"] = "true"
    try:
        aw = _reload_modules()
        from core.models import ReasonCode
        # total_cost_usd near ceiling; projected estimate will push over
        state = make_state(amount=5000.0, record_id="PROBE-BUDGET-001",
                           status="processing", total_cost_usd=0.00009,
                           source_hash_char="e")
        result = aw.worker_draft(state)
        if result.exception is None:
            print("FAIL check-C: worker_draft did not raise BUDGET_EXCEEDED")
            return False
        if result.exception.reason_code != ReasonCode.BUDGET_EXCEEDED:
            print(f"FAIL check-C: expected BUDGET_EXCEEDED, got {result.exception.reason_code}")
            return False
        if result.status != "exception":
            print("FAIL check-C: state.status is not 'exception'")
            return False
        print("PASS check-C: worker_draft raised BUDGET_EXCEEDED correctly")
        return True
    finally:
        del os.environ["MAX_COST_PER_RECORD"]


def main() -> int:
    print("probe-budget: verifying per-record cost ceiling enforcement")
    checks = [check_a_exceeds_budget, check_b_within_budget, check_c_worker_raises_budget_exceeded]
    results = [fn() for fn in checks]
    if all(results):
        print("probe-budget: PASS")
        return 0
    print(f"probe-budget: FAIL ({sum(1 for r in results if not r)}/{len(checks)} checks failed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
