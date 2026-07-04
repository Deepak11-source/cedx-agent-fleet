from datetime import date

import pytest

from core.models import NormalizedRecord, SourceFormat
from core.model_router import (
    CHEAP_MODEL, STRONG_MODEL, estimate_cost, select_model, would_exceed_budget,
)


def _record(amount: float = 4800.0, category: str = "ONBOARDING") -> NormalizedRecord:
    return NormalizedRecord(
        id="REC-001", owner="a.shah", deadline=date(2026, 7, 15), category=category,
        notes="x", version=1, amount=amount, source_format=SourceFormat.FEED, source_hash="h",
    )


def test_select_model_defaults_to_cheap():
    assert select_model(_record()) == CHEAP_MODEL


def test_select_model_escalates_at_amendment_threshold():
    assert select_model(_record(amount=32000.0)) == STRONG_MODEL


def test_select_model_escalates_below_threshold_stays_cheap():
    assert select_model(_record(amount=31999.99)) == CHEAP_MODEL


def test_select_model_escalates_when_verifier_flagged():
    assert select_model(_record(), verifier_flagged=True) == STRONG_MODEL


def test_select_model_escalates_for_ambiguous_category():
    assert select_model(_record(category="?")) == STRONG_MODEL
    assert select_model(_record(category="UNKNOWN")) == STRONG_MODEL


def test_estimate_cost_cheap_model_is_cheaper_than_strong():
    cheap = estimate_cost(CHEAP_MODEL, 1000, 500)
    strong = estimate_cost(STRONG_MODEL, 1000, 500)
    assert cheap < strong


def test_would_exceed_budget_true_when_over_ceiling(monkeypatch):
    monkeypatch.setenv("MAX_COST_PER_RECORD", "0.01")
    assert would_exceed_budget(current_cost=0.005, projected_additional=0.01)


def test_would_exceed_budget_false_when_under_ceiling(monkeypatch):
    monkeypatch.setenv("MAX_COST_PER_RECORD", "0.05")
    assert not would_exceed_budget(current_cost=0.01, projected_additional=0.01)
