from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from core.hashing import sha

TRANSCRIPTS_DIR = Path(__file__).parent.parent / "transcripts"
INDEX_PATH = TRANSCRIPTS_DIR / "index.json"


def _index_key(record_id: str, agent: str, prompt_version: str) -> str:
    return f"{record_id}|{agent}|{prompt_version}"


def _load_index() -> dict[str, str]:
    if not INDEX_PATH.exists():
        return {}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _save_index(index: dict[str, str]) -> None:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def save_transcript(
    record_id: str,
    agent: str,
    prompt_version: str,
    response: dict[str, Any],
    delivered_fields: dict[str, Any] | None,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: float,
    retries: int = 0,
) -> dict[str, Any]:
    """Write a content-addressed transcript and update the lookup index.

    Filename and response_hash are both sha256(response) -- this exact
    scheme is dictated by verify_audit.py's integrity check, not a style
    choice. delivered_fields_hash lets verify_audit.py cross-check a
    delivered record's hash against the transcript that produced it.
    """
    response_hash = sha(response)
    hexdigest = response_hash.split(":", 1)[1]
    transcript = {
        "agent": agent,
        "prompt_version": prompt_version,
        "model": model,
        "response": response,
        "response_hash": response_hash,
        "delivered_fields_hash": sha(delivered_fields) if delivered_fields is not None else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "retries": retries,
    }
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    (TRANSCRIPTS_DIR / f"{hexdigest}.json").write_text(
        json.dumps(transcript, indent=2, sort_keys=True), encoding="utf-8"
    )
    index = _load_index()
    index[_index_key(record_id, agent, prompt_version)] = hexdigest
    _save_index(index)
    return transcript


def load_transcript(record_id: str, agent: str, prompt_version: str) -> dict[str, Any]:
    index = _load_index()
    key = _index_key(record_id, agent, prompt_version)
    if key not in index:
        raise FileNotFoundError(
            f"No transcript indexed for {key}. Run scripts/generate_transcripts.py first."
        )
    path = TRANSCRIPTS_DIR / f"{index[key]}.json"
    if not path.exists():
        raise FileNotFoundError(f"Transcript file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
