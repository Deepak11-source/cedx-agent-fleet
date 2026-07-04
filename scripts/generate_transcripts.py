from __future__ import annotations
import json
from datetime import date
from pathlib import Path

from agents.orchestrator import dedupe_versions, orchestrate
from core.model_router import STRONG_MODEL, select_model
from core.models import NormalizedRecord, PipelineState
from core.transcripts import save_transcript
from intake import load_all_records

# Scripted scenarios for the dev seed, since none of the 22 real records is
# itself an agent-layer failure -- that's a transcript-level property, not
# a data property. See docs/superpowers/specs/2026-07-03-cedx-agent-fleet-design.md
# Decision Log items 5-6.
SCENARIOS: dict[str, dict] = {
    "REC-002": {"confidence": 0.93, "hallucinate": True},
    "REC-021": {"confidence": 0.35, "hallucinate": False},
    "REC-015": {"confidence": 0.68, "hallucinate": False},
}
DEFAULT_CONFIDENCE = 0.92


def _synthetic_delivered_fields(record: NormalizedRecord, hallucinate: bool) -> dict:
    fields = {
        "summary": f"{record.category.title()} request for {record.owner}, due {record.deadline}.",
        "formatted_amount": f"${record.amount:,.2f}",
        "urgency_label": "normal",
        "branded_header": f"CEDX Financial Services — {record.category} Notice",
    }
    if hallucinate:
        # A field with no basis in the source record -- the Verifier's
        # structural check must catch this (AGENT_HALLUCINATION).
        fields["internal_risk_score"] = 87
    return fields


def _wrap_worker_response(delivered_fields: dict, confidence: float) -> dict:
    payload = dict(delivered_fields)
    payload["confidence_score"] = confidence
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "usage": {"input_tokens": 320, "output_tokens": 140},
    }


def _wrap_verifier_response(verdict: str, reasoning: str) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(
            {"verdict": verdict, "reasoning": reasoning}, sort_keys=True,
        )}],
        "usage": {"input_tokens": 220, "output_tokens": 60},
    }


def generate_all_transcripts(seed_dir: Path, pipeline_now: date) -> list[str]:
    """Generate (or regenerate) every transcript needed for REPLAY_LLM=true.

    Only records that clear the Orchestrator's checks reach the Worker, so
    only those get transcripts. Only records that clear the Worker's
    abstain path and aren't scripted to hallucinate reach the Verifier.
    """
    raw_records = load_all_records(seed_dir)
    kept, _superseded = dedupe_versions(raw_records)
    batch_amounts = [r.amount for r in kept if r.amount is not None]

    generated: list[str] = []
    for raw in kept:
        state = orchestrate(PipelineState(record_id=raw.id, raw=raw), batch_amounts, pipeline_now)
        if state.exception is not None or state.normalized is None:
            continue

        record = state.normalized
        scenario = SCENARIOS.get(record.id, {})
        confidence = scenario.get("confidence", DEFAULT_CONFIDENCE)
        hallucinate = scenario.get("hallucinate", False)
        model = select_model(record)

        delivered_fields = _synthetic_delivered_fields(record, hallucinate)
        worker_response = _wrap_worker_response(delivered_fields, confidence)
        save_transcript(
            record_id=record.id, agent="worker", prompt_version="worker_v1",
            response=worker_response, delivered_fields=delivered_fields, model=model,
            tokens_in=320, tokens_out=140, latency_ms=650.0,
        )
        generated.append(f"{record.id}:worker")

        if confidence >= 0.5 and not hallucinate:
            verifier_response = _wrap_verifier_response(
                "pass", "Formatted amount matches source; summary consistent with category and notes.",
            )
            save_transcript(
                record_id=record.id, agent="verifier", prompt_version="verifier_v1",
                response=verifier_response, delivered_fields=None, model=STRONG_MODEL,
                tokens_in=220, tokens_out=60, latency_ms=900.0,
            )
            generated.append(f"{record.id}:verifier")

    return generated


if __name__ == "__main__":
    from core.config import get_pipeline_now, get_seed_dir

    seed_dir = Path(get_seed_dir())
    pipeline_now = date.fromisoformat(get_pipeline_now())
    result = generate_all_transcripts(seed_dir, pipeline_now)
    print(f"Generated {len(result)} transcripts under transcripts/")
