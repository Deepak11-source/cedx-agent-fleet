# CEDX-DCB8F2 — Codebase Guide (living document)

> **Purpose of this file:** a single place to understand how this
> multi-agent system is put together — where each piece of code lives, how
> data flows through it end to end, and what every function does and why.
> It is kept up to date as the system is built, so you can read this one
> file instead of jumping across the whole repo. If you're new to
> multi-agent systems, read this top to bottom once the pipeline is built —
> it walks the exact path one record takes from raw file to delivered
> package.
>
> This is a *reference*, not the graded deliverable — `ARCHITECTURE.md` and
> `DECISIONS.md` (required by `TASK.md`) are the formal submission docs.
> This file is more informal and more detailed on the "how" for your own
> understanding, especially ahead of the live extension call where you'll
> need to modify this code yourself, live, in ~20 minutes.

**Status:** scaffold — filled in incrementally as each part of the system
is implemented. Sections marked `(not yet implemented)` are placeholders
tracking what's coming, per the approved design at
`docs/superpowers/specs/2026-07-03-cedx-agent-fleet-design.md`.

---

## 1. The Big Picture — What Runs When

```
$ make demo
   │
   ▼
1. INTAKE           read seed/feed.json + seed/inbox/*.{eml,pdf}
                     → RawRecord objects, one per record
   │
   ▼
2. DEDUPE PASS      group by id, keep highest version
                     (SUPERSEDED_VERSION for the rest)
   │
   ▼
3. ORCHESTRATOR     per record: normalize + run all detection rules
   │                 → NormalizedRecord  OR  ExceptionRecord (blocked)
   │
   ├── blocked ──────────────────────────────► EXCEPTION QUEUE
   │
   ▼
4. WORKER           draft branded output via Claude (replayed or real)
   │                 → WorkerOutput (or abstain → LOW_CONFIDENCE)
   │
   ├── abstained ────────────────────────────► EXCEPTION QUEUE
   │
   ▼
5. VERIFIER         independent check of WorkerOutput against source
   │                 → VerifierDecision: pass / fail / needs_human
   │
   ├── fail/needs_human ─────────────────────► EXCEPTION QUEUE
   │
   ▼
6. APPROVAL         held in "draft" state until a human (CLI) approves
   │                 (+ legal_counsel approval if amount >= 32,000)
   │
   ▼
7. DELIVERY         package assembled, out/audit.json + out/package/ written
```

Every step appends to the **audit trail** (`PipelineState.audit_trail`) and,
for anything blocked, to the **exception queue**
(`out/exception_queue.json`). Nothing reaches delivery without passing
through the Verifier with a `pass` verdict and getting human approval.

---

## 2. Where Everything Lives

| Path | What it is | Why it's separate |
|---|---|---|
| `core/models.py` | Every Pydantic type used anywhere in the system | Single source of truth for data shapes — agents never invent their own dict shapes |
| `core/graph.py` | The plain-Python pipeline dispatcher | *(not yet implemented)* — decides which function runs next based on `PipelineState` |
| `core/model_router.py` | Picks haiku vs sonnet, estimates cost | *(not yet implemented)* — keeps "which model" logic in one place, out of the Worker |
| `core/audit_store.py` | Writes/reads `out/audit.json`, enforces append-only | *(not yet implemented)* |
| `core/state_store.py` | Idempotency ledger (`out/.state/ledger.json`) | *(not yet implemented)* — lets `make demo` run twice safely |
| `core/approval.py` | Approval state machine + the amendment gate | *(not yet implemented)* — the one place `can_deliver()` lives |
| `agents/orchestrator.py` | Normalizes + detects problems + routes | *(not yet implemented)* |
| `agents/worker.py` | Drafts the branded output | *(not yet implemented)* |
| `agents/verifier.py` | Independently checks the Worker | *(not yet implemented)* |
| `agents/delivery.py` | Assembles the final package | *(not yet implemented)* |
| `intake/*.py` | One parser per source format (feed/pdf/eml) | *(not yet implemented)* — each format's quirks stay contained |
| `prompts/*.txt` | The actual prompt text sent to Claude | *(not yet implemented)* — versioned, never inline in Python |
| `transcripts/*.json` | Committed LLM call records for offline replay | *(not yet implemented)* |
| `cli.py` | The `cedx` command-line entrypoint | *(not yet implemented)* |
| `eval/golden_cases.json` | Known-answer test cases for `make eval` | *(not yet implemented)* |
| `seed/` | **Read-only** input data — never edit | n/a |
| `out/` | Everything this program writes | n/a — gitignored except `.gitkeep` |

---

## 3. Data Models (`core/models.py`)

*(To be filled in once implemented — will document every Pydantic class:
what it represents, which agent produces it, which agent consumes it, and
why each field exists.)*

---

## 4. Agent-by-Agent Walkthrough

### 4.1 Orchestrator (`agents/orchestrator.py`)
*(not yet implemented)*

### 4.2 Worker (`agents/worker.py`)
*(not yet implemented)*

### 4.3 Verifier (`agents/verifier.py`)
*(not yet implemented)*

### 4.4 Delivery (`agents/delivery.py`)
*(not yet implemented)*

---

## 5. Supporting Modules

### 5.1 Model Router (`core/model_router.py`)
*(not yet implemented)*

### 5.2 Audit Store (`core/audit_store.py`)
*(not yet implemented)*

### 5.3 Approval + Amendment Gate (`core/approval.py`)
*(not yet implemented)*

### 5.4 State/Idempotency Ledger (`core/state_store.py`)
*(not yet implemented)*

---

## 6. Intake Parsers (`intake/*.py`)
*(not yet implemented)*

---

## 7. The CLI (`cli.py`)
*(not yet implemented)*

---

## 8. Reason Codes — Where Each One Fires

| Code | Class | Which function raises it |
|---|---|---|
| `STALE` | A | *(TBD: agents/orchestrator.py)* |
| `MISSING_INPUT` | A | *(TBD: agents/orchestrator.py)* |
| `OUTLIER` | A | *(TBD: agents/orchestrator.py)* |
| `INJECTION_BLOCKED` | A | *(TBD: agents/orchestrator.py)* |
| `LOW_CONFIDENCE` | A | *(TBD: agents/worker.py)* |
| `UNVERIFIED_ANOMALY` | A | *(TBD: agents/orchestrator.py)* |
| `AGENT_HALLUCINATION` | A | *(TBD: agents/verifier.py)* |
| `AGENT_LOOP` | A | *(TBD: core/graph.py)* |
| `AGENT_MALFORMED` | A | *(TBD: agents/worker.py, agents/verifier.py)* |
| `BUDGET_EXCEEDED` | A | *(TBD: agents/worker.py, core/model_router.py)* |
| `SCHEMA_DRIFT` | B | *(TBD: agents/orchestrator.py)* |
| `SUPERSEDED_VERSION` | B | *(TBD: core/graph.py batch pre-pass)* |

---

## 9. How to Trace a Record's Full Story

Once built: `make trace ID=REC-001` prints that record's entire journey —
every agent that touched it, what model was used, cost, latency, and the
Verifier's verdict — reconstructed purely from `out/audit.json`. This
section will document exactly how that reconstruction works once
`cli.py`'s `trace` command exists.

---

## Changelog

- 2026-07-03 — scaffold created alongside the approved architecture design.
