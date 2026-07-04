from __future__ import annotations
import hashlib
import json
from pathlib import Path

from core.hashing import sha
from core.models import PipelineState


def assemble_package(state: PipelineState, out_dir: Path, case_id: str) -> Path:
    """Write one delivered record's branded output package as JSON."""
    assert state.status == "delivered", f"{state.record_id} is not delivered (status={state.status})"
    assert state.worker_output is not None and state.normalized is not None

    out_dir.mkdir(parents=True, exist_ok=True)
    package = {
        "case_id": case_id,
        "record_id": state.record_id,
        "owner": state.normalized.owner,
        "category": state.normalized.category,
        "amount": state.normalized.amount,
        "deadline": state.normalized.deadline.isoformat(),
        **state.worker_output.delivered_fields,
    }
    path = out_dir / f"{state.record_id}.json"
    path.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")
    return path


def compute_package_hash(package_dir: Path) -> str:
    """Hash of the whole package directory's contents, for audit.json's
    output_package_hash. Uses core.hashing.sha for the same canonicalization
    as every other hash in this system."""
    entries = []
    for path in sorted(package_dir.glob("*.json")):
        entries.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return sha(entries)
