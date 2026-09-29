"""
SQLite-backed activity timeline. Lives in the same alerts.db as the rule engine,
in its own `activity_log` table. Thread-safe for engine writes + API reads.
"""
from __future__ import annotations
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from ..paths import DB_PATH, ensure_dirs
from .models import ActivityEvent

ensure_dirs()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id          TEXT PRIMARY KEY,
                profile_id  TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                activity    TEXT NOT NULL,
                label       TEXT NOT NULL,
                category    TEXT NOT NULL,
                zone        TEXT,
                detail      TEXT,
                icon        TEXT NOT NULL DEFAULT 'activity',
                severity    TEXT NOT NULL DEFAULT 'info',
                confidence  REAL NOT NULL DEFAULT 1.0,
                source      TEXT NOT NULL DEFAULT 'heuristic'
            )
        """)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        if "source" not in cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN source TEXT NOT NULL DEFAULT 'heuristic'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_act_profile_ts "
                     "ON activity_log(profile_id, timestamp)")
        conn.commit()


def insert(event: ActivityEvent) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO activity_log
               (id, profile_id, timestamp, activity, label, category,
                zone, detail, icon, severity, confidence, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event.id, event.profile_id, event.timestamp, event.activity, event.label,
             event.category, event.zone, event.detail, event.icon, event.severity,
             event.confidence, event.source),
        )
        conn.commit()


def query(
    profile_id: Optional[str] = None,
    category: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    include_demo: bool = False,
) -> list[ActivityEvent]:
    clauses, params = [], []
    if profile_id:
        clauses.append("profile_id = ?"); params.append(profile_id)
    if category:
        clauses.append("category = ?"); params.append(category)
    if since:
        clauses.append("timestamp >= ?"); params.append(since)
    if until:
        clauses.append("timestamp <= ?"); params.append(until)
    if not include_demo:
        clauses.append("source != 'demo'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    sql = f"SELECT * FROM activity_log {where} ORDER BY timestamp DESC LIMIT ?"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_event(r) for r in rows]


def last_event(profile_id: str, include_demo: bool = False) -> Optional[ActivityEvent]:
    with _connect() as conn:
        sql = "SELECT * FROM activity_log WHERE profile_id=?"
        params: list = [profile_id]
        if not include_demo:
            sql += " AND source != 'demo'"
        sql += " ORDER BY timestamp DESC LIMIT 1"
        row = conn.execute(sql, params).fetchone()
    return _row_to_event(row) if row else None


def summary(profile_id: str, days: int = 7, include_demo: bool = False) -> dict:
    """Aggregates for the Activity screen's Week/Month charts."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    events = query(profile_id=profile_id, since=since, limit=5000, include_demo=include_demo)

    by_category: Counter = Counter()
    by_activity: Counter = Counter()
    by_day: defaultdict = defaultdict(Counter)   # "YYYY-MM-DD" -> {category: count}
    by_hour: Counter = Counter()                 # hour (local) -> count

    for e in events:
        by_category[e.category] += 1
        by_activity[e.activity] += 1
        try:
            dt = datetime.fromisoformat(e.timestamp).astimezone()
        except ValueError:
            continue
        by_day[dt.strftime("%Y-%m-%d")][e.category] += 1
        by_hour[dt.hour] += 1

    return {
        "profile_id": profile_id,
        "days": days,
        "total": len(events),
        "by_category": dict(by_category),
        "by_activity": dict(by_activity),
        "by_day": {d: dict(c) for d, c in sorted(by_day.items())},
        "by_hour": {str(h): by_hour.get(h, 0) for h in range(24)},
    }


def _fmt_hhmm(hours_float: float) -> str:
    total_min = int(round(hours_float * 60)) % (24 * 60)
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def _clock_stats(times_h: list[float]) -> Optional[dict]:
    """Mean time-of-day + spread for a list of local-hour floats (e.g. 7.5 = 07:30)."""
    if not times_h:
        return None
    import statistics
    mean = sum(times_h) / len(times_h)
    spread = statistics.pstdev(times_h) if len(times_h) > 1 else 0.0
    return {"mean": _fmt_hhmm(mean), "spread_min": round(spread * 60), "n": len(times_h)}


