# payguard context
Deterministic policy layer between an LLM agent's tool calls and PayPal payouts.
- src/payguard/policy.py is plain Python, no LLM calls, default-deny. Never add allow-by-default paths.
- The validator and the executor must agree on canonical data (amounts: max 2 decimals).
- Unit tests: `pytest -q` (no network). Evals: `python -m evals.run_agent_eval` (Groq, cached in evals/results/).
- Never read or edit .env, audit_log.jsonl, or evals/results/*.json by hand.