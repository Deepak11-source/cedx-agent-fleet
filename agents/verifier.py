from __future__ import annotations
import json
import re

from core.config import get_replay_llm
from core.hashing import sha
from core.model_router import STRONG_MODEL, estimate_cost
from core.models import (
    AgentStatus, AgentTrace, ExceptionRecord, PipelineState, ReasonClass,
    ReasonCode, VerifierDecision, VerifierVerdict,
)
from core.prompts import load_prompt
from core.transcripts import load_transcript

PROMPT_VERSION = "verifier_v1"

# Fields the Worker is allowed to compute/derive (not directly copied from source).
ALLOWED_DERIVED_FIELDS = {"summary", "formatted_amount", "urgency_label", "branded_header", "processing_date"}


def _amount_matches(formatted: str, amount: float) -> bool:
    digits = re.sub(r"[^0-9.]", "", formatted)
    try:
        return abs(float(digits) - amount) < 0.01
    except ValueError:
        return False


def verify(state: PipelineState) -> PipelineState:
    record = state.normalized
    worker = state.worker_output
    assert record is not None and worker is not None, "verify called before worker_draft"

    worker_hash = sha(worker.delivered_fields)
    hallucinated: list[str] = [
        field for field in worker.delivered_fields if field not in ALLOWED_DERIVED_FIELDS
    ]
    if "formatted_amount" in worker.delivered_fields:
        if not _amount_matches(str(worker.delivered_fields["formatted_amount"]), record.amount):
            hallucinated.append("formatted_amount(value_mismatch)")

    if hallucinated:
        trace = AgentTrace(agent="verifier", status=AgentStatus.OVERRULED, verdict=VerifierVerdict.FAIL)
        decision = VerifierDecision(
            record_id=record.id, verdict=VerifierVerdict.FAIL, worker_output_hash=worker_hash,
            hallucinated_fields=hallucinated,
            reasoning=f"Worker output contains fields/values not traceable to the source record: {hallucinated}",
            prompt_version=PROMPT_VERSION,
        )
        return state.model_copy(update={
            "verifier_decision": decision,
            "exception": ExceptionRecord(
                record_id=record.id, reason_code=ReasonCode.AGENT_HALLUCINATION, reason_class=ReasonClass.A,
                detail=decision.reasoning, raw_snapshot=worker.delivered_fields,
            ),
            "audit_trail": state.audit_trail + [trace],
            "step_count": state.step_count + 1,
            "status": "exception",
        })

    if get_replay_llm():
        transcript = load_transcript(record.id, "verifier", PROMPT_VERSION)
    else:
        transcript = _call_real_verifier(record, worker)

    tokens_in = transcript["tokens_in"]
    tokens_out = transcript["tokens_out"]
    latency_ms = transcript["latency_ms"]
    transcript_hash = transcript["response_hash"]
    cost = estimate_cost(STRONG_MODEL, tokens_in, tokens_out)

    payload = json.loads(transcript["response"]["content"][0]["text"])
    verdict = VerifierVerdict(payload["verdict"])
    reasoning = payload.get("reasoning", "")

    decision = VerifierDecision(
        record_id=record.id, verdict=verdict, worker_output_hash=worker_hash, reasoning=reasoning,
        model_used=STRONG_MODEL, prompt_version=PROMPT_VERSION, tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=cost, latency_ms=latency_ms, transcript_hash=transcript_hash,
    )
    status_map = {
        VerifierVerdict.PASS: AgentStatus.OK,
        VerifierVerdict.FAIL: AgentStatus.OVERRULED,
        VerifierVerdict.NEEDS_HUMAN: AgentStatus.ROUTED,
    }
    trace = AgentTrace(
        agent="verifier", model=STRONG_MODEL, prompt_version=PROMPT_VERSION, tokens_in=tokens_in,
        tokens_out=tokens_out, cost_usd=cost, latency_ms=latency_ms, transcript_hash=transcript_hash,
        status=status_map[verdict], verdict=verdict,
    )

    update: dict = {
        "verifier_decision": decision,
        "audit_trail": state.audit_trail + [trace],
        "step_count": state.step_count + 1,
        "total_cost_usd": state.total_cost_usd + cost,
    }
    if verdict != VerifierVerdict.PASS:
        # verify_audit.py requires a passing verifier span for anything
        # delivered, so FAIL and NEEDS_HUMAN both route to the exception
        # queue in this tiny kit rather than a second-pass reprocessing loop.
        code = ReasonCode.AGENT_MALFORMED if verdict == VerifierVerdict.FAIL else ReasonCode.LOW_CONFIDENCE
        update["exception"] = ExceptionRecord(
            record_id=record.id, reason_code=code, reason_class=ReasonClass.A,
            detail=f"Verifier verdict={verdict.value}: {reasoning}", raw_snapshot=worker.delivered_fields,
        )
        update["status"] = "exception"

    return state.model_copy(update=update)


def _call_real_verifier(record, worker) -> dict:
    """Real Claude call path (REPLAY_LLM=false). Not exercised until an
    LLM_API_KEY is provided -- see scripts/generate_transcripts.py's note."""
    from anthropic import Anthropic
    from core.transcripts import save_transcript
    import time

    import os
    client = Anthropic(api_key=os.environ["LLM_API_KEY"])
    prompt = load_prompt(PROMPT_VERSION).format(
        normalized_record_json=record.model_dump_json(indent=2),
        worker_delivered_fields_json=json.dumps(worker.delivered_fields, indent=2),
    )
    t0 = time.monotonic()
    response = client.messages.create(model=STRONG_MODEL, max_tokens=256, messages=[{"role": "user", "content": prompt}])
    latency_ms = (time.monotonic() - t0) * 1000
    raw_response = {
        "content": [{"type": "text", "text": response.content[0].text}],
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
    }
    return save_transcript(
        record_id=record.id, agent="verifier", prompt_version=PROMPT_VERSION,
        response=raw_response, delivered_fields=None, model=STRONG_MODEL,
        tokens_in=response.usage.input_tokens, tokens_out=response.usage.output_tokens,
        latency_ms=latency_ms,
    )
