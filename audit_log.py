"""Audit log for Provenance Guard, backed by SQLite.

Every call to POST /submit writes one structured entry here. The schema starts
simple in M3 (content id, creator, timestamp, attribution, signal-1 score) and
is extended in later milestones (stylometric score, appeals, review status).

Entry shape returned by `get_log()`:
    {
      "content_id":  "3f7a2b1e-...",
      "creator_id":  "test-user-1",
      "timestamp":   "2025-04-01T14:32:10.123Z",   # ISO-8601 UTC
      "attribution": "likely_ai",                   # likely_ai|uncertain|likely_human
      "confidence":  0.78,
      "llm_score":   0.81,
      "status":      "classified"
    }
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("PROVENANCE_DB_PATH", "db.sqlite3")


@contextmanager
def _connect():
    """Yield a connection that commits on success and always closes.

    Note: sqlite3's own connection context manager handles the transaction but
    does NOT close the connection, which leaks file handles, so we close here.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the audit log table if it does not already exist.

    `llm_score` is the Groq signal and `stylo_score` is the stylometric signal;
    `confidence` is the blended score (0.6*llm + 0.4*stylo).
    """
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                content_id  TEXT PRIMARY KEY,
                creator_id  TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL,
                attribution TEXT    NOT NULL,
                confidence  REAL,
                llm_score   REAL,
                stylo_score REAL,
                status      TEXT    NOT NULL,
                appeal_reasoning TEXT,
                appealed_at      TEXT
            )
            """
        )
        # Migration: add columns to pre-existing tables that lack them.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(audit_log)")}
        for col, col_type in (("stylo_score", "REAL"), ("appeal_reasoning", "TEXT"), ("appealed_at", "TEXT")):
            if col not in columns:
                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {col_type}")


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with millisecond Z suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def add_entry(
    *,
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float | None,
    llm_score: float | None,
    stylo_score: float | None,
    status: str = "classified",
    timestamp: str | None = None,
) -> dict:
    """Insert a structured entry and return it as a dict."""
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp or utc_now_iso(),
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "stylo_score": stylo_score,
        "status": status,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log
                (content_id, creator_id, timestamp, attribution, confidence, llm_score, stylo_score, status)
            VALUES
                (:content_id, :creator_id, :timestamp, :attribution, :confidence, :llm_score, :stylo_score, :status)
            """,
            entry,
        )
    return entry


def get_entry(content_id: str) -> dict | None:
    """Return a single audit entry by content_id, or None if it does not exist."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE content_id = ?", (content_id,)
        ).fetchone()
    return dict(row) if row else None


def record_appeal(content_id: str, appeal_reasoning: str) -> dict | None:
    """Record an appeal against an existing entry.

    Updates the entry in place: sets status to "under_review" and stores the
    appeal reasoning + timestamp, while preserving the original classification
    (scores, label, attribution). Returns the updated entry, or None if the
    content_id does not exist.
    """
    if get_entry(content_id) is None:
        return None
    with _connect() as conn:
        conn.execute(
            """
            UPDATE audit_log
               SET status = 'under_review',
                   appeal_reasoning = ?,
                   appealed_at = ?
             WHERE content_id = ?
            """,
            (appeal_reasoning, utc_now_iso(), content_id),
        )
    return get_entry(content_id)


def get_log(limit: int = 50) -> list[dict]:
    """Return the most recent audit log entries, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

def clear_logs() -> str:
    """Delete all audit log entries."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM audit_log")
    return f"Deleted {cursor.rowcount} audit log entr{'y' if cursor.rowcount == 1 else 'ies'}."