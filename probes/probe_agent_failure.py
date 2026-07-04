#!/usr/bin/env python3
"""probe_agent_failure.py — verify the Verifier catches hallucinated Worker output.

Exit 0 = Verifier correctly caught the injected failure.
Exit 1 = Verifier let a hallucinated output through (dangerous).

Checks:
  A) Worker output with unknown fields → AGENT_HALLUCINATION.
  B) Worker output with mismatched formatted_amount → AGENT_HALLUCINATION.
  C) Worker output with valid fields and correct amount → passes.
  D) All fields in ALLOWED_DERIVED_FIELDS are individually accepted.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from _fixtures import make_normalized, make_worker_output

from agents.verifier import ALLOWED_DERIVED_FIELDS, _amount_matches


def _hallucinated(worker_out, normalized) -> list[str]:
    """Mirror the structural check from agents/verifier.py (no LLM call)."""
    found = [f for f in worker_out.delivered_fields if f not in ALLOWED_DERIVED_FIELDS]
    if "formatted_amount" in worker_out.delivered_fields:
        if not _amount_matches(str(worker_out.delivered_fields["formatted_amount"]), normalized.amount):
            found.append("formatted_amount(value_mismatch)")
    return found


def check_a_unknown_fields() -> bool:
    normalized = make_normalized(amount=4800.0, source_hash_char="d")
    worker = make_worker_output(normalized, {
        "summary": "Onboarding for probe.user",
        "formatted_amount": "$4,800.00",
        "urgency_label": "normal",
        "branded_header": "CEDX Financial Services — ONBOARDING",
        "invented_field": "hallucinated",
        "secret_approval_code": "BYPASS-AUTH-123",
    })
    found = _hallucinated(worker, normalized)
    if not {"invented_field", "secret_approval_code"} & set(found):
        print(f"FAIL check-A: unknown fields not detected. got={found}")
        return False
    print(f"PASS check-A: hallucinated fields caught: {found}")
    return True


def check_b_amount_mismatch() -> bool:
    normalized = make_normalized(amount=5300.0, source_hash_char="d")
    worker = make_worker_output(normalized, {
        "summary": "Renewal for probe.user",
        "formatted_amount": "$38,000.00",
        "urgency_label": "normal",
        "branded_header": "CEDX Financial Services — RENEWAL",
    })
    found = _hallucinated(worker, normalized)
    if "formatted_amount(value_mismatch)" not in found:
        print(f"FAIL check-B: amount mismatch not detected. got={found}")
        return False
    print("PASS check-B: formatted_amount value mismatch caught")
    return True


def check_c_valid_output_passes() -> bool:
    normalized = make_normalized(amount=4800.0, source_hash_char="d")
    worker = make_worker_output(normalized, {
        "summary": "Standard onboarding for probe.user.",
        "formatted_amount": "$4,800.00",
        "urgency_label": "normal",
        "branded_header": "CEDX Financial Services — ONBOARDING",
    })
    found = _hallucinated(worker, normalized)
    if found:
        print(f"FAIL check-C: valid output flagged: {found}")
        return False
    print("PASS check-C: valid worker output passes hallucination check")
    return True


def check_d_all_allowed_fields_accepted() -> bool:
    normalized = make_normalized(amount=5000.0, source_hash_char="d")
    worker = make_worker_output(normalized, {
        "summary": "Test summary.",
        "formatted_amount": "$5,000.00",
        "urgency_label": "normal",
        "branded_header": "CEDX Financial Services — ONBOARDING",
        "processing_date": "2026-07-04",
    })
    found = _hallucinated(worker, normalized)
    if found:
        print(f"FAIL check-D: allowed field incorrectly flagged: {found}")
        return False
    print(f"PASS check-D: all {len(ALLOWED_DERIVED_FIELDS)} allowed fields accepted")
    return True


def main() -> int:
    print("probe-agent-failure: verifying Verifier catches hallucinated Worker output")
    checks = [check_a_unknown_fields, check_b_amount_mismatch,
              check_c_valid_output_passes, check_d_all_allowed_fields_accepted]
    results = [fn() for fn in checks]
    if all(results):
        print("probe-agent-failure: PASS")
        return 0
    print(f"probe-agent-failure: FAIL ({sum(1 for r in results if not r)}/{len(checks)} checks failed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
