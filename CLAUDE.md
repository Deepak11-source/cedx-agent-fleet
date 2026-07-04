# CLAUDE.md — CEDX-DCB8F2

This file tells Claude Code (and any AI assistant) what this project is, how it is structured, and what conventions to follow. Read this before touching any file.

## Project Identity

**CASE_ID:** `CEDX-DCB8F2`  
**Amendment:** second approver role = `legal_counsel` · threshold = `32,000`  
**Industry:** Financial Services — Document Processing & Compliance  
**Assessment:** CEDX Systems — AI Full-Stack Automation Engineer build task  
**Deadline:** 72 hours from interview

## What This Project Is

A multi-agent AI pipeline that processes financial services work-request records through a fleet of cooperating AI agents, enforces human approval, and produces a branded output package with a full append-only audit trail.

The project is graded almost entirely on whether the system generalizes to unseen data with injected agent failures. Architecture and controls matter more than domain logic.

## Critical Constraints — Never Violate These

1. **DO NOT edit anything in `/seed/`** — canonical hash is verified; editing = auto-fail
2. **DO NOT hardcode record IDs, amounts, or field names** in agent logic — the held-out seed uses different values
3. **DO NOT stub or mock intake/parse/normalize/exceptions/router/state-machine/audit** — only LLM model calls may be replayed via transcripts
4. **DO NOT use n8n, Zapier, Make, or any no-code orchestrator** — pure code + LLM only
5. **DO NOT create one god-function** — agents must be separate files, individually testable
6. **DO NOT commit `.env` or any file containing `LLM_API_KEY`**
7. **DO NOT generate `out/audit.json` or `out/package/` at edit time** — these are runtime outputs

## Architecture at a Glance

> **Stack note:** this project uses a **simplified, dependency-light stack**
> — pure Python 3.11, no Postgres/Redis/FastAPI/LangGraph. See the approved
> design at `docs/superpowers/specs/2026-07-03-cedx-agent-fleet-design.md`
> for the full rationale. `PipelineState` flows through an explicit plain-Python
> dispatcher (`core/graph.py`), not a graph framework — same conditional-routing
> semantics, fewer moving parts to keep working through the live extension call.

```
PipelineState (Pydantic) flows through core/graph.py's plain-Python dispatcher:

orchestrator → [exception_queue | worker]
worker       → [exception_queue | verifier]
verifier     → [exception_queue | held-for-approval → delivery]
```

**3 agents — all required, all distinct:**
- `agents/orchestrator.py` — normalizes, detects all problems, routes exceptions
- `agents/worker.py` — Assembly draft via Claude; model router (haiku default, sonnet escalation)
- `agents/verifier.py` — independent check; structural hallucination detection + LLM quality check; can OVERRULE

## Directory Map

```
agents/          # one file per agent — never merge them
  orchestrator.py
  worker.py
  verifier.py
  delivery.py
core/
  models.py      # ALL Pydantic schemas — source of truth; define here, import everywhere
  model_router.py
  graph.py       # plain-Python pipeline dispatcher — only place agents are connected
  audit_store.py # append-only JSON event log; writes out/audit.json + out/exception_queue.json
  state_store.py # idempotency ledger (out/.state/ledger.json) — keyed by (source_hash, pipeline_version)
  approval.py    # approval state machine + can_deliver() amendment gate — CLI-enforced, not FastAPI
intake/
  feed_parser.py
  pdf_parser.py
  eml_parser.py
prompts/         # versioned prompt files — never inline prompt strings in agent code
  worker_v1.txt
  verifier_v1.txt
  judge_v1.txt   # LLM-judge prompt for make eval
transcripts/     # committed LLM transcripts — required for REPLAY_LLM=true
scripts/
  generate_transcripts.py  # real API if LLM_API_KEY set, else deterministic synthetic transcripts
eval/
  golden_cases.json   # ≥10 golden cases for make eval
cli.py           # single CLI entrypoint: demo, approve/reject/deliver, trace, replay
out/             # runtime only — gitignored except .gitkeep
seed/            # READ ONLY — never touch
docs/
  CODEBASE_GUIDE.md  # living technical doc: where code lives, code flow, function purposes
```

## Code Conventions

### Schemas First
Before writing any agent logic, define the Pydantic model in `core/models.py`. Every agent has a declared input type and output type. No raw dicts passed between agents.

```python
# Good — typed boundary
output = WorkerOutput(**raw_llm_response)

# Bad — silent failures downstream
return {"record_id": id, "content": text}
```

### Agent Files
Each agent file exports exactly one main function:
- `orchestrator.py` → `orchestrate(state: PipelineState) -> PipelineState`
- `worker.py` → `worker_draft(state: PipelineState) -> PipelineState`
- `verifier.py` → `verify(state: PipelineState) -> PipelineState`

