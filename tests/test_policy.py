import pytest
from concurrent.futures import ThreadPoolExecutor

from src.payguard import policy
from src.payguard.store import PolicyStore
from evals.cases.policy_cases import CASES, seed_store, A, B

@pytest.fixture
def store():
    return PolicyStore()          # fresh in-memory DB: nothing shared between tests

@pytest.mark.parametrize("c", CASES, ids=lambda c: c.id)
def test_case(c, store):
    seed_store(store, c.seed)
    d, _ = store.check_and_reserve(c.tool, c.args)
    assert (d.verdict, d.rule) == (c.expect, c.rule)

def test_evaluate_is_pure():
    d = policy.evaluate("send_payment", {"recipient": A, "amount": 5}, [], now=0.0)
    assert (d.verdict, d.rule, d.cents) == (policy.ALLOW, "within_policy", 500)

def test_daily_limit_accumulates(store):
    store.add_executed(A, 90)
    store.add_executed(B, 80)
    d, _ = store.check_and_reserve("send_payment", {"recipient": A, "amount": 40})
    assert d.rule == "daily_limit"

def test_reservation_counts_before_commit(store):
    d, rid = store.check_and_reserve("send_payment", {"recipient": A, "amount": 20})
    assert d.verdict == policy.ALLOW and rid is not None
    d2, _ = store.check_and_reserve("send_payment", {"recipient": A, "amount": 20})
    assert (d2.verdict, d2.rule) == (policy.APPROVE, "duplicate")   # first one is still in flight

def test_release_frees_the_budget(store):
    d, rid = store.check_and_reserve("send_payment", {"recipient": A, "amount": 20})
    store.release(rid)
    d2, _ = store.check_and_reserve("send_payment", {"recipient": A, "amount": 20})
    assert d2.verdict == policy.ALLOW

def test_human_approval_cannot_override_hard_blocks(store):
    d, rid = store.reserve_approved("send_payment", {"recipient": A, "amount": 500})
    assert d.verdict == policy.BLOCK and rid is None
    d, rid = store.reserve_approved("send_payment", {"recipient": "attacker@evil.com", "amount": 10})
    assert d.rule == "allowlist" and rid is None

def test_approval_rechecks_budget_after_the_wait(store):
    d, _ = store.check_and_reserve("send_payment", {"recipient": A, "amount": 60})
    assert d.verdict == policy.APPROVE
    store.add_executed(B, 95)            # money spent while the human was deciding
    store.add_executed(A, 95)
    d2, rid = store.reserve_approved("send_payment", {"recipient": A, "amount": 60})
    assert (d2.verdict, d2.rule) == (policy.BLOCK, "daily_limit") and rid is None

def test_every_decision_is_logged(store):
    store.check_and_reserve("send_payment", {"recipient": A, "amount": 5})
    n = store._db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    assert n == 1

def test_concurrent_reservations_never_exceed_daily_limit(store):
    def attempt(i):
        who = A if i % 2 else B
        d, _ = store.check_and_reserve("send_payment",
                                       {"recipient": who, "amount": f"{(1000 + i) / 100:.2f}"})
        return d.verdict == policy.ALLOW
    with ThreadPoolExecutor(max_workers=16) as ex:
        allowed = sum(ex.map(attempt, range(50)))
    assert store.exposure_cents() <= 20000      # the invariant the old design could not guarantee
    assert allowed >= 15                        # and the guard isn't just blocking everything