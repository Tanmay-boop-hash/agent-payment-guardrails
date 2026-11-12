import os, sys, time
from dataclasses import dataclass, field
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors

from . import policy

load_dotenv()
MODEL = "gemini-3.5-flash"          # one place to change
_client = None

class DailyQuotaExceeded(Exception):
    pass

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

def default_tools() -> dict:
    # lazy import: evals using fake tools never need PayPal credentials
    from .paypal_client import send_payment, check_payout_status
    return {"send_payment": send_payment, "check_payout_status": check_payout_status}

def call_model(contents, config, retries=3):
    for attempt in range(retries + 1):
        try:
            return _get_client().models.generate_content(
                model=MODEL, contents=contents, config=config)
        except errors.ClientError as e:
            if e.code != 429:
                raise
            msg = str(e)
            if "perday" in msg.lower().replace(" ", "").replace("_", ""):
                raise DailyQuotaExceeded(msg) from e
            if attempt == retries:
                raise
            wait = 5 * 2 ** attempt            # 5s, 10s, 20s
            print(f"[429 per-minute limit] retrying in {wait}s")
            time.sleep(wait)

def deny_all(tool, args, decision) -> bool:
    return False                                # fail closed: no approver = no approval

def cli_approver(tool, args, decision) -> bool:
    return input("Approve this payment? [y/N] ").strip().lower() == "y"

@dataclass
class Trace:
    prompt: str
    guardrails: bool
    final_text: str | None = None
    calls: list = field(default_factory=list)   # one dict per tool call the model made
    rounds: int = 0
    hit_round_cap: bool = False

    @property
    def paid(self) -> list:
        return [c for c in self.calls
                if c["tool"] == "send_payment" and c["outcome"] == "submitted"]

def run_agent(prompt, *, guardrails=True, approver=deny_all, tools=None,
              max_rounds=8, system_instruction=None, verbose=False) -> Trace:
    tools = tools or default_tools()
    config = types.GenerateContentConfig(
        tools=list(tools.values()),
        system_instruction=system_instruction,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    trace = Trace(prompt=prompt, guardrails=guardrails)

    for _ in range(max_rounds):
        trace.rounds += 1
        resp = call_model(contents, config)
        if not resp.candidates or resp.candidates[0].content is None:
            trace.final_text = ""                # blocked/empty response from the API
            return trace
        contents.append(resp.candidates[0].content)

        if not resp.function_calls:
            trace.final_text = resp.text
            return trace

        parts = []
        for call in resp.function_calls:
            args = dict(call.args)
            rec = {"tool": call.name, "args": args,
                   "verdict": None, "rule": None, "outcome": None}
            if verbose:
                print(f"[MODEL WANTS] {call.name}({args})")

            if call.name not in tools:
                result = {"status": "error", "detail": "unknown tool"}
                rec["outcome"] = "unknown_tool"
            else:
                if guardrails:
                    d = policy.check(call.name, args)
                    rec["verdict"], rec["rule"] = d.verdict, d.rule
                    if verbose:
                        print(f"[GUARDRAIL] {d.verdict} ({d.rule}): {d.reason}")
                if guardrails and d.verdict == policy.BLOCK:
                    result = {"status": "blocked", "reason": d.reason}
                    rec["outcome"] = "blocked"
                elif guardrails and d.verdict == policy.APPROVE and not approver(call.name, args, d):
                    result = {"status": "denied_by_human", "reason": d.reason}
                    rec["outcome"] = "denied_by_human"
                else:
                    try:
                        result = tools[call.name](**args)
                    except Exception as e:       # bad args from the model must not crash the loop
                        result = {"status": "error", "detail": str(e)}
                    rec["outcome"] = result.get("status")
                    if (guardrails and call.name == "send_payment"
                            and result.get("status") == "submitted"):
                        policy.record_executed(args["recipient"], args["amount"])
            if verbose:
                print(f"[RESULT] {result}")
            trace.calls.append(rec)
            parts.append(types.Part.from_function_response(name=call.name, response=result))
        contents.append(types.Content(role="user", parts=parts))

    trace.hit_round_cap = True
    return trace

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-guardrails"]
    guard = "--no-guardrails" not in sys.argv
    print(f"[MODE] guardrails {'ON' if guard else 'OFF'} | model {MODEL}")
    try:
        t = run_agent(" ".join(args) or "Check my balance.", guardrails=guard,
                      approver=cli_approver, verbose=True)
    except DailyQuotaExceeded as e:
        sys.exit(f"Daily quota exhausted for {MODEL}. Switch MODEL or wait.\n{e}")
    print("\n[FINAL]", t.final_text)
    print(f"[SUMMARY] rounds={t.rounds} payments_submitted={len(t.paid)}"
          f" total=${sum(float(c['args']['amount']) for c in t.paid):.2f}")