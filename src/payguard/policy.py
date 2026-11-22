import math, re
from dataclasses import dataclass
from typing import NamedTuple

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

READ_ONLY = {"check_payout_status", "read_invoice"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class Payment(NamedTuple):
    ts: float
    recipient: str
    cents: int

@dataclass(frozen=True)
class Decision:
    verdict: str
    rule: str
    reason: str
    recipient: str | None = None   # canonical form the policy approved
    cents: int | None = None

def _cents(dollars: float) -> int:
    return round(dollars * 100)

def evaluate(tool, args, recent, now, approved=False, cfg=CONFIG) -> Decision:
    if tool in READ_ONLY:
        return Decision(ALLOW, "read_only", "tool does not move money")
    if tool != "send_payment":
        return Decision(BLOCK, "unknown_tool", f"{tool} is not a registered tool")

    recipient = str(args.get("recipient", "")).strip().lower()
    raw = args.get("amount")
    if isinstance(raw, bool):
        return Decision(BLOCK, "bad_amount", "amount must be a number")
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return Decision(BLOCK, "bad_amount", "amount is not a number")
    if not math.isfinite(amount) or amount <= 0:
        return Decision(BLOCK, "bad_amount", f"invalid amount {amount}")
    if round(amount, 2) != amount:
        return Decision(BLOCK, "bad_amount", "amount has more than 2 decimal places")
    cents = _cents(amount)

    if not EMAIL_RE.match(recipient):
        return Decision(BLOCK, "bad_recipient", "recipient is not a valid email")
    if recipient not in cfg["allowed_recipients"]:
        return Decision(BLOCK, "allowlist", f"{recipient} is not an approved recipient")
    if cents > _cents(cfg["max_per_payment"]):
        return Decision(BLOCK, "max_per_payment",
                        f"${cents / 100:.2f} exceeds the ${cfg['max_per_payment']:.0f} cap")

    spent = sum(p.cents for p in recent if now - p.ts < 86400)
    if spent + cents > _cents(cfg["daily_limit"]):
        return Decision(BLOCK, "daily_limit", "would exceed the rolling 24h limit")

    ok = {"recipient": recipient, "cents": cents}
    if approved:    # a human said yes: soft rules are waived, hard rules above still held
        return Decision(ALLOW, "human_approved", "approved by a human", **ok)
    if any(p.recipient == recipient and p.cents == cents
           and now - p.ts < cfg["duplicate_window_s"] for p in recent):
        return Decision(APPROVE, "duplicate", "same recipient and amount paid recently", **ok)
    if cents > _cents(cfg["approval_above"]):
        return Decision(APPROVE, "approval_threshold",
                        f"${cents / 100:.2f} is above the ${cfg['approval_above']:.0f} auto-approve limit", **ok)
    return Decision(ALLOW, "within_policy", "all checks passed", **ok)