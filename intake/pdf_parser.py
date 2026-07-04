from __future__ import annotations
import hashlib
from pathlib import Path

from pypdf import PdfReader

from core.models import RawRecord, SourceFormat
from intake.common import build_raw_record, extract_fields


def parse_pdf(path: Path) -> RawRecord:
    raw_bytes = path.read_bytes()
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    fields = extract_fields(text)
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    return build_raw_record(fields, SourceFormat.PDF, source_hash)
