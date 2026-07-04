# CEDX-DCB8F2 — Build Strategy

## Guiding Principle

> Every architectural decision must make a grading criterion easier to satisfy — not harder.

The task is graded ~70% on whether the system holds up on **data it has never seen**, with **agent failures injected**. This means:
- No hardcoded IDs, values, or thresholds
- Every error path must be explicit and logged
- Agents must be genuinely independent — not one function pretending to be three

---

## Tech Stack — Choices and Rationale

### Python 3.11+
- The entire AI agent ecosystem is Python-first. Fighting this costs time with no upside.
- `asyncio` is mature — agents can run concurrently without blocking each other.
- Pydantic v2 (the foundation of typed contracts) is optimized for 3.11+.

### LangGraph — Core Orchestration

LangGraph models the pipeline as a **directed graph with explicit typed state**. This is the right tool here because:

**Why not plain LangChain?**  
LangChain is a component library — it composes prompts, models, and retrievers into chains. It has no native concept of:
- Conditional routing based on agent output (exception queue logic)
- A state machine that pauses for human approval
- A Verifier that can overrule a Worker at the graph topology level
- Checkpoint-based replay

In plain LangChain you end up writing custom Python glue between chains. At that point you've abandoned the framework — you're just writing Python with extra steps.

**Why not CrewAI?**  
CrewAI hides the graph from you. Agents communicate via an opaque crew abstraction. This means:
- You can't precisely control what happens when the Worker misbehaves
- Audit traces are not per-step — they're post-hoc summaries
- The approval state machine is not a CrewAI concept
- Hard to replay: no checkpoint interface

CrewAI is built for autonomous agents that figure things out. This task needs **controlled agents that follow explicit rules** — the opposite design philosophy.

**Why not AutoGen?**  
AutoGen is built around agents having conversations with each other. Conversational agents are non-deterministic by design. The grader injects failures and expects specific, predictable error handling. AutoGen makes that hard to guarantee. It also has no native concept of blocking a record with a typed reason code.

**Why LangGraph wins:**

1. **Explicit state object** — the audit log practically writes itself:
   ```python
   class PipelineState(BaseModel):
       record_id: str
       raw_input: dict
       normalized: NormalizedRecord | None
       exception: ExceptionRecord | None
       worker_output: WorkerOutput | None
       verifier_decision: VerifierDecision | None
       approval_status: ApprovalStatus
       audit_trail: list[AgentTrace]
   ```
   Every agent reads from and writes to this state. Serialize it to Postgres = audit log, replay capability, and per-agent traces for free.

2. **Conditional edges** — exception routing is declarative:
   ```python
   def route_after_orchestrator(state: PipelineState) -> str:
       if state.exception is not None:
           return "exception_queue"
       return "worker"
   graph.add_conditional_edges("orchestrator", route_after_orchestrator)
   ```

3. **Verifier overrule is topological** — enforced by the graph, not by the Worker choosing to listen:
   ```python
   def route_after_verifier(state: PipelineState) -> str:
       if state.verifier_decision.verdict == "overruled":
           return "exception_queue"
       return "delivery"
   ```

4. **Checkpointer = built-in replay** — `SqliteSaver` or `PostgresSaver` snapshots state after every node. Re-run any record from any step.

5. **Human-in-the-loop is native** — `interrupt_before=["delivery"]` pauses the graph, exposes a FastAPI endpoint for approval, then resumes. The approval state machine is built into the graph.

### Pydantic v2 — Typed Contracts

The task explicitly requires typed contracts between agents. Pydantic enforces this at runtime:

```python
class WorkerOutput(BaseModel):
    record_id: str
    draft_content: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    model_used: str
    abstained: bool
    abstain_reason: str | None
    input_hash: str  # hash of source record — provenance
```

If the Worker returns garbage, `WorkerOutput(**raw)` throws before the Verifier ever sees it. Bad data is caught at the boundary — exactly where the grader is looking.

### PostgreSQL + SQLAlchemy

- **Append-only audit**: Postgres enforces this with insert-only grants on the `audit_events` table + a trigger that raises on UPDATE/DELETE.
- **JSONB**: stores full per-agent state snapshots without rigid schema per trace format.
- **Transactions + unique constraints**: idempotency via `UNIQUE(source_hash, pipeline_version)`.
- **LangGraph PostgresSaver**: native checkpointer — one package, no extra plumbing.

Why not MongoDB? The approval state machine and relational integrity between `records`, `approvals`, and `audit_events` genuinely benefits from SQL constraints. A document DB makes those harder to enforce.

