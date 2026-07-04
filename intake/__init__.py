from __future__ import annotations
from pathlib import Path

from core.models import RawRecord
from intake.eml_parser import parse_eml
from intake.feed_parser import parse_feed
from intake.pdf_parser import parse_pdf


def load_all_records(seed_dir: Path) -> list[RawRecord]:
    """Parse feed.json plus every .eml/.pdf under inbox/ into RawRecords.

    Order: feed.json records first, then inbox records sorted by filename,
    for deterministic output across runs (needed for stable hashing/replay).
    """
    records: list[RawRecord] = []
    feed_path = seed_dir / "feed.json"
    if feed_path.exists():
        records.extend(parse_feed(feed_path))

    inbox_dir = seed_dir / "inbox"
    if inbox_dir.exists():
        for path in sorted(inbox_dir.iterdir()):
            # Skip macOS AppleDouble sidecar files (e.g. "._REC-006_v1.eml")
            # that can end up alongside real seed data after archive
            # extraction on some platforms. Not real seed content.
            if path.name.startswith("._"):
                continue
            if path.suffix == ".eml":
                records.append(parse_eml(path))
            elif path.suffix == ".pdf":
                records.append(parse_pdf(path))
    return records
