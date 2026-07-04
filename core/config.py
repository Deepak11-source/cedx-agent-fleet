from __future__ import annotations
import os

AMENDMENT_ROLE = "legal_counsel"
AMENDMENT_THRESHOLD = 32_000


def get_case_id() -> str:
    return os.getenv("CASE_ID", "CEDX-DCB8F2")


def get_seed_dir() -> str:
    return os.getenv("SEED_DIR", "seed")


def get_replay_llm() -> bool:
    return os.getenv("REPLAY_LLM", "true").lower() == "true"


def get_pipeline_now() -> str:
    return os.getenv("PIPELINE_NOW", "2026-06-26")


def get_max_cost_per_record() -> float:
    return float(os.getenv("MAX_COST_PER_RECORD", "0.05"))


def get_max_steps_per_record() -> int:
    return int(os.getenv("MAX_STEPS_PER_RECORD", "10"))
