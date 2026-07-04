from __future__ import annotations
import re
import statistics
from datetime import date
from typing import Any

from core.models import (
    AgentStatus, AgentTrace, ExceptionRecord, NormalizedRecord, PipelineState,
    RawRecord, ReasonClass, ReasonCode,
)

INJECTION_PATTERNS = [
    r"approve.{0,20}immediately",
    r"skip\s+review",
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"ignore\s+your\s+rules",
    r"bypass\s+(approval|controls|checks)",
    r"override\s+(all|approval|policy)",
    r"disregard\s+(instructions|policy|rules)",
]

FIELD_ALIASES: dict[str, str] = {
    "due_date": "deadline",
    "due": "deadline",
    "value": "amount",
    "cost": "amount",
    "total": "amount",
    "requester": "owner",
    "requestor": "owner",
    "type": "category",
    "kind": "category",
    "description": "notes",
    "comment": "notes",
}

REQUIRED_FIELDS = ["id", "owner", "deadline", "amount"]


def compute_outlier_threshold(amounts: list[float]) -> float:
    """Robust outlier threshold using Median Absolute Deviation (MAD).

    MAD is preferred over mean+stddev because it isn't skewed by the very
    outliers being detected, and it generalizes to any distribution of
    amounts in a held-out seed. The 1.4826 factor makes MAD consistent with
    standard deviation for a normal distribution.
    """
    if len(amounts) < 3:
        return float("inf")
    med = statistics.median(amounts)
    mad = statistics.median([abs(x - med) for x in amounts])
    return med + 3 * 1.4826 * mad


def is_injection(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)


def apply_field_aliases(raw_dict: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Map known field aliases to canonical names; never overwrite an
    already-present canonical field. Returns (mapped_dict, drift_labels).
    """
    result = dict(raw_dict)
    drifts: list[str] = []
    for alias, canonical in FIELD_ALIASES.items():
        if alias in result and result.get(canonical) in (None, ""):
            result[canonical] = result.pop(alias)
            drifts.append(f"{alias}→{canonical}")
        elif alias in result:
            result.pop(alias)
    return result, drifts


def dedupe_versions(raw_records: list[RawRecord]) -> tuple[list[RawRecord], list[ExceptionRecord]]:
    """Group by id; keep the highest version, mark the rest SUPERSEDED_VERSION (Class B)."""
    by_id: dict[str, list[RawRecord]] = {}
    for r in raw_records:
        by_id.setdefault(r.id, []).append(r)

    kept: list[RawRecord] = []
    superseded: list[ExceptionRecord] = []
    for versions in by_id.values():
        if len(versions) == 1:
            kept.append(versions[0])
            continue
        latest = max(versions, key=lambda r: r.version)
        for v in versions:
            if v.version == latest.version:
                kept.append(v)
            else:
                superseded.append(ExceptionRecord(
                    record_id=v.id, reason_code=ReasonCode.SUPERSEDED_VERSION,
                    reason_class=ReasonClass.B,
                    detail=f"version {v.version} superseded by version {latest.version}",
                    raw_snapshot=v.model_dump(mode="json"),
                ))
    return kept, superseded


def orchestrate(state: PipelineState, batch_amounts: list[float], pipeline_now: date) -> PipelineState:
    """Normalize a record and detect all Class-A/B problems. Returns updated state."""
    raw = state.raw
    raw_dict = raw.model_dump(mode="json")
    raw_dict.update(raw.extra_fields)
    mapped, drifts = apply_field_aliases(raw_dict)

    def make_exception(code: ReasonCode, cls: ReasonClass, detail: str) -> PipelineState:
        trace = AgentTrace(agent="orchestrator", status=AgentStatus.ROUTED)
        return state.model_copy(update={
            "exception": ExceptionRecord(
                record_id=raw.id, reason_code=code, reason_class=cls,
                detail=detail, raw_snapshot=raw_dict,
            ),
            "audit_trail": state.audit_trail + [trace],
            "step_count": state.step_count + 1,
            "status": "exception",
        })

    for field in REQUIRED_FIELDS:
        if mapped.get(field) in (None, ""):
            return make_exception(
                ReasonCode.MISSING_INPUT, ReasonClass.A,
                f"Required field '{field}' is null or missing",
            )

    try:
        deadline = date.fromisoformat(str(mapped["deadline"]))
    except (ValueError, TypeError):
        return make_exception(
            ReasonCode.UNVERIFIED_ANOMALY, ReasonClass.A,
            f"Cannot parse deadline: {mapped.get('deadline')!r}",
        )

    if deadline < pipeline_now:
        return make_exception(
            ReasonCode.STALE, ReasonClass.A,
            f"Deadline {deadline} is before pipeline_now {pipeline_now}",
        )

    try:
        amount = float(mapped["amount"])
    except (TypeError, ValueError):
        return make_exception(
            ReasonCode.MISSING_INPUT, ReasonClass.A,
            f"Cannot parse amount: {mapped.get('amount')!r}",
        )

    threshold = compute_outlier_threshold(batch_amounts)
    if amount > threshold:
        return make_exception(
            ReasonCode.OUTLIER, ReasonClass.A,
            f"Amount {amount} exceeds outlier threshold {threshold:.2f} "
            f"(MAD-based, over a batch of {len(batch_amounts)} amounts)",
        )

    if is_injection(mapped.get("notes")):
        return make_exception(
            ReasonCode.INJECTION_BLOCKED, ReasonClass.A,
            "notes field matches a prompt-injection pattern",
        )

    try:
        normalized = NormalizedRecord(
            id=raw.id,
            owner=str(mapped["owner"]),
            deadline=deadline,
            category=str(mapped.get("category") or "UNKNOWN"),
            notes=str(mapped.get("notes") or ""),
            version=int(mapped.get("version") or 1),
            amount=amount,
            source_format=raw.source_format,
            source_hash=raw.source_hash,
            schema_drifts=drifts,
        )
    except Exception as e:
        return make_exception(
            ReasonCode.UNVERIFIED_ANOMALY, ReasonClass.A,
            f"Normalization failed: {e}",
        )

    trace = AgentTrace(agent="orchestrator", status=AgentStatus.OK)
    return state.model_copy(update={
        "normalized": normalized,
        "audit_trail": state.audit_trail + [trace],
        "step_count": state.step_count + 1,
    })
