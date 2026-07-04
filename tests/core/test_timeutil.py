from datetime import datetime

from core.timeutil import now_iso


def test_now_iso_is_parseable_and_has_timezone():
    value = now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
