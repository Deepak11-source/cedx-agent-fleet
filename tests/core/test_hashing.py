import hashlib
import json

from core.hashing import canon, sha


def test_canon_matches_verify_audit_py_canonicalization():
    obj = {"b": 2, "a": 1, "nested": {"z": [3, 2, 1]}}
    expected = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert canon(obj) == expected


def test_sha_is_sha256_prefixed_hex_of_canon():
    obj = {"x": 1}
    expected = "sha256:" + hashlib.sha256(canon(obj)).hexdigest()
    assert sha(obj) == expected


def test_sha_is_order_independent():
    assert sha({"a": 1, "b": 2}) == sha({"b": 2, "a": 1})
