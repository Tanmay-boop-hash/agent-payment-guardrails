import json, sys
from src.payguard.llm import MODEL

cache = json.load(open("evals/results/agent_runs.json"))
for sid in sys.argv[1:]:
    for mode in ("off", "on"):
        run = cache.get(f"{MODEL}|{sid}|{mode}|0")
        print(f"\n== {sid} | guardrails {mode} ==")
        for c in run["calls"]:
            print(f"  {c['tool']}({c['args']}) verdict={c['verdict']} "
                  f"rule={c['rule']} outcome={c['outcome']}")
        print("  FINAL:", (run["final_text"] or "")[:300])