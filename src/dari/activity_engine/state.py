"""
Turn raw Home Assistant entity states into a normalised `WorldState`.

`build_sensor_index` runs once (and is refreshed periodically) to learn which entities
belong to which area / zone. `build_world_state` runs every tick and is cheap.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Optional

from .models import WorldState
from .zones import classify_zone, is_door_entity, door_kind, is_toilet_vibration_entity

# FP2 presence sensors drop out between re-triggers even while someone stays in the room.
# Measured off-gaps between re-triggers: p50≈16s, p90≈82s, p99≈116s — a 10s hold cleared
# "occupied" through most of them, flapping area_since / current_area on every quiet moment.
PRESENCE_HOLD_SEC = 90
# Smart-plug appliance detection. Hysteresis: ON at >= on_watts, OFF only after power has
# stayed <= off_watts for APPLIANCE_OFF_HOLD_SEC. The gap matters for microwaves: at
# part power the magnetron cycles on/off every ~10-20 s while the fan and light keep
# drawing tens of watts, so a single threshold would log a burst of on/off pairs.
APPLIANCE_ON_WATTS = 25
APPLIANCE_OFF_WATTS = 8
APPLIANCE_OFF_HOLD_SEC = 30
# name keyword -> kind; cooking kinds let the resolver say "Cooking" in the kitchen.
APPLIANCE_KINDS = ("microwave", "kettle", "stove", "cooktop", "hot_plate", "oven",
                   "toaster", "coffee", "rice_cooker", "air_fryer")
COOKING_KINDS = set(APPLIANCE_KINDS)
WATCH_STALE_MIN = 5     # ignore wearable readings older than this — command_update_sensors pushes every 30s, so 5 min means ~10 missed cycles before we stop trusting it

# profile.watch keys that are plain numeric sensors (vs. binary/text state)
_WATCH_NUMERIC = {"heart_rate", "steps_today"}
_WATCH_BOOL_ON = {"on_body"}


def _friendly(states: dict, eid: str) -> str:
    return states.get(eid, {}).get("attributes", {}).get("friendly_name", "")


def _appliance_kind(*names: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", " ".join(n or "" for n in names).lower())
    return next((k for k in APPLIANCE_KINDS if k in text), "appliance")


def build_sensor_index(area_sensors: dict, states: dict, watch: dict | None = None,
                       appliances: dict | None = None) -> dict:
    """
    Build a static map of which entities matter for activity inference.

    `area_sensors` is the output of rule_engine.ha_client.get_sensors_by_area():
        {area_name: {"presence": [...], "door": [...], "fall": [...], "numeric": [...], "all": [...]}}

    `watch` is a profile's `watch:` block (entity_id per wearable signal), e.g.
        {"heart_rate": "sensor.<watch>_heart_rate", "sleep_confidence": "sensor...", ...}

    `appliances` is a profile's `appliances:` block, keyed by plug power entity_id:
        {"sensor.kitchen_plug_power": {"name": "Microwave", "kind": "microwave",
                                       "area": "Kitchen", "on_watts": 25, "off_watts": 8}}
    Every field is optional, and plugs not listed are still tracked under their HA name.

    Returns:
        {
          "areas": [area names],
          "presence_by_area": {area: [presence+fall entity_ids]},
          "area_of": {entity_id: area},
          "zone_of": {entity_id: semantic_zone or None},
          "doors": [{"entity_id","kind","area"}],
          "falls": [entity_ids],
          "plugs": [power sensor entity_ids],
          "watch": {signal_name: entity_id},
        }
    """
    idx: dict = {
        "areas": [],
        "presence_by_area": {},
        "area_of": {},
        "zone_of": {},
        "doors": [],
        "falls": [],
        "plugs": [],
        "plug_area": {},          # entity_id -> area, so "cooking" only counts kitchen plugs
        "watch": dict(watch or {}),
        "toilet_vibration": [],   # entity_ids of toilet-flush vibration sensors
        "appliances": {},         # plug power entity_id -> {name, kind, area, on_watts, off_watts}
    }

    for area, buckets in area_sensors.items():
        idx["areas"].append(area)
        presence = list(buckets.get("presence", [])) + list(buckets.get("fall", []))
        idx["presence_by_area"][area] = presence
        for eid in presence:
            idx["area_of"][eid] = area
            idx["zone_of"][eid] = classify_zone(eid, _friendly(states, eid))
        for eid in buckets.get("fall", []):
            idx["falls"].append(eid)
        for eid in buckets.get("door", []):
            idx["doors"].append({
                "entity_id": eid,
                "kind": door_kind(eid, _friendly(states, eid)),
                "area": area,
            })
        for eid in buckets.get("all", []):
            if eid.split(".")[0] != "sensor":
                continue
            unit = states.get(eid, {}).get("attributes", {}).get("unit_of_measurement", "")
            if "power" in eid.lower() and unit in ("W", "kW"):
                idx["plug_area"][eid] = area

    # Doors/contacts that HA didn't assign to an area still matter (e.g. front door).
    seen_doors = {d["entity_id"] for d in idx["doors"]}
    for eid, s in states.items():
        if eid in seen_doors:
            continue
        if eid.split(".")[0] == "binary_sensor" and is_door_entity(eid, _friendly(states, eid)):
            idx["doors"].append({
                "entity_id": eid,
                "kind": door_kind(eid, _friendly(states, eid)),
                "area": None,
            })

    # Toilet-flush vibration sensor(s) — identified by keyword regardless of HA area
    # tag, which is often wrong for a pipe-mounted sensor (see zones.py docstring).
    for eid, s in states.items():
        if eid.split(".")[0] == "binary_sensor" and is_toilet_vibration_entity(eid, _friendly(states, eid)):
            idx["toilet_vibration"].append(eid)

    # Smart-plug power sensors (for cooking / appliance use). Watts only.
    for eid, s in states.items():
        if eid.split(".")[0] != "sensor":
            continue
        low = eid.lower()
        unit = s.get("attributes", {}).get("unit_of_measurement", "")
        if "power" in low and unit in ("W", "kW"):
            idx["plugs"].append(eid)

    # One appliance per plug: profile overrides first, HA's name/area as the fallback.
    appliances = appliances or {}
    for eid in idx["plugs"]:
        cfg = appliances.get(eid) or {}
        name = cfg.get("name") or _friendly(states, eid) or eid
        area = cfg.get("area") or idx["plug_area"].get(eid)
        if cfg.get("area"):
            idx["plug_area"][eid] = cfg["area"]   # fixes a plug HA has in the wrong area
        idx["appliances"][eid] = {
            "name": re.sub(r"\s*power$", "", name, flags=re.I) or name,
            "kind": cfg.get("kind") or _appliance_kind(cfg.get("name", ""), name, eid),
            "area": area,
            "on_watts": float(cfg.get("on_watts", APPLIANCE_ON_WATTS)),
            "off_watts": float(cfg.get("off_watts", APPLIANCE_OFF_WATTS)),
        }

    return idx


def _to_float(val) -> Optional[float]:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _is_fresh(state: Optional[dict], now: datetime) -> bool:
    """A wearable reading only corroborates the heuristic if it's actually recent —
    a watch that stopped syncing days ago must not silently count as evidence."""
    if not state:
        return False
    ts = state.get("last_changed") or state.get("last_updated")
    if not ts:
        return False
    try:
        changed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - changed).total_seconds() <= WATCH_STALE_MIN * 60


def _apply_watch(w: WorldState, states: dict, watch: dict, prev: Optional[WorldState], now: datetime) -> None:
    """Populate WorldState's wearable fields, gated on freshness (see _is_fresh)."""
    fresh = {key: _is_fresh(states.get(eid), now) for key, eid in watch.items()}
    w.watch_stale = not any(fresh.values())

    def read(key):
        eid = watch.get(key)
        return states.get(eid, {}).get("state") if eid and fresh.get(key) else None

    w.heart_rate = _to_float(read("heart_rate"))
    w.sleep_confidence = _to_float(read("sleep_confidence"))
    w.steps_today = _to_float(read("steps_today"))
    if w.steps_today is not None and prev is not None and prev.steps_today is not None:
        w.steps_delta = max(0.0, w.steps_today - prev.steps_today)

    on_body_raw = read("on_body")
    w.on_body = (on_body_raw == "on") if on_body_raw is not None else None

    w.activity_state = read("activity_state")
    w.phone_activity = read("phone_activity")


