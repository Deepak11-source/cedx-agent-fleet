from __future__ import annotations
import re

from core.models import RawRecord, SourceFormat

KNOWN_FIELDS = {"id", "owner", "deadline", "category", "notes", "version", "amount"}
LINE_PATTERN = re.compile(r"^([A-Za-z_]+):\s*(.+)$")


def extract_fields(text: str) -> dict[str, str]:
    """Parse 'Key: value' lines out of free text (shared by the .eml and
    .pdf parsers, both of which use this exact line format)."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = LINE_PATTERN.match(line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return fields


def build_raw_record(fields: dict[str, str], source_format: SourceFormat, source_hash: str) -> RawRecord:
    """Build a RawRecord from a flat key/value dict parsed from any source format.

    Keys are matched case-insensitively against the seven canonical field
    names; anything else is preserved verbatim (lowercased key) in
    extra_fields so the orchestrator's alias map can recognize renamed
    fields (SCHEMA_DRIFT) without the parser needing to know about aliases.
    """
    normalized = {k.lower(): v for k, v in fields.items()}
    known = {k: normalized.get(k) for k in KNOWN_FIELDS}
    extra = {k: v for k, v in normalized.items() if k not in KNOWN_FIELDS}

    version_raw = known.get("version")
    amount_raw = known.get("amount")

    return RawRecord(
        id=str(known["id"]),
        owner=known.get("owner"),
        deadline=known.get("deadline"),
        category=known.get("category"),
        notes=known.get("notes"),
        version=int(version_raw) if version_raw not in (None, "") else 1,
        amount=float(amount_raw) if amount_raw not in (None, "") else None,
        source_format=source_format,
        source_hash=source_hash,
        extra_fields=extra,
    )
