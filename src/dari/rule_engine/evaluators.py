"""
One evaluator function per trigger type.
Each returns (fired: bool, context_zone: str | None).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from dari.env_metrics import env_metric, normalize_temp
from .models import Rule, TimeWindow


# ── Time-window helper ────────────────────────────────────────────────────────

def _in_window(tw: Optional[TimeWindow]) -> bool:
    """True if current local time falls inside the time window (handles midnight spans)."""
    if tw is None:
        return True
    now_str = datetime.now().strftime("%H:%M")
    s, e = tw.start, tw.end
    if s <= e:
        return s <= now_str < e
    # Spans midnight: e.g. start=22:00, end=06:00
    return now_str >= s or now_str < e


def _minutes_since(iso_ts: str) -> float:
    """Minutes elapsed since an ISO-8601 timestamp (UTC-aware or naive)."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60
    except Exception:
        return 0.0


def _render(template: str, **kwargs) -> str:
    """Simple {{key}} replacement."""
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", str(v or ""))
    return template


def compare(val: float, op: Optional[str], threshold: float) -> bool:
    return {
        "gt":  val > threshold,
        "lt":  val < threshold,
        "gte": val >= threshold,
        "lte": val <= threshold,
    }.get(op or "", False)


def _sustained(ctx: dict, key: str, condition: bool, minutes: Optional[int]) -> bool:
    """True once `condition` has held continuously for `minutes` (0/None = immediately).

    A single evaluation where the condition is false — or the reading is missing —
    restarts the clock, so a one-off spike (a hair dryer blast past the sensor, one
    bad watch sample) doesn't page anyone.
    """
    since = ctx.setdefault("cond_since", {})
    if not condition:
        since.pop(key, None)
        return False
    now = datetime.now(timezone.utc)
    start = since.setdefault(key, now)
    return (now - start).total_seconds() / 60 >= (minutes or 0)


def _set_vars(ctx: dict, rule: Rule, **kwargs) -> None:
    """Extra template variables for this firing ({{value}}, {{sensor}}), read by the engine."""
    ctx.setdefault("render_vars", {})[rule.id] = kwargs


def _last_seen(s: dict) -> str:
    """Most recent of HA's timestamps. `last_changed` alone only moves when the value
    changes, so a steady heart rate would otherwise look stale."""
    return max((s.get(k) or "" for k in ("last_reported", "last_updated", "last_changed")),
               default="")


# ── Evaluators ────────────────────────────────────────────────────────────────

def _presence_entities_for_zone(zone: str, ctx: dict) -> list[str]:
    """
    Return presence entity_ids for a given zone name.
    Uses ctx['area_sensors'] (built from HA area registry at engine startup).
    Falls back to name-pattern matching if the map is missing.
    """
    area_sensors = ctx.get("area_sensors", {})
    if area_sensors:
        # area_sensors keys are area *names* as returned by HA (e.g. "Living room")
        for area_name, buckets in area_sensors.items():
            if area_name.lower() == zone.lower():
                return buckets.get("presence", []) + buckets.get("fall", [])
    # Fallback: pattern match on entity_id
    zone_key = zone.lower().replace(" ", "_")
    return []


def _all_presence_entities(ctx: dict, state: dict) -> list[str]:
    """Return all known presence entity_ids (from area_sensors map or pattern match)."""
    area_sensors = ctx.get("area_sensors", {})
    if area_sensors:
        eids = []
        for buckets in area_sensors.values():
            eids.extend(buckets.get("presence", []))
            eids.extend(buckets.get("fall", []))
        return eids
    # Fallback
    return [
        e for e in state
        if ("presence_sensor" in e.lower() or "occupancy" in e.lower())
        and e.split(".")[0] == "binary_sensor"
    ]


_warned_no_fall = False

# binary_sensor "on", plus the words a sensor/event-style fall entity might report.
FALL_ACTIVE_STATES = {"on", "detected", "fall", "fall_detected", "fallen", "true"}


