import os, uuid, httpx
from dotenv import load_dotenv
load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"
auth = (os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"])

tok = httpx.post(f"{BASE}/v1/oauth2/token", auth=auth,
                 data={"grant_type": "client_credentials"}).json()["access_token"]

body = {
  "sender_batch_header": {"sender_batch_id": str(uuid.uuid4()),
                          "email_subject": "Test payout"},
  "items": [{
    "recipient_type": "EMAIL",
    "receiver": "sb-eeygt53271593@personal.example.com",
    "amount": {"value": "5.00", "currency": "USD"},
    "note": "test", "sender_item_id": "item-1",
  }],
}
r = httpx.post(f"{BASE}/v1/payments/payouts", json=body,
               headers={"Authorization": f"Bearer {tok}"})
print(r.status_code, r.json())
