# CEDX-DCB8F2 — Prerequisites & Setup Guide

## Complete list of everything needed before writing a single line of agent code.

---

## 1. System Tools

```bash
# Check what you have
python3 --version        # need 3.11+
docker --version         # need 24+
docker compose version   # need v2 (not docker-compose v1)
git --version
```

**Install if missing (macOS):**
```bash
brew install python@3.11
brew install --cask docker     # Docker Desktop
```

---

## 2. API Keys Required

### Anthropic (Claude) — Primary LLM
- **Where to get:** platform.anthropic.com → sign in → API Keys → Create Key
- **What you need:** a key starting with `sk-ant-api03-...`
- **Cost estimate for this project:** ~$1–3 total (haiku is very cheap; sonnet only for escalations)
- **Models used:**
  - `claude-haiku-4-5-20251001` — default (cheap)
  - `claude-sonnet-4-6` — escalation (Verifier + high-value records)
- **Set credits:** Add a $5 credit at platform.anthropic.com/settings/billing — more than enough

```bash
# In your .env
LLM_API_KEY=sk-ant-api03-...
```

> **Note:** When `REPLAY_LLM=true` (the default offline mode), this key is **not used**. You only need it when running `REPLAY_LLM=false` against the real held-out seed during grading. You can develop the entire system without spending a dollar — generate real transcripts once at the end to commit them.

---

## 3. Local Software

### Python packages
```bash
pip install -r requirements.txt
```

**Full `requirements.txt`:**
```
# Core agent framework
langgraph>=0.2
langchain-anthropic>=0.3
anthropic>=0.40
pydantic>=2.0
pydantic-settings>=2.0

# Database
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
psycopg2-binary>=2.9

# API
fastapi>=0.115
uvicorn[standard]>=0.30

# Intake parsers
pdfplumber>=0.11

# Audit verification (already in kit)
jsonschema>=4.0
pypdf>=4.0

# Dev / eval
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
python-dotenv>=1.0
```

### Docker services (run via Docker Compose — nothing to install separately)
- **PostgreSQL 16** — records, audit log, LangGraph checkpointer
- **Redis 7** — exception queue (optional: can use Postgres as queue to keep stack simpler)

---

## 4. Accounts to Create

| Service | Why | Free? |
|---------|-----|-------|
| **Anthropic** (platform.anthropic.com) | Claude API for Worker + Verifier agents | Pay-as-you-go; ~$1–3 for this project |
| **GitHub** | Public repo required for submission | Free |
| **Loom** (loom.com) | Narrated video walkthrough — mandatory for submission | Free tier works (under 5 min) |

---

## 5. Environment File

Create `.env` in the project root — **never commit this file.**

```bash
# ── Required ────────────────────────────────────────────────────
CASE_ID=CEDX-DCB8F2
DATABASE_URL=postgresql+asyncpg://cedx:cedx@db:5432/cedx

# ── LLM ─────────────────────────────────────────────────────────
LLM_API_KEY=sk-ant-api03-YOUR_KEY_HERE
LLM_MODEL=claude-haiku-4-5-20251001        # default cheap model

# ── Pipeline control ─────────────────────────────────────────────
REPLAY_LLM=true          # true = offline replay (default, no API needed)
SEED_DIR=/app/seed       # override to /app/held-out at grading

# ── Cost ceilings ────────────────────────────────────────────────
MAX_COST_PER_RECORD=0.05   # USD; triggers BUDGET_EXCEEDED if exceeded
MAX_STEPS_PER_RECORD=10    # triggers AGENT_LOOP if exceeded

# ── Logging ──────────────────────────────────────────────────────
LOG_LEVEL=INFO
```

---

## 6. Docker Compose Services

Your `docker-compose.yml` must define these (the kit already has a skeleton — extend it):

