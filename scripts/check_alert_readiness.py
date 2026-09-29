"""
What the new alert rules are bound to in the live Home Assistant, and a live view of
the readings they watch. Needs HA reachable (Tailscale up).

    python scripts/check_alert_readiness.py                 # one-shot readiness report
    python scripts/check_alert_readiness.py --watch 10      # re-read every 10 s (Ctrl+C stops)
    python scripts/check_alert_readiness.py --watch 10 --csv data/env_test.csv

The watch mode is for the environmental test scenarios (hair dryer, humidifier, …):
step 1 "does the sensor respond" is the value column moving; step 2 "does the alert
fire" is the rule column flipping to BREACH, then the rule engine raising the alert
once the rule's "must hold for" time has passed.
"""
from __future__ import annotations
import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dari.env_metrics import env_metric, normalize_temp
from dari.rule_engine.evaluators import compare, _last_seen, _minutes_since
from dari.rule_engine.ha_client import states_as_dict, get_sensors_by_area
from dari.rule_engine.models import Profile
from dari.activity_engine.state import build_sensor_index

sys.stdout.reconfigure(encoding="utf-8")


def breached(rules, kind, area, eid, value, unit):
    hits = []
    for r in rules:
        if not (r.enabled and r.trigger_type == "env_threshold" and r.metric == kind):
            continue
        if (r.zone and (area or "").lower() != r.zone.lower()) or (r.entity_id and r.entity_id != eid):
            continue
        v = normalize_temp(value, unit, r.unit) if (r.unit and kind == "temperature") else value
        if compare(v, r.operator, r.value):
            hits.append(r.id)
    return hits


def env_rows(states, entity_area, rules):
    rows = []
    for eid, s in sorted(states.items()):
        attrs = s.get("attributes", {})
        kind = env_metric(eid, attrs.get("device_class"))
        if not kind:
            continue
        unit = attrs.get("unit_of_measurement", "")
        try:
            value = float(s["state"])
        except (ValueError, TypeError):
            rows.append((kind, entity_area.get(eid), eid, None, unit, []))
            continue
        rows.append((kind, entity_area.get(eid), eid, value, unit,
                     breached(rules, kind, entity_area.get(eid), eid, value, unit)))
    return rows


def report(profile, states, area_sensors):
    entity_area = {e: a for a, b in area_sensors.items() for e in b.get("all", [])}
    print("== Fall detection")
    falls = [(a, e) for a, b in area_sensors.items() for e in b.get("fall", [])]
    pins = [r.entity_id for r in profile.active_rules if r.trigger_type == "fall" and r.entity_id]
    for a, e in falls:
        print(f"  {a:18s} {e:60s} {states.get(e, {}).get('state')}")
    for e in pins:
        print(f"  pinned by rule     {e:60s} {states.get(e, {}).get('state', 'MISSING')}")
    if not falls and not pins:
        print("  NONE - fall rules are inactive. Look for a fall entity from the FP2 in HA")
        print("  (Settings > Devices) and pin it with `entity_id:` on rule-001 if its name")
        print("  doesn't contain 'fall'.")

    print("\n== Smart-plug appliances")
    idx = build_sensor_index(area_sensors, states, appliances=profile.appliances)
    for eid, app in idx["appliances"].items():
        w = states.get(eid, {}).get("state")
        print(f"  {app['name'][:24]:24s} {app['kind']:10s} {str(app['area']):16s} {eid:48s} {w} W"
              f"  (on >= {app['on_watts']:.0f} W)")
    if not idx["appliances"]:
        print("  NONE - no sensor.*power* entity in W/kW")

    print("\n== Environment sensors  (BREACH = over a rule's threshold right now)")
    rows = env_rows(states, entity_area, profile.rules)
    for kind, area, eid, value, unit, hits in rows:
        flag = f"BREACH {','.join(hits)}" if hits else ""
        print(f"  {kind:11s} {str(area):16s} {eid:58s} {value} {unit}  {flag}")
    covered = {r.metric for r in profile.active_rules if r.trigger_type == "env_threshold"}
    missing = covered - {r[0] for r in rows}
    if missing:
        print(f"  no sensor found for: {', '.join(sorted(missing))} - those rules can't fire")

    print("\n== Watch (vital_threshold)")
    for key in ("heart_rate", "on_body", "activity_state", "steps_today"):
        eid = profile.watch.get(key)
        s = states.get(eid, {}) if eid else {}
        age = _minutes_since(_last_seen(s)) if s else None
        print(f"  {key:15s} {str(eid):45s} {s.get('state', 'MISSING'):>10}"
              + (f"  ({age:.0f} min old)" if age is not None else ""))


def watch_loop(profile, every, csv_path):
    area_sensors = get_sensors_by_area()
    entity_area = {e: a for a, b in area_sensors.items() for e in b.get("all", [])}
    writer = None
    if csv_path:
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        fh = open(csv_path, "a", newline="", encoding="utf-8")
        writer = csv.writer(fh)
        if fh.tell() == 0:
            writer.writerow(["timestamp", "kind", "area", "entity_id", "value", "unit", "breached"])
    hr_eid = profile.watch.get("heart_rate")
    while True:
        states = states_as_dict()
        now = datetime.now(timezone.utc).astimezone()
        print(f"\n-- {now:%H:%M:%S}")
        for kind, area, eid, value, unit, hits in env_rows(states, entity_area, profile.rules):
            print(f"  {kind:11s} {str(area):16s} {value!s:>8} {unit:6s} {'BREACH ' + ','.join(hits) if hits else ''}")
            if writer:
                writer.writerow([now.isoformat(), kind, area, eid, value, unit, ";".join(hits)])
        for eid in (e for e in states if e.startswith("sensor.") and "power" in e
                    and states[e].get("attributes", {}).get("unit_of_measurement") in ("W", "kW")):
            print(f"  {'plug':11s} {str(entity_area.get(eid)):16s} {states[eid]['state']:>8} W      {eid}")
        if hr_eid and hr_eid in states:
            print(f"  {'heart_rate':11s} {'watch':16s} {states[hr_eid]['state']:>8} bpm    "
                  f"({_minutes_since(_last_seen(states[hr_eid])):.0f} min old)")
        if writer:
            fh.flush()
        time.sleep(every)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="config/profiles/patient_001.yaml")
    ap.add_argument("--watch", type=float, metavar="SEC", help="re-read readings every SEC seconds")
    ap.add_argument("--csv", help="with --watch: append readings to this CSV")
    args = ap.parse_args()
    profile = Profile.load(args.profile)
    if args.watch:
        try:
            watch_loop(profile, args.watch, args.csv)
        except KeyboardInterrupt:
            pass
        return
    report(profile, states_as_dict(), get_sensors_by_area())


if __name__ == "__main__":
    main()
