from pathlib import Path

from intake import load_all_records


def test_load_all_records_combines_feed_and_inbox():
    records = load_all_records(Path("seed"))
    ids = [r.id for r in records]
    assert "REC-001" in ids
    assert "REC-006" in ids
    assert "REC-007" in ids
    # REC-017 appears twice: v1 in feed.json, v2 in inbox
    assert ids.count("REC-017") == 2


def test_load_all_records_source_formats_are_correct():
    records = load_all_records(Path("seed"))
    by_id = {}
    for r in records:
        by_id.setdefault(r.id, []).append(r)
    assert any(r.source_format.value == "eml" for r in by_id["REC-006"])
    assert any(r.source_format.value == "pdf" for r in by_id["REC-007"])
    assert any(r.source_format.value == "feed" for r in by_id["REC-001"])
