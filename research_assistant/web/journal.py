"""Durable idempotency journal. Uncertain outcomes are never retried blindly."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class RequestJournal:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.path = Path(root) / 'application.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (owner TEXT, id TEXT, hash TEXT, thread TEXT, run TEXT, PRIMARY KEY(owner,id))')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, user_id, request_id, payload):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.connect() as db:
            row = db.execute('SELECT hash,thread,run FROM requests WHERE owner=? AND id=?', (user_id, request_id)).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError('request_id уже использован с другим содержимым.')
                return {'thread_id': row[1], 'run_id': row[2]}
            db.execute('INSERT INTO requests VALUES(?,?,?,NULL,NULL)', (user_id, request_id, digest))
        return None

    def bind_run(self, user_id, request_id, thread_id, run_id):
        with self.connect() as db:
            db.execute('UPDATE requests SET thread=?,run=? WHERE owner=? AND id=?',
                       (thread_id, run_id, user_id, request_id))

    def lookup(self, user_id, request_id, payload):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.connect() as db:
            row = db.execute('SELECT hash,thread,run FROM requests WHERE owner=? AND id=?', (user_id, request_id)).fetchone()
            if row is None:
                return None
            if row[0] != digest:
                raise ValueError('request_id уже использован с другим содержимым.')
            return {'thread_id': row[1], 'run_id': row[2]}
