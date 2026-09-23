"""Persistent cache for match.py's API verdicts, keyed by the exact inputs that produced them.

Re-running the eval (e.g. after fixing a fetch bug for 8 unrelated rows, or re-scoring the
same 290 cases against a documentation rewrite) must not re-pay Anthropic API cost for a case
whose answer literally cannot have changed. This module hashes (input_name, input_dob,
article_title, article_text, model, PROMPT_VERSION) into a cache key and stores/retrieves the
resulting MatchResult fields as JSON in db/nameRecognition.db.

PROMPT_VERSION must be bumped whenever SYSTEM_PROMPT or VERDICT_TOOL changes meaningfully --
otherwise a stale cached verdict from a materially different prompt would be served silently,
which would defeat the entire point of the eval.
"""

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "nameRecognition.db"

PROMPT_VERSION = "v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS match_cache (
    cache_key       TEXT PRIMARY KEY,
    response_json   TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def make_key(
    input_name: str, input_dob: str, article_title: str | None, article_text: str, model: str,
    db_context: str = "",
) -> str:
    # db_context is part of the actual prompt sent to the model (known aliases, collision
    # warnings) and MUST be in the key -- otherwise a knowledge-base change (a new alias, a
    # new collision cataloged, exactly what happened for RFK Jr. this session) would silently
    # serve a stale verdict computed under the old, less-informed DB state.
    payload = "\u241f".join([input_name, input_dob, article_title or "", article_text, model, PROMPT_VERSION, db_context])
    return sha256(payload.encode("utf-8")).hexdigest()


def get(cache_key: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT response_json FROM match_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def put(cache_key: str, response: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO match_cache (cache_key, response_json) VALUES (?, ?)",
            (cache_key, json.dumps(response, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
