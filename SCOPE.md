# SCOPE -- CEDX-DCB8F2

- **Candidate name:** Deepak Naidu
- **CASE_ID (assigned live):** CEDX-DCB8F2
- **Industry chosen (from cedxsystems.com/workflows):** Financial Services -- Document Processing & Compliance
- **Tier:** Tiny (kit default)
- **Stack / language:** Python 3.11, pure stdlib + Pydantic (no DB/API/LangGraph -- see DECISIONS.md)

## Amendment (computed from CASE_ID)
H = sha256("CEDX-DCB8F2"); role R = legal_counsel; threshold T = 32000

- **My role R:** legal_counsel
- **My threshold T:** 32000

## What I will build (the 5 governed stages)
- [x] Sources/Intake (parse feed.json + inbox PDF/email)
- [x] Orchestration (declarative normalize + exception queue, all reason codes)
- [x] Assembly (LLM structured output + abstain path)
- [x] Review (operator surface + approval state machine + my CASE_ID amendment)
- [x] Delivery (branded package + append-only audit + replay)

## What I will deliberately NOT build (and why)
- Postgres/Redis/FastAPI/LangGraph: verify_audit.py and the actual Makefile/Dockerfile/docker-compose.yml
  only require a single container, out/audit.json, and a CLI operator surface -- a DB/API adds
  failure surface on the grading box without satisfying any check that isn't already met by a
  JSON-file audit log + CLI. See DECISIONS.md.
