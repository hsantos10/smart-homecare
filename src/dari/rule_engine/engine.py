"""
Rule Engine — subscribes to HA WebSocket, evaluates rules, stores alerts.

Usage:
    python -m rule_engine.engine --profile profiles/patient_001.yaml

The engine runs two loops:
  1. WebSocket listener  → triggers fall, door_opened, night_wandering on state_changed
  2. Periodic poll (60s) → triggers inactivity, long_stay, and the sustained-threshold
     rules (sensor_threshold, env_threshold, vital_threshold)
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

import websockets
from dotenv import load_dotenv

from . import care_mode
from .alert_store import init_db, insert, last_fired, make_alert
from .evaluators import EVALUATORS, render_message
from .ha_client import HA_TOKEN, HA_WS, states_as_dict, get_all_states, get_sensors_by_area
from .models import Profile, Rule
from .notifier import NotifyConfig, notify_alert

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ENGINE] %(message)s")
log = logging.getLogger(__name__)

# Trigger types evaluated on WebSocket events (fast-path)
REALTIME_TRIGGERS = {"fall", "door_opened", "night_wandering"}
# Trigger types evaluated on periodic poll (need time elapsed)
POLL_TRIGGERS     = {"room_inactivity", "global_inactivity", "long_stay", "sensor_threshold",
                     "env_threshold", "vital_threshold"}
POLL_INTERVAL_SEC = 60
MODE_CACHE_SEC    = 15    # how stale the care mode may be (it's read on every WS event)


def _log_mode_change(profile_id: str, mode: str, detail: str) -> None:
    """Timeline entry for a care-mode change, so the history shows when alerts were paused."""
    from dari.activity_engine import activity_store
    from dari.activity_engine.models import ActivityEvent
    key = "care_mode_alone" if mode == care_mode.ALONE else "care_mode_with_others"
    try:
        activity_store.insert(ActivityEvent.create(profile_id, key, detail=detail))
    except Exception as exc:
        log.warning("Could not log care-mode change: %s", exc)


class RuleEngine:
    def __init__(self, profile: Profile, dry_run_notify: bool = False):
        self.profile = profile
        self.notify_cfg = NotifyConfig.from_dict(profile.notify)
        self.dry_run_notify = dry_run_notify
        self.ctx: dict = {
            "door_open_since":  {},   # entity_id → datetime
            "zone_entry_times": {},   # zone → datetime
            "area_sensors":     {},   # area_name → {presence, door, fall, numeric, all}
            "entity_area":      {},   # entity_id → area_name (from area_sensors["all"])
            "watch":            dict(profile.watch),  # signal → entity_id, for vital_threshold
            "cond_since":       {},   # threshold rules: key → when the condition began holding
            "render_vars":      {},   # rule_id → extra message vars ({{value}}, {{sensor}})
        }
        self._state: dict = {}        # entity_id → state dict (kept current)
        self._mode: str = care_mode.ALONE
        self._mode_read_at: float = 0.0

    def _build_area_map(self) -> None:
        """Fetch area→sensor mapping from HA and cache in ctx."""
        try:
            self.ctx["area_sensors"] = get_sensors_by_area()
            self.ctx["entity_area"] = {
                eid: area for area, b in self.ctx["area_sensors"].items() for eid in b.get("all", [])
            }
            log.info("Area map built: %s", list(self.ctx["area_sensors"].keys()))
        except Exception as exc:
            log.warning("Could not build area map: %s", exc)

    # ── Evaluation ───────────────────────────────────────────────────────────

    def _current_mode(self) -> str:
        if time.monotonic() - self._mode_read_at > MODE_CACHE_SEC:
            m = care_mode.get(self.profile.profile_id)
            if m["mode"] != self._mode:
                log.info("Care mode: %s%s", m["mode"], " (timer ended)" if m["expired"] else "")
                if m["expired"]:
                    _log_mode_change(self.profile.profile_id, m["mode"], "timer ended")
            self._mode = m["mode"]
            self._mode_read_at = time.monotonic()
        return self._mode

    def _evaluate_rules(self, trigger_set: set[str]) -> None:
        """Evaluate all active rules whose type is in trigger_set."""
        state = self._state
        mode = self._current_mode()
        for rule in self.profile.active_rules:
            if rule.trigger_type not in trigger_set:
                continue
            if not care_mode.rule_active_in(rule, mode):
                # Paused by the care mode. Drop its timers so it starts fresh on resume
                # instead of firing at once on time that ran while it was paused.
                self.ctx["cond_since"].pop(rule.id, None)
                if rule.zone:
                    self.ctx["zone_entry_times"].pop(rule.zone, None)
                continue
            evaluator = EVALUATORS.get(rule.trigger_type)
            if not evaluator:
                continue
            try:
                fired, zone = evaluator(rule, state, self.ctx)
            except Exception as exc:
                log.warning("Error evaluating rule %s: %s", rule.id, exc)
                continue

            extra = self.ctx["render_vars"].pop(rule.id, {})
            if not fired:
                continue

            # Cooldown check
            prev = last_fired(self.profile.profile_id, rule.id)
            if prev:
                elapsed_min = (datetime.now(timezone.utc) - prev).total_seconds() / 60
                if elapsed_min < rule.cooldown_minutes:
                    log.debug("Rule %s on cooldown (%.1f min)", rule.id, elapsed_min)
                    continue

            message = render_message(
                rule.message,
                patient_name=self.profile.patient_name,
                zone=zone,
                duration_minutes=rule.duration_minutes,
                **extra,
            )
            alert = make_alert(
                profile_id=self.profile.profile_id,
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                message=message,
                zone=zone,
            )
            insert(alert)
            log.info("🔔 ALERT [%s] %s — %s", rule.severity, rule.name, message)

            # Push to the caregiver's phone via HA. Best-effort by design: a delivery
            # failure must not stop the alert being recorded or the loop continuing.
            notify_alert(alert, self.profile.patient_name, self.notify_cfg,
                         dry_run=self.dry_run_notify)

    # ── WebSocket listener ───────────────────────────────────────────────────

    async def _ws_listener(self) -> None:
        while True:
            try:
                async with websockets.connect(HA_WS, open_timeout=15) as ws:
                    # Auth
                    msg = json.loads(await ws.recv())
                    if msg.get("type") != "auth_required":
                        raise RuntimeError(f"Unexpected greeting: {msg}")
                    await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                    msg = json.loads(await ws.recv())
                    if msg.get("type") != "auth_ok":
                        raise RuntimeError(f"Auth failed: {msg}")
                    log.info("HA WebSocket connected and authenticated.")

                    # Subscribe to state_changed events
                    await ws.send(json.dumps({
                        "id": 1,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }))
                    msg = json.loads(await ws.recv())
                    if not msg.get("success", False):
                        raise RuntimeError(f"Subscribe failed: {msg}")
                    log.info("Subscribed to state_changed events.")

                    # Initial state snapshot
                    self._state = states_as_dict()
                    log.info("Initial state loaded: %d entities.", len(self._state))

                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") != "event":
                            continue
                        data = event.get("event", {}).get("data", {})
                        entity_id = data.get("entity_id")
                        new_state  = data.get("new_state")
                        if entity_id and new_state:
                            self._state[entity_id] = new_state
                        self._evaluate_rules(REALTIME_TRIGGERS)

            except (websockets.ConnectionClosed, OSError, RuntimeError) as exc:
                log.warning("WebSocket disconnected: %s — reconnecting in 15s", exc)
                await asyncio.sleep(15)

    # ── Periodic poll ────────────────────────────────────────────────────────

    async def _poller(self) -> None:
        while True:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                self._state = states_as_dict()
                self._evaluate_rules(POLL_TRIGGERS)
            except Exception as exc:
                log.warning("Poller error: %s", exc)

    # ── Entry point ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        init_db()
        log.info("Starting rule engine for profile: %s", self.profile.profile_id)
        log.info("Active rules: %d", len(self.profile.active_rules))
        if self.notify_cfg.enabled and self.notify_cfg.services:
            log.info("Push notifications: %s (>= %s)%s",
                     ", ".join(self.notify_cfg.services), self.notify_cfg.min_severity,
                     "  [DRY RUN]" if self.dry_run_notify else "")
        else:
            log.info("Push notifications: disabled (see `notify:` in the profile)")
        self._build_area_map()
        await asyncio.gather(self._ws_listener(), self._poller())


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = ArgumentParser(description="DARI Rule Engine")
    parser.add_argument("--profile", required=True, help="Path to patient profile YAML")
    parser.add_argument("--dry-run-notify", action="store_true",
                        help="Log push notifications instead of sending them to phones")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    if not profile_path.exists():
        print(f"Profile not found: {profile_path}", file=sys.stderr)
        sys.exit(1)

    profile = Profile.load(str(profile_path))
    engine = RuleEngine(profile, dry_run_notify=args.dry_run_notify)
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
