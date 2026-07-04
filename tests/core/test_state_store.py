import pytest

import core.state_store as state_store_mod
from core.state_store import is_already_processed, load_ledger, record_processed


@pytest.fixture
def ledger_path(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setattr(state_store_mod, "LEDGER_PATH", path)
    return path


def test_record_processed_appends_new_entry(ledger_path):
    record_processed("hash1", "v1", "REC-001", "delivered", path=ledger_path)
    entries = load_ledger(ledger_path)
    assert len(entries) == 1
    assert entries[0].record_id == "REC-001"


def test_record_processed_upserts_same_key(ledger_path):
    record_processed("hash1", "v1", "REC-001", "delivered", path=ledger_path)
    record_processed("hash1", "v1", "REC-001", "delivered", path=ledger_path)
    entries = load_ledger(ledger_path)
    assert len(entries) == 1


def test_record_processed_distinct_keys_both_kept(ledger_path):
    record_processed("hash1", "v1", "REC-001", "delivered", path=ledger_path)
    record_processed("hash2", "v1", "REC-002", "exception", path=ledger_path)
    entries = load_ledger(ledger_path)
    assert len(entries) == 2


def test_is_already_processed(ledger_path):
    assert not is_already_processed("hash1", "v1", path=ledger_path)
    record_processed("hash1", "v1", "REC-001", "delivered", path=ledger_path)
    assert is_already_processed("hash1", "v1", path=ledger_path)


def test_load_ledger_missing_file_returns_empty(ledger_path):
    assert load_ledger(ledger_path) == []
