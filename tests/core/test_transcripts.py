import json

import pytest

import core.transcripts as transcripts_mod
from core.hashing import sha


@pytest.fixture(autouse=True)
def isolated_transcripts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts_mod, "TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(transcripts_mod, "INDEX_PATH", tmp_path / "index.json")
    yield


def test_save_transcript_writes_content_addressed_file():
    response = {"content": "hello", "usage": {"input_tokens": 10, "output_tokens": 5}}
    delivered_fields = {"summary": "hello"}
    t = transcripts_mod.save_transcript(
        record_id="REC-001", agent="worker", prompt_version="worker_v1",
        response=response, delivered_fields=delivered_fields,
        model="claude-haiku-4-5-20251001", tokens_in=10, tokens_out=5, latency_ms=12.0,
    )
    expected_hash = sha(response)
    hexdigest = expected_hash.split(":", 1)[1]
    written_path = transcripts_mod.TRANSCRIPTS_DIR / f"{hexdigest}.json"
    assert written_path.exists()
    on_disk = json.loads(written_path.read_text(encoding="utf-8"))
    assert on_disk["response_hash"] == expected_hash
    assert on_disk["delivered_fields_hash"] == sha(delivered_fields)
    assert on_disk["agent"] == "worker"


def test_load_transcript_round_trips_via_index():
    response = {"content": "world"}
    transcripts_mod.save_transcript(
        record_id="REC-002", agent="verifier", prompt_version="verifier_v1",
        response=response, delivered_fields=None,
        model="claude-sonnet-4-6", tokens_in=1, tokens_out=1, latency_ms=1.0,
    )
    loaded = transcripts_mod.load_transcript("REC-002", "verifier", "verifier_v1")
    assert loaded["response"] == response
    assert loaded["delivered_fields_hash"] is None


def test_load_transcript_missing_raises():
    with pytest.raises(FileNotFoundError):
        transcripts_mod.load_transcript("REC-999", "worker", "worker_v1")
