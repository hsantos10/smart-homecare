"""
SQLite-backed alert log.
Thread-safe for concurrent reads/writes from engine + API.
"""
from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..paths import DB_PATH, ensure_dirs
from .models import Alert

ensure_dirs()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id           TEXT PRIMARY KEY,
                profile_id   TEXT NOT NULL,
                rule_id      TEXT NOT NULL,
                rule_name    TEXT NOT NULL,
                severity     TEXT NOT NULL,
                category     TEXT NOT NULL,
                message      TEXT NOT NULL,
                zone         TEXT,
                timestamp    TEXT NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0,
                source       TEXT NOT NULL DEFAULT 'heuristic'
            )
        """)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
        if "source" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN source TEXT NOT NULL DEFAULT 'heuristic'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profile ON alerts(profile_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON alerts(timestamp)")
        conn.commit()


def insert(alert: Alert) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO alerts
               (id, profile_id, rule_id, rule_name, severity, category,
                message, zone, timestamp, acknowledged, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (alert.id, alert.profile_id, alert.rule_id, alert.rule_name,
             alert.severity, alert.category, alert.message, alert.zone,
             alert.timestamp, int(alert.acknowledged), alert.source),
        )
        conn.commit()


def acknowledge(alert_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,)
        )
        conn.commit()
        return cur.rowcount > 0


def query(
    profile_id: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    since: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = 50,
    include_demo: bool = False,
) -> list[Alert]:
    clauses = []
    params: list = []
    if profile_id:
        clauses.append("profile_id = ?"); params.append(profile_id)
    if category:
        clauses.append("category = ?"); params.append(category)
    if severity:
        clauses.append("severity = ?"); params.append(severity)
    if since:
        clauses.append("timestamp >= ?"); params.append(since)
    if acknowledged is not None:
        clauses.append("acknowledged = ?"); params.append(int(acknowledged))
    if not include_demo:
        clauses.append("source != 'demo'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    sql = f"SELECT * FROM alerts {where} ORDER BY timestamp DESC LIMIT ?"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_alert(r) for r in rows]


def last_fired(profile_id: str, rule_id: str) -> Optional[datetime]:
    """Return timestamp of the most recent alert for this rule (for cooldown check)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT timestamp FROM alerts WHERE profile_id=? AND rule_id=? "
            "ORDER BY timestamp DESC LIMIT 1",
            (profile_id, rule_id),
        ).fetchone()
    if row:
        return datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc)
    return None


def _row_to_alert(row: sqlite3.Row) -> Alert:
    return Alert(
        id=row["id"],
        profile_id=row["profile_id"],
        rule_id=row["rule_id"],
        rule_name=row["rule_name"],
        severity=row["severity"],
        category=row["category"],
        message=row["message"],
        zone=row["zone"],
        timestamp=row["timestamp"],
        acknowledged=bool(row["acknowledged"]),
        source=row["source"] if "source" in row.keys() else "heuristic",
    )


def make_alert(profile_id: str, rule_id: str, rule_name: str,
               severity: str, category: str, message: str,
               zone: Optional[str] = None, source: str = "heuristic") -> Alert:
    return Alert(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        rule_id=rule_id,
        rule_name=rule_name,
        severity=severity,
        category=category,
        message=message,
        zone=zone,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
    )
