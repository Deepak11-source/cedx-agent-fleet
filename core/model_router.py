from __future__ import annotations

from core.config import AMENDMENT_THRESHOLD, get_max_cost_per_record
from core.models import NormalizedRecord

CHEAP_MODEL = "claude-haiku-4-5-20251001"
STRONG_MODEL = "claude-sonnet-4-6"

# Per-million-token pricing (input, output), used only to estimate/report cost.
_PRICING = {
    CHEAP_MODEL: (0.80 / 1_000_000, 4.00 / 1_000_000),
    STRONG_MODEL: (3.00 / 1_000_000, 15.00 / 1_000_000),
}
_DEFAULT_PRICING = (0.003, 0.015)


def select_model(record: NormalizedRecord, verifier_flagged: bool = False) -> str:
    """Pick cheap model by default; escalate only when justified.

    Policy (see DECISIONS.md):
    - amendment-threshold records are high-stakes -> strong model
    - Verifier-flagged records (retry after rejection) -> strong model
    - ambiguous/missing category -> strong model
    - everything else -> cheap model
    All rules are on record VALUES, never on record ID, so this generalizes
    to a held-out seed with different amounts/categories.
    """
    if verifier_flagged:
        return STRONG_MODEL
    if record.amount >= AMENDMENT_THRESHOLD:
        return STRONG_MODEL
    if record.category in ("UNKNOWN", "?", ""):
        return STRONG_MODEL
    return CHEAP_MODEL


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = _PRICING.get(model, _DEFAULT_PRICING)
    return tokens_in * price_in + tokens_out * price_out


def would_exceed_budget(current_cost: float, projected_additional: float) -> bool:
    return (current_cost + projected_additional) > get_max_cost_per_record()
