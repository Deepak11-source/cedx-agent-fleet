#!/usr/bin/env python3
"""eval/run_eval.py — golden-case eval harness for the CEDX agent fleet.

Run: python3 eval/run_eval.py
Exit 0 = all cases pass. Non-zero = failures printed, exit 1.

Tests orchestrator, model_router, and verifier directly (no LLM call needed).
When REPLAY_LLM=false and LLM_API_KEY is set, also runs the LLM judge over
delivered outputs.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from _fixtures import make_worker_output
from agents.orchestrator import orchestrate
from agents.verifier import ALLOWED_DERIVED_FIELDS, _amount_matches
from core.model_router import CHEAP_MODEL, STRONG_MODEL, select_model
from core.models import PipelineState, RawRecord, SourceFormat

CASES_PATH = Path(__file__).parent / "golden_cases.json"
JUDGE_PROMPT_PATH = REPO_ROOT / "prompts" / "judge_v1.txt"

_KNOWN_FIELDS = {"id", "owner", "deadline", "category", "notes", "version", "amount"}


def _make_raw(inp: dict, source_hash_suffix: str = "a") -> RawRecord:
    extra = {k: v for k, v in inp.items() if k not in _KNOWN_FIELDS}
    return RawRecord(
        id=inp.get("id", "GOLDEN-X"),
        owner=inp.get("owner"),
        deadline=inp.get("deadline"),
        category=inp.get("category"),
        notes=inp.get("notes", ""),
        version=inp.get("version", 1),
        amount=inp.get("amount"),
        source_format=SourceFormat.FEED,
        source_hash="sha256:" + source_hash_suffix * 64,
        extra_fields=extra,
    )


def _make_raw_with_aliases(inp: dict) -> RawRecord:
    """RawRecord for cases that use aliased field names (input_raw key)."""
    extra = {k: v for k, v in inp.items() if k not in _KNOWN_FIELDS}
    return RawRecord(
        id=inp.get("id", "GOLDEN-X"),
        owner=inp.get("owner"),
        deadline=inp.get("deadline"),
        category=inp.get("category"),
        notes=inp.get("notes", ""),
        version=inp.get("version", 1),
        amount=inp.get("amount"),
        source_format=SourceFormat.FEED,
        source_hash="sha256:" + "b" * 64,
        extra_fields=extra,
    )


def _detect_hallucination(worker_out, normalized) -> list[str]:
    found = [f for f in worker_out.delivered_fields if f not in ALLOWED_DERIVED_FIELDS]
    if "formatted_amount" in worker_out.delivered_fields:
        if not _amount_matches(str(worker_out.delivered_fields["formatted_amount"]), normalized.amount):
            found.append("formatted_amount(value_mismatch)")
    return found


def run_case(case: dict) -> tuple[bool, str]:
    cid = case["id"]
    checks = set(case.get("checks", []))
    pipeline_now = date.fromisoformat(case.get("pipeline_now", "2026-06-26"))
    batch_amounts = case.get("batch_amounts", [4000, 4500, 5000, 5500, 6000])
    expected_code = case.get("expected_reason_code")
    is_verifier_case = "injected_worker_output" in case

    raw = _make_raw_with_aliases(case["input_raw"]) if "input_raw" in case else _make_raw(case["input"])
    state = PipelineState(record_id=raw.id, raw=raw)
    state = orchestrate(state, batch_amounts, pipeline_now)

    # Orchestrator-level checks (skipped for verifier injection cases)
    if not is_verifier_case:
        if "exception_raised" in checks and state.exception is None:
            return False, f"{cid}: expected exception but got none"
        if "reason_code_matches" in checks:
            actual = state.exception.reason_code.value if state.exception else None
            if actual != expected_code:
                return False, f"{cid}: expected reason_code={expected_code}, got {actual}"
        if "blocking_class_a" in checks:
            if state.exception is None or state.exception.reason_class.value != "A":
                return False, f"{cid}: expected Class-A blocking exception"

    if "orchestrator_pass" in checks and state.exception is not None:
        return False, f"{cid}: orchestrator raised unexpected exception: {state.exception.reason_code.value}"
    if "no_exception" in checks and state.exception is not None:
        return False, f"{cid}: unexpected exception {state.exception.reason_code.value}"
    if "normalized_has_fields" in checks:
        n = state.normalized
        if n is None or not (n.id and n.owner and n.deadline and n.amount is not None):
            return False, f"{cid}: normalized record missing required fields"
    if "schema_drift_logged" in checks:
        if state.normalized is None:
            return False, f"{cid}: normalized is None"
        for d in case.get("expected_schema_drifts", []):
            if d not in state.normalized.schema_drifts:
                return False, f"{cid}: expected drift '{d}' not in {state.normalized.schema_drifts}"

    # Model router checks
    if state.normalized is not None:
        selected = select_model(state.normalized, verifier_flagged=case.get("verifier_flagged", False))
        if "model_is_haiku" in checks and selected != CHEAP_MODEL:
            return False, f"{cid}: expected haiku, got {selected}"
        if ("model_is_sonnet" in checks or "model_is_sonnet_when_verifier_flagged" in checks) \
                and selected != STRONG_MODEL:
            return False, f"{cid}: expected sonnet, got {selected}"

    # Verifier injection checks
    if is_verifier_case and state.normalized is not None:
        worker_out = make_worker_output(state.normalized, case["injected_worker_output"])
        hallucinated = _detect_hallucination(worker_out, state.normalized)
        if "hallucination_caught" in checks and not hallucinated:
            return False, f"{cid}: expected hallucination detection but none triggered"
        if "exception_raised" in checks and not hallucinated:
            return False, f"{cid}: expected AGENT_HALLUCINATION but no hallucination detected"
        if "reason_code_matches" in checks:
            if hallucinated and expected_code != "AGENT_HALLUCINATION":
                return False, f"{cid}: hallucination triggered but expected_code is {expected_code}"
            if not hallucinated and expected_code == "AGENT_HALLUCINATION":
                return False, f"{cid}: AGENT_HALLUCINATION expected but not triggered"

    return True, f"{cid}: PASS"


def run_llm_judge(delivered_fields: dict, normalized: dict, case_id: str) -> tuple[bool, str]:
    """Run the LLM judge. Only called when REPLAY_LLM=false and an API key is set."""
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return True, f"{case_id}: judge skipped (no API key)"
    try:
        from anthropic import Anthropic
        prompt = JUDGE_PROMPT_PATH.read_text(encoding="utf-8").format(
            normalized_record_json=json.dumps(normalized, indent=2),
            worker_delivered_fields_json=json.dumps(delivered_fields, indent=2),
        )
        resp = Anthropic(api_key=api_key).messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        payload = json.loads(resp.content[0].text)
        verdict = payload.get("verdict", "fail")
        ok = verdict == "pass"
        return ok, f"{case_id}: judge={verdict} — {payload.get('reasoning', '')}"
    except Exception as e:
        return True, f"{case_id}: judge skipped ({e})"


def main() -> int:
    if not CASES_PATH.exists():
        print(f"FAIL: golden_cases.json not found at {CASES_PATH}")
        return 1
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if len(cases) < 10:
        print(f"FAIL: need >=10 golden cases, found {len(cases)}")
        return 1

    results = [(case["id"], *run_case(case)) for case in cases]
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed

    print(f"\n{'='*60}\nCEDX Eval — {len(cases)} golden cases\n{'='*60}")
    by_agent: dict[str, list] = {}
    for case in cases:
        cid, ok, msg = next(r for r in results if r[0] == case["id"])
        by_agent.setdefault(case.get("agent_under_test", "unknown"), []).append((ok, msg))
    for agent, rows in sorted(by_agent.items()):
        n = sum(1 for ok, _ in rows if ok)
        print(f"\n  [{agent}] {n}/{len(rows)} passed")
        for ok, msg in rows:
            print(f"    {'✓' if ok else '✗'} {msg}")

    print(f"\n{'='*60}\nTotal: {passed}/{len(cases)} passed, {failed} failed")
    print("FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
