# Uniform probe interface — graders invoke THESE targets identically on every repo,
# whatever language you build in. Wire each to your implementation. Exit codes matter.
# v2: adds agent-fleet targets (trace, eval, probe-agent-failure, probe-budget).
SEED_DIR ?= seed
REPLAY_LLM ?= true
PIPELINE_NOW ?= 2026-06-26

.PHONY: demo verify trace eval replay probe-approval probe-agent-failure probe-budget \
        probe-append-only probe-idempotency probe-crash clean

# Full multi-agent pipeline, offline replay, on $(SEED_DIR). Must write out/<package>,
# out/audit.json (incl. agents roster + per-record agent_trace + cost), out/exception_queue.json.
demo:
	SEED_DIR=$(SEED_DIR) REPLAY_LLM=$(REPLAY_LLM) PIPELINE_NOW=$(PIPELINE_NOW) python3 cli.py demo

# Run the PROVIDED gate on your audit bundle. Do not modify verify_audit.py.
verify:
	python3 verify_audit.py --audit out/audit.json --transcripts transcripts --schema audit.schema.json

# Print one record's FULL agent decision path from the log alone:
# which agent ran, model, tokens/cost, retries, Verifier verdict, where it routed.
trace:
	python3 cli.py trace $(ID)

# Run your agent eval harness: >=10 golden cases + an LLM-judge per agent. Print per-agent scores.
eval:
	python3 eval/run_eval.py

# Reconstruct one delivered output's DATA lineage from the append-only log alone.
replay:
	python3 cli.py replay $(ID)

# Exit 0 ONLY if delivery of a NON-approved item (incl. CASE_ID amendment role) is refused + logged.
probe-approval:
	python3 probes/probe_approval.py

# Exit 0 ONLY if a hallucinated/malformed WORKER output is caught by the Verifier and routed
# (AGENT_HALLUCINATION / AGENT_MALFORMED) — never delivered.
probe-agent-failure:
	python3 probes/probe_agent_failure.py

# Exit 0 ONLY if a record exceeding the per-record cost/step ceiling raises BUDGET_EXCEEDED
# and is downgraded or routed — never silently overspent.
probe-budget:
	python3 probes/probe_budget.py

# Exit 0 ONLY if mutating/deleting a past audit entry is refused.
probe-append-only:
	python3 probes/probe_append_only.py

# Exit 0 ONLY if running demo twice produces no duplicate outputs/exceptions/approvals.
probe-idempotency:
	python3 probes/probe_idempotency.py

# BONUS. Exit 0 if the pipeline resumes from the last completed stage after a SIGKILL.
probe-crash:
	python3 probes/probe_crash.py

clean:
	rm -rf out