def eval_fall(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when a dedicated FP2 fall-detection entity turns on.

    Fails **closed**: if HA exposes no fall-specific entity, this rule never fires.
    (It used to fall back to matching *any* presence sensor, which turned every bit
    of movement into a CRITICAL "fall". A fall rule with nothing to bind to should
    stay silent, not scream.)
    """
    global _warned_no_fall
    area_sensors = ctx.get("area_sensors", {})
    fall_entities: list[str] = []
    zone_map: dict[str, str] = {}   # entity_id → area_name

    for area_name, buckets in area_sensors.items():
        for eid in buckets.get("fall", []):
            fall_entities.append(eid)
            zone_map[eid] = area_name

    # An explicit `entity_id` pins the rule to one entity, for a fall signal whose
    # name doesn't say "fall" (e.g. arriving via the Aqara cloud integration).
    if rule.entity_id:
        fall_entities = [rule.entity_id]
        zone_map.setdefault(rule.entity_id, ctx.get("entity_area", {}).get(rule.entity_id, ""))

    if not fall_entities:
        if not _warned_no_fall:
            import logging
            logging.getLogger(__name__).warning(
                "eval_fall: no fall-capable entity in HA — fall rules are inactive. "
                "Enable fall mode on a ceiling FP2 and confirm it publishes a fall "
                "entity (not just presence)."
            )
            _warned_no_fall = True
        return False, None

    # Filter to specific zone if requested
    if rule.zone and not rule.entity_id:
        fall_entities = [e for e in fall_entities
                         if zone_map.get(e, "").lower() == rule.zone.lower()]

    for eid in fall_entities:
        if str(state.get(eid, {}).get("state", "")).lower() in FALL_ACTIVE_STATES:
            zone = zone_map.get(eid) or rule.zone or "unknown area"
            return True, zone

    return False, None


def eval_door_opened(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """
    Fires when the door is open AND (no_return_minutes has elapsed OR no_return not set).
    Uses ctx['door_open_since'] to track when door first opened.
    """
    if not rule.entity_id:
        return False, None
    door_state = state.get(rule.entity_id, {}).get("state", "off")

    # Door closed — reset timer
    if door_state != "on":
        ctx["door_open_since"].pop(rule.entity_id, None)
        return False, None

    if not _in_window(rule.time_window):
        ctx["door_open_since"].pop(rule.entity_id, None)
        return False, None

    now = datetime.now(timezone.utc)
    opened_at = ctx["door_open_since"].setdefault(rule.entity_id, now)
    elapsed_min = (now - opened_at).total_seconds() / 60

    if rule.no_return_minutes and elapsed_min < rule.no_return_minutes:
        return False, None

    fn = state.get(rule.entity_id, {}).get("attributes", {}).get("friendly_name", "Door")
    return True, fn


def eval_room_inactivity(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when a specific room has had no presence state-change for duration_minutes."""
    if not rule.zone or not rule.duration_minutes:
        return False, None
    if not _in_window(rule.time_window):
        return False, None

    presence_entities = _presence_entities_for_zone(rule.zone, ctx)
    if not presence_entities:
        return False, None

    # All sensors must be off AND none changed recently
    all_off = all(state.get(e, {}).get("state", "off") == "off" for e in presence_entities)
    if not all_off:
        return False, None

    oldest_inactive = max(
        _minutes_since(state.get(e, {}).get("last_changed", "")) for e in presence_entities
    )
    return oldest_inactive >= rule.duration_minutes, rule.zone


def eval_global_inactivity(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when no presence entity anywhere has changed in duration_minutes."""
    if not rule.duration_minutes:
        return False, None
    if not _in_window(rule.time_window):
        return False, None

    presence_entities = _all_presence_entities(ctx, state)
    if not presence_entities:
        return False, None

    # The MOST RECENT change anywhere decides. (This was max() — the least recent — so one
    # idle zone, e.g. an unused doorway, made "no movement anywhere" true all day.)
    # Entities with no timestamp are skipped — _minutes_since would read them as 0 and
    # one missing entity would silence the rule for good.
    ages = [_minutes_since(state[e]["last_changed"]) for e in presence_entities
            if state.get(e, {}).get("last_changed")]
    if not ages:
        return False, None
    return min(ages) >= rule.duration_minutes, None


def eval_night_wandering(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when any presence is detected during the specified night window."""
    if not _in_window(rule.time_window):
        return False, None

    presence_entities = _all_presence_entities(ctx, state)
    area_sensors = ctx.get("area_sensors", {})
    # Build reverse map: entity_id → area_name
    entity_to_area: dict[str, str] = {}
    for area_name, buckets in area_sensors.items():
        for eid in buckets.get("presence", []) + buckets.get("fall", []):
            entity_to_area[eid] = area_name

    active = [e for e in presence_entities if state.get(e, {}).get("state") == "on"]
    if not active:
        return False, None

    zone = entity_to_area.get(active[0], "unknown area")
    return True, zone


def eval_long_stay(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when the patient has been continuously present in a room for > duration_minutes."""
    if not rule.zone or not rule.duration_minutes:
        return False, None

    presence_entities = _presence_entities_for_zone(rule.zone, ctx)
    if not presence_entities:
        return False, None

    currently_on = any(state.get(e, {}).get("state") == "on" for e in presence_entities)
    if not currently_on:
        ctx["zone_entry_times"].pop(rule.zone, None)
        return False, None

    now = datetime.now(timezone.utc)
    entered_at = ctx["zone_entry_times"].setdefault(rule.zone, now)
    elapsed_min = (now - entered_at).total_seconds() / 60
    return elapsed_min >= rule.duration_minutes, rule.zone


def eval_sensor_threshold(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when one numeric sensor crosses the threshold (for `duration_minutes`, if set).

    Also the building block for "appliance left on": point it at a smart plug's power
    sensor with `operator: gt`, a wattage and a duration.
    """
    if not rule.entity_id or rule.value is None or not rule.operator:
        return False, None
    s = state.get(rule.entity_id, {})
    try:
        val = float(s.get("state", ""))
    except (ValueError, TypeError):
        _sustained(ctx, rule.id, False, None)
        return False, None
    if not _in_window(rule.time_window):
        _sustained(ctx, rule.id, False, None)
        return False, None
    fired = _sustained(ctx, rule.id, compare(val, rule.operator, rule.value),
                       rule.duration_minutes)
    if fired:
        unit = s.get("attributes", {}).get("unit_of_measurement", "")
        _set_vars(ctx, rule, value=f"{val:g} {unit}".strip(),
                  sensor=s.get("attributes", {}).get("friendly_name", rule.entity_id))
    return fired, ctx.get("entity_area", {}).get(rule.entity_id)


def eval_env_threshold(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when any sensor measuring `rule.metric` (optionally only in `rule.zone`,
    or only `rule.entity_id`) stays past the threshold for `duration_minutes`.

    Binding by metric rather than entity_id means a rule written from the IAQ threshold
    table works on every air-quality sensor in the house, and keeps working when a
    sensor is swapped. °F readings are converted when `rule.unit` is °C (and vice versa).
    """
    if not rule.metric or rule.value is None or not rule.operator:
        return False, None
    in_window = _in_window(rule.time_window)
    entity_area = ctx.get("entity_area", {})

    worst: Optional[tuple[float, str, str]] = None   # (value, entity_id, unit)
    for eid, s in state.items():
        if rule.entity_id and eid != rule.entity_id:
            continue
        attrs = s.get("attributes", {})
        if env_metric(eid, attrs.get("device_class")) != rule.metric:
            continue
        if rule.zone and (entity_area.get(eid) or "").lower() != rule.zone.lower():
            continue
        key = f"{rule.id}|{eid}"
        try:
            val = float(s.get("state", ""))
        except (ValueError, TypeError):
            _sustained(ctx, key, False, None)       # unavailable → restart the clock
            continue
        unit = attrs.get("unit_of_measurement", "")
        if rule.unit and rule.metric == "temperature":
            val = normalize_temp(val, unit, rule.unit)
            unit = rule.unit
        if not _sustained(ctx, key, in_window and compare(val, rule.operator, rule.value),
                          rule.duration_minutes):
            continue
        more_extreme = worst is None or (
            val > worst[0] if rule.operator in ("gt", "gte") else val < worst[0])
        if more_extreme:
            worst = (val, eid, unit)

    if worst is None:
        return False, None
    val, eid, unit = worst
    shown = f"{val:.1f}" if rule.metric == "temperature" else f"{val:g}"
    _set_vars(ctx, rule, value=f"{shown} {unit}".strip(),
              sensor=state[eid].get("attributes", {}).get("friendly_name", eid))
    return True, entity_area.get(eid) or rule.zone


# Watch/phone activity states under which a raised heart rate is expected, not alarming.
_EXERTION_STATES = ("exercise", "walking", "running", "on_bicycle", "cycling", "biking")
VITAL_STALE_MIN = 10      # older watch readings never fire a vital alert
RECENT_STEPS_MIN = 5      # steps counted this recently → treat the person as moving


def eval_vital_threshold(rule: Rule, state: dict, ctx: dict) -> tuple[bool, Optional[str]]:
    """Fires when a wearable vital sign (a `profile.watch` key in `rule.metric`, e.g.
    heart_rate) stays past the threshold for `duration_minutes`.

    Deliberately conservative, since a false "abnormal heart rate" is worse than none:
      * no alert off a stale reading, or while the watch reports it is off the wrist;
      * a *high* reading is ignored while the person is exerting themselves (watch
        activity state, phone activity recognition, or steps counted in the last few
        minutes) - the Minder thresholds this implements were set for resting
        measurements.
    """
    if not rule.metric or rule.value is None or not rule.operator:
        return False, None
    watch = ctx.get("watch", {})
    eid = rule.entity_id or watch.get(rule.metric)
    if not eid:
        return False, None

    def st(key: str) -> dict:
        e = watch.get(key)
        return state.get(e, {}) if e else {}

    s = state.get(eid, {})
    ok = _in_window(rule.time_window)
    try:
        val = float(s.get("state", ""))
    except (ValueError, TypeError):
        ok, val = False, 0.0
    if ok and _minutes_since(_last_seen(s)) > VITAL_STALE_MIN:
        ok = False
    if ok and st("on_body").get("state") == "off":
        ok = False
    if ok and rule.operator in ("gt", "gte"):
        activity = " ".join(str(st(k).get("state", "")) for k in ("activity_state", "phone_activity")).lower()
        steps = st("steps_today")
        if any(a in activity for a in _EXERTION_STATES) or (
                steps and _minutes_since(steps.get("last_changed", "")) < RECENT_STEPS_MIN):
            ok = False

    fired = _sustained(ctx, rule.id, ok and compare(val, rule.operator, rule.value),
                       rule.duration_minutes)
    if fired:
        unit = s.get("attributes", {}).get("unit_of_measurement", "")
        _set_vars(ctx, rule, value=f"{val:g} {unit}".strip(),
                  sensor=s.get("attributes", {}).get("friendly_name", eid))
    return fired, None


# ── Dispatch table ────────────────────────────────────────────────────────────

EVALUATORS = {
    "fall":               eval_fall,
    "door_opened":        eval_door_opened,
    "room_inactivity":    eval_room_inactivity,
    "global_inactivity":  eval_global_inactivity,
    "night_wandering":    eval_night_wandering,
    "long_stay":          eval_long_stay,
    "sensor_threshold":   eval_sensor_threshold,
    "env_threshold":      eval_env_threshold,
    "vital_threshold":    eval_vital_threshold,
}


def render_message(template: str, patient_name: str, zone: Optional[str],
                   duration_minutes: Optional[int], **extra) -> str:
    now_str = datetime.now().strftime("%I:%M %p")
    duration_str = f"{duration_minutes}" if duration_minutes else ""
    return _render(
        template,
        patient_name=patient_name,
        zone=zone or "unknown area",
        time=now_str,
        duration=duration_str,
        **extra,
    )
