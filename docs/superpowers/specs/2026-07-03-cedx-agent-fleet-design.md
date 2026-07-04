# CEDX-DCB8F2 — Tiny Agent Fleet: Architecture Design

**Date:** 2026-07-03
**Status:** Approved for implementation planning

## Context

CEDX Systems hiring assessment. Build a multi-agent AI pipeline (≥3 agents:
Orchestrator, Worker, Verifier) that processes financial-services
work-request records from `seed/feed.json` + `seed/inbox/` (PDF + `.eml`),
enforces an approval chain (with a CASE_ID-bound amendment), and produces a
branded output package with a full append-only audit trail.

**CASE_ID:** `CEDX-DCB8F2` — amendment: role `legal_counsel`, threshold `32,000`.

Grading is ~70% about generalizing to a held-out seed (same problem types,
different values, shuffled order, plus injected agent-level failures) — so
every detector must be rule-based, never hardcoded to a specific ID or value.

The candidate kit's aspirational docs (`STRATEGY.md`, `IMPLEMENTATION.md`,
`PREREQUISITES.md`) describe a LangGraph + Postgres + FastAPI + Docker
Compose (multi-service) stack. However, the **actual** grading artifacts
(`verify_audit.py`, `Makefile`, `Dockerfile`, `docker-compose.yml`) only
require: one container, `out/audit.json` passing schema/invariant checks,
and a CLI operator surface (`TASK.md`: "operator surface (CLI fine)"). This
design follows the actual kit contract, not the aspirational docs, and
simplifies the stack accordingly — see Decision Log.

## Decision Log

1. **No Postgres/Redis/FastAPI/LangGraph.** Pure Python 3.11, explicit
   function-dispatch pipeline, JSON-file-based append-only audit log, CLI
   for intake/approval/delivery/trace/replay/probes. Fewer moving parts to
   keep working through the live extension call; matches what
   `verify_audit.py` actually checks.
2. **Transcripts are synthesized now, real-API-capable later.**
   `scripts/generate_transcripts.py` calls the real Claude API when
   `LLM_API_KEY` is set and `REPLAY_LLM=false`; otherwise writes
   deterministic synthetic transcripts (correct shape, hashes, agent tags)
   so `REPLAY_LLM=true` works fully offline today.
3. **`pypdf`, not `pdfplumber`**, for PDF text extraction — matches the
   kit's actual `requirements.txt`, not the aspirational doc.
4. **REC-022's "ignore the field amount" note** is handled as a Worker
   prompt constraint + Verifier structural hallucination check, not a new
   reason code — the Worker must never let free-text `notes` override the
   normalized `amount` field.
5. **One dev-seed record is chosen to carry a synthetic hallucinated Worker
   transcript** (planned: `REC-002`) to deterministically exercise
   `AGENT_HALLUCINATION` / `probe-agent-failure`, since none of the real 21
   seed records is itself an agent-layer failure (that's a transcript-level
   property, not a data property). Documented explicitly in `DECISIONS.md`
   as synthetic, not a real record defect.
6. **`REC-021`** (`category: "?"`, ambiguous notes) gets a synthetic
   low-confidence Worker transcript to exercise the abstain / `LOW_CONFIDENCE`
   path deterministically.
7. **Idempotency/resume via a JSON ledger**, not DB unique constraints:
   `out/.state/ledger.json` keyed by `(source_hash, pipeline_version)`.
8. **Append-only enforcement via hash-chain**, not a DB trigger: each audit
   event embeds `prev_hash`; the whole file is rewritten atomically
   (temp file + rename) on each append; tamper attempts break the chain.
9. **"Server-side" approval enforcement** = a single shared
   `can_deliver(record, approvals)` function in `core/approval.py` that
   every caller (CLI, probes, future API) must go through — not just a CLI
   warning.
