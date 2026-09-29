"""
Activity Engine — subscribes to HA, infers what the patient is doing, logs a timeline.

Usage:
    python -m activity_engine.engine --profile profiles/patient_001.yaml

Runs two loops (same pattern as rule_engine.engine):
  1. WebSocket listener → re-evaluates on every state_changed (fast: movement, doors, falls)
  2. Periodic poll (60s) → catches time-based states (inactivity while home)

Activity STATE changes are logged once, when the inferred activity changes and has been
stable for MIN_DWELL_SEC (debounces sensor flapping). Momentary events (door, fall, fridge)
are logged immediately, with per-type cooldowns.
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

import websockets
from dotenv import load_dotenv

from dari.rule_engine.ha_client import HA_TOKEN, HA_WS, states_as_dict, get_sensors_by_area, call_service
from dari.rule_engine.models import Profile

from .models import ActivityEvent, WorldState
from .state import build_sensor_index, build_world_state
from .detectors import resolve_activity, detect_discrete, transition_label
from . import activity_store

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ACTIVITY] %(message)s")
log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 60
MIN_DWELL_SEC = 25                       # an activity must persist this long before logging
DISCRETE_COOLDOWN = {                    # seconds between repeated momentary events
    "front_door_opened": 120,
    "fall_detected":      60,
    "fridge_left_open":  600,
    "toilet_flushed":     60,
    "refrigerator_use":   30,
    "cabinet_access":     30,
    "appliance_on":       30,   # per appliance (dedupe_key); state.py already debounces
    "appliance_off":      30,
}
DEFAULT_DISCRETE_COOLDOWN = 300

# Ask the Companion App to push a fresh sensor reading instead of waiting on its own
# background cycle, via the profile's `notify.services` (the caregiver/patient phone).
# Only the phone honors "command_update_sensors" — the Wear OS build ignores it (verified:
# pushing it to a watch's notify service left every watch sensor's last_changed unmoved).
# Watch-sourced signals stay on Wear OS's own schedule; see README.md's Wearable section.
REFRESH_MESSAGE = {"message": "command_update_sensors"}


class ActivityEngine:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.ctx: dict = {
            "current_activity_key": None,
            "current_since": None,
            "pending_key": None,
            "pending_since": None,
            "front_door_open_at": None,
            "away_since": None,
            "fridge_open_since": {},
            "discrete_last": {},          # key -> datetime last logged
        }
        self.idx: dict = {}
        self._state: dict = {}
        self._prev_world: WorldState | None = None

    def _build_index(self) -> None:
        try:
            self.idx = build_sensor_index(get_sensors_by_area(), self._state or states_as_dict(),
                                          watch=self.profile.watch,
                                          appliances=self.profile.appliances)
            log.info("Sensor index built: %d areas, %d doors, %d plugs",
                     len(self.idx.get("areas", [])), len(self.idx.get("doors", [])),
                     len(self.idx.get("plugs", [])))
            for eid, app in self.idx.get("appliances", {}).items():
                log.info("  appliance %s (%s, %s) <- %s, on >= %.0f W",
                         app["name"], app["kind"], app["area"] or "no area", eid, app["on_watts"])
        except Exception as exc:
            log.warning("Could not build sensor index: %s", exc)

    def _seed_current(self) -> None:
        last = activity_store.last_event(self.profile.profile_id)
        if last:
            self.ctx["current_activity_key"] = last.activity
            self.ctx["current_since"] = last.timestamp
            log.info("Seeded current activity from log: %s", last.activity)

    # ── Core tick ────────────────────────────────────────────────────────────────
    def tick(self) -> None:
        if not self.idx:
            return
        now = datetime.now(timezone.utc)
        world = build_world_state(self._state, self.idx, self._prev_world, now)
        cand = resolve_activity(world, self.ctx, self.profile)

        # Momentary events (immediate, with cooldown).
        for dc in detect_discrete(self._prev_world, world, self.idx, self.ctx):
            self._maybe_log_discrete(dc, now)

        # Continuous-state change (debounced).
        key = cand.activity
        if key != self.ctx["current_activity_key"]:
            if self.ctx["pending_key"] != key:
                self.ctx["pending_key"] = key
                self.ctx["pending_since"] = now
            elapsed = (now - self.ctx["pending_since"]).total_seconds()
            if elapsed >= MIN_DWELL_SEC:
                log_key = transition_label(self.ctx["current_activity_key"], cand, world, self.ctx)
                evt = ActivityEvent.create(
                    self.profile.profile_id, log_key,
                    zone=cand.zone, detail=cand.detail,
                    confidence=cand.confidence, source=cand.source, timestamp=now.isoformat(),
                )
                activity_store.insert(evt)
                log.info("📝 %s%s", evt.label, f" — {evt.detail}" if evt.detail else "")
                self.ctx["current_activity_key"] = key
                self.ctx["current_since"] = now.isoformat()
                self.ctx["pending_key"] = None
        else:
            self.ctx["pending_key"] = None

        self._prev_world = world

    def _maybe_log_discrete(self, cand, now: datetime) -> None:
        key = cand.activity
        ckey = f"{key}|{cand.dedupe_key}" if cand.dedupe_key else key
        last = self.ctx["discrete_last"].get(ckey)
        cooldown = DISCRETE_COOLDOWN.get(key, DEFAULT_DISCRETE_COOLDOWN)
        if last and (now - last).total_seconds() < cooldown:
            return
        evt = ActivityEvent.create(
            self.profile.profile_id, key, zone=cand.zone, detail=cand.detail,
            confidence=cand.confidence, source=cand.source, timestamp=now.isoformat(),
        )
        activity_store.insert(evt)
        self.ctx["discrete_last"][ckey] = now
        log.info("⚡ %s%s", evt.label, f" — {evt.detail}" if evt.detail else "")

    # ── WebSocket listener ─────────────────────────────────────────────────────────
    async def _ws_listener(self) -> None:
        while True:
            try:
                async with websockets.connect(HA_WS, open_timeout=15) as ws:
                    msg = json.loads(await ws.recv())
                    if msg.get("type") != "auth_required":
                        raise RuntimeError(f"Unexpected greeting: {msg}")
                    await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                    msg = json.loads(await ws.recv())
                    if msg.get("type") != "auth_ok":
                        raise RuntimeError(f"Auth failed: {msg}")
                    log.info("HA WebSocket connected.")

                    await ws.send(json.dumps({
                        "id": 1, "type": "subscribe_events", "event_type": "state_changed",
                    }))
                    msg = json.loads(await ws.recv())
                    if not msg.get("success", False):
                        raise RuntimeError(f"Subscribe failed: {msg}")

                    self._state = states_as_dict()
                    if not self.idx:
                        # get_sensors_by_area() calls asyncio.run() internally, which can't
                        # nest inside this coroutine's already-running event loop.
                        await asyncio.to_thread(self._build_index)
                    log.info("Initial state: %d entities.", len(self._state))

                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") != "event":
                            continue
                        data = event.get("event", {}).get("data", {})
                        eid, new_state = data.get("entity_id"), data.get("new_state")
                        if eid and new_state:
                            self._state[eid] = new_state
                        self.tick()
            except (websockets.ConnectionClosed, OSError, RuntimeError) as exc:
                log.warning("WebSocket disconnected: %s — reconnecting in 15s", exc)
                await asyncio.sleep(15)

    # ── Periodic poll (time-based states) ────────────────────────────────────────
    async def _poller(self) -> None:
        while True:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                self._request_watch_refresh()
                self._state = states_as_dict()
                self.tick()
            except Exception as exc:
                log.warning("Poller error: %s", exc)

    def _request_watch_refresh(self) -> None:
        """Ask the companion app(s) to push a fresh sensor reading (best-effort)."""
        for full in (self.profile.notify or {}).get("services", []):
            domain, _, service = str(full).partition(".")
            try:
                call_service(domain, service, REFRESH_MESSAGE)
            except Exception as exc:
                log.debug("Watch refresh push to %s.%s failed: %s", domain, service, exc)

    async def run(self) -> None:
        activity_store.init_db()
        self._seed_current()
        log.info("Starting activity engine for profile: %s", self.profile.profile_id)
        await asyncio.gather(self._ws_listener(), self._poller())


def main() -> None:
    parser = ArgumentParser(description="DARI Activity Engine")
    parser.add_argument("--profile", required=True, help="Path to patient profile YAML")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    if not profile_path.exists():
        print(f"Profile not found: {profile_path}", file=sys.stderr)
        sys.exit(1)

    profile = Profile.load(str(profile_path))
    asyncio.run(ActivityEngine(profile).run())


if __name__ == "__main__":
    main()
