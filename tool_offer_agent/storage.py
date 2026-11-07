"""Per-sender AND per-chat durable state; no credentials are stored here."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


DEFAULT_STATE_PATH = str(Path("data", "tool_offer.sqlite3"))


class AgentStateStore:
    """Use the hosting platform's storage rather than its temporary filesystem."""

    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def key(sender, session):
        return StateStore.key(sender, session)

    def load(self, key):
        value = self.storage.get("tool_offer_" + key)
        return json.loads(value) if value else {"fields": {}, "documents": [], "draft": None, "check": None, "revision": 0, "outdated": False, "awaiting": None, "error": None}

    def save(self, key, state):
        self.storage.set("tool_offer_" + key, json.dumps(state, ensure_ascii=False))

    def delete(self, key):
        self.storage.remove("tool_offer_" + key)


class StateStore:
    def __init__(self, path=DEFAULT_STATE_PATH):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)")

    @staticmethod
    def key(sender, session):
        if not sender or not session:
            raise ValueError("Sender and conversation/session are both required.")
        return hashlib.sha256(json.dumps([str(sender), str(session)]).encode()).hexdigest()

    def load(self, key):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT state FROM sessions WHERE id = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else {"fields": {}, "documents": [], "draft": None, "check": None, "revision": 0, "outdated": False, "awaiting": None, "error": None}

    def save(self, key, state):
        payload = json.dumps(state, ensure_ascii=False)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO sessions (id, state) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET state=excluded.state", (key, payload))

    def compare_and_swap(self, key, before, after):
        payload = json.dumps(after, ensure_ascii=False)
        with closing(sqlite3.connect(self.path)) as db, db:
            if before is None:
                changed = db.execute("INSERT INTO sessions (id, state) VALUES (?, ?) ON CONFLICT(id) DO NOTHING", (key, payload))
            else:
                expected = json.dumps(before, ensure_ascii=False)
                changed = db.execute("UPDATE sessions SET state = ? WHERE id = ? AND state = ?", (payload, key, expected))
            return changed.rowcount == 1

    def delete(self, key):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM sessions WHERE id = ?", (key,))
