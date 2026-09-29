"""
Seed a realistic day of activity events (and a couple of alerts) for demoing the
caregiver app UI without waiting for the live activity engine to accumulate history.

    python scripts/seed_demo.py            # insert demo rows for today
    python scripts/seed_demo.py --clear    # remove all demo rows (source='demo')

Demo rows are tagged source='demo' so they're easy to identify and clear. Live current
status still comes from Home Assistant — this only populates the timeline/summary/charts.
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


from dari.activity_engine import activity_store
from dari.activity_engine.models import ActivityEvent
from dari.rule_engine import alert_store, models as rmodels

PROFILE_ID = "patient-001"

# (minutes-ago, activity_key, zone, detail)
TODAY_PLAN = [
    (0,   "sitting",            "Living room",       None),
    (28,  "front_door_opened",  "Front Door",        "Unusual time"),
    (33,  "in_living_room",     "Living room",       None),
    (60,  "breakfast",          "Living room",       None),
    (95,  "in_bathroom",        "Bedroom Bathroom",  None),
    (110, "woke_up",            "Bedroom",           None),
    (300, "went_to_bed",        "Bedroom",           None),
    (520, "in_bathroom",        "Bedroom Bathroom",  None),
    (540, "sleeping",           "Bedroom",           None),
]


def clear() -> None:
    with sqlite3.connect(str(activity_store.DB_PATH)) as conn:
        n = conn.execute("DELETE FROM activity_log WHERE source='demo'").rowcount
        conn.commit()
    print(f"Removed {n} demo activity rows.")


def seed() -> None:
    activity_store.init_db()
    alert_store.init_db()
    now = datetime.now(timezone.utc)
    for mins, key, zone, detail in TODAY_PLAN:
        ts = (now - timedelta(minutes=mins)).isoformat()
        activity_store.insert(ActivityEvent.create(
            PROFILE_ID, key, zone=zone, detail=detail, source="demo", timestamp=ts,
        ))
    print(f"Seeded {len(TODAY_PLAN)} demo activity events.")

    # One representative active alert (matches the rule book "Night exit" rule).
    alert = alert_store.make_alert(
        profile_id=PROFILE_ID, rule_id="rule-002", rule_name="Night exit — front door",
        severity="HIGH", category="Safety",
        message="Front door opened at 9:32 AM — Patient A may have left", zone="Front Door",
        source="demo",
    )
    alert.timestamp = (now - timedelta(minutes=28)).isoformat()
    alert_store.insert(alert)
    print("Seeded 1 demo alert.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="remove demo rows instead of seeding")
    args = ap.parse_args()
    clear() if args.clear else seed()
