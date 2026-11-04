import os, uuid, httpx
from dotenv import load_dotenv
load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"
_auth = (os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"])

def _token() -> str:
    r = httpx.post(f"{BASE}/v1/oauth2/token", auth=_auth,
                   data={"grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]

def send_payment(recipient: str, amount: float) -> dict:
    """Send a payout in USD to a PayPal account identified by email."""
    body = {
        "sender_batch_header": {"sender_batch_id": str(uuid.uuid4()),
                                "email_subject": "Payment"},
        "items": [{"recipient_type": "EMAIL", "receiver": recipient,
                   "amount": {"value": f"{amount:.2f}", "currency": "USD"},
                   "sender_item_id": str(uuid.uuid4())}],
    }
    r = httpx.post(f"{BASE}/v1/payments/payouts", json=body,
                   headers={"Authorization": f"Bearer {_token()}"})
    if r.status_code != 201:
        return {"status": "error", "detail": r.json().get("message", r.text)}
    return {"status": "submitted",
            "batch_id": r.json()["batch_header"]["payout_batch_id"]}

def check_payout_status(batch_id: str) -> dict:
    """Check the status of a payout batch by its batch id."""
    r = httpx.get(f"{BASE}/v1/payments/payouts/{batch_id}",
                  headers={"Authorization": f"Bearer {_token()}"})
    if r.status_code != 200:
        return {"status": "error", "detail": r.text}
    return {"status": r.json()["batch_header"]["batch_status"]}