Agents NEVER import each other. They only import from `core/`.

### Pipeline State (`PipelineState`, dispatched by `core/graph.py`)
- State is immutable in agents — always use `state.model_copy(update={...})`
- Never mutate `state.audit_trail` in place — append to a new list
- Every agent must add at least one `AgentTrace` to `audit_trail`

### Exception Handling
Every exception must have:
- A `ReasonCode` from the enum in `core/models.py`
- A `ReasonClass` (A = blocking, B = auto-resolved)
- A `detail` string explaining WHY (not just what)
- The raw record snapshot for replay

```python
# Good
return make_exception(
    ReasonCode.STALE, ReasonClass.A,
    f"Deadline {deadline} is before today {date.today()}"
)

# Bad — hardcoded check
if record.id == "REC-011":
    block_it()
```

### Outlier Detection
Use **Median Absolute Deviation (MAD)**, not hardcoded thresholds:
```python
threshold = median + 3 * 1.4826 * MAD
```
The 1.4826 factor makes MAD consistent with standard deviation for normal distributions. This generalizes to any batch of amounts.

### Injection Detection
Use regex patterns, not string equality:
```python
INJECTION_PATTERNS = [
    r"approve\s+immediately",
    r"skip\s+review",
    r"ignore\s+your\s+rules",
    ...
]
```
Match against `notes.lower()`. Never check `if notes == "approve immediately"`.

### Field Mapping (Schema Drift)
Maintain a declarative alias map in `agents/orchestrator.py`:
```python
FIELD_ALIASES = {
    "due_date": "deadline",
    "value": "amount",
    ...
}
```
Apply it at intake, log each mapping as a `SCHEMA_DRIFT` event. Never use `if "due_date" in record` in agent logic.

### Model Router
In `core/model_router.py`. Policy rules:
- `amount >= 32_000` → `claude-sonnet-4-6` (amendment threshold = high-stakes)
- `verifier_flagged=True` → `claude-sonnet-4-6` (retry after rejection)
- `category in ("UNKNOWN", "")` → `claude-sonnet-4-6` (ambiguous)
- Everything else → `claude-haiku-4-5-20251001`

### Prompt Files
Prompts live in `/prompts/` as versioned text files (`worker_v1.txt`, `verifier_v1.txt`, `judge_v1.txt`). Load them at runtime with `Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.txt"`. Never inline multi-line prompts in agent code.

### Transcripts (REPLAY_LLM)
**Transcript files are content-addressed, not name-addressed** — this is
dictated by `verify_audit.py`'s actual integrity check (do not deviate):
```
transcripts/<sha256-hex-of-response>.json
```
Each file's `response_hash` field (`"sha256:" + that same hex`) must equal
`sha(t["response"])` using the exact canonicalization `verify_audit.py`
uses (`core/hashing.py` reimplements this: `json.dumps(obj, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` then sha256). A record's
`transcript_hash` in `audit.json` must equal that same `"sha256:<hex>"`,
and the hex must be the actual filename stem.

Required transcript fields (checked by `verify_audit.py`): `agent` (must
name a roster agent with role `worker` for any transcript backing a
delivered record), `response` (the raw payload that was hashed),
`response_hash`, `delivered_fields_hash` (must match the record's own
`delivered_fields_hash`). Also store `model`, `prompt_version`, `tokens_in`,
`tokens_out`, `latency_ms`, `retries` for `agent_trace`/cost reporting —
`verify_audit.py` doesn't require these but the audit schema and cost
summary do.

Because REPLAY_LLM needs to find "the worker transcript for record X"
without knowing its hash up front, maintain a lookup index at
`transcripts/index.json`: `{"<record_id>|<agent>|<prompt_version>": "<hex>"}`.
`load_transcript(record_id, agent, prompt_version)` reads the index to find
the hex, then loads `transcripts/<hex>.json`.

