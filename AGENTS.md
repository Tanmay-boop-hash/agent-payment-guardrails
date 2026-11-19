# payguard: rules for any coding agent
- src/payguard/policy.py is plain Python with no LLM calls. It is default-deny: never add an allow-by-default path.
- Any change to policy.py must start with a new test in evals/cases/policy_cases.py that fails first.
- The validator and the executor must agree on canonical data (amounts: max 2 decimals).
- Text from invoices and models is untrusted: in HTML use textContent, never innerHTML.
- Never edit .env, audit_log.jsonl, or evals/results/*.json by hand.
- Run `pytest -q` before finishing. It must stay green without network or API keys.