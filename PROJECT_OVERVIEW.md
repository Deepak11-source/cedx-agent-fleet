# CEDX-DCB8F2 — Project Overview

## What This Is

A **multi-agent AI automation pipeline** built for the CEDX Systems hiring assessment. The system processes work-request records from a financial services intake (JSON feed + PDF/email inbox), routes them through a fleet of cooperating AI agents, enforces an approval chain, and delivers a branded output package with a full append-only audit trail.

**CASE_ID:** `CEDX-DCB8F2`  
**Amendment:** second approver role = `legal_counsel` · threshold = `32,000`  
**Industry:** Financial Services — Document Processing & Compliance  
**Stack:** Python 3.11 · LangGraph · Claude API · PostgreSQL · FastAPI · Docker

---

## The Problem Being Solved

Financial services firms receive hundreds of work-request records daily (new client onboarding, renewals, compliance reviews, report bundles). Each record must be:

1. Parsed from heterogeneous sources (structured JSON, PDFs, emails)
2. Validated against business rules — bad records must never reach delivery
3. Drafted by an AI agent into a branded output package
4. Independently verified by a second AI agent that can overrule the first
5. Approved by a human operator (with a second approver for high-value records)
6. Delivered with a full, tamper-proof audit trail

A single monolithic script cannot do this reliably at scale. The system needs to be observable, resumable, auditable, and cheap per record.

---

## Agent Fleet (3 Core Agents)

```
┌─────────────────────────────────────────────────────────────────┐
│                        PIPELINE STATE                           │
│              (Typed Pydantic object — shared across agents)     │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     typed contract      ┌──────────────────┐
│   ORCHESTRATOR  │ ──────────────────────► │     WORKER       │
│                 │                          │                  │
│ • Owns the run  │     ┌─────────────────► │ • Drafts output  │
│ • Routes all    │     │   overrule?        │ • Model router   │
│   exceptions    │     │                   │ • Abstain path   │
│ • Enforces      │     ▼                   └──────────────────┘
│   budgets       │  ┌──────────────────┐            │
│ • Blocks Class-A│  │    VERIFIER      │ ◄──────────┘
│   records       │  │                  │   checks Worker output
└─────────────────┘  │ • Independent    │
         │           │   check          │
         │           │ • Can OVERRULE   │
         ▼           │ • Logs both      │
  ┌─────────────┐   │   sides          │
  │  EXCEPTION  │   └──────────────────┘
  │   QUEUE     │            │
  │             │            ▼
  │ Class-A:    │   ┌─────────────────┐
  │ STALE       │   │  APPROVAL CHAIN │
  │ MISSING_IN  │   │  (State Machine)│
  │ OUTLIER     │   │                 │
  │ INJECTION   │   │ draft →         │
  │ LOW_CONF    │   │ in_review →     │
  │ UNVERIFIED  │   │ approved →      │
  │             │   │ delivered       │
  │ Agent-layer:│   │                 │
  │ HALLUCINATE │   │ + CASE_ID       │
  │ LOOP        │   │ amendment:      │
  │ MALFORMED   │   │ legal_counsel   │
  │ BUDGET_EXC  │   │ ≥ $32,000       │
  └─────────────┘   └─────────────────┘
```

---

## The 5 Pipeline Stages

| Stage | Agent | What Happens |
|-------|-------|-------------|
| **Intake** | Orchestrator | Parse `feed.json` + `inbox/` (PDF + .eml); persist each record with hash |
| **Orchestration** | Orchestrator | Normalize to versioned schema; detect all Class-A/B problems; route exceptions |
| **Assembly** | Worker | Draft branded output via Claude; cheap model default, escalate on complexity |
| **Review** | Verifier + Human | Verifier independently checks Worker output; approval state machine; CASE_ID amendment |
| **Delivery** | Orchestrator | Package output; append-only audit with per-agent traces, cost, replay |

---

## Planted Problems This System Must Handle

### Data Layer (Class A — blocking)
| Record | Problem | Reason Code |
|--------|---------|-------------|
| REC-011 | Deadline `2026-06-01` — already past | `STALE` |
| REC-012 | `amount: null` | `MISSING_INPUT` |
| REC-013 | `amount: 250,000` — extreme outlier | `OUTLIER` |
| REC-014 (inbox) | Notes contain prompt injection text | `INJECTION_BLOCKED` |
| Ambiguous record | LLM cannot produce confident output | `LOW_CONFIDENCE` |
| Unknown anomaly (held-out) | Fails validation, matches no known rule | `UNVERIFIED_ANOMALY` |

### Data Layer (Class B — auto-resolved)
| Pattern | Reason Code |
|---------|-------------|
| Field renamed mid-batch | `SCHEMA_DRIFT` |
| Same ID appears twice (REC-017 v1 in feed + v2 in inbox) | `SUPERSEDED_VERSION` |

### Agent Layer (caught by Verifier)
| Problem | Reason Code |
|---------|-------------|
| Worker invents a field not in source | `AGENT_HALLUCINATION` |
| Worker loops / exceeds step budget | `AGENT_LOOP` |
| Worker returns structurally invalid output | `AGENT_MALFORMED` |
| Record would exceed cost/latency ceiling | `BUDGET_EXCEEDED` |

---

## Grading Rubric — How We Score

| Criterion | Weight | How We Satisfy It |
|-----------|--------|-------------------|
| Agent topology + Verifier overrules Worker | 18% | LangGraph graph with conditional edges; Verifier is a separate agent with its own prompt |
| Exception queue + held-out generalization | 18% | Rule-based detection (no hardcoding); `UNVERIFIED_ANOMALY` catches unknowns |
| Append-only audit + agent traces + replay | 16% | Postgres append-only table; LangGraph checkpointer; `make trace ID=<id>` |
| Approval chain + CASE_ID amendment | 10% | FastAPI state machine; `legal_counsel` gate at `≥32,000` |
| Cost/latency budget + model router | 12% | Haiku default; Sonnet escalation; per-record cost ceiling |
| Declarative normalization + agent eval | 10% | Pydantic schemas; `make eval` with LLM-judge per agent |
| Prompt-injection neutralization | 6% | Orchestrator detects injection patterns in `notes` field |
| Idempotency + resumability | 6% | Hash-based deduplication; LangGraph checkpoint resume |
| Live extension readiness | 4% | Modular agent files; clean contracts — easy to add a 4th agent |

---

## Key Constraints

- `docker compose up` — one command, no manual steps
- `REPLAY_LLM=true` — default offline mode using committed transcripts
- `REPLAY_LLM=false` — real Claude API against held-out seed
- `SEED_DIR` env var — never hardcode seed path
- `/seed` is read-only — canonical hash verified; editing = auto-fail
- No n8n / Zapier / no-code tools
- No god-function — agents are individually testable units

---

## Amendment Details

```
CASE_ID: CEDX-DCB8F2
H = sha256("CEDX-DCB8F2") → first nibble selects role, next two bytes select threshold
Role R:      legal_counsel
Threshold T: 32,000

Rule: any record whose normalized `amount` >= 32,000 requires approval by
      a legal_counsel actor, in addition to standard operator approval,
      before delivery is permitted.
```

Printed at startup: `AMENDMENT: role=legal_counsel threshold=32000`  
Recorded in `audit.json` under `amendment`.  
`make probe-approval` tests that a record with `amount=32000` is blocked without the second approval.
