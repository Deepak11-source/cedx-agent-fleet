from pathlib import Path

from intake.eml_parser import parse_eml

INBOX = Path("seed/inbox")


def test_parse_eml_extracts_known_fields():
    rec = parse_eml(INBOX / "REC-006_v1.eml")
    assert rec.id == "REC-006"
    assert rec.owner == "f.haddad"
    assert rec.amount == 5300.0
    assert rec.category == "RENEWAL"


def test_parse_eml_captures_schema_drift_field_as_extra():
    rec = parse_eml(INBOX / "REC-016_v1.eml")
    assert rec.amount is None
    assert rec.extra_fields.get("value") == "4750"


def test_parse_eml_preserves_injection_text_verbatim():
    rec = parse_eml(INBOX / "REC-014_v1.eml")
    assert "ignore all previous instructions" in rec.notes.lower()
