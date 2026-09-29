"""Measure end-to-end alert latency: sensor event → HA → rule engine → alert row → phone.

Produces the "median X s, p90 Y s" number for the paper, from the *real* pipeline — the
running rule engine, its WebSocket subscription, its evaluator, its SQLite insert and its
notifier. Only the rule is synthetic: a door rule bound to a virtual HA entity, so trials
never depend on the time of day or on a physical door.

Setup (once):

    python scripts/measure_latency.py --setup
        # writes config/profiles/latency_probe.yaml (probe rule + notify block copied
        # from patient_001.yaml; pass --push to enable live phone pushes in it)

Run the rule engine against the probe profile, in its own terminal:

    conda run -n LLMs python -m dari.rule_engine.engine --profile config/profiles/latency_probe.yaml

Then measure:

    python scripts/measure_latency.py --trials 50
    python scripts/measure_latency.py --mode observe --entity binary_sensor.<real_door> \
        --profile config/profiles/patient_001.yaml --rule-id rule-002
        # observe mode injects nothing: it waits for real state changes on `--entity`
        # and times the alert the *production* profile produces for them

What gets timestamped, per trial (all UTC):

    t_inject   harness clock — the moment the REST call that flips the probe entity returns
    t_ha       HA's own `last_changed` on the resulting state_changed event (HA clock)
    t_ws       harness clock — when that state_changed event arrived over the WebSocket
    t_alert    engine clock — `alerts.timestamp` written by make_alert() at fire time
    t_seen     harness clock — when the harness first saw the alert row in alerts.db
    t_push     harness clock — when HA relayed `mobile_app_notification_received` from the
               phone (Android Companion app fires it on receipt); absent if push is off,
               the phone is unreachable, or the event never came within --push-timeout

Harness and engine run on the same machine, so t_alert − t_inject is a clean number. The
HA hub has its own clock; t_ha is reported for information, not used in the headline.

Outputs (under docs/paper/data/, which is git-ignored):

    latency_<stamp>.csv       one row per trial
    latency_<stamp>.json      summary — n, median / p90 / p99 / max for each segment
    latency_<stamp>.png/.pdf  CDF of end-to-end latency with the segment breakdown

Probe alert rows are deleted from alerts.db at the end unless --keep-alerts is given — they
belong to the probe profile_id, so nothing from the patient profile is touched.
"""
from __future__ import annotations

import asyncio
import csv
import json
import sqlite3
import statistics
import sys
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import websockets
import yaml
from dotenv import load_dotenv

from dari.paths import DB_PATH, DEFAULT_PROFILE, PROFILES_DIR, DOCS_DIR
from dari.rule_engine.ha_client import HA_URL, HA_WS, HA_TOKEN, HEADERS

load_dotenv()

# Windows consoles default to cp1252; keep the arrows in the trial table printable
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROBE_PROFILE_ID = "latency-probe"
PROBE_PROFILE    = PROFILES_DIR / "latency_probe.yaml"
PROBE_ENTITY     = "binary_sensor.dari_latency_probe"
PROBE_RULE_ID    = "probe-door"
OUT_DIR          = DOCS_DIR / "paper" / "data"

RECEIPT_EVENTS = ("mobile_app_notification_received", "mobile_app_notification_action")


# ── helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> str:
    return dt.isoformat() if dt else ""


