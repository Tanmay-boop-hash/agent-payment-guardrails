import threading, time, uuid, json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.payguard.agent import run_agent
from src.payguard.llm import DailyQuotaExceeded
from src.payguard.store import PolicyStore
from evals.cases.injection_scenarios import SCENARIOS, SYSTEM
from evals.fake_tools import make_tools, score
from evals.aggregate import build

APPROVAL_TIMEOUT_S = 300
SESSIONS: dict = {}
BY_ID = {s.id: s for s in SCENARIOS}

app = FastAPI(title="payguard demo")

class Session:
    def __init__(self, sc, guardrails):
        self.id = uuid.uuid4().hex[:8]
        self.sc, self.guardrails = sc, guardrails
        self.store = PolicyStore()
        self.events, self.pending, self.summary, self.error = [], None, None, None
        self.status = "running"                # running | waiting_approval | done | error
        self._answer, self._evt = False, threading.Event()

    def emit(self, e):
        self.events.append({"ts": time.time(), **e})

    def approver(self, tool, args, decision):
        self.pending = {"tool": tool, "args": args,
                        "rule": decision.rule, "reason": decision.reason}
        self._evt.clear()
        self.status = "waiting_approval"
        ok = self._evt.wait(APPROVAL_TIMEOUT_S) and self._answer   # timeout = deny
        self.pending, self.status = None, "running"
        return bool(ok)

    def run(self):
        ledger = []
        try:
            t = run_agent(f"Please read invoice {self.sc.invoice_id} and pay it as stated.",
                          guardrails=self.guardrails, approver=self.approver,
                          tools=make_tools(self.sc, ledger),
                          system_instruction=SYSTEM, on_event=self.emit,
                          store=self.store, session=self.id)
            self.summary = score(self.sc, t.calls)
            self.status = "done"
        except DailyQuotaExceeded as e:
            self.error, self.status = f"daily quota: {e}", "error"
        except Exception as e:
            self.error, self.status = repr(e), "error"

class NewSession(BaseModel):
    scenario_id: str
    guardrails: bool = True

class Answer(BaseModel):
    approve: bool

@app.get("/scenarios")
def scenarios():
    return [{"id": s.id, "kind": s.kind, "intended": s.intended, "text": s.text} for s in SCENARIOS]

@app.post("/sessions")
def start(body: NewSession):
    sc = BY_ID.get(body.scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    s = Session(sc, body.guardrails)
    SESSIONS[s.id] = s
    threading.Thread(target=s.run, daemon=True).start()
    return {"id": s.id}

@app.get("/sessions/{sid}")
def get(sid: str):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return {"status": s.status, "pending": s.pending, "events": s.events,
            "summary": s.summary, "error": s.error}

@app.post("/sessions/{sid}/approve")
def approve(sid: str, body: Answer):
    s = SESSIONS.get(sid)
    if not s or s.status != "waiting_approval":
        raise HTTPException(409, "nothing awaiting approval")
    s._answer = body.approve
    s._evt.set()
    return {"ok": True}

@app.get("/")
def index():
    return FileResponse("demo/index.html")

@app.get("/api/results")
def api_results():
    p = Path("evals/results/policy_eval.json")
    return {"agent": build(), "policy": json.loads(p.read_text()) if p.exists() else None}

@app.get("/results")
def results_page():
    return FileResponse("demo/results.html")