def _regularity(wake: list[float], bed: list[float]) -> Optional[str]:
    """Coarse label for how consistent the daily routine is, from wake/bed spread."""
    if len(wake) < 3 and len(bed) < 3:
        return None
    import statistics
    spreads = []
    if len(wake) > 1:
        spreads.append(statistics.pstdev(wake) * 60)
    if len(bed) > 1:
        spreads.append(statistics.pstdev(bed) * 60)
    if not spreads:
        return None
    worst = max(spreads)
    return "high" if worst < 45 else "moderate" if worst < 90 else "low"


def adl_summary(profile_id: str, days: int = 14, include_demo: bool = False) -> dict:
    """Daily-routine patterns from the activity log: average wake/bed/meal times,
    routine regularity, night bathroom trips, outings, and a rough time-in-room split.

    Counts of steady-state events are used as a proxy for time-in-room — the log
    stores transitions, not durations. Everything degrades gracefully to null when
    there isn't enough data.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    events = query(profile_id=profile_id, since=since, limit=20000, include_demo=include_demo)

    days_seen: set[str] = set()
    wake: list[float] = []
    bed: list[float] = []
    breakfast_t: list[float] = []
    meal_t: list[float] = []
    room_counts: Counter = Counter()
    nights_with_bathroom: set[str] = set()
    night_bathroom = 0
    outings = 0

    _ROOM_KEYS = {"sitting", "at_desk", "sleeping", "in_bed", "using_toilet", "in_shower", "cooking"}

    for e in events:
        try:
            dt = datetime.fromisoformat(e.timestamp).astimezone()
        except ValueError:
            continue
        days_seen.add(dt.strftime("%Y-%m-%d"))
        hf = dt.hour + dt.minute / 60
        a = e.activity
        if a == "woke_up":
            wake.append(hf)
        elif a == "went_to_bed":
            bed.append(hf + 24 if hf < 12 else hf)   # keep past-midnight bedtimes contiguous
        elif a == "breakfast":
            breakfast_t.append(hf)
        elif a == "meal":
            meal_t.append(hf)
        elif a == "left_home":
            outings += 1
        if a in ("using_toilet", "in_bathroom", "toilet_flushed") and (dt.hour >= 22 or dt.hour < 6):
            night_bathroom += 1
            anchor = dt if dt.hour < 12 else dt + timedelta(days=1)
            nights_with_bathroom.add(anchor.strftime("%Y-%m-%d"))
        if (a.startswith("in_") or a in _ROOM_KEYS) and e.zone:
            room_counts[e.zone] += 1

    n_days = max(1, len(days_seen))
    total_room = sum(room_counts.values()) or 1

    return {
        "profile_id": profile_id,
        "days": days,
        "days_with_data": len(days_seen),
        "wake_time": _clock_stats(wake),
        "bed_time": _clock_stats(bed),
        "breakfast_time": _clock_stats(breakfast_t),
        "midday_meal_time": _clock_stats(meal_t),
        "night_bathroom_visits_per_night": (
            round(night_bathroom / max(1, len(nights_with_bathroom)), 1) if night_bathroom else 0
        ),
        "outings_per_day": round(outings / n_days, 1),
        "time_in_room_pct": {z: round(100 * c / total_room) for z, c in room_counts.most_common()},
        "routine_regularity": _regularity(wake, bed),
    }


def _row_to_event(row: sqlite3.Row) -> ActivityEvent:
    return ActivityEvent(
        id=row["id"], profile_id=row["profile_id"], timestamp=row["timestamp"],
        activity=row["activity"], label=row["label"], category=row["category"],
        zone=row["zone"], detail=row["detail"], icon=row["icon"],
        severity=row["severity"], confidence=row["confidence"], source=row["source"],
    )