Agent roster `can_call` must only reference other **roster agent names**
(never things like `"exception_queue"`, which isn't an agent) —
`verify_audit.py` fails the whole audit if any `can_call` target is
unknown. Use: `orchestrator.can_call = ["worker"]`,
`worker.can_call = ["verifier"]`, `verifier.can_call = []`.

When `REPLAY_LLM=true`, load the transcript instead of calling the API.

### Audit Log
The audit log is **append-only**. Enforced at two levels:
1. Postgres trigger that raises on UPDATE/DELETE to `audit_events`
2. `make probe-append-only` must exit 0

Every action that matters must call `append_audit_event(actor, action, record_id, payload)`.

### Approval Chain
Approval is enforced by a single shared **`can_deliver(record, approvals)`**
function in `core/approval.py` — not just a CLI print/warning. Every caller
(the `cli.py deliver` command, the probes, any future API) must go through
this one function, which checks:
1. Standard approval exists
2. If `amount >= 32_000`: `legal_counsel` approval also exists

If either check fails: raise + log `delivery_refused` to the audit event
log. Enforcing this in `core/approval.py` rather than in the CLI layer is
what makes it "server-side" in spirit even without an HTTP server — the
gate lives in shared core logic, not in a UI-only check that could be
bypassed by calling something else.

## Reason Codes Reference

| Code | Class | Trigger |
|------|-------|---------|
| `STALE` | A | `deadline < today` |
| `MISSING_INPUT` | A | Required field is `None` |
| `OUTLIER` | A | `amount > median + 3*1.4826*MAD` |
| `INJECTION_BLOCKED` | A | `notes` matches injection regex |
| `LOW_CONFIDENCE` | A | Worker `confidence_score < 0.5` |
| `UNVERIFIED_ANOMALY` | A | Fails validation, matches no known rule |
| `AGENT_HALLUCINATION` | A | Worker invented a field not in source |
| `AGENT_LOOP` | A | Worker exceeded `MAX_STEPS_PER_RECORD` |
| `AGENT_MALFORMED` | A | Worker returned invalid structured output |
| `BUDGET_EXCEEDED` | A | Projected cost exceeds `MAX_COST_PER_RECORD` |
| `SCHEMA_DRIFT` | B | Known field alias detected → mapped + logged |
| `SUPERSEDED_VERSION` | B | Same `id`, higher `version` seen → v1 marked superseded |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REPLAY_LLM` | `true` | `true` = use committed transcripts; `false` = real API |
| `SEED_DIR` | `/app/seed` | Path to seed directory — override for held-out grading |
| `DATABASE_URL` | set in docker-compose | Postgres connection string |
| `LLM_API_KEY` | — | Anthropic API key (ignored when `REPLAY_LLM=true`) |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Base model |
| `CASE_ID` | `CEDX-DCB8F2` | Must appear in audit.json and final commit |
| `MAX_COST_PER_RECORD` | `0.05` | USD ceiling per record |
| `MAX_STEPS_PER_RECORD` | `10` | Step ceiling per record (AGENT_LOOP guard) |

## Makefile Targets

| Target | Must Do |
|--------|---------|
| `make demo` | Full pipeline on `SEED_DIR`; writes `out/audit.json` |
| `make verify` | Run `verify_audit.py` on `out/audit.json` → exit 0 |
| `make trace ID=<id>` | Print full agent decision path + cost for one record |
| `make eval` | Run ≥10 golden cases + LLM-judge per agent → exit 0 |
| `make replay ID=<id>` | Reconstruct data lineage from audit log alone |
| `make probe-approval` | Non-approved delivery → refused + logged |
| `make probe-agent-failure` | Hallucinated Worker output → Verifier catches |
| `make probe-budget` | Record exceeds cost ceiling → `BUDGET_EXCEEDED` |
| `make probe-append-only` | Mutation attempt on audit → refused |
| `make probe-idempotency` | Run demo twice → no duplicates on run 2 |

## CASE_ID Amendment

```
CASE_ID: CEDX-DCB8F2
Role:      legal_counsel
Threshold: 32,000 (USD)

Rule: any record with normalized amount >= 32,000 requires an additional
      approval action from an actor with role "legal_counsel" before
      delivery is permitted. This is in addition to standard operator approval.
```

Print at startup: `AMENDMENT: role=legal_counsel threshold=32000`  
Record in `audit.json` under `amendment` key.

## What NOT to Do (Common Mistakes)

- Do not add `if record.id == "REC-013"` anywhere
- Do not commit `out/audit.json` or `out/package/` — they are runtime outputs
- Do not inline prompts as Python strings — use `/prompts/*.txt`
- Do not let the Verifier see the Worker's reasoning chain — only its output
- Do not mock intake, normalization, exception detection, or the approval state machine — only LLM calls may be replayed
- Do not write a single `main.py` that contains all agent logic — each agent must be its own module

## Submission Checklist

- [ ] `SCOPE.md` filled with CASE_ID and pushed (tracer commit)
- [ ] `docker compose up` runs end-to-end on a clean machine
- [ ] `make verify` exits 0
- [ ] All `make probe-*` targets exit 0
- [ ] `make eval` runs ≥10 golden cases and exits 0
- [ ] `/transcripts/` contains committed transcripts for all records
- [ ] `ARCHITECTURE.md` has Mermaid agent topology diagram
- [ ] `DECISIONS.md` explains outlier threshold, model router policy, cost numbers
- [ ] Loom video: 3–5 min, your voice, covers all 7 required demo points
- [ ] Final commit message contains `CEDX-DCB8F2`
- [ ] `case_id: "CEDX-DCB8F2"` present in `out/audit.json`
- [ ] `amendment.role: "legal_counsel"` and `amendment.threshold: 32000` in audit