def build_world_state(
    states: dict,
    idx: dict,
    prev: Optional[WorldState] = None,
    now: Optional[datetime] = None,
) -> WorldState:
    """Construct the current WorldState from live HA states."""
    now = now or datetime.now(timezone.utc)
    w = WorldState(timestamp=now)

    # ── Areas ──────────────────────────────────────────────────────────────────
    # Every known area gets an explicit True/False entry — callers (e.g. the API's
    # presence_by_zone, used to render one tab per room) need to see unoccupied
    # rooms too, not just have them silently missing from the dict.
    for area, entities in idx["presence_by_area"].items():
        raw_occupied = any(states.get(e, {}).get("state") == "on" for e in entities)
        prev_occupied = bool(prev and prev.area_occupied.get(area))
        clear_since = prev.area_clear_since.get(area) if prev else None

        w.area_occupied[area] = False
        if raw_occupied:
            w.area_occupied[area] = True
            w.area_since[area] = prev.area_since.get(area, now) if prev_occupied else now
        elif prev_occupied:
            clear_since = clear_since or now
            if (now - clear_since).total_seconds() < PRESENCE_HOLD_SEC:
                w.area_occupied[area] = True
                w.area_since[area] = prev.area_since.get(area, now)
                w.area_clear_since[area] = clear_since
            else:
                w.area_clear_since[area] = clear_since
        if raw_occupied:
            w.area_clear_since.pop(area, None)

    # ── Sub-zones (bed, sofa, …) ────────────────────────────────────────────────
    # Keyed by (area, zone), NOT just zone name — a "desk" held True in Study room must
    # never be read as "the desk in whatever area happens to be current_area right now".
    # Multiple areas can each have their own e.g. "bed" zone; they must not leak into
    # each other, especially in a multi-occupant home.
    for eid, zone in idx["zone_of"].items():
        if not zone:
            continue
        area = idx["area_of"].get(eid)
        key = (area, zone)
        raw_occupied = states.get(eid, {}).get("state") == "on"
        prev_occupied = bool(prev and prev.zone_occupied.get(key))
        clear_since = prev.zone_clear_since.get(key) if prev else None

        if raw_occupied:
            w.zone_occupied[key] = True
        elif prev_occupied:
            clear_since = clear_since or now
            if (now - clear_since).total_seconds() < PRESENCE_HOLD_SEC:
                w.zone_occupied[key] = True
                w.zone_clear_since[key] = clear_since
            else:
                w.zone_clear_since[key] = clear_since
        if raw_occupied:
            w.zone_clear_since.pop(key, None)

    # ── Doors ───────────────────────────────────────────────────────────────────
    for d in idx["doors"]:
        w.door_open[d["entity_id"]] = states.get(d["entity_id"], {}).get("state") == "on"

    # ── Plugs ─────────────────────────────────────────────────────────────────────
    plug_area = idx.get("plug_area", {})
    for eid in idx["plugs"]:
        watts = _to_float(states.get(eid, {}).get("state"))
        if watts is not None:
            unit = states.get(eid, {}).get("attributes", {}).get("unit_of_measurement", "W")
            watts = watts * 1000 if unit == "kW" else watts
            w.plug_power[eid] = watts
            area = plug_area.get(eid)
            if area:
                w.plug_power_by_area[area] = max(w.plug_power_by_area.get(area, 0.0), watts)

    # ── Appliances (hysteresis on plug power — see APPLIANCE_OFF_HOLD_SEC) ─────────
    for eid, app in idx.get("appliances", {}).items():
        watts = w.plug_power.get(eid)
        on_since = prev.appliance_on.get(eid) if prev else None
        if watts is None:                       # unavailable: keep the last known state
            if on_since:
                w.appliance_on[eid] = on_since
            continue
        if watts >= app["on_watts"]:
            w.appliance_on[eid] = on_since or now
        elif on_since:
            if watts > app["off_watts"]:
                w.appliance_on[eid] = on_since
            else:
                below = prev.appliance_below_since.get(eid) or now
                if (now - below).total_seconds() < APPLIANCE_OFF_HOLD_SEC:
                    w.appliance_on[eid] = on_since
                    w.appliance_below_since[eid] = below
    w.cooking_appliance_on = any(
        idx["appliances"][e]["kind"] in COOKING_KINDS for e in w.appliance_on)

    # ── Falls ─────────────────────────────────────────────────────────────────────
    w.fall_active = any(states.get(e, {}).get("state") == "on" for e in idx["falls"])

    # ── Toilet vibration (flush) ────────────────────────────────────────────────────
    w.toilet_vibration = any(states.get(e, {}).get("state") == "on" for e in idx.get("toilet_vibration", []))

    # ── Derived ────────────────────────────────────────────────────────────────────
    w.any_presence = any(w.area_occupied.values())
    occupied_areas = [a for a, occ in w.area_occupied.items() if occ]
    if occupied_areas:
        # Current area = the occupied area that turned on most recently.
        w.current_area = max(occupied_areas, key=lambda a: w.area_since.get(a, now))
    elif prev:
        w.current_area = prev.current_area  # keep last known; person may be still

    # Movement = a change in which areas/zones are occupied.
    if prev is None:
        w.last_movement = now if w.any_presence else None
    else:
        changed = (
            w.area_occupied != prev.area_occupied
            or w.zone_occupied != prev.zone_occupied
        )
        w.last_movement = now if (changed and w.any_presence) else prev.last_movement

    # `home` is refined by the resolver using door history; default carry-over.
    w.home = True if w.any_presence else (prev.home if prev else True)

    # ── Wearable (optional, corroborating only) ─────────────────────────────────
    _apply_watch(w, states, idx.get("watch") or {}, prev, now)

    return w
