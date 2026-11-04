import sys
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os
import src.payguard.policy as policy

from src.payguard.paypal_client import send_payment, check_payout_status

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

TOOLS = {"send_payment": send_payment, "check_payout_status": check_payout_status}

config = types.GenerateContentConfig(
    tools=[send_payment, check_payout_status],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)

prompt = " ".join(sys.argv[1:]) or "Check my balance."
contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

for step in range(8):  # <-- THE LOOP (capped at 8 rounds)
    resp = client.models.generate_content(
        model="gemini-3.5-flash", contents=contents, config=config
    )
    contents.append(resp.candidates[0].content)  # keep the model's turn

    if not resp.function_calls:  # no tool wanted -> final answer
        print(resp.text)
        break

    parts = []
    for call in resp.function_calls:
        args = dict(call.args)
        print(f"[MODEL WANTS] {call.name}({args})")

        d = policy.check(call.name, args)
        print(f"[GUARDRAIL] {d.verdict} ({d.rule}): {d.reason}")

        if d.verdict == policy.BLOCK:
            result = {"status": "blocked", "reason": d.reason}
        elif d.verdict == policy.APPROVE and \
                input("Approve this payment? [y/N] ").strip().lower() != "y":
            result = {"status": "denied_by_human", "reason": d.reason}
        else:
            result = TOOLS[call.name](**args)
            if call.name == "send_payment" and result.get("status") == "submitted":
                policy.record_executed(args["recipient"], args["amount"])

        parts.append(types.Part.from_function_response(name=call.name, response=result))
    contents.append(types.Content(role="user", parts=parts))  # feed results back