```yaml
services:
  app:
    build: .
    env_file: .env
    volumes:
      - ./seed:/app/seed:ro        # read-only — never write to seed
      - ./out:/app/out             # runtime output
      - ./transcripts:/app/transcripts
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"                # FastAPI approval API

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: cedx
      POSTGRES_PASSWORD: cedx
      POSTGRES_DB: cedx
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cedx"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

---

## 7. GitHub Repository Setup

```bash
# Initialize and push
git init
git remote add origin https://github.com/YOUR_USERNAME/cedx-dcb8f2
git add .
git commit -m "tracer: scaffold CEDX-DCB8F2 — 3 agents, SCOPE.md, docker compose"
git push -u origin main
```

**Repo must be public** — the grader accesses it directly.

**`.gitignore` — critical entries:**
```
.env
__pycache__/
*.pyc
out/audit.json
out/package/
.venv/
*.egg-info/
```

**What MUST be committed (not gitignored):**
```
/transcripts/     ← committed LLM transcripts (REPLAY_LLM=true depends on these)
/prompts/         ← versioned prompt files
/eval/            ← golden cases
/seed/            ← read-only; already in the kit
SCOPE.md          ← first thing you push (authorship anchor)
ARCHITECTURE.md
DECISIONS.md
CLAUDE.md
```

---

## 8. Verification — Confirm Everything Works

Run these before writing any agent code:

```bash
# 1. Python version
python3 --version   # must be 3.11+

# 2. Docker
docker compose up db -d
docker compose ps   # db should show "healthy"

# 3. Python packages
pip install -r requirements.txt
python -c "import langgraph, anthropic, pydantic, fastapi; print('all good')"

# 4. Anthropic API (only needed when REPLAY_LLM=false)
python -c "
import anthropic, os
client = anthropic.Anthropic(api_key=os.environ['LLM_API_KEY'])
r = client.messages.create(
    model='claude-haiku-4-5-20251001',
    max_tokens=10,
    messages=[{'role': 'user', 'content': 'hi'}]
)
print('API works:', r.content[0].text)
"

# 5. Kit verify script
python verify_audit.py --help   # should print usage, not an error
```

---

## 9. What You Do NOT Need

- No OpenAI key — the task says support ≥1 of `gpt-4o-mini`, `claude-3-5-haiku`, `gemini-1.5-flash`; Claude alone satisfies this
- No AWS / GCP / Azure — everything runs locally in Docker
- No paid Loom plan — free tier allows recordings under 5 min
- No separate vector database — this pipeline does not need RAG
- No Kubernetes or complex infra — Docker Compose is the entire deployment target

---

## 10. Quick-Start Sequence

Once all the above is in place, follow this exact order:

```bash
# Step 1 — Fill SCOPE.md and push (authorship anchor — do this first, before anything else)
cp SCOPE.template.md SCOPE.md
# Edit SCOPE.md: your name, CEDX-DCB8F2, industry choice, amendment details
git add SCOPE.md && git commit -m "tracer: SCOPE.md CEDX-DCB8F2" && git push

# Step 2 — Set up environment
cp .env.example .env       # then fill in your LLM_API_KEY
docker compose up db -d    # start Postgres

# Step 3 — Python environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Step 4 — Verify the kit
python verify_audit.py --help

# Step 5 — Start building (in this order)
# core/models.py first — all Pydantic schemas before any agent code
# then agents/orchestrator.py → agents/worker.py → agents/verifier.py
# then core/graph.py → api/approval.py → intake parsers
```

---

## 11. Cost Breakdown

| Component | Model | Estimated cost |
|-----------|-------|---------------|
| Worker (routine records) | claude-haiku-4-5-20251001 | ~$0.0002/record |
| Worker (high-value / escalated) | claude-sonnet-4-6 | ~$0.004/record |
| Verifier (all records) | claude-sonnet-4-6 | ~$0.004/record |
| **Total for ~20 seed records** | | **~$0.10–0.15** |
| **Total for held-out grading (~25 records)** | | **~$0.15–0.25** |
| **Safe budget to load** | | **$5.00** |

The Anthropic API key is the **only thing that costs money** in this entire project. Everything else — Postgres, Docker, Python, GitHub, Loom (free tier) — is free.

---

## 12. Amendment Reference (CEDX-DCB8F2)

```
CASE_ID:   CEDX-DCB8F2
Role R:    legal_counsel
Threshold: 32,000 (USD)

Rule: any record whose normalized amount >= 32,000 requires an additional
      approval from an actor with role "legal_counsel", on top of standard
      operator approval, before delivery is permitted.

Print at startup:  AMENDMENT: role=legal_counsel threshold=32000
Record in audit:   audit.json → amendment.role + amendment.threshold
Probe:             make probe-approval must exit 0 (delivery refused without amendment approval)
```
