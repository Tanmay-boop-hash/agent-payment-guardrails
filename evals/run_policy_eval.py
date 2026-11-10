import tempfile, time, statistics
from pathlib import Path
from src.payguard import policy
from evals.cases.policy_cases import CASES, seed_audit

rows = []
with tempfile.TemporaryDirectory() as d:
    for c in CASES:
        policy.AUDIT = Path(d) / f"{c.id}.jsonl"
        seed_audit(policy.AUDIT, c.seed)
        t = time.perf_counter()
        dec = policy.check(c.tool, c.args)
        rows.append((c, dec, (time.perf_counter() - t) * 1000))

attacks = [r for r in rows if r[0].kind == "attack"]
legit   = [r for r in rows if r[0].kind == "legit"]
stopped = sum(d.verdict != policy.ALLOW for _, d, _ in attacks)   # blocked OR sent to a human
false_block = sum(d.verdict == policy.BLOCK for _, d, _ in legit)
prompted    = sum(d.verdict == policy.APPROVE for _, d, _ in legit)
lat = sorted(ms for *_, ms in rows)

print(f"attack cases: {len(attacks)} | stopped: {stopped} ({stopped/len(attacks):.0%}) | "
      f"unguarded would have executed: {len(attacks)}")
print(f"legit cases:  {len(legit)} | false-block: {false_block} ({false_block/len(legit):.0%}) | "
      f"approval prompts: {prompted}")
print(f"policy latency: p50 {statistics.median(lat):.2f} ms | p95 {lat[int(len(lat)*.95)-1]:.2f} ms")