"""
Shared, request-friendly helpers used by the API (and reusable by any client backend).

Keeps a short-lived cache of the sensor index (which entities are where) so the API
doesn't hit the HA registry on every request, plus a module-level inference context so
home/away detection persists across requests in the same process.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Optional

from dari.rule_engine.ha_client import states_as_dict, get_sensors_by_area
from dari.rule_engine import alert_store

from .models import CurrentStatus, WorldState
from .state import build_sensor_index, build_world_state
from .detectors import resolve_activity, ActivityCandidate
from .models import catalog_entry
from . import activity_store

_INDEX_CACHE: dict = {"idx": None, "built_at": 0.0}
_INDEX_TTL = 30  # seconds
_API_CTX: dict = {}  # persists front_door_open_at / away_since across API calls


def get_sensor_index(watch: Optional[dict] = None, force: bool = False) -> dict:
    now = time.time()
    if force or _INDEX_CACHE["idx"] is None or (now - _INDEX_CACHE["built_at"]) > _INDEX_TTL:
        states = states_as_dict()
        _INDEX_CACHE["idx"] = build_sensor_index(get_sensors_by_area(), states, watch=watch)
        _INDEX_CACHE["built_at"] = now
    return _INDEX_CACHE["idx"]


def _risk_level(active_alerts: list) -> str:
    sev = {a.severity for a in active_alerts}
    if "CRITICAL" in sev or "HIGH" in sev:
        return "alert"
    if active_alerts:
        return "attention"
    return "ok"


def compute_status(profile, world: WorldState, cand: ActivityCandidate,
                   last_evt, active_alerts: list) -> CurrentStatus:
    """Assemble a CurrentStatus from a resolved world + the persisted timeline."""
    label, category, icon, _sev = catalog_entry(cand.activity)
    now = world.timestamp

    since = last_evt.timestamp if last_evt else None
    duration = None
    if since:
        try:
            started = datetime.fromisoformat(since)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            duration = int((now - started).total_seconds() / 60)
        except ValueError:
            pass

    return CurrentStatus(
        profile_id=profile.profile_id,
        patient_name=profile.patient_name,
        timestamp=now.isoformat(),
        home=world.home,
        current_zone=cand.zone or world.current_area,
        current_activity=cand.activity,
        activity_label=label,
        activity_icon=icon,
        activity_category=category,
        since=since,
        duration_minutes=duration,
        last_movement=since,
        presence_by_zone={a: bool(o) for a, o in world.area_occupied.items()},
        risk_level=_risk_level(active_alerts),
        active_alerts=len(active_alerts),
    )


def get_status(profile, include_demo: bool = False) -> CurrentStatus:
    """Live status for one profile — what the Summary/Room screens poll."""
    states = states_as_dict()
    idx = get_sensor_index(watch=getattr(profile, "watch", None))
    world = build_world_state(states, idx)
    cand = resolve_activity(world, _API_CTX, profile)
    last_evt = activity_store.last_event(profile.profile_id, include_demo=include_demo)
    active_alerts = alert_store.query(profile_id=profile.profile_id, acknowledged=False, limit=50, include_demo=include_demo)
    return compute_status(profile, world, cand, last_evt, active_alerts)