10. **`out/exception_queue.json`** is a required run output (per `TASK.md`'s
    run contract and the `Makefile`'s `demo` target) — an array of every
    blocked record's `ExceptionRecord`, written alongside `audit.json`.
11. **`make eval`'s LLM-judge is real**, not simulated by rule-based checks
    alone — `TASK.md` and rubric criterion 6 explicitly require "≥10 golden
    cases + an LLM-judge per agent." A `judge_v1.txt` prompt scores each
    agent's actual output, replayable via committed transcripts like
    Worker/Verifier calls (see Eval Harness section).

## Architecture

```
cedx-tiny-kit/
├── agents/
│   ├── orchestrator.py      # normalize + detect problems + route
│   ├── worker.py            # draft output + model router + abstain
│   ├── verifier.py          # independent check, can overrule
│   └── delivery.py          # package assembly + audit finalize
├── core/
│   ├── models.py            # ALL Pydantic schemas (source of truth)
│   ├── model_router.py      # cheap/strong model selection + cost estimate
│   ├── graph.py             # plain-Python pipeline dispatcher
│   ├── audit_store.py       # append-only JSON event log + audit.json writer
│   ├── state_store.py       # per-record processing ledger (idempotency/resume)
│   └── approval.py          # approval state machine + amendment gate
├── intake/
│   ├── feed_parser.py
│   ├── pdf_parser.py
│   └── eml_parser.py
├── prompts/
│   ├── worker_v1.txt
│   ├── verifier_v1.txt
│   └── judge_v1.txt
├── transcripts/              # committed, REPLAY_LLM=true source of truth
├── scripts/
│   └── generate_transcripts.py
├── eval/
│   └── golden_cases.json
├── cli.py                    # demo, approve, deliver, trace, replay, probes
├── seed/                      # untouched
└── out/                        # runtime only
```

Pipeline: `orchestrate → (exception_queue | worker) → (exception_queue |
verifier) → (exception_queue | held-for-approval) → delivery`.

## Data Models (`core/models.py`)

Adopted from `IMPLEMENTATION.md`'s schemas (already aligned with
`audit.schema.json`), with additions:

- `RawRecord`, `NormalizedRecord`, `ExceptionRecord`, `WorkerOutput`,
  `VerifierDecision`, `AgentTrace`, `PipelineState` — as specified in
  `IMPLEMENTATION.md` Step 3.
- `ApprovalEntry` gains `actor_role` (needed for the amendment gate check).
- New `ProcessingLedgerEntry` (`source_hash, pipeline_version, record_id,
  completed_stage, ts`) for idempotency/resume.
- Enums (`ReasonCode`, `ReasonClass`, `SourceFormat`, `ApprovalState`,
  `VerifierVerdict`, `AgentStatus`) copied verbatim — already match
  `audit.schema.json`'s allowed values.

## Intake & Orchestrator

Parsers emit `RawRecord` with `source_hash = sha256(raw bytes)`:
- `feed_parser.py` — reads `feed.json` array.
- `eml_parser.py` — stdlib `email.parser`; body is `Key: value` lines
  (confirmed against real samples, e.g. `REC-016_v1.eml` uses `Value:`
  instead of `Amount:` — a live `SCHEMA_DRIFT` case).
- `pdf_parser.py` — `pypdf` text extraction, same `Key: value` pattern.

**Batch pre-pass:** group raw records by `id`; any `id` with multiple
versions (e.g. `REC-017`: v1 in `feed.json`, v2 in
`inbox/REC-017_v2.pdf`) — mark non-max versions `SUPERSEDED_VERSION`
(Class B), only the latest version proceeds.

**Orchestrator detection rules** (all rule-based, generalize to held-out):
- `MISSING_INPUT` — any required field (`id/owner/deadline/amount`) is `None`
- `STALE` — `deadline < PIPELINE_NOW`
- `OUTLIER` — MAD-based threshold: `median + 3 * 1.4826 * MAD` over the batch
- `INJECTION_BLOCKED` — regex against `notes` (approve-immediately /
  skip-review / ignore-rules / bypass / override / disregard patterns)
- `SCHEMA_DRIFT` — declarative alias map (`due_date→deadline`,
  `value→amount`, etc.), auto-mapped, logged, continues
- `UNVERIFIED_ANOMALY` — catch-all for anything that fails validation but
  matches no rule above
- `LOW_CONFIDENCE` — fires downstream from the Worker's own
  `confidence_score < 0.5` abstain, not an orchestrator check

## Worker, Model Router, Verifier

**Model router** (`core/model_router.py`), rule-based:
- `amount >= 32_000` → `claude-sonnet-4-6`
- `verifier_flagged=True` (retry after rejection) → `claude-sonnet-4-6`
- `category in ("UNKNOWN", "?", "")` → `claude-sonnet-4-6`
- else → `claude-haiku-4-5-20251001`
- Cost/step ceiling checked before every call → `BUDGET_EXCEEDED` if it
  would exceed `MAX_COST_PER_RECORD`; never silent overspend.

