from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReasonCode(str, Enum):
    STALE = "STALE"
    MISSING_INPUT = "MISSING_INPUT"
    OUTLIER = "OUTLIER"
    INJECTION_BLOCKED = "INJECTION_BLOCKED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNVERIFIED_ANOMALY = "UNVERIFIED_ANOMALY"
    AGENT_HALLUCINATION = "AGENT_HALLUCINATION"
    AGENT_LOOP = "AGENT_LOOP"
    AGENT_MALFORMED = "AGENT_MALFORMED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    SUPERSEDED_VERSION = "SUPERSEDED_VERSION"


class ReasonClass(str, Enum):
    A = "A"
    B = "B"


class SourceFormat(str, Enum):
    FEED = "feed"
    EML = "eml"
    PDF = "pdf"


class ApprovalState(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    DELIVERED = "delivered"
    BLOCKED = "blocked"


class VerifierVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_HUMAN = "needs_human"


class AgentStatus(str, Enum):
    OK = "ok"
    RETRIED = "retried"
    REJECTED = "rejected"
    OVERRULED = "overruled"
    ROUTED = "routed"
    ABSTAINED = "abstained"
    KILLED = "killed"


class RawRecord(BaseModel):
    id: str
    owner: str | None = None
    deadline: str | None = None
    category: str | None = None
    notes: str | None = None
    version: int = 1
    amount: float | None = None
    source_format: SourceFormat
    source_hash: str
    extra_fields: dict[str, Any] = Field(default_factory=dict)


class NormalizedRecord(BaseModel):
    id: str
    owner: str
    deadline: date
    category: str
    notes: str
    version: int
    amount: float
    source_format: SourceFormat
    source_hash: str
    schema_drifts: list[str] = Field(default_factory=list)
    pipeline_version: str = "v1"


class ExceptionRecord(BaseModel):
    record_id: str
    reason_code: ReasonCode
    reason_class: ReasonClass
    detail: str
    raw_snapshot: dict[str, Any]


class WorkerOutput(BaseModel):
    record_id: str
    input_hash: str
    delivered_fields: dict[str, Any]
    confidence_score: float = Field(ge=0.0, le=1.0)
    model_used: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    retries: int = 0
    abstained: bool = False
    abstain_reason: str | None = None
    transcript_hash: str | None = None


class VerifierDecision(BaseModel):
    record_id: str
    verdict: VerifierVerdict
    worker_output_hash: str
    hallucinated_fields: list[str] = Field(default_factory=list)
    reasoning: str
    model_used: str | None = None
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    transcript_hash: str | None = None


class AgentTrace(BaseModel):
    agent: str
    model: str | None = None
    prompt_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    retries: int | None = None
    transcript_hash: str | None = None
    status: AgentStatus
    verdict: VerifierVerdict | None = None


class ApprovalEntry(BaseModel):
    state: ApprovalState
    actor: str
    actor_role: str
    ts: str
    reason: str | None = None


class ProcessingLedgerEntry(BaseModel):
    source_hash: str
    pipeline_version: str
    record_id: str
    completed_stage: str
    ts: str


class PipelineState(BaseModel):
    record_id: str
    raw: RawRecord
    normalized: NormalizedRecord | None = None
    exception: ExceptionRecord | None = None
    worker_output: WorkerOutput | None = None
    verifier_decision: VerifierDecision | None = None
    approval_status: ApprovalState = ApprovalState.DRAFT
    approval_trail: list[ApprovalEntry] = Field(default_factory=list)
    audit_trail: list[AgentTrace] = Field(default_factory=list)
    step_count: int = 0
    total_cost_usd: float = 0.0
    delivered: bool = False
    status: str = "processing"
