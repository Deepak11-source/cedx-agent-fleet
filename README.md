# CEDX Agent Fleet — CEDX-DCB8F2

## 1. Industry & Scope

**Industry:** Financial Services — Document Processing & Compliance  
**Tier:** Tiny (kit default)  
**CASE_ID:** `CEDX-DCB8F2`  
**Amendment:** second approver role = `legal_counsel` · threshold = `32,000`

Records are financial work-request documents (approvals, disbursements, transfers). The pipeline
normalizes them, detects data and agent-level problems, drafts a structured output, verifies it
independently, enforces a human approval gate (including the amendment gate), and delivers a
branded package with a full append-only audit trail.

---

## 2. Agent Topology

```
Intake (feed_parser / pdf_parser / eml_parser)
        │
        ▼
Orchestrator  ──exception──▶  Exception Queue
        │
        ▼
  Worker Agent  ──exception──▶  Exception Queue
        │
        ▼
 Verifier Agent  ──overrule──▶  Exception Queue
        │
        ▼
  Approval Gate  ──refused──▶  Exception Queue
        │
        ▼
   Delivery Agent  ──▶  out/package/ + audit.json
```

### Agent roster

| Agent | File | Role | Model(s) | Can call |
|---|---|---|---|---|
| Orchestrator | `agents/orchestrator.py` | Normalize, detect all data + agent-layer problems, route exceptions | — (no LLM) | worker |
| Worker | `agents/worker.py` | Draft structured branded output via LLM; abstain on ambiguity | haiku (default), sonnet (escalation) | verifier |
| Verifier | `agents/verifier.py` | Independent structural + LLM quality check; can OVERRULE Worker | haiku or sonnet | — |
| Delivery | `agents/delivery.py` | Package approved records; write `out/package/` | — | — |

**Typed contracts:** every agent receives and returns `PipelineState` (Pydantic, immutable). All
schemas are defined in `core/models.py` — no raw dicts cross agent boundaries. The Verifier
sees only `WorkerOutput`, never the Worker's internal reasoning chain.

**Verifier overrule:** when the Verifier rejects, it sets `verifier_verdict = "rejected"`, appends an
`AgentTrace` with its reasoning, and routes the record to the exception queue with reason code
`AGENT_HALLUCINATION`. The disagreement is logged with both the Worker's output and the
Verifier's verdict. This is enforced in `agents/verifier.py` and recorded in the audit trail.

---

## 3. How to Run

### One-command (Docker)

```bash
docker compose up
# writes out/audit.json, out/package/, out/exception_queue.json
```

### Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make demo          # full pipeline, REPLAY_LLM=true
make verify        # run grading gate on out/audit.json
```

### Real LLM mode

```bash
REPLAY_LLM=false LLM_API_KEY=sk-... make demo
```

Supports any of: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `gpt-4o-mini`, `gemini-1.5-flash`.

---

## 4. Controls

| Command | What it does | Pass = |
|---|---|---|
| `make demo` | Full fleet, `REPLAY_LLM=true`, on `SEED_DIR` | exit 0; writes package + audit.json + exception dump |
| `make verify` | Run `verify_audit.py` on `out/audit.json` | exit 0 |
| `make trace ID=<id>` | Print full agent decision path + cost for one record | exit 0 |
| `make eval` | Run 15 golden cases + LLM-judge per agent | exit 0; prints per-agent scores |
| `make replay ID=<id>` | Reconstruct data lineage from audit log alone | exit 0 |
| `make probe-approval` | Try to deliver a non-approved item | exit 0 only if refused + logged |
| `make probe-agent-failure` | Feed hallucinated/malformed worker output | exit 0 only if Verifier catches + routes |
| `make probe-budget` | Feed a record that exceeds cost/step ceiling | exit 0 only if `BUDGET_EXCEEDED` raised |
| `make probe-append-only` | Try to mutate a past audit entry | exit 0 only if refused |
| `make probe-idempotency` | Run demo twice | exit 0 only if no duplicates on run 2 |

---

## 5. Planted-Problem Handling

### Data layer (Class A — blocking)

| Problem | Reason Code | How detected |
|---|---|---|
| `deadline` already passed | `STALE` | `deadline < today` (date comparison in orchestrator) |
| Required field is null | `MISSING_INPUT` | Null check on `id`, `owner`, `deadline`, `amount` |
| Extreme numeric outlier | `OUTLIER` | MAD: `amount > median + 3 × 1.4826 × MAD` over batch |
| Injection in `notes` | `INJECTION_BLOCKED` | Regex match on `notes.lower()` against `INJECTION_PATTERNS` |
| Ambiguous record, LLM abstains | `LOW_CONFIDENCE` | Worker returns `confidence_score < 0.5` |
| Fails validation, no known rule | `UNVERIFIED_ANOMALY` | Catches the held-out unknown problem type |

### Agent layer (Class A — blocking)

| Problem | Reason Code | How caught |
|---|---|---|
| Worker invents a field/value | `AGENT_HALLUCINATION` | Verifier: field allowlist check + `_amount_matches()` |
| Worker exceeds step budget | `AGENT_LOOP` | Orchestrator: `steps > MAX_STEPS_PER_RECORD` (default 10) |
| Worker returns invalid output | `AGENT_MALFORMED` | Worker: Pydantic parse failure after bounded retry |
| Processing would exceed cost ceiling | `BUDGET_EXCEEDED` | `would_exceed_budget()` pre-call check in worker |

### Auto-resolved (Class B — logged, continues to delivery)

| Problem | Reason Code | How handled |
|---|---|---|
| Field renamed mid-batch | `SCHEMA_DRIFT` | `FIELD_ALIASES` map in orchestrator; logs mapping event |
| Same record id, higher version seen | `SUPERSEDED_VERSION` | `dedupe_versions()` in orchestrator; v1 marked superseded |

### Records that reached delivery in this run (15/23)

`REC-001`, `REC-003`, `REC-005`, `REC-006`, `REC-007`, `REC-008`, `REC-009`, `REC-010`,
`REC-015`, `REC-016`, `REC-017`, `REC-018`, `REC-019`, `REC-020`, `REC-022`

Exception queue (7): `REC-002` (STALE), `REC-004` (MISSING_INPUT), `REC-011` (OUTLIER),
`REC-012` (INJECTION_BLOCKED), `REC-013` (AGENT_HALLUCINATION), `REC-014` (LOW_CONFIDENCE),
`REC-021` (UNVERIFIED_ANOMALY)

---

## 6. Generalization

No record IDs, amounts, or field names are hardcoded in agent logic. Every detector is rule-based
and parameterized:

- **Outlier threshold** is computed dynamically from the batch using MAD — scales to any
  distribution of amounts.
- **Injection detection** uses regex patterns — matches any phrasing variation, not literal strings.
- **Schema drift** uses a declarative alias map — add an alias, it handles the renamed field.
- **Agent failure** detection is structural (field allowlist + value cross-check) — generalizes to any
  Worker output, not just the planted sample.
- **UNVERIFIED_ANOMALY** is a catch-all for any record that fails validation but matches no
  known reason code — this is exactly what fires on the held-out unknown problem.

The held-out seed can use different record IDs, different amounts, different field alias names, and
shuffle order. None of those break the pipeline.

---

## 7. LLM / Agent Contract & Eval

### REPLAY_LLM=true (default, offline)

Only the LLM model calls are replaced — by committed transcripts in `/transcripts/`. Transcripts
are content-addressed (`sha256(response).json`) with a lookup index at `transcripts/index.json`.
Intake, parsing, normalization, exception detection, the approval state machine, and the audit log
are all real code — none are stubbed.

Every transcript stores: `agent`, `model`, `prompt_version`, `response`, `response_hash`,
`delivered_fields_hash`, `tokens_in`, `tokens_out`, `latency_ms`, `retries`.

### REPLAY_LLM=false (real API)

Set `LLM_API_KEY` and optionally `LLM_MODEL`. The model router will use real API calls, the
router will still downgrade to haiku for easy records, and the system generalizes to the held-out
seed.

### Eval harness

`make eval` runs 15 golden cases across three agents:

- **Orchestrator (9 cases):** STALE, MISSING_INPUT, OUTLIER, INJECTION_BLOCKED, SCHEMA_DRIFT,
  SUPERSEDED_VERSION, UNVERIFIED_ANOMALY, clean pass-through, multi-problem detection
- **Model router (4 cases):** haiku default, sonnet on high-amount, sonnet on UNKNOWN category,
  sonnet on verifier-flagged retry
- **Verifier (2 cases):** catches hallucinated field, accepts valid output

All 15 cases pass without any LLM API key. An LLM-judge pass runs when `LLM_API_KEY` is set.

---

## 8. Cost & Scale

| Metric | Value |
|---|---|
| Avg cost per record | **$0.0017** |
| p95 latency per record | **900 ms** |
| Total run cost (23 records) | **$0.040** |
| Projected cost at 10,000 records/day | **$17.18/day** |

**Model router policy** keeps costs low: `claude-haiku-4-5-20251001` handles clean, low-value
records (~$0.0008/record); `claude-sonnet-4-6` is used only when `amount ≥ 32,000`, category
is UNKNOWN, or the Verifier flags a retry (~$0.008/record). With the seed distribution, ~85% of
records use haiku.

**Per-record cost ceiling** is `$0.05` (env `MAX_COST_PER_RECORD`). `would_exceed_budget()`
checks the projected cost before every LLM call; if it would exceed the ceiling, the record routes
to `BUDGET_EXCEEDED` instead of spending.

**What breaks first at 10k records:** the current bottleneck is sequential per-record processing
(~900ms p95). At 10k/day that's ~2.5 hours of wall-clock. Parallelizing the worker fleet across
records (worker pool, async) would be the first scaling step — the architecture supports it since
`PipelineState` is immutable and agents share no mutable state.

---

## 9. Amendment

```
CASE_ID:   CEDX-DCB8F2
Role:      legal_counsel
Threshold: 32,000 (USD)
```

Any record with `normalized_amount >= 32,000` requires a second approval from an actor with
role `legal_counsel`, in addition to standard operator approval, before delivery is permitted.

This is enforced server-side in `core/approval.py::can_deliver()` — not just a CLI warning. Every
caller (CLI, probes) goes through this single function. If the `legal_counsel` approval is missing,
`can_deliver()` raises and logs `delivery_refused` to the audit event log.

`make probe-approval` verifies both paths: standard approval gate and the amendment gate.

The pipeline prints `AMENDMENT: role=legal_counsel threshold=32000` at startup and records
`amendment.role` and `amendment.threshold` in `out/audit.json`.

---

## 10. AI Usage / Real-vs-Faked

Claude Code (claude-sonnet-4-6) was used to implement the full codebase. All architectural
decisions (MAD outlier, model router policy, content-addressed transcripts, hash-chained audit,
approval gate in shared core) were made and reviewed by me. The system is not a mockup — every
control is real code, tested by the probe suite and `verify_audit.py`.

What is real (not stubbed):
- Intake: `feed_parser.py`, `pdf_parser.py`, `eml_parser.py`
- Normalization and exception detection in `orchestrator.py`
- Model router in `core/model_router.py`
- Approval state machine in `core/approval.py`
- Append-only hash-chained audit in `core/audit_store.py`
- Idempotency ledger in `core/state_store.py`

What is replayed (by design, per task spec):
- LLM model calls — replaced by committed transcripts when `REPLAY_LLM=true`

