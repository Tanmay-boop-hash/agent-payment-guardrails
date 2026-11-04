import json, math, re, time
from dataclasses import dataclass
from pathlib import Path

ALLOW, BLOCK, APPROVE = "allow", "block", "needs_approval"

CONFIG = {
    "allowed_recipients": {
        "sb-eeygt53271593@personal.example.com",
        "sb-ru47ew53270980@personal.example.com",
    },
    "max_per_payment": 100.0,    # hard cap: above this, block
    "approval_above": 25.0,      # above this, a human must confirm
    "daily_limit": 200.0,        # rolling 24h total
    "duplicate_window_s": 600,   # same recipient+amount within 10 min
}

AUDIT = Path("audit_log.jsonl")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@dataclass
class Decision:
    verdict: str
    rule: str
    reason: str

def _log(event: str, **fields):
    with AUDIT.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "event": event, **fields}) + "\n")

def _recent_executed(window_s: float) -> list:
    if not AUDIT.exists():
        return []
    now, out = time.time(), []
    for line in AUDIT.read_text().splitlines():
        rec = json.loads(line)
        if rec["event"] == "executed" and now - rec["ts"] < window_s:
            out.append(rec)
    return out

def record_executed(recipient: str, amount: float):
    _log("executed", recipient=recipient.strip().lower(), amount=float(amount))

def _evaluate(tool: str, args: dict) -> Decision:
    if tool != "send_payment":
        return Decision(ALLOW, "read_only", "tool does not move money")

    recipient = str(args.get("recipient", "")).strip().lower()
    try:
        amount = float(args.get("amount"))
    except (TypeError, ValueError):
        return Decision(BLOCK, "bad_amount", "amount is not a number")
    if not math.isfinite(amount) or amount <= 0:
        return Decision(BLOCK, "bad_amount", f"invalid amount {amount}")
    if not EMAIL_RE.match(recipient):
        return Decision(BLOCK, "bad_recipient", "recipient is not a valid email")
    if recipient not in CONFIG["allowed_recipients"]:
        return Decision(BLOCK, "allowlist", f"{recipient} is not an approved recipient")
    if amount > CONFIG["max_per_payment"]:
        return Decision(BLOCK, "max_per_payment",
                        f"${amount:.2f} exceeds the ${CONFIG['max_per_payment']:.0f} cap")

    recent = _recent_executed(86400)
    if sum(r["amount"] for r in recent) + amount > CONFIG["daily_limit"]:
        return Decision(BLOCK, "daily_limit", "would exceed the rolling 24h limit")

    now = time.time()
    if any(r["recipient"] == recipient and r["amount"] == amount
           and now - r["ts"] < CONFIG["duplicate_window_s"] for r in recent):
        return Decision(APPROVE, "duplicate", "same recipient and amount paid recently")
    if amount > CONFIG["approval_above"]:
        return Decision(APPROVE, "approval_threshold",
                        f"${amount:.2f} is above the ${CONFIG['approval_above']:.0f} auto-approve limit")
    return Decision(ALLOW, "within_policy", "all checks passed")

def check(tool: str, args: dict) -> Decision:
    d = _evaluate(tool, args)
    _log("decision", tool=tool, args=args, verdict=d.verdict, rule=d.rule, reason=d.reason)
    return d