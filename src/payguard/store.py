import json, sqlite3, threading, time
from contextlib import contextmanager

from . import policy

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    recipient TEXT NOT NULL, 
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reserved', 'executed')));
CREATE TABLE IF NOT decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL, session TEXT, tool TEXT, args TEXT, 
    verdict TEXT, rule TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS payments_ts ON payments(ts);
"""

class PolicyStore:
    def __init__(self, path=":memory:", clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        # autocommit mode (isolation_level=None): we issue BEGIN/COMMIT ourselves
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _recent(self, db, now):
        rows = db.execute("SELECT ts, recipient, amount_cents FROM payments WHERE ts > ?", 
                          (now - 86400,)).fetchall()
        return [policy.Payment(*r) for r in rows]

    def _log(self, db, session, tool, args, d):
        db.execute("INSERT INTO decisions(ts, session, tool, args, verdict, rule, reason)"
                   " VALUES (?,?,?,?,?,?,?)", (self.clock(), session, tool, json.dumps(args, default=str), d.verdict, d.rule, d.reason))

    def _reserve(self, db, d, now):
        cur = db.execute("INSERT INTO payments(ts, recipient, amount_cents, status)"
                         " VALUES (?, ?, ?, 'reserved')", (now, d.recipient, d.cents))
        return cur.lastrowid

    def check_and_reserve(self, tool, args, session=None):
        """Decide and, if allowed to move money, hold the budget: one atomic step."""
        now = self.clock()
        with self._tx() as db:
            d = policy.evaluate(tool, args, self._recent(db, now), now)
            self._log(db, session, tool, args, d)
            rid = (self._reserve(db, d, now)
                   if d.verdict == policy.ALLOW and d.cents is not None else None)
        return d, rid

    def commit(self, rid):
        with self.tx() as db:
            db.execute("UPDATE payments SET status='executed' WHERE id=? AND status='reserved'", (rid,))

    def release(self, rid):
        with self._tx() as db:
            db.execute("DELETE FROM payments WHERE id=? AND status='reserved'", (rid,))

    # helpers for tests, seeding and the demo
    def add_executed(self, recipient, amount, age=0.0):
        with self._tx() as db:
            db.execute("INSERT INTO payments(ts, recipient, amount_cents, status)"
                       " VALUES (?,?,?,'executed')", (self.clock() - age, recipient.strip().lower(), round(float(amount * 100))))

    def exposure_cents(self):
        with self._tx() as db:
            return db.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE ts > ?", (self.clock() - 86400,)).fetchone()[0]
        
        