def _secs(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    return (b - a).total_seconds() if (a and b) else None


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pct(vals: list[float], p: float) -> Optional[float]:
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def _summ(vals: list[Optional[float]]) -> dict:
    xs = [v for v in vals if v is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "median": round(statistics.median(xs), 3),
            "p90": round(_pct(xs, .90), 3), "p99": round(_pct(xs, .99), 3),
            "max": round(max(xs), 3), "min": round(min(xs), 3)}


# ── setup: write the probe profile ───────────────────────────────────────────

def write_probe_profile(src_profile: Path, push: bool) -> Path:
    """Probe profile = one door rule on a virtual entity + the notify block of the source."""
    src = yaml.safe_load(src_profile.read_text(encoding="utf-8")) or {}
    notify = dict(src.get("notify") or {})
    notify["enabled"] = bool(push)
    if push:
        notify.setdefault("min_severity", "HIGH")
        notify["min_severity"] = "HIGH"

    probe = {
        "profile_id": PROBE_PROFILE_ID,
        "patient_name": "Latency Probe",
        "caregiver_name": src.get("caregiver_name", "Caregiver"),
        "rules": [{
            "id": PROBE_RULE_ID,
            "name": "Latency probe (virtual door)",
            "enabled": True,
            "category": "Safety",
            "severity": "HIGH",
            "trigger_type": "door_opened",
            "message": "Latency probe fired at {{time}}",
            "entity_id": PROBE_ENTITY,
            "cooldown_minutes": 0,          # never on cooldown: elapsed < 0 is impossible
            # no time_window, no no_return_minutes → fires on the first state_changed to "on"
        }],
        "notify": notify,
    }
    for k in ("watch",):                     # carry over so the engine's loaders stay happy
        if k in src:
            probe[k] = src[k]

    PROBE_PROFILE.write_text(
        "# Generated by scripts/measure_latency.py --setup. Safe to delete.\n"
        "# Run the rule engine with this profile while measuring; never for a patient.\n"
        + yaml.safe_dump(probe, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return PROBE_PROFILE


# ── HA access ────────────────────────────────────────────────────────────────

def ha_ok() -> bool:
    try:
        r = requests.get(f"{HA_URL}/api/", headers=HEADERS, timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def delete_probe_entity(entity: str) -> bool:
    """Remove the virtual probe entity from HA's state machine (it is not a real device)."""
    r = requests.delete(f"{HA_URL}/api/states/{entity}", headers=HEADERS, timeout=10)
    return r.status_code in (200, 204)


def set_probe_state(entity: str, on: bool) -> datetime:
    """POST /api/states — sets the entity's state in HA without touching any device.
    Returns the harness time at which the call returned."""
    body = {"state": "on" if on else "off",
            "attributes": {"friendly_name": "DARI latency probe", "device_class": "door"}}
    r = requests.post(f"{HA_URL}/api/states/{entity}", headers=HEADERS, json=body, timeout=10)
    r.raise_for_status()
    return _utcnow()


class HAEvents:
    """One WebSocket to HA; fans state_changed + notification-receipt events into a queue."""

    def __init__(self, entity: str):
        self.entity = entity
        self.q: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        self._ws = await websockets.connect(HA_WS, open_timeout=15)
        await self._ws.recv()                                   # auth_required
        await self._ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        msg = json.loads(await self._ws.recv())
        if msg.get("type") != "auth_ok":
            raise RuntimeError(f"HA auth failed: {msg}")
        for i, ev in enumerate(("state_changed",) + RECEIPT_EVENTS, start=1):
            await self._ws.send(json.dumps({"id": i, "type": "subscribe_events", "event_type": ev}))
            await self._ws.recv()
        self._task = asyncio.create_task(self._reader())
        return self

    async def __aexit__(self, *exc):
        if self._task:
            self._task.cancel()
        await self._ws.close()

    async def _reader(self):
        async for raw in self._ws:
            msg = json.loads(raw)
            if msg.get("type") != "event":
                continue
            ev = msg["event"]
            et, data, now = ev.get("event_type"), ev.get("data", {}), _utcnow()
            if et == "state_changed" and data.get("entity_id") == self.entity:
                new = data.get("new_state") or {}
                await self.q.put(("state", now, new.get("state"), new.get("last_changed")))
            elif et in RECEIPT_EVENTS:
                tag = (data.get("data") or {}).get("tag") or data.get("tag")
                await self.q.put(("push", now, tag, et))

    async def wait_for(self, kind: str, timeout: float, pred=lambda item: True):
        """Return the first queued item of `kind` satisfying pred, or None on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                item = await asyncio.wait_for(self.q.get(), left)
            except asyncio.TimeoutError:
                return None
            if item[0] == kind and pred(item):
                return item


# ── alert table access ───────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=5)
    c.row_factory = sqlite3.Row
    return c


def latest_alert_after(profile_id: str, rule_id: str, after: datetime) -> Optional[sqlite3.Row]:
    with _db() as c:
        return c.execute(
            "SELECT id, timestamp FROM alerts WHERE profile_id=? AND rule_id=? AND timestamp>? "
            "ORDER BY timestamp DESC LIMIT 1",
            (profile_id, rule_id, after.isoformat())).fetchone()


async def wait_for_alert(profile_id: str, rule_id: str, after: datetime,
                         timeout: float, poll: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = latest_alert_after(profile_id, rule_id, after)
        if row:
            return row, _utcnow()
        await asyncio.sleep(poll)
    return None, None


def purge_probe_alerts(profile_id: str) -> int:
    with _db() as c:
        n = c.execute("DELETE FROM alerts WHERE profile_id=?", (profile_id,)).rowcount
        c.commit()
    return n


# ── the measurement ──────────────────────────────────────────────────────────

async def run_trials(args) -> list[dict]:
    rows: list[dict] = []
    inject = args.mode == "inject"
    print(f"HA: {HA_URL}   mode: {args.mode}   entity: {args.entity}   "
          f"profile: {args.profile_id}   rule: {args.rule_id}")
    print(f"{'#':>3}  {'inj->ws':>7}  {'inj->alert':>9}  {'alert->push':>10}  {'inj->push':>8}")

    async with HAEvents(args.entity) as ha:
        if inject:                                    # make sure we start from "off"
            set_probe_state(args.entity, False)
            await asyncio.sleep(1.0)
            while not ha.q.empty():
                ha.q.get_nowait()

        for i in range(1, args.trials + 1):
            if inject:
                t_before = _utcnow()
                t_inject = set_probe_state(args.entity, True)
            else:
                print(f"  waiting for {args.entity} → on (trial {i}) …", end="\r")
                item = await ha.wait_for("state", args.observe_timeout,
                                         lambda it: it[2] == "on")
                if not item:
                    print("\n  no state change observed; stopping.")
                    break
                t_before = t_inject = item[1]         # the WS arrival is our reference

            item = await ha.wait_for("state", args.alert_timeout, lambda it: it[2] == "on") \
                if inject else item
            t_ws = item[1] if item else None
            t_ha = _parse_ts(item[3]) if (item and item[3]) else None

            row, t_seen = await wait_for_alert(args.profile_id, args.rule_id, t_before,
                                               args.alert_timeout)
            t_alert = _parse_ts(row["timestamp"]) if row else None

            t_push = None
            if row and args.push_timeout > 0:
                tag = f"dari-{args.rule_id}"
                p = await ha.wait_for("push", args.push_timeout,
                                      lambda it: it[2] in (None, tag))
                t_push = p[1] if p else None

            if inject:
                set_probe_state(args.entity, False)

            rec = {
                "trial": i,
                "t_inject": _iso(t_inject), "t_ha": _iso(t_ha), "t_ws": _iso(t_ws),
                "t_alert": _iso(t_alert), "t_seen": _iso(t_seen), "t_push": _iso(t_push),
                "t_before": _iso(t_before),
                "submit_to_alert_s": _secs(t_before, t_alert),   # includes the REST round-trip to HA
                "submit_to_ws_s":    _secs(t_before, t_ws),
                "inject_to_ws_s":    _secs(t_inject, t_ws),
                "inject_to_alert_s": _secs(t_inject, t_alert),
                "ws_to_alert_s":     _secs(t_ws, t_alert),
                "alert_to_seen_s":   _secs(t_alert, t_seen),
                "alert_to_push_s":   _secs(t_alert, t_push),
                "inject_to_push_s":  _secs(t_inject, t_push),
                "alert_id": row["id"] if row else "",
                "fired": bool(row),
            }
            rows.append(rec)
            f = lambda v: f"{v:7.3f}" if v is not None else "      —"
            print(f"{i:>3}  {f(rec['inject_to_ws_s'])}  {f(rec['inject_to_alert_s']):>9}  "
                  f"{f(rec['alert_to_push_s']):>10}  {f(rec['inject_to_push_s']):>8}"
                  + ("" if row else "   NO ALERT — is the rule engine running with the probe profile?"))
            await asyncio.sleep(args.gap)
    return rows


def write_outputs(rows: list[dict], args) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = OUT_DIR / f"latency_{stamp}"

    with open(f"{base}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    fired = [r for r in rows if r["fired"]]
    summary = {
        "generated": _utcnow().isoformat(), "mode": args.mode, "entity": args.entity,
        "profile_id": args.profile_id, "rule_id": args.rule_id, "ha_url": HA_URL,
        "trials": len(rows), "fired": len(fired), "missed": len(rows) - len(fired),
        "segments_s": {
            "submit_to_alert": _summ([r["submit_to_alert_s"] for r in rows]),
            "submit_to_ws":    _summ([r["submit_to_ws_s"] for r in rows]),
            "inject_to_ws":    _summ([r["inject_to_ws_s"] for r in rows]),
            "ws_to_alert":     _summ([r["ws_to_alert_s"] for r in rows]),
            "inject_to_alert": _summ([r["inject_to_alert_s"] for r in rows]),
            "alert_to_push":   _summ([r["alert_to_push_s"] for r in rows]),
            "inject_to_push":  _summ([r["inject_to_push_s"] for r in rows]),
        },
        "notes": [
            "submit_to_alert: from just before the REST call that changes the state in HA to the "
            "alert row (harness + HA round-trip + engine). inject_to_alert: from the moment HA "
            "acknowledged the change, i.e. the engine's own reaction time. Both exclude the physical "
            "sensor's radio hop to HA.",
            "inject_to_push includes HA notify, FCM and the phone; needs push enabled and the "
            "Companion app's mobile_app_notification_received event.",
            "t_ha uses the HA hub's clock and is informational only.",
        ],
    }
    Path(f"{base}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        def cdf(ax, vals, label):
            xs = sorted(v for v in vals if v is not None)
            if not xs:
                return
            ys = [(k + 1) / len(xs) for k in range(len(xs))]
            ax.step(xs, ys, where="post", label=f"{label} (n={len(xs)})")

        fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=150)
        cdf(ax, [r["submit_to_alert_s"] for r in rows], "state change submitted → alert row")
        cdf(ax, [r["inject_to_alert_s"] for r in rows], "HA acknowledged → alert row (engine only)")
        cdf(ax, [r["inject_to_push_s"] for r in rows], "sensor → phone (end-to-end)")
        ax.set_xlabel("latency (s)"); ax.set_ylabel("fraction of trials ≤ x")
        ax.set_ylim(0, 1.02); ax.grid(alpha=.3); ax.legend(loc="lower right", frameon=False)
        ax.set_title("Alert latency — empirical CDF", fontsize=10)
        fig.tight_layout()
        fig.savefig(f"{base}.png"); fig.savefig(f"{base}.pdf")
        summary["figure"] = f"{base}.pdf"
    except Exception as e:                       # plotting is a convenience, not the result
        print(f"(figure skipped: {e})")

    print(f"\nwrote {base}.csv / .json" + (" / .png / .pdf" if "figure" in summary else ""))
    return summary


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--setup", action="store_true",
                    help="write the probe profile and exit")
    ap.add_argument("--push", action="store_true",
                    help="with --setup: enable live phone pushes in the probe profile")
    ap.add_argument("--source-profile", default=str(DEFAULT_PROFILE),
                    help="profile whose notify block the probe copies (--setup)")
    ap.add_argument("--mode", choices=["inject", "observe"], default="inject")
    ap.add_argument("--entity", default=PROBE_ENTITY,
                    help="entity to flip (inject) or watch (observe)")
    ap.add_argument("--profile", default=str(PROBE_PROFILE),
                    help="profile the running rule engine was started with")
    ap.add_argument("--rule-id", default=PROBE_RULE_ID,
                    help="rule whose alerts to time")
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between trials")
    ap.add_argument("--alert-timeout", type=float, default=30.0)
    ap.add_argument("--push-timeout", type=float, default=20.0,
                    help="0 disables waiting for phone receipt")
    ap.add_argument("--observe-timeout", type=float, default=600.0,
                    help="observe mode: max seconds to wait for each real state change")
    ap.add_argument("--keep-alerts", action="store_true",
                    help="leave probe alert rows in alerts.db")
    ap.add_argument("--keep-entity", action="store_true",
                    help="leave the virtual probe entity in HA after the run")
    ap.add_argument("--cleanup", action="store_true",
                    help="only remove the probe entity from HA and probe alert rows, then exit")
    args = ap.parse_args()

    if args.setup:
        p = write_probe_profile(Path(args.source_profile), push=args.push)
        print(f"wrote {p}\n  push: {'ENABLED — real notifications will go to the phone' if args.push else 'disabled'}\n"
              f"\nstart the rule engine with it, then run this script again:\n"
              f"  conda run -n LLMs python -m dari.rule_engine.engine --profile {p}\n"
              f"  conda run -n LLMs python scripts/measure_latency.py --trials 50")
        return

    if args.cleanup:
        ok = delete_probe_entity(args.entity) if HA_TOKEN and ha_ok() else False
        n = purge_probe_alerts(PROBE_PROFILE_ID) if DB_PATH.exists() else 0
        print(f"probe entity {args.entity}: {'removed from HA' if ok else 'not removed (absent or HA unreachable)'}; "
              f"{n} probe alert rows removed")
        return

    profile_path = Path(args.profile)
    if not profile_path.exists():
        sys.exit(f"profile not found: {profile_path}  (run --setup first?)")
    prof = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    args.profile_id = prof.get("profile_id", PROBE_PROFILE_ID)
    if not any(r.get("id") == args.rule_id for r in prof.get("rules", [])):
        sys.exit(f"rule {args.rule_id!r} not in {profile_path}")
    if not HA_TOKEN:
        sys.exit("HA_TOKEN not set (.env)")
    if not ha_ok():
        sys.exit(f"HA not reachable at {HA_URL} — is Tailscale up?")
    if not DB_PATH.exists():
        sys.exit(f"alerts DB not found: {DB_PATH} — is the rule engine running?")
    if args.mode == "inject" and not args.entity.startswith("binary_sensor.dari_"):
        sys.exit("inject mode only flips virtual dari_* entities; use --mode observe for real sensors")

    rows = asyncio.run(run_trials(args))
    if not rows:
        sys.exit("no trials recorded")
    summary = write_outputs(rows, args)

    s = summary["segments_s"]
    print(f"\nfired {summary['fired']}/{summary['trials']}")
    for k in ("submit_to_alert", "inject_to_ws", "ws_to_alert", "inject_to_alert", "alert_to_push", "inject_to_push"):
        v = s[k]
        print(f"  {k:<16} " + (f"n={v['n']:<3} median {v['median']:.3f}s  p90 {v['p90']:.3f}s  max {v['max']:.3f}s"
                               if v.get("n") else "n=0"))

    if not args.keep_alerts and args.mode == "inject":
        n = purge_probe_alerts(args.profile_id)
        print(f"\nremoved {n} probe alert rows from {DB_PATH.name}")


if __name__ == "__main__":
    main()
