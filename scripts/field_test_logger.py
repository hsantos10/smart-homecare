"""Poll the live activity API during a field test and capture what the app believes
is happening, second by second, so it can be diffed against a ground-truth route log
afterward. Doesn't touch HA directly — reads exactly what the caregiver app reads.

Usage:
    python scripts/field_test_logger.py --profile patient-001 --port 8001 --out field_test.csv

Stop with Ctrl+C when the walkthrough is done. Then log the actual steps you performed
(with wall-clock start times) in a plain text/CSV and compare against field_test.csv.
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timezone

import requests

parser = argparse.ArgumentParser(description="Live-poll the DARI API during a field test")
parser.add_argument("--profile", default="patient-001")
parser.add_argument("--port", type=int, default=8001)
parser.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
parser.add_argument("--out", default="field_test.csv")
args = parser.parse_args()

BASE = f"http://127.0.0.1:{args.port}"

rows = []
areas_seen: set[str] = set()

print(f"Polling {BASE}/api/current_status every {args.interval}s. Ctrl+C to stop and save.", flush=True)
try:
    while True:
        wall_clock = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        try:
            resp = requests.get(f"{BASE}/api/current_status",
                                params={"profile_id": args.profile}, timeout=5)
            resp.raise_for_status()
            status = resp.json()
        except requests.exceptions.RequestException as exc:
            print(f"[warn] poll failed: {exc}", file=sys.stderr)
            time.sleep(args.interval)
            continue

        presence = status.get("presence_by_zone", {})
        areas_seen.update(presence.keys())
        row = {
            "wall_clock": wall_clock,
            "home": status.get("home"),
            "current_zone": status.get("current_zone"),
            "current_activity": status.get("current_activity"),
            "activity_label": status.get("activity_label"),
            "since": status.get("since"),
        }
        for area in presence:
            row[f"presence::{area}"] = presence[area]
        rows.append(row)
        print(f"{wall_clock}  zone={row['current_zone']!s:<18} activity={row['activity_label']}", flush=True)
        time.sleep(args.interval)
except KeyboardInterrupt:
    pass

if not rows:
    print("No rows captured.")
    sys.exit(0)

fieldnames = ["wall_clock", "home", "current_zone", "current_activity", "activity_label", "since"]
fieldnames += sorted(f"presence::{a}" for a in areas_seen)
with open(args.out, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

print(f"\nSaved {len(rows)} rows to {args.out}")
