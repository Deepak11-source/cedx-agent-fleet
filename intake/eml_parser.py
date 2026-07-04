from __future__ import annotations
import email
import hashlib
from pathlib import Path

from core.models import RawRecord, SourceFormat
from intake.common import build_raw_record, extract_fields


def parse_eml(path: Path) -> RawRecord:
    raw_bytes = path.read_bytes()
    msg = email.message_from_bytes(raw_bytes)
    payload = msg.get_payload(decode=True)
    text = payload.decode("utf-8") if isinstance(payload, bytes) else str(msg.get_payload())
    fields = extract_fields(text)
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    return build_raw_record(fields, SourceFormat.EML, source_hash)
