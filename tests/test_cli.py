import json
import subprocess
import sys
from argparse import Namespace

import cli
import core.audit_store as audit_store_mod
import core.state_store as state_store_mod


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(cli, "PACKAGE_DIR", tmp_path / "out" / "package")
    monkeypatch.setattr(cli, "RECORDS_STORE_PATH", tmp_path / "out" / ".state" / "records.json")
    monkeypatch.setattr(audit_store_mod, "EVENTS_PATH", tmp_path / "out" / ".state" / "events.json")
    monkeypatch.setattr(state_store_mod, "LEDGER_PATH", tmp_path / "out" / ".state" / "ledger.json")


def test_cmd_demo_writes_audit_json_and_passes_verify_audit(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    rc = cli.cmd_demo(Namespace(seed_dir=None, pipeline_now=None))
    assert rc == 0
    audit_path = cli.OUT_DIR / "audit.json"
    assert audit_path.exists()

    result = subprocess.run(
        [sys.executable, "verify_audit.py", "--audit", str(audit_path),
         "--transcripts", "transcripts", "--schema", "audit.schema.json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_cmd_demo_covers_all_required_reason_codes(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    cli.cmd_demo(Namespace(seed_dir=None, pipeline_now=None))
    audit = json.loads((cli.OUT_DIR / "audit.json").read_text(encoding="utf-8"))
    codes = {r["reason_code"] for r in audit["records"] if r["reason_code"]}
    for required in ["STALE", "MISSING_INPUT", "OUTLIER", "INJECTION_BLOCKED",
                      "LOW_CONFIDENCE", "SCHEMA_DRIFT", "SUPERSEDED_VERSION"]:
        assert required in codes


def test_cmd_run_then_manual_approve_and_deliver(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    cli.cmd_run(Namespace(seed_dir=None, pipeline_now=None))
    records = cli._load_records_store()
    assert records["REC-001"].status == "held_for_approval"

    rc = cli.cmd_deliver(Namespace(record_id="REC-001", actor="op.1"))
    assert rc == 1  # not approved yet -- refused

    cli.cmd_approve(Namespace(record_id="REC-001", actor="op.1", role="operator", reason=None))
    rc = cli.cmd_deliver(Namespace(record_id="REC-001", actor="op.1"))
    assert rc == 0

    records = cli._load_records_store()
    assert records["REC-001"].status == "delivered"
    assert (cli.PACKAGE_DIR / "REC-001.json").exists()


def test_cmd_trace_and_replay_print_output(tmp_path, monkeypatch, capsys):
    _patch_paths(tmp_path, monkeypatch)
    cli.cmd_demo(Namespace(seed_dir=None, pipeline_now=None))
    capsys.readouterr()

    rc = cli.cmd_trace(Namespace(record_id="REC-001"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "REC-001" in out
    assert "orchestrator" in out

    rc = cli.cmd_replay(Namespace(record_id="REC-001"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Lineage for REC-001" in out
