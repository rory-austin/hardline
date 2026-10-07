"""Private metadata-only ledger for idempotent sends across token rotation."""

import hashlib
import json
import sqlite3
from pathlib import Path


class Sends:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sends(agent TEXT,request TEXT,digest TEXT,event TEXT,PRIMARY KEY(agent,request))"
        )
        Path(path).chmod(0o600)

    def reserve(self, agent, request, content):
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True).encode()
        ).hexdigest()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO sends VALUES(?,?,?,NULL)",
                (agent, request, digest),
            )
            row = self.db.execute(
                "SELECT digest,event FROM sends WHERE agent=? AND request=?",
                (agent, request),
            ).fetchone()
            if row[0] != digest:
                raise ValueError("request_id already belongs to a different message")
            return row[1]

    def complete(self, agent, request, event):
        with self.db:
            self.db.execute(
                "UPDATE sends SET event=? WHERE agent=? AND request=?",
                (event, agent, request),
            )
