"""
Data models for the activity-recognition layer.

This layer answers a different question than `rule_engine`:
  rule_engine  → "did something cross a threshold? send an alert."
  activity_engine → "what is the person doing right now, and what have they done today?"

Activities are inferred from the SAME raw sensor data (FP2 presence/zones, door/window
contacts, smart-plug power) using explainable heuristics, then logged as a timeline.

The catalog below is the single source of truth for activity labels + UI hints. Both the
web app and the future Android app render from these keys, so a new activity only has to be
defined once here.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional
import uuid

# Activity categories — used for filtering + colour-coding in the UI.
CATEGORIES = (
    "sleep", "hygiene", "meal", "mobility", "rest", "exit", "safety", "environment", "unknown"
)

# Severity for a timeline entry. Most activities are routine ("info").
# "notice" = worth a glance, "warning" = the activity itself implies concern.
SEVERITIES = ("info", "notice", "warning")

# ── Activity catalog ────────────────────────────────────────────────────────────
# key → (label, category, icon, severity)
# icon names map to lucide-react icons so the web + Android clients share them.
ACTIVITY_CATALOG: dict[str, tuple[str, str, str, str]] = {
    # sleep
    "sleeping":        ("Sleeping",            "sleep",    "moon",          "info"),
    "in_bed":          ("Resting in bed",      "rest",     "bed",           "info"),
    "went_to_bed":     ("Went to bed",         "sleep",    "bed",           "info"),
    "woke_up":         ("Woke up",             "sleep",    "sun",           "info"),
    # hygiene
    "in_bathroom":     ("In the bathroom",     "hygiene",  "bath",          "info"),
    "in_shower":       ("In the shower",       "hygiene",  "shower-head",   "info"),
    "using_toilet":    ("Using the toilet",    "hygiene",  "bath",          "info"),
    # meal / kitchen
    "in_kitchen":      ("In the kitchen",      "meal",     "utensils",      "info"),
    "cooking":         ("Cooking",             "meal",     "cooking-pot",   "info"),
    "breakfast":       ("Breakfast",           "meal",     "coffee",        "info"),
    "meal":            ("Having a meal",       "meal",     "utensils",      "info"),
    # living areas
    "sitting":         ("Sitting",             "rest",     "armchair",      "info"),
    "at_desk":         ("At the desk",         "rest",     "lamp-desk",     "info"),
    "in_living_room":  ("In the living room",  "mobility", "sofa",          "info"),
    "in_study":        ("In the study",        "mobility", "lamp-desk",     "info"),
    "in_bedroom":      ("In the bedroom",      "mobility", "bed-single",    "info"),
    "in_room":         ("Moving around",       "mobility", "footprints",    "info"),
    # mobility / global
    "active":          ("Active",              "mobility", "footprints",    "info"),
    "inactive":        ("No movement",         "rest",     "pause",         "notice"),
    "no_presence":     ("No presence detected","mobility", "user-x",        "notice"),
    # exit
    "left_home":       ("Left home",           "exit",     "log-out",       "notice"),
    "returned_home":   ("Returned home",       "exit",     "log-in",        "info"),
    "away":            ("Away from home",      "exit",     "door-open",     "info"),
    # discrete events
    "front_door_opened": ("Front door opened", "exit",     "door-open",     "notice"),
    "fridge_left_open":  ("Fridge left open",  "safety",   "refrigerator",  "warning"),
    "fall_detected":     ("Fall detected",     "safety",   "alert-triangle","warning"),
    "toilet_flushed":    ("Toilet flushed",    "hygiene",  "bath",          "info"),
    "refrigerator_use":  ("Refrigerator use",  "meal",     "refrigerator",  "info"),
    "cabinet_access":    ("Cabinet access",    "meal",     "door-open",     "info"),
    # smart-plug appliance use — detail names the appliance ("Microwave · 1150 W")
    "appliance_on":      ("Appliance on",      "meal",     "plug-zap",      "info"),
    "appliance_off":     ("Appliance off",     "meal",     "plug",          "info"),
    # care mode — caregiver switched between "home alone" and "with others"
    "care_mode_alone":       ("Home alone mode",   "safety", "user",  "info"),
    "care_mode_with_others": ("With others mode",  "safety", "users", "notice"),
}


def catalog_entry(key: str) -> tuple[str, str, str, str]:
    """Return (label, category, icon, severity) for an activity key, with a safe fallback."""
    return ACTIVITY_CATALOG.get(key, (key.replace("_", " ").title(), "unknown", "activity", "info"))


@dataclass
class ActivityEvent:
    """A single entry in the patient's activity timeline."""
    id: str
    profile_id: str
    timestamp: str          # ISO-8601 UTC — when the activity started
    activity: str           # machine key, e.g. "woke_up"
    label: str              # human-readable, e.g. "Woke up"
    category: str
    zone: Optional[str]     # area / zone name, e.g. "Living room"
    detail: Optional[str]   # extra context, e.g. "No movement for 32 min"
    icon: str               # lucide icon hint
    severity: str           # info | notice | warning
    confidence: float       # 0..1 — 1.0 for deterministic heuristics
    source: str             # "heuristic" | "ml" | detector name

    @classmethod
    def create(
        cls,
        profile_id: str,
        activity: str,
        *,
        zone: Optional[str] = None,
        detail: Optional[str] = None,
        confidence: float = 1.0,
        source: str = "heuristic",
        timestamp: Optional[str] = None,
        label: Optional[str] = None,
    ) -> "ActivityEvent":
        cat_label, category, icon, severity = catalog_entry(activity)
        return cls(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            activity=activity,
            label=label or cat_label,
            category=category,
            zone=zone,
            detail=detail,
            icon=icon,
            severity=severity,
            confidence=confidence,
            source=source,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CurrentStatus:
    """Live snapshot of the patient — derived on demand, never stored.

    Drives the app's Summary floor-plan dot and the Room screen's
    "Current Activity: Sitting since 9:15 AM".
    """
    profile_id: str
    patient_name: str
    timestamp: str
    home: bool
    current_zone: Optional[str]
    current_activity: str
    activity_label: str
    activity_icon: str
    activity_category: str
    since: Optional[str]            # when the current activity began
    duration_minutes: Optional[int]
    last_movement: Optional[str]
    presence_by_zone: dict          # area name -> occupied bool
    risk_level: str                 # ok | attention | alert
    active_alerts: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorldState:
    """Normalised view of the home at one instant, built from raw HA states.

    Detectors read this instead of touching HA entities directly, which keeps the
    inference logic testable and decoupled from entity naming.
    """
    timestamp: datetime
    area_occupied: dict = field(default_factory=dict)      # area name -> bool
    area_since: dict = field(default_factory=dict)         # area name -> datetime first occupied
    area_clear_since: dict = field(default_factory=dict)   # area name -> datetime raw-off began
    zone_occupied: dict = field(default_factory=dict)      # (area, zone) -> bool, e.g. ("Bedroom","bed")
    zone_clear_since: dict = field(default_factory=dict)   # (area, zone) -> datetime raw-off began
    door_open: dict = field(default_factory=dict)          # entity_id -> bool
    plug_power: dict = field(default_factory=dict)         # entity_id -> watts (float)
    plug_power_by_area: dict = field(default_factory=dict)  # area name -> max watts of plugs IN that area
    appliance_on: dict = field(default_factory=dict)        # plug entity_id -> datetime it turned on
    appliance_below_since: dict = field(default_factory=dict)  # entity_id -> when power fell below off_watts
    cooking_appliance_on: bool = False                      # a microwave/kettle/stove… plug is running
    toilet_vibration: bool = False                          # toilet-flush vibration sensor currently "on"
    fall_active: bool = False
    current_area: Optional[str] = None                     # where the person is now
    any_presence: bool = False
    last_movement: Optional[datetime] = None
    home: bool = True

    # ── Wearable (profile.watch), corroborating signal only — see classifier.py ──
    heart_rate: Optional[float] = None
    sleep_confidence: Optional[float] = None
    steps_today: Optional[float] = None                     # raw cumulative counter
    steps_delta: Optional[float] = None                     # vs. previous tick's steps_today
    on_body: Optional[bool] = None
    activity_state: Optional[str] = None
    phone_activity: Optional[str] = None
    watch_stale: bool = True                                # True until a fresh reading arrives
