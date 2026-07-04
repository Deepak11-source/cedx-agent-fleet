from pathlib import Path

from intake.pdf_parser import parse_pdf

INBOX = Path("seed/inbox")


def test_parse_pdf_extracts_known_fields():
    rec = parse_pdf(INBOX / "REC-007_v1.pdf")
    assert rec.id == "REC-007"
    assert rec.owner == "g.silva"
    assert rec.amount == 4700.0
    assert rec.category == "REVIEW"


def test_parse_pdf_v2_has_version_2():
    rec = parse_pdf(INBOX / "REC-017_v2.pdf")
    assert rec.id == "REC-017"
    assert rec.version == 2
    assert rec.amount == 4650.0
