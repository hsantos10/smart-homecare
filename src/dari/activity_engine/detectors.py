"""
Heuristic activity inference.

Two kinds of output:
  • `resolve_activity` — the single best label for what the person is doing *now*
    (a continuous state: sleeping / in the bathroom / sitting / away …).
  • `detect_discrete` — momentary events worth their own timeline entry
    (front door opened, fall detected, fridge left open).

Everything here is deterministic and explainable — no training data required. The output
is intentionally the same shape an ML classifier would produce (`ActivityCandidate` with a
confidence), so a model can be swapped in later (see classifier.py) without touching the
engine or the API.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .models import WorldState
from .zones import area_role

# ── Tunable thresholds ──────────────────────────────────────────────────────────
INACTIVITY_MIN = 30          # minutes of no movement (while home) → "No movement"
AWAY_GRACE_MIN = 3           # minutes after front-door open with no presence → "away"
COOKING_WATTS = 150          # plug power above this in the kitchen → "cooking"
FRIDGE_OPEN_MIN = 2          # minutes a fridge door stays open → "fridge left open"

MEAL_WINDOWS = {             # local-hour ranges (start, end) → meal label key
    "breakfast": (6, 10),
    "meal":      (11, 14),   # lunch
    "meal_pm":   (17, 20),   # dinner (still labelled "meal")
}


@dataclass
class ActivityCandidate:
    """What the person is doing now, as inferred from one WorldState."""
    activity: str
    zone: Optional[str] = None
    detail: Optional[str] = None
    confidence: float = 1.0
    source: str = "heuristic"
    dedupe_key: Optional[str] = None   # separates cooldowns, e.g. per appliance


def _local_hour(now: datetime) -> int:
    return now.astimezone().hour


def _is_night(now: datetime) -> bool:
    h = _local_hour(now)
    return h >= 21 or h < 8


def _meal_label(now: datetime) -> Optional[str]:
    h = _local_hour(now)
    for label, (s, e) in MEAL_WINDOWS.items():
        if s <= h < e:
            return "breakfast" if label == "breakfast" else "meal"
    return None


def _minutes_since(then: Optional[datetime], now: datetime) -> float:
    if then is None:
        return 1e9
    return (now - then).total_seconds() / 60


def refine_home(world: WorldState, ctx: dict) -> bool:
    """Decide whether the person is home, using door history tracked in ctx.

    Logic: presence anywhere → home. No presence but the front door opened recently
    and stayed quiet → away. Otherwise assume still-at-home (sensor gap / sitting still).
    """
    now = world.timestamp
    if world.any_presence:
        ctx["away_since"] = None
        return True
    front_open_at = ctx.get("front_door_open_at")
    if front_open_at and _minutes_since(front_open_at, now) <= 30:
        if _minutes_since(front_open_at, now) >= AWAY_GRACE_MIN:
            ctx.setdefault("away_since", now)
            return False
    # Already flagged away and still no presence → stay away.
    if ctx.get("away_since"):
        return False
    return True


def resolve_activity(world: WorldState, ctx: dict, profile=None) -> ActivityCandidate:
    """Return the single best current-activity label (prioritised heuristics)."""
    now = world.timestamp
    world.home = refine_home(world, ctx)

    # 1. Away from home
    if not world.home:
        conf = 0.8
        # Wearable corroboration (only when it's actually fresh — see state.py::_is_fresh).
        if not world.watch_stale:
            if world.on_body is False:
                conf = 0.9   # watch off the wrist while the house is empty — stronger "away"
            elif world.on_body and world.heart_rate:
                conf = 0.6   # watch worn + live heart rate contradicts "away" somewhat
        return ActivityCandidate("away", zone=None, confidence=conf)

    # 2. No presence detected at all (while home)
    if not world.any_presence:
        # No baseline yet (cold start) → we genuinely don't know.
        if world.last_movement is None:
            return ActivityCandidate("no_presence", zone=world.current_area, confidence=0.5)
        idle = _minutes_since(world.last_movement, now)
        # Steps climbing while no room sensor sees anyone = probably a blind spot, not stillness.
        moving_off_sensor = not world.watch_stale and (world.steps_delta or 0) > 0
        if idle >= INACTIVITY_MIN:
            conf = 0.5 if moving_off_sensor else 0.7
            detail = f"No movement for {int(idle)} min"
            if moving_off_sensor:
                detail += " (watch shows steps — may be outside sensor coverage)"
            return ActivityCandidate("inactive", zone=world.current_area, detail=detail, confidence=conf)
        return ActivityCandidate("no_presence", zone=world.current_area,
                                 confidence=0.4 if moving_off_sensor else 0.6)

    area = world.current_area
    role = area_role(area or "")

    # 3. Shower zone — checked within the CURRENT area only. (Previously checked
    # globally by zone name — a shower held True in one area could get attributed to
    # whoever's current_area was a completely different room.)
    if world.zone_occupied.get((area, "shower")):
        return ActivityCandidate("in_shower", zone=area, confidence=0.85)

    # 4. Bathroom
    if role == "bathroom":
        if world.zone_occupied.get((area, "toilet")):
            return ActivityCandidate("using_toilet", zone=area, confidence=0.8)
        return ActivityCandidate("in_bathroom", zone=area, confidence=0.85)

    # 5. Kitchen / meals
    if role == "kitchen":
        # Only a plug actually located IN this kitchen area counts — a bedroom/living-room
        # appliance drawing power must not trigger "cooking" just because someone's in the kitchen.
        # A plug the profile names as a microwave/kettle/… counts wherever HA filed it.
        cooking = (world.plug_power_by_area.get(area, 0.0) >= COOKING_WATTS
                   or world.cooking_appliance_on)
        if cooking:
            return ActivityCandidate("cooking", zone=area, confidence=0.8)
        meal = _meal_label(now)
        if meal:
            return ActivityCandidate(meal, zone=area, confidence=0.7)
        return ActivityCandidate("in_kitchen", zone=area, confidence=0.85)

    # 6. Bedroom / sleep
    if role == "bedroom":
        if world.zone_occupied.get((area, "bed")):
            # Wearable's sleep_confidence corroborates (not replaces) the time-of-night heuristic.
            sc = world.sleep_confidence
            watch_confirms = not world.watch_stale and sc is not None and sc >= 50
            watch_disputes = not world.watch_stale and sc is not None and sc < 30
            if _is_night(now):
                conf = 0.9 if watch_confirms else (0.65 if watch_disputes else 0.8)
                return ActivityCandidate("sleeping", zone=area, confidence=conf)
            conf = 0.85 if watch_confirms else 0.75
            return ActivityCandidate("in_bed", zone=area, confidence=conf)
        return ActivityCandidate("in_bedroom", zone=area, confidence=0.85)

    # 7. Living room
    if role == "living":
        if world.zone_occupied.get((area, "sofa")):
            return ActivityCandidate("sitting", zone=area, confidence=0.8)
        if world.zone_occupied.get((area, "desk")):
            return ActivityCandidate("at_desk", zone=area, confidence=0.8)
        return ActivityCandidate("in_living_room", zone=area, confidence=0.85)

    # 7b. Study / office as its own HA area (otherwise it would fall through to the
    # generic "in a room" fallback and the desk sub-zone would never resolve).
    if role == "study":
        if world.zone_occupied.get((area, "desk")):
            return ActivityCandidate("at_desk", zone=area, confidence=0.8)
        return ActivityCandidate("in_study", zone=area, confidence=0.85)

    # 8. Fallback — in some room, moving around
    if area:
        return ActivityCandidate("in_room", zone=area, detail=area, confidence=0.6)
    return ActivityCandidate("active", confidence=0.5)


# Transitions that deserve a nicer label than the steady-state they lead to.
_SLEEP_KEYS = {"sleeping", "in_bed"}


def transition_label(prev_key: Optional[str], cand: ActivityCandidate,
                     world: WorldState, ctx: dict) -> str:
    """Pick the activity key to LOG when the current activity changes.

    The steady-state we track is `cand.activity`, but the timeline reads better with
    "Woke up" / "Went to bed" / "Left home" at the moment of transition.
    """
    cur = cand.activity
    was_sleeping = prev_key in _SLEEP_KEYS
    now_sleeping = cur in _SLEEP_KEYS

    if was_sleeping and not now_sleeping and cur != "away":
        return "woke_up"
    if now_sleeping and not was_sleeping:
        return "went_to_bed"
    if cur == "away" and prev_key not in ("away", None):
        return "left_home"
    if prev_key == "away" and cur != "away":
        return "returned_home"
    return cur


def detect_discrete(prev: Optional[WorldState], world: WorldState,
                    idx: dict, ctx: dict) -> list[ActivityCandidate]:
    """Momentary events that always earn their own timeline entry (with cooldowns)."""
    out: list[ActivityCandidate] = []
    now = world.timestamp

    door_kind_by_id = {d["entity_id"]: d["kind"] for d in idx["doors"]}

    for eid, is_open in world.door_open.items():
        was_open = prev.door_open.get(eid, False) if prev else False
        kind = door_kind_by_id.get(eid, "door")

        # Front door opening — track for away-detection + log it.
        if kind == "front" and is_open and not was_open:
            ctx["front_door_open_at"] = now
            out.append(ActivityCandidate("front_door_opened", zone="Front Door", confidence=1.0))

        # Fridge/cabinet opening — logged as its own activity the moment it opens.
        # Deliberately NOT gated on role=="kitchen" (unlike cooking/meals) — a fridge or
        # cabinet door event is meaningful on its own even in a home with no Kitchen
        # area defined in HA.
        if kind == "fridge" and is_open and not was_open:
            out.append(ActivityCandidate("refrigerator_use", zone=world.current_area, confidence=1.0))
        if kind == "cabinet" and is_open and not was_open:
            out.append(ActivityCandidate("cabinet_access", zone=world.current_area, confidence=1.0))

        # Fridge left open too long (safety — separate from the "use" event above).
        if kind == "fridge":
            if is_open:
                opened = ctx.setdefault("fridge_open_since", {}).setdefault(eid, now)
                if _minutes_since(opened, now) >= FRIDGE_OPEN_MIN:
                    out.append(ActivityCandidate(
                        "fridge_left_open", zone="Kitchen",
                        detail=f"Open for {int(_minutes_since(opened, now))} min", confidence=1.0,
                    ))
            else:
                ctx.get("fridge_open_since", {}).pop(eid, None)

    # Fall just became active.
    if world.fall_active and not (prev and prev.fall_active):
        out.append(ActivityCandidate("fall_detected", zone=world.current_area, confidence=1.0))

    # Appliance switched on / off (smart-plug power, debounced in state.py).
    apps = idx.get("appliances", {})
    prev_on = prev.appliance_on if prev else {}
    for eid in world.appliance_on.keys() - prev_on.keys():
        app = apps.get(eid, {})
        out.append(ActivityCandidate(
            "appliance_on", zone=app.get("area") or world.current_area,
            detail=f"{app.get('name', eid)} · {world.plug_power.get(eid, 0):.0f} W",
            confidence=1.0, dedupe_key=eid,
        ))
    for eid in prev_on.keys() - world.appliance_on.keys():
        app = apps.get(eid, {})
        ran = int(_minutes_since(prev_on[eid], now))
        out.append(ActivityCandidate(
            "appliance_off", zone=app.get("area") or world.current_area,
            detail=f"{app.get('name', eid)} · ran {ran} min" if ran else f"{app.get('name', eid)} · ran <1 min",
            confidence=1.0, dedupe_key=eid,
        ))

    # Toilet flush — a vibration burst, not a sustained state, so log it as a discrete
    # event on the rising edge rather than trying to fold it into "using_toilet" confidence
    # (by the time a continuous-state change would debounce/log, the flush is long over).
    if world.toilet_vibration and not (prev and prev.toilet_vibration):
        out.append(ActivityCandidate("toilet_flushed", zone=world.current_area, confidence=1.0))

    return out
