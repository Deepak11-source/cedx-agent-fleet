from __future__ import annotations
import json

from core.hashing import sha
from core.config import get_replay_llm
from core.model_router import estimate_cost, select_model, would_exceed_budget
from core.models import (
    AgentStatus, AgentTrace, ExceptionRecord, PipelineState, ReasonClass,
    ReasonCode, WorkerOutput,
)
from core.prompts import load_prompt
from core.transcripts import load_transcript

PROMPT_VERSION = "worker_v1"

# Conservative pre-call token estimate used only for the budget gate, before
# the real/replayed token counts are known.
_ESTIMATE_TOKENS_IN = 400
_ESTIMATE_TOKENS_OUT = 200


def worker_draft(state: PipelineState) -> PipelineState:
    record = state.normalized
    assert record is not None, "worker_draft called on a state with no normalized record"

    model = select_model(record)
    projected = estimate_cost(model, _ESTIMATE_TOKENS_IN, _ESTIMATE_TOKENS_OUT)
    if would_exceed_budget(state.total_cost_usd, projected):
        trace = AgentTrace(agent="worker", model=model, status=AgentStatus.KILLED)
        return state.model_copy(update={
            "exception": ExceptionRecord(
                record_id=record.id, reason_code=ReasonCode.BUDGET_EXCEEDED, reason_class=ReasonClass.A,
                detail=f"Projected cost ${state.total_cost_usd + projected:.6f} exceeds per-record ceiling",
                raw_snapshot=record.model_dump(mode="json"),
            ),
            "audit_trail": state.audit_trail + [trace],
            "step_count": state.step_count + 1,
            "status": "exception",
        })

    input_hash = sha(record.model_dump(mode="json"))

    if get_replay_llm():
        transcript = load_transcript(record.id, "worker", PROMPT_VERSION)
    else:
        transcript = _call_real_worker(record, model)

    tokens_in = transcript["tokens_in"]
    tokens_out = transcript["tokens_out"]
    latency_ms = transcript["latency_ms"]
    retries = transcript.get("retries", 0)
    transcript_hash = transcript["response_hash"]
    cost = estimate_cost(model, tokens_in, tokens_out)

    try:
        raw_text = transcript["response"]["content"][0]["text"]
        payload = json.loads(raw_text)
        confidence = float(payload.pop("confidence_score"))
        delivered_fields = payload
    except Exception as e:
        trace = AgentTrace(
            agent="worker", model=model, prompt_version=PROMPT_VERSION,
            tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost, latency_ms=latency_ms,
            retries=retries, transcript_hash=transcript_hash, status=AgentStatus.REJECTED,
        )
        return state.model_copy(update={
            "exception": ExceptionRecord(
                record_id=record.id, reason_code=ReasonCode.AGENT_MALFORMED, reason_class=ReasonClass.A,
                detail=f"Worker returned structurally invalid output: {e}",
                raw_snapshot={"raw_text": transcript.get("response", {})},
            ),
            "audit_trail": state.audit_trail + [trace],
            "step_count": state.step_count + 1,
            "total_cost_usd": state.total_cost_usd + cost,
            "status": "exception",
        })

    abstained = confidence < 0.5
    abstain_reason = f"confidence {confidence:.2f} below 0.5 threshold" if abstained else None

    output = WorkerOutput(
        record_id=record.id, input_hash=input_hash, delivered_fields=delivered_fields,
        confidence_score=confidence, model_used=model, prompt_version=PROMPT_VERSION,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost, latency_ms=latency_ms,
        retries=retries, abstained=abstained, abstain_reason=abstain_reason,
        transcript_hash=transcript_hash,
    )
    status = AgentStatus.ABSTAINED if abstained else AgentStatus.OK
    trace = AgentTrace(
        agent="worker", model=model, prompt_version=PROMPT_VERSION,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost, latency_ms=latency_ms,
        retries=retries, transcript_hash=transcript_hash, status=status,
    )

    update: dict = {
        "worker_output": output,
        "audit_trail": state.audit_trail + [trace],
        "step_count": state.step_count + 1,
        "total_cost_usd": state.total_cost_usd + cost,
    }
    if abstained:
        update["exception"] = ExceptionRecord(
            record_id=record.id, reason_code=ReasonCode.LOW_CONFIDENCE, reason_class=ReasonClass.A,
            detail=abstain_reason, raw_snapshot=record.model_dump(mode="json"),
        )
        update["status"] = "exception"

    return state.model_copy(update=update)


def _call_real_worker(record, model: str) -> dict:
    """Real Claude call path (REPLAY_LLM=false). Not exercised until an
    LLM_API_KEY is provided -- see scripts/generate_transcripts.py's note."""
    from anthropic import Anthropic
    from core.transcripts import save_transcript
    import time

    import os
    client = Anthropic(api_key=os.environ["LLM_API_KEY"])
    prompt = load_prompt(PROMPT_VERSION).format(
        record_id=record.id, owner=record.owner, deadline=record.deadline,
        category=record.category, amount=record.amount, notes=record.notes,
    )
    t0 = time.monotonic()
    response = client.messages.create(model=model, max_tokens=512, messages=[{"role": "user", "content": prompt}])
    latency_ms = (time.monotonic() - t0) * 1000
    raw_response = {
        "content": [{"type": "text", "text": response.content[0].text}],
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
    }
    try:
        delivered_fields = json.loads(response.content[0].text)
    except Exception:
        delivered_fields = None
    return save_transcript(
        record_id=record.id, agent="worker", prompt_version=PROMPT_VERSION,
        response=raw_response, delivered_fields=delivered_fields, model=model,
        tokens_in=response.usage.input_tokens, tokens_out=response.usage.output_tokens,
        latency_ms=latency_ms,
    )
