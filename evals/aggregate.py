import json
from pathlib import Path

from src.payguard import policy
from src.payguard.llm import MODEL
from evals.cases.injection_scenarios import SCENARIOS
from evals.fake_tools import score
from evals.stats import wilson

CACHE = Path("evals/results/agent_runs.json")
OUT = Path("evals/results/results.json")

def _runs_for(cache, model, sid, mode):
    out, trial = [], 0
    while(run := cache.get(f"{model}|{sid}|{mode}|{trial}")):
        s = score(next(x for x in SCENARIOS if x.id == sid), run["calls"])
        intervened = any(c["outcome"] in ("blocked", "denied by human") for c in run["calls"])
        out.append({
            "attack": s["attack_success"],
            "task": s["task_success"],
            "blocked_incomplete": intervened and not s["task_success"] and not s["attack_success"],
            "rules": {c["rule"] for c in run["calls"] if c["verdict"] in (policy.BLOCK, policy.APPROVE)},
        })
        trial += 1
    return out


def _tot(rows, kind, mode, bad):
    sel = [r[mode] for r in rows if r["kind"] == kind]
    n, k = sum(x["n"] for x in sel), sum(bad(x) for x in sel)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "lo": lo, "hi": hi}

def build(model=MODEL) -> dict:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = []
    for sc in SCENARIOS:
        row = {"id": sc.id, "kind": sc.kind}
        for mode in ("off", "on"):
            rs = _runs_for(cache, model, sc.id, mode)
            row[mode] = {"n": len(rs),
                         "attack": sum(r["attack"] for r in rs),
                         "task": sum(r["task"] for r in rs),
                         "blocked_incomplete": sum(r["blocked_incomplete"] for r in rs),
                         "rules": sorted({x for r in rs for x in r["rules"]})}
        rows.append(row)
    return {
        "model": model,
        "scenarios": rows,
        "attack_success": {m: _tot(rows, "attack", m, lambda x: x["attack"]) for m in ("off", "on")},
        "control_false_block": {m: _tot(rows, "control", m, lambda x: x["n"] - x["task"])
                                for m in ("off", "on")},
    }


if __name__ == "__main__":
    res = build()
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "scenarios"}, indent=1))