### FastAPI — Approval State Machine API

- Native `async` — plays well with LangGraph's async execution.
- Pydantic models for request/response — same models used inside agents, zero duplication.
- The approval endpoint is a proper REST API because the grader will test `make probe-approval` independently from the pipeline.

### Claude API — Model Router

The task requires a model router: cheap by default, escalate only when needed.

```
claude-haiku-4-5-20251001   → default (routine records, low complexity)
claude-sonnet-4-6           → escalation (ambiguous, Verifier-flagged, high-value)
```

Routing policy (justified in DECISIONS.md):
- Escalate if `confidence_score < 0.7` from a haiku attempt
- Escalate if `amount >= 32,000` (amendment threshold — already high-stakes)
- Escalate if Verifier returns `needs_human` on first pass
- Cap per-record cost at `$0.05` — `BUDGET_EXCEEDED` if projected to exceed

### Docker Compose

Required by the task. Single command: `docker compose up`.  
Services: `app` (Python pipeline + FastAPI) · `db` (Postgres) · `redis` (exception queue).

---

## Phase-by-Phase Build Plan

### Phase 0 — Foundation (Hours 0–2)

**Do first, before any agent code:**

1. Fill and commit `SCOPE.md` with CASE_ID — this is the authorship anchor
2. Define ALL Pydantic models in `core/models.py` — this forces clarity on what each agent receives and returns before you write a single prompt
3. Wire up Docker Compose with Postgres — `docker compose up` must work even if agents do nothing
4. Tracer commit: scaffold all 3 agent files + `SCOPE.md` pushed to GitHub

**Directory structure:**
```
cedx-tiny-kit/
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py      # owns the run, routes, enforces budgets
│   ├── worker.py            # Assembly draft + model router
│   ├── verifier.py          # independent check, can overrule
│   └── delivery.py          # package + audit finalization
├── core/
│   ├── models.py            # ALL Pydantic schemas — source of truth
│   ├── database.py          # Postgres + append-only audit
│   ├── model_router.py      # cheap vs expensive model decision
│   ├── state.py             # LangGraph PipelineState definition
│   └── graph.py             # LangGraph graph wiring
├── api/
│   └── approval.py          # FastAPI approval state machine
├── intake/
│   ├── feed_parser.py       # feed.json parser
│   ├── pdf_parser.py        # pdfplumber-based inbox parser
│   └── eml_parser.py        # email parser
├── transcripts/             # committed LLM transcripts (REPLAY_LLM=true)
├── prompts/                 # versioned prompt files (not inline strings)
│   ├── worker_v1.txt
│   └── verifier_v1.txt
├── out/                     # written at runtime (gitignored except .gitkeep)
│   ├── audit.json           # append-only; must pass verify_audit.py
│   └── package/             # branded output per delivered record
├── eval/
│   └── golden_cases.json    # ≥10 cases for make eval
├── seed/                    # DO NOT TOUCH
├── SCOPE.md
├── ARCHITECTURE.md
├── DECISIONS.md
├── PROJECT_OVERVIEW.md
├── STRATEGY.md
├── IMPLEMENTATION.md
├── docker-compose.yml
├── Makefile
└── requirements.txt
```

### Phase 1 — Data Layer (Hours 2–5)

**Database schema:**
```sql
-- Append-only. No UPDATE/DELETE ever — enforced by trigger.
CREATE TABLE audit_events (
    seq        BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    record_id  TEXT,
    payload    JSONB
);

CREATE TABLE records (
    id             TEXT NOT NULL,
    source_hash    TEXT NOT NULL,
    pipeline_ver   TEXT NOT NULL,
    source_format  TEXT NOT NULL,
    raw            JSONB NOT NULL,
    state          JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_hash, pipeline_ver)  -- idempotency key
);

CREATE TABLE approvals (
    record_id   TEXT NOT NULL,
    state       TEXT NOT NULL,
    actor       TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason      TEXT,
    PRIMARY KEY (record_id, state, actor)
);
```

**Idempotency pattern:**
```python
source_hash = sha256(json.dumps(raw_record, sort_keys=True)).hexdigest()
# UNIQUE constraint on (source_hash, pipeline_version) prevents double-processing
# INSERT ... ON CONFLICT DO NOTHING — second run is a no-op
```

**Intake parsers** — one per format, never mixed:
- `feed_parser.py` — reads `feed.json`, emits `RawRecord` objects
- `pdf_parser.py` — `pdfplumber` extracts text; regex/heuristic field extraction
- `eml_parser.py` — `email.parser` stdlib; extracts headers + body

### Phase 2 — Agent Topology (Hours 5–14)

Build agents in dependency order. Each agent is individually unit-testable.

**Orchestrator** — most critical agent:
- Receives: `RawRecord`
- Emits: `NormalizedRecord | ExceptionRecord`
- Detection rules (ALL rule-based, no hardcoding):
  ```
  STALE:            deadline < today (datetime.date.today())
  MISSING_INPUT:    any required field is None
  OUTLIER:          amount > (median + 3 * MAD) across the batch
  INJECTION_BLOCKED: notes matches injection regex patterns
  UNVERIFIED_ANOMALY: fails any validation rule not in the above list
  SCHEMA_DRIFT:     known field alias detected → map to canonical name
  SUPERSEDED_VERSION: same id seen before → keep latest version
  ```

- Outlier threshold is **robust statistics** (Median Absolute Deviation), not a hardcoded value. This generalizes to the held-out seed with different amounts.

**Worker** — Assembly draft:
- Receives: `NormalizedRecord`
- Emits: `WorkerOutput`
- Must record: `input_hash`, `model_used`, `prompt_version`, `tokens_in`, `tokens_out`, `cost_usd`
- Abstain path: if `confidence_score < 0.5` → `abstained=True`, reason logged, routes to exception queue as `LOW_CONFIDENCE`
- Model router lives here: checks complexity score, amount, category → picks haiku or sonnet

**Verifier** — independent check:
- Receives: `NormalizedRecord` + `WorkerOutput` (separately — NOT the Worker's reasoning chain)
- Emits: `VerifierDecision`
- Checks:
  - Every field in `WorkerOutput.delivered_fields` traces back to a field in `NormalizedRecord` — catches `AGENT_HALLUCINATION`
  - `WorkerOutput` passes its own Pydantic schema — catches `AGENT_MALFORMED`
  - Confidence score sanity check
- Can return: `pass | fail | needs_human`
- On `fail`: logs both Worker output and Verifier reasoning, routes to exception queue
- On `needs_human`: escalates to approval chain with a flag

**LangGraph graph wiring** (in `core/graph.py`):
```python
graph = StateGraph(PipelineState)

graph.add_node("orchestrator", orchestrator_node)
graph.add_node("worker", worker_node)
graph.add_node("verifier", verifier_node)
graph.add_node("exception_queue", exception_queue_node)
graph.add_node("delivery", delivery_node)

graph.set_entry_point("orchestrator")

graph.add_conditional_edges("orchestrator", route_after_orchestrator, {
    "worker": "worker",
    "exception_queue": "exception_queue",
})
graph.add_edge("worker", "verifier")
graph.add_conditional_edges("verifier", route_after_verifier, {
    "delivery": "delivery",
    "exception_queue": "exception_queue",
})
graph.add_edge("exception_queue", END)
graph.add_edge("delivery", END)

checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
app = graph.compile(checkpointer=checkpointer, interrupt_before=["delivery"])
```

### Phase 3 — Approval Chain (Hours 14–18)

FastAPI state machine with server-side enforcement:

```
draft → in_review → approved → delivered
                 ↘ changes_requested → in_review (loop)
                 ↘ blocked (non-approved delivery attempt — logged)
```

**Amendment enforcement:**
```python
async def can_deliver(record_id: str, db: AsyncSession) -> bool:
    record = await get_record(record_id, db)
    approvals = await get_approvals(record_id, db)
    
    # Standard: at least one 'approved' state by any operator
    has_standard = any(a.state == "approved" for a in approvals)
    
    # Amendment: if amount >= 32000, also need legal_counsel approval
    needs_amendment = record.normalized["amount"] >= 32_000
    has_amendment = any(
        a.actor_role == "legal_counsel" and a.state == "approved"
        for a in approvals
    )
    
    if needs_amendment:
        return has_standard and has_amendment
    return has_standard

# Delivery endpoint — server-side block, not just a UI warning
@router.post("/deliver/{record_id}")
async def deliver(record_id: str, db: AsyncSession = Depends(get_db)):
    if not await can_deliver(record_id, db):
        await append_audit_event("system", "delivery_refused", record_id)
        raise HTTPException(403, "Delivery refused: approval requirements not met")
    # ... proceed
```

### Phase 4 — Transcripts + REPLAY_LLM (Hours 18–22)

Every real LLM call must be saved as a committed transcript:

```json
{
  "transcript_id": "tr_REC001_worker_v1",
  "agent": "worker",
  "model": "claude-haiku-4-5-20251001",
  "prompt_version": "worker_v1",
  "request": { "messages": [...], "tools": [...] },
  "response": { "content": [...], "usage": {...} },
  "response_hash": "sha256:...",
  "cost_usd": 0.00023,
  "latency_ms": 847
}
```

`REPLAY_LLM=true` mode replays these deterministically — the model call is replaced by returning the committed response. This means `make demo` runs offline without an API key, in under 5 minutes, and produces the same audit every time.

The planted ambiguous record's transcript IS the low-confidence response — so `abstained=True` fires deterministically in replay mode.
The sample agent-failure record's transcript IS the hallucinated output — so the Verifier's `AGENT_HALLUCINATION` catch fires deterministically.

### Phase 5 — Hardening (Hours 22–30)

Run all Makefile probes against the seed. Each must exit 0:

```bash
make demo                  # full pipeline, writes out/audit.json
make verify                # verify_audit.py passes
make trace ID=REC-001      # shows agent path + cost
make eval                  # ≥10 golden cases, LLM-judge per agent
make replay ID=REC-001     # data lineage from log alone
make probe-approval        # non-approved delivery is refused + logged
make probe-agent-failure   # hallucinated worker output → Verifier catches
make probe-budget          # exceeds cost ceiling → BUDGET_EXCEEDED
make probe-append-only     # mutation attempt → refused
make probe-idempotency     # run demo twice → no duplicates
```

**Generalization checklist before submission:**
- [ ] No hardcoded record IDs anywhere in agent code
- [ ] Outlier threshold computed from batch statistics, not a fixed number
- [ ] Field mapping is declarative (a config file), not `if field == "amount"`
- [ ] `UNVERIFIED_ANOMALY` catch-all fires for anything that fails validation but matches no known rule
- [ ] Injection detection uses regex patterns, not string equality
- [ ] Model router policy is based on rules, not on specific record IDs

### Phase 6 — Docs + Loom (Hours 30–40)

**ARCHITECTURE.md:** Mermaid diagram of the full agent topology — every agent, its typed input/output, who it can call, where the Verifier overrules, where the budget/router decisions live.

**DECISIONS.md:** The hardest decisions and their justification:
- Why MAD for outlier detection (not IQR, not hardcoded)
- Why Haiku default vs Sonnet (cost numbers backing the policy)
- Why the exception queue is Postgres (not Redis) at this scale
- What breaks first at 10,000 records/day

**Loom (3–5 min, your voice, mandatory):**
1. Architecture tour — show the agent graph
2. Full pipeline run — `make demo`
3. Class-A problem firing — show the exception queue entry
4. Verifier catching a bad agent — show the overrule log
5. Approval blocking then releasing — show the state machine transition
6. Injection neutralized — show `INJECTION_BLOCKED` in audit
7. `make trace REC-001` — show per-agent cost breakdown

**Final commit message must include:** `CEDX-DCB8F2`

---

## Risk Register

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Held-out seed has renamed fields | High (by design) | Declarative field-mapping config; `SCHEMA_DRIFT` handler |
| Verifier passes hallucinated output | High if not careful | Verifier checks every delivered field traces to source — no exceptions |
| Injection in held-out `notes` | Certain | Regex + LLM-based injection detection; `INJECTION_BLOCKED` before Worker sees it |
| `make demo` fails on grading box | Medium | Test on clean Docker, linux/amd64, no local deps |
| Live extension: can't add 4th agent | Controllable | Keep agent files thin; graph wiring is the only change needed |
| Cost ceiling hit on held-out records | Low with router | Haiku for routine; model router logic is rules-based, not record-specific |

---

## Time Budget (72 hours)

| Phase | Hours | Deliverable |
|-------|-------|-------------|
| Foundation + tracer commit | 0–2 | SCOPE.md pushed, Docker works |
| Data layer + intake parsers | 2–5 | Records in Postgres |
| Agent topology (all 3 agents) | 5–14 | End-to-end happy path works |
| Approval chain + amendment | 14–18 | State machine + probe-approval passes |
| Transcripts + REPLAY_LLM | 18–22 | make demo runs offline |
| Hardening + all probes | 22–30 | All make probe-* exit 0 |
| Eval harness (10 golden cases) | 30–34 | make eval passes |
| ARCHITECTURE.md + DECISIONS.md | 34–40 | Docs complete |
| Loom recording | 40–44 | 3–5 min narrated video |
| Final review + submission | 44–48 | GitHub repo + portal submission |
| Buffer | 48–72 | Bug fixes, live extension prep |
