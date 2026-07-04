from core.models import SourceFormat
from intake.common import build_raw_record, extract_fields


def test_extract_fields_parses_key_value_lines():
    text = "Id: REC-006\nOwner: f.haddad\nAmount: 5300\n"
    fields = extract_fields(text)
    assert fields == {"Id": "REC-006", "Owner": "f.haddad", "Amount": "5300"}


def test_extract_fields_ignores_lines_without_a_colon():
    text = "Work Request REC-007\nId: REC-007\nOwner: g.silva\n"
    fields = extract_fields(text)
    assert "Id" in fields and "Owner" in fields
    assert len(fields) == 2


def test_build_raw_record_maps_known_fields():
    fields = {"Id": "REC-006", "Owner": "f.haddad", "Deadline": "2026-07-18",
              "Amount": "5300", "Category": "RENEWAL", "Version": "1",
              "Notes": "Renewal with minor scope bump."}
    rec = build_raw_record(fields, SourceFormat.EML, "hash123")
    assert rec.id == "REC-006"
    assert rec.owner == "f.haddad"
    assert rec.amount == 5300.0
    assert rec.version == 1
    assert rec.extra_fields == {}


def test_build_raw_record_captures_unknown_fields_as_extra():
    fields = {"Id": "REC-016", "Owner": "p.larsen", "Deadline": "2026-07-23",
              "Value": "4750", "Category": "RENEWAL", "Version": "1",
              "Notes": "Renewal via partner feed."}
    rec = build_raw_record(fields, SourceFormat.EML, "hash456")
    assert rec.amount is None
    assert rec.extra_fields == {"value": "4750"}


def test_build_raw_record_defaults_missing_amount_to_none():
    fields = {"Id": "REC-012", "Owner": "l.fischer", "Deadline": "2026-07-19",
              "Category": "RENEWAL", "Version": "1", "Notes": "Amount TBD by ops."}
    rec = build_raw_record(fields, SourceFormat.FEED, "hash789")
    assert rec.amount is None