**Worker** (`agents/worker.py`): loads `prompts/worker_v1.txt`, computes
`input_hash` over `NormalizedRecord`, loads/calls transcript per
`REPLAY_LLM`. Structured-output parse failure → `AGENT_MALFORMED`.
`confidence_score < 0.5` → abstain → `LOW_CONFIDENCE`.

**Verifier** (`agents/verifier.py`), two-phase:
1. Structural (no LLM cost): every `delivered_fields` key must exist in
   `NormalizedRecord` or in `ALLOWED_DERIVED_FIELDS` (`summary`,
   `formatted_amount`, `urgency_label`, `branded_header`,
   `processing_date`). Anything else → `AGENT_HALLUCINATION`, overrule,
   no LLM call needed.
2. LLM-based pass/fail/needs_human quality check via `verifier_v1.txt`,
   only if structural check passes.
   - `fail` → exception queue, both sides logged
   - `needs_human` → approval chain, flagged for extra scrutiny
- `AGENT_LOOP` — orchestrator-level step counter kills a record's run past
  `MAX_STEPS_PER_RECORD`.

**Transcripts**: `scripts/generate_transcripts.py` — real API if
`LLM_API_KEY` set + `REPLAY_LLM=false`, else deterministic synthetic
transcripts (still hash-verified, still agent-tagged). `REC-002` gets a
synthetic hallucinated transcript (agent-failure demo); `REC-021` gets a
synthetic low-confidence transcript (abstain demo).

## Audit, Approval, Amendment, CLI, Probes

**Audit store** (`core/audit_store.py`): assembles `out/audit.json`
matching `audit.schema.json` exactly, and also writes
`out/exception_queue.json` (an array of every `ExceptionRecord`, one per
blocked record, with reason code/class/detail) — both are required run
outputs per `TASK.md`'s run contract and the `Makefile`'s `demo` target.
Append-only via atomic rewrite + hash-chain (`prev_hash` per event) —
tamper attempts break the chain, detected on load.

**Approval chain** (`core/approval.py`): `draft → in_review →
changes_requested → approved → delivered`, driven by CLI commands, each
appending an `ApprovalEntry` + audit event. Delivery gate is
`can_deliver(record, approvals)`:
- requires ≥1 `approved` entry
- if `amount >= 32000`: also requires an entry with
  `actor_role == "legal_counsel"` and `state == "approved"`
- refusal → `delivery_refused` audit event, not just a CLI message
- Startup prints `AMENDMENT: role=legal_counsel threshold=32000`

**Idempotency/resume**: `core/state_store.py` ledger keyed by
`(source_hash, pipeline_version)` under `out/.state/ledger.json`.

**CLI (`cli.py`)**: `demo`, `approve/reject/request-changes/deliver <id>`,
`trace <id>`, `replay <id>`.

**Probes**: `probe-approval`, `probe-agent-failure`, `probe-budget`,
`probe-append-only`, `probe-idempotency` (bonus `probe-crash` as a natural
byproduct of the ledger).

**Eval harness**: `eval/golden_cases.json`, ≥10 cases, two layers per
`TASK.md` Step 6 / rubric criterion 6 ("≥10 golden cases + an LLM-judge per
agent"):
1. Rule-based structural checks against each case's `expected_*` fields
   (fast, deterministic, catches routing/reason-code regressions).
2. An actual **LLM-judge step** — a fourth lightweight prompt
   (`prompts/judge_v1.txt`) that scores each agent's actual output on a
   small rubric (faithfulness to source, no hallucinated fields, reasoning
   quality) on a 0–1 scale. Like Worker/Verifier calls, judge calls are
   transcript-replayable (`transcripts/{case_id}_judge_{prompt_version}.json`)
   so `make eval` stays offline-capable under `REPLAY_LLM=true`, and uses
   the real API when `REPLAY_LLM=false`.
`make eval` prints both the structural pass rate and the judge's per-agent
average score.

## Out of Scope

- Postgres, Redis, FastAPI, LangGraph, Docker Compose multi-service setup
- Real-time HTTP approval API (CLI is sufficient per `TASK.md`)
- Non-Anthropic model backends (Claude alone satisfies the "≥1 model" rule)
