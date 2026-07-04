import json
from datetime import date
from pathlib import Path

import pytest

import core.transcripts as transcripts_mod
from core.transcripts import load_transcript
from scripts.generate_transcripts import generate_all_transcripts

SEED_DIR = Path("seed")
PIPELINE_NOW = date(2026, 6, 26)


@pytest.fixture(autouse=True)
def isolated_transcripts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts_mod, "TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(transcripts_mod, "INDEX_PATH", tmp_path / "index.json")
    yield


def _worker_payload(record_id: str) -> dict:
    t = load_transcript(record_id, "worker", "worker_v1")
    return json.loads(t["response"]["content"][0]["text"])


def test_generates_hallucinated_transcript_for_rec_002():
    generate_all_transcripts(SEED_DIR, PIPELINE_NOW)
    payload = _worker_payload("REC-002")
    assert "internal_risk_score" in payload


def test_generates_low_confidence_transcript_for_rec_021():
    generate_all_transcripts(SEED_DIR, PIPELINE_NOW)
    payload = _worker_payload("REC-021")
    assert payload["confidence_score"] < 0.5


def test_clean_record_gets_worker_and_passing_verifier_transcript():
    generate_all_transcripts(SEED_DIR, PIPELINE_NOW)
    payload = _worker_payload("REC-001")
    assert payload["confidence_score"] >= 0.5
    verifier_t = load_transcript("REC-001", "verifier", "verifier_v1")
    verdict = json.loads(verifier_t["response"]["content"][0]["text"])
    assert verdict["verdict"] == "pass"


def test_blocked_records_get_no_worker_transcript():
    generate_all_transcripts(SEED_DIR, PIPELINE_NOW)
    for blocked_id in ["REC-011", "REC-012", "REC-013", "REC-014"]:
        with pytest.raises(FileNotFoundError):
            load_transcript(blocked_id, "worker", "worker_v1")


def test_hallucinated_record_gets_no_verifier_transcript():
    generate_all_transcripts(SEED_DIR, PIPELINE_NOW)
    with pytest.raises(FileNotFoundError):
        load_transcript("REC-002", "verifier", "verifier_v1")
