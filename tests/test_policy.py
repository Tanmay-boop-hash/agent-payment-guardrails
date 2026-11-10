import pytest
from src.payguard import policy
from evals.cases.policy_cases import CASES, seed_audit, A, B

@pytest.fixture(autouse=True)
def isolated_audit(tmp_path, monkeypatch):
    # never touch the real audit log; every test starts with empty history
    monkeypatch.setattr(policy, "AUDIT", tmp_path / "audit.jsonl")

@pytest.mark.parametrize("c", CASES, ids=lambda c: c.id)
def test_case(c):
    seed_audit(policy.AUDIT, c.seed)
    d = policy.check(c.tool, c.args)
    assert (d.verdict, d.rule) == (c.expect, c.rule)

def test_daily_limit_accumulates_through_record_executed():
    policy.record_executed(A, 90)
    policy.record_executed(B, 80)
    assert policy.check("send_payment", {"recipient": A, "amount": 40}).rule == "daily_limit"

def test_every_decision_is_audited():
    policy.check("send_payment", {"recipient": A, "amount": 5})
    assert len(policy.AUDIT.read_text().splitlines()) == 1