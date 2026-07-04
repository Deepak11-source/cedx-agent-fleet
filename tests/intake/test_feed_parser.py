from pathlib import Path

from intake.feed_parser import parse_feed

SEED_FEED = Path("seed/feed.json")


def test_parse_feed_returns_all_records():
    records = parse_feed(SEED_FEED)
    ids = {r.id for r in records}
    assert "REC-001" in ids
    assert "REC-013" in ids
    assert len(records) == 16


def test_parse_feed_preserves_null_amount():
    records = parse_feed(SEED_FEED)
    rec_012 = next(r for r in records if r.id == "REC-012")
    assert rec_012.amount is None


def test_parse_feed_records_have_source_hash():
    records = parse_feed(SEED_FEED)
    assert all(r.source_hash for r in records)
    assert len({r.source_hash for r in records}) == len(records)
