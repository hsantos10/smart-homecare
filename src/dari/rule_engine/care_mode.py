"""
Care mode: is the person with dementia home alone, or at home with others?

The presence sensors can't tell *who* they see. With a caregiver or visitor in the house,
rules that treat every movement as the patient's (night wandering, inactivity, a long
bathroom stay) raise false alarms, so the caregiver switches the app to "with others"
and those rules pause. Rules that don't depend on who is moving — falls, doors,
environment, the patient's own watch — keep running.

Stored in alerts.db (shared by the API and both engines), not the profile YAML, because
it changes several times a day and is set from the phone.

Safety bias: the dangerous mistake is staying in "with others" after everyone has left,
since alerts stay paused. So "with others" normally carries an end time and reverts to
"alone" on its own, and anything unreadable also counts as "alone".
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from ..paths import DB_PATH, ensure_dirs
from .models import Rule

ALONE = "alone"
WITH_OTHERS = "with_others"
MODES = (ALONE, WITH_OTHERS)

# Which modes a rule runs in when it doesn't say (`Rule.modes`). Triggers that read
# "someone is (not) moving" as "the patient is (not) moving" only make sense alone.
PRESENCE_ATTRIBUTED = {"room_inactivity", "global_inactivity", "night_wandering", "long_stay"}

ensure_dirs()


def rule_modes(rule: Rule) -> list[str]:
    if rule.modes:
        return [m for m in rule.modes if m in MODES]
    return [ALONE] if rule.trigger_type in PRESENCE_ATTRIBUTED else list(MODES)


def rule_active_in(rule: Rule, mode: str) -> bool:
    return mode in rule_modes(rule)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS care_mode (
            profile_id TEXT PRIMARY KEY,
            mode       TEXT NOT NULL,
            until      TEXT,            -- ISO UTC; NULL = until switched back
            changed_at TEXT NOT NULL
        )
    """)
    return conn


def get(profile_id: str, now: Optional[datetime] = None) -> dict:
    """Effective mode: {mode, until, changed_at, expired}. An expired or missing
    "with others" reads as "alone"."""
    now = now or datetime.now(timezone.utc)
    try:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM care_mode WHERE profile_id=?", (profile_id,)).fetchone()
    except sqlite3.Error:
        row = None
    if not row or row["mode"] not in MODES:
        return {"mode": ALONE, "until": None, "changed_at": None, "expired": False}
    if row["mode"] == WITH_OTHERS and row["until"]:
        try:
            if datetime.fromisoformat(row["until"]) <= now:
                return {"mode": ALONE, "until": None, "changed_at": row["until"], "expired": True}
        except ValueError:
            return {"mode": ALONE, "until": None, "changed_at": row["changed_at"], "expired": True}
    return {"mode": row["mode"], "until": row["until"], "changed_at": row["changed_at"], "expired": False}


def set_mode(profile_id: str, mode: str, until: Optional[datetime] = None) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    now = datetime.now(timezone.utc)
    until_s = until.astimezone(timezone.utc).isoformat() if (until and mode == WITH_OTHERS) else None
    with _connect() as conn:
        conn.execute(
            "INSERT INTO care_mode (profile_id, mode, until, changed_at) VALUES (?,?,?,?) "
            "ON CONFLICT(profile_id) DO UPDATE SET mode=excluded.mode, until=excluded.until, "
            "changed_at=excluded.changed_at",
            (profile_id, mode, until_s, now.isoformat()),
        )
        conn.commit()
    return get(profile_id, now)
