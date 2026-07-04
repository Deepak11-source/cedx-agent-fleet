import pytest

from core.prompts import load_prompt


def test_load_prompt_worker_v1_contains_json_instruction():
    text = load_prompt("worker_v1")
    assert "confidence_score" in text
    assert "amount" in text.lower()


def test_load_prompt_verifier_v1_contains_verdict_instruction():
    text = load_prompt("verifier_v1")
    assert "verdict" in text.lower()


def test_load_prompt_judge_v1_contains_score_instruction():
    text = load_prompt("judge_v1")
    assert "score" in text.lower()


def test_load_prompt_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist_v9")
