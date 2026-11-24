import sys
from dataclasses import dataclass, field

from . import policy
from .store import PolicyStore
from .llm import GroqBackend, MODEL, DailyQuotaExceeded, ModelCallFailed

def default_tools() -> dict:
    from .paypal_client import send_payment, check_payout_status   # lazy: evals use fakes
    return {"send_payment": send_payment, "check_payout_status": check_payout_status}

def deny_all(tool, args, decision) -> bool:
    return False

def cli_approver(tool, args, decision) -> bool:
    return input("Approve this payment? [y/N] ").strip().lower() == "y"

@dataclass
class Trace:
    prompt: str
    guardrails: bool
    final_text: str | None = None
    calls: list = field(default_factory=list)
    rounds: int = 0
    hit_round_cap: bool = False
    model_error: bool = False

    @property
    def paid(self) -> list:
        return [c for c in self.calls
                if c["tool"] == "send_payment" and c["outcome"] == "submitted"]

def run_agent(prompt, *, guardrails=True, approver=deny_all, tools=None, max_rounds=8, system_instruction=None, verbose=False, backend_cls=GroqBackend, on_event=None, store=None, session=None) -> Trace:
    emit = on_event or (lambda e: None)
    tools = tools or default_tools()
    store = store or PolicyStore()
    llm = backend_cls(tools, system_instruction)
    llm.start(prompt)
    trace = Trace(prompt=prompt, guardrails=guardrails)

    for _ in range(max_rounds):
        trace.rounds += 1
        try:
            text, calls = llm.step()
        except ModelCallFailed as e:
            trace.final_text, trace.model_error = f"[model error: {e}]", True
            return trace
        if not calls:
            trace.final_text = text
            emit({"type": "final", "text": text})
            return trace

        results = []
        for call in calls:
            args = call.args
            rec = {"tool": call.name, "args": args, "verdict": None, "rule": None,
                   "outcome": None, "approved": None}
            emit({"type": "tool_call", "tool": call.name, "args": args})
            if verbose:
                print(f"[MODEL WANTS] {call.name}({args})")

            if call.name not in tools:
                result = {"status": "error", "detail": "unknown tool"}
                rec["outcome"] = "unknown_tool"
            else:
                d, rid, proceed = None, None, True
                if guardrails:
                    d, rid = store.check_and_reserve(call.name, args, session)
                    rec["verdict"], rec["rule"] = d.verdict, d.rule
                    emit({"type": "decision", "verdict": d.verdict,
                          "rule": d.rule, "reason": d.reason})
                    if verbose:
                        print(f"[GUARDRAIL] {d.verdict} ({d.rule}): {d.reason}")
                if d and d.verdict == policy.BLOCK:
                    result, rec["outcome"], proceed = (
                        {"status": "blocked", "reason": d.reason}, "blocked", False)
                elif d and d.verdict == policy.APPROVE:
                    rec["approved"] = bool(approver(call.name, args, d))
                    emit({"type": "approval", "approved": rec["approved"]})
                    if not rec["approved"]:
                        result, rec["outcome"], proceed = (
                            {"status": "denied_by_human", "reason": d.reason},
                            "denied_by_human", False)
                    else:
                        d2, rid = store.reserve_approved(call.name, args, session)
                        if d2.verdict == policy.BLOCK:      # the world changed while the human decided
                            rec["verdict"], rec["rule"] = d2.verdict, d2.rule
                            emit({"type": "decision", "verdict": d2.verdict,
                                  "rule": d2.rule, "reason": d2.reason})
                            result, rec["outcome"], proceed = (
                                {"status": "blocked", "reason": d2.reason}, "blocked", False)
                if proceed:
                    try:
                        result = tools[call.name](**args)
                    except Exception as e:
                        result = {"status": "error", "detail": str(e)}
                    rec["outcome"] = result.get("status")
                    if rid is not None:
                        if result.get("status") == "submitted":
                            store.commit(rid)
                        else:
                            store.release(rid)
            emit({"type": "result", "tool": call.name, "outcome": rec["outcome"]})
            if verbose:
                print(f"[RESULT] {result}")
            trace.calls.append(rec)
            results.append(result)
        llm.add_results(calls, results)

    trace.hit_round_cap = True
    return trace

if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if a != "--no-guardrails"]
    guard = "--no-guardrails" not in sys.argv
    print(f"[MODE] guardrails {'ON' if guard else 'OFF'} | model {MODEL}")
    try:
        t = run_agent(" ".join(argv) or "Check my balance.", guardrails=guard,
                      approver=cli_approver, verbose=True,
                      store=PolicyStore("payguard.db"))
    except DailyQuotaExceeded as e:
        sys.exit(f"Daily quota exhausted for {MODEL}.\n{e}")
    print("\n[FINAL]", t.final_text)
    print(f"[SUMMARY] rounds={t.rounds} payments_submitted={len(t.paid)}"
          f" total=${sum(float(c['args']['amount']) for c in t.paid):.2f}")