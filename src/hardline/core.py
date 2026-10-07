import sqlite3
from pathlib import Path


def eligible(event, user, senders, assigned_threads=(), aliases=(), direct=False):
    c = event.get("content", {})
    relation = c.get("m.relates_to", {})
    body_mentions = {
        word.strip(".,!?;()[]{}").casefold() for word in c.get("body", "").split()
    }
    short_name = user.split(":", 1)[0].casefold()
    text = (
        " ".join(w for w in c.get("body", "").split() if not w.startswith("@"))
        .strip()
        .lower()
        .strip(".!")
    )
    if text in {"thanks", "thank you", "ok", "okay", "ack", "acknowledged"}:
        return False
    return (
        event.get("type") == "m.room.message"
        and c.get("msgtype") == "m.text"
        and event.get("sender") in senders
        and event.get("sender") != user
        and relation.get("rel_type") != "m.replace"
        and (
            direct
            or user in c.get("m.mentions", {}).get("user_ids", [])
            or user.casefold() in body_mentions
            or short_name in body_mentions
            or any(
                "@" + alias.casefold().lstrip("@") in body_mentions for alias in aliases
            )
            or (
                relation.get("rel_type") == "m.thread"
                and relation.get("event_id") in assigned_threads
            )
        )
    )


class Queue:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS events(id TEXT,agent TEXT,room TEXT,status TEXT,turn TEXT,PRIMARY KEY(id,agent)); CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);"
        )
        columns = self.db.execute("PRAGMA table_info(events)").fetchall()
        if sum(bool(c[5]) for c in columns) == 1:
            with self.db:
                self.db.execute("ALTER TABLE events RENAME TO events_v1")
                self.db.execute(
                    "CREATE TABLE events(id TEXT,agent TEXT,room TEXT,status TEXT,turn TEXT,PRIMARY KEY(id,agent))"
                )
                self.db.execute("INSERT INTO events SELECT * FROM events_v1")
        if "root" not in {c[1] for c in self.db.execute("PRAGMA table_info(events)")}:
            self.db.execute("ALTER TABLE events ADD COLUMN root TEXT")
            self.db.commit()
        Path(path).chmod(0o600)

    def cursor(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()
        return row[0] if row else None

    def capture(self, events, cursor):
        with self.db:
            for event in events:
                eid, agent, room = event[:3]
                root = event[3] if len(event) > 3 else eid
                count = self.db.execute(
                    "SELECT count(*) FROM events WHERE root=? AND status!=?",
                    (root, "loop_limit"),
                ).fetchone()[0]
                status = (
                    "loop_limit"
                    if count >= 20
                    else (event[4] if len(event) > 4 else "pending")
                )
                self.db.execute(
                    "INSERT OR IGNORE INTO events(id,agent,room,status,turn,root) VALUES(?,?,?,?,NULL,?)",
                    (eid, agent, room, status, root),
                )
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('cursor',?)", (cursor,))

    def pending(self):
        return self.db.execute(
            "SELECT id,agent,room FROM events WHERE status='pending'"
        ).fetchall()

    def mark(self, event, status, turn=None, owner=None):
        with self.db:
            self.db.execute(
                "UPDATE events SET status=?,turn=? WHERE id=?"
                + (" AND agent=?" if owner else ""),
                (status, turn, event, owner) if owner else (status, turn, event),
            )
