"""
DARI Alerts REST API — FastAPI
Run with:  uvicorn dari.api_server.main:app --host 0.0.0.0 --port 8000

Endpoints:
  GET  /api/alerts            → list alerts with optional filters
  GET  /api/patient_state     → current zone + active unacknowledged alerts (legacy)
  POST /api/alerts/{id}/acknowledge
  GET  /api/current_status    → live location + inferred activity + risk (activity engine)
  GET  /api/activity_log      → activity timeline with optional filters
  GET  /api/activity_summary  → aggregated activity counts for charts
  GET  /api/profiles          → list available patient profiles

This API is the single source of truth shared by the caregiver web app and the future
Android app — all activity inference happens here, never in a client.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone, timedelta

import uuid
import requests as _requests
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dari.rule_engine import alert_store, care_mode
from dari.rule_engine.ha_client import (
    get_all_states, states_as_dict, get_sensors_by_area, get_areas, get_history,
    get_device_registry, _ws_call,
)
from dari.rule_engine.models import Profile, Rule, TimeWindow
from dari.rule_engine.evaluators import compare
from dari.env_metrics import env_metric, normalize_temp

from dari.activity_engine import activity_store, service

from dari.paths import PROFILES_DIR


def _load_profile(profile_id: str) -> Profile:
    """Resolve a profile by id. The file stem (patient_001) and the profile_id field
    (patient-001) can differ, so we try common filename variants, then scan by field."""
    for stem in (profile_id, profile_id.replace("-", "_"), profile_id.replace("_", "-")):
        p = PROFILES_DIR / f"{stem}.yaml"
        if p.exists():
            return Profile.load(str(p))
    for p in PROFILES_DIR.glob("*.yaml"):
        if p.stem.startswith("suggested"):
            continue
        try:
            prof = Profile.load(str(p))
        except Exception:
            continue
        if prof.profile_id == profile_id:
            return prof
    raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")


def _profile_path(profile_id: str) -> Path:
    for stem in (profile_id, profile_id.replace("-", "_"), profile_id.replace("_", "-")):
        p = PROFILES_DIR / f"{stem}.yaml"
        if p.exists():
            return p
    return PROFILES_DIR / f"{profile_id.replace('-', '_')}.yaml"


def _save_profile(profile: Profile) -> None:
    profile.save(str(_profile_path(profile.profile_id)))


app = FastAPI(title="DARI Alerts API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

alert_store.init_db()
activity_store.init_db()


# ── Response models ───────────────────────────────────────────────────────────

class AlertOut(BaseModel):
    id: str
    profile_id: str
    rule_id: str
    rule_name: str
    severity: str
    category: str
    message: str
    zone: Optional[str]
    timestamp: str
    acknowledged: bool


class PatientState(BaseModel):
    profile_id: str
    patient_name: str
    current_zone: Optional[str]
    active_alerts: list[AlertOut]
    presence_summary: dict


class ActivityEventOut(BaseModel):
    id: str
    profile_id: str
    timestamp: str
    activity: str
    label: str
    category: str
    zone: Optional[str]
    detail: Optional[str]
    icon: str
    severity: str
    confidence: float
    source: str


class CurrentStatusOut(BaseModel):
    profile_id: str
    patient_name: str
    timestamp: str
    home: bool
    current_zone: Optional[str]
    current_activity: str
    activity_label: str
    activity_icon: str
    activity_category: str
    since: Optional[str]
    duration_minutes: Optional[int]
    last_movement: Optional[str]
    presence_by_zone: dict
    risk_level: str
    active_alerts: int


class ProfileOut(BaseModel):
    profile_id: str
    patient_name: str
    caregiver_name: str


class EnvReadingOut(BaseModel):
    entity_id: str
    name: str
    area: Optional[str]
    value: Optional[float]
    unit: str
    kind: str          # temperature | humidity | co2 | pm25 | co | voc | other
    status: Optional[str] = None       # ok | warn | alert, from the profile's env_threshold
                                       # rules; None when no rule covers this kind
    status_text: Optional[str] = None  # name of the rule the reading currently breaches


class HealthDataOut(BaseModel):
    watch_name: str
    connected: bool
    heart_rate: Optional[float]
    heart_rate_unit: str
    steps_today: Optional[int]
    calories: Optional[float]
    distance: Optional[float]
    distance_unit: str
    battery_level: Optional[int]
    battery_state: Optional[str]
    on_body: Optional[bool]
    activity_state: Optional[str]
    phone_activity: Optional[str]
    sleep_confidence: Optional[float]
    last_updated: Optional[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/alerts", response_model=list[AlertOut])
def get_alerts(
    profile_id:   Optional[str]  = Query(None),
    category:     Optional[str]  = Query(None),
    severity:     Optional[str]  = Query(None),
    since:        Optional[str]  = Query(None, description="ISO-8601 timestamp"),
    acknowledged: Optional[bool] = Query(None),
    limit:        int            = Query(50, ge=1, le=500),
    include_demo: bool           = Query(False, description="Include seeded demo rows"),
):
    alerts = alert_store.query(
        profile_id=profile_id,
        category=category,
        severity=severity,
        since=since,
        acknowledged=acknowledged,
        limit=limit,
        include_demo=include_demo,
    )
    return [AlertOut(**a.__dict__) for a in alerts]


@app.get("/api/patient_state", response_model=PatientState)
def get_patient_state(profile_id: str = Query(...), include_demo: bool = Query(False, description="Include seeded demo rows")):
    profile = _load_profile(profile_id)

    try:
        state = states_as_dict()
    except Exception:
        state = {}

    # Determine current zone from presence sensors
    current_zone = None
    presence_summary: dict[str, str] = {}
    for eid, s in state.items():
        if "presence" in eid.lower() or "fp2" in eid.lower():
            if s.get("state") == "on":
                zone_guess = eid.split(".")[1].replace("_presence", "").replace("_", " ").title()
                presence_summary[zone_guess] = "occupied"
                if current_zone is None:
                    current_zone = zone_guess
            else:
                zone_guess = eid.split(".")[1].replace("_presence", "").replace("_", " ").title()
                presence_summary.setdefault(zone_guess, "empty")

    active_alerts = alert_store.query(profile_id=profile_id, acknowledged=False, limit=20, include_demo=include_demo)

    return PatientState(
        profile_id=profile_id,
        patient_name=profile.patient_name,
        current_zone=current_zone,
        active_alerts=[AlertOut(**a.__dict__) for a in active_alerts],
        presence_summary=presence_summary,
    )


@app.post("/api/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: str):
    ok = alert_store.acknowledge(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "acknowledged", "id": alert_id}


# ── Activity recognition ────────────────────────────────────────────────────────

@app.get("/api/current_status", response_model=CurrentStatusOut)
def current_status(profile_id: str = Query(...), include_demo: bool = Query(False, description="Include seeded demo rows")):
    """Live location + inferred activity + risk level. Polled by Summary/Room screens."""
    profile = _load_profile(profile_id)
    try:
        status = service.get_status(profile, include_demo=include_demo)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")
    return CurrentStatusOut(**status.to_dict())


@app.get("/api/activity_log", response_model=list[ActivityEventOut])
def activity_log(
    profile_id: str           = Query(...),
    category:   Optional[str] = Query(None),
    since:      Optional[str] = Query(None, description="ISO-8601 timestamp"),
    until:      Optional[str] = Query(None, description="ISO-8601 timestamp"),
    limit:      int           = Query(100, ge=1, le=1000),
    include_demo: bool        = Query(False, description="Include seeded demo rows"),
):
    """The activity timeline (newest first). Drives the Activity screen + recent-activity lists."""
    events = activity_store.query(
        profile_id=profile_id, category=category, since=since, until=until, limit=limit,
        include_demo=include_demo,
    )
    return [ActivityEventOut(**e.to_dict()) for e in events]


@app.get("/api/activity_summary")
def activity_summary(profile_id: str = Query(...), days: int = Query(7, ge=1, le=90), include_demo: bool = Query(False, description="Include seeded demo rows")):
    """Aggregated activity counts (by category / day / hour) for charts."""
    return activity_store.summary(profile_id=profile_id, days=days, include_demo=include_demo)


@app.get("/api/activity_patterns")
def activity_patterns(profile_id: str = Query(...), days: int = Query(14, ge=1, le=90), include_demo: bool = Query(False, description="Include seeded demo rows")):
    """Daily-routine patterns (average wake/bed/meal times, regularity, night bathroom
    trips, outings, time-in-room split) derived from the activity log."""
    return activity_store.adl_summary(profile_id=profile_id, days=days, include_demo=include_demo)


_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _env_status(rules: list[Rule], kind: str, area: Optional[str], eid: str,
                value: Optional[float], unit: str) -> tuple[Optional[str], Optional[str]]:
    """Judge a reading against the same env_threshold rules the rule engine alerts on,
    ignoring their duration — the page shows *now*, the alert waits for it to persist."""
    applicable = [
        r for r in rules
        if r.enabled and r.trigger_type == "env_threshold" and r.metric == kind
        and (not r.zone or (area or "").lower() == r.zone.lower())
        and (not r.entity_id or r.entity_id == eid)
        and r.operator and r.value is not None
    ]
    if not applicable:
        return None, None
    if value is None:
        return "ok", None
    breached = [
        r for r in applicable
        if compare(normalize_temp(value, unit, r.unit) if (r.unit and kind == "temperature")
                    else value, r.operator, r.value)
    ]
    if not breached:
        return "ok", None
    worst = min(breached, key=lambda r: _SEV_RANK.get(r.severity, 9))
    return ("alert" if worst.severity in ("CRITICAL", "HIGH") else "warn"), worst.name


@app.get("/api/environment", response_model=list[EnvReadingOut])
def environment(profile_id: str = Query(...)):
    """Live environmental sensor readings (temperature/humidity/IAQ), grouped by area."""
    rules = _load_profile(profile_id).rules
    try:
        states = states_as_dict()
        by_area = get_sensors_by_area()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")

    out: list[EnvReadingOut] = []
    for area, buckets in by_area.items():
        for eid in buckets.get("numeric", []):
            s = states.get(eid, {})
            kind = env_metric(eid, s.get("attributes", {}).get("device_class")) or "other"
            if kind == "other":      # skip light-level etc. — keep the page focused
                continue
            try:
                value = float(s.get("state"))
            except (ValueError, TypeError):
                value = None
            attrs = s.get("attributes", {})
            unit = attrs.get("unit_of_measurement", "")
            status, status_text = _env_status(rules, kind, area, eid, value, unit)
            out.append(EnvReadingOut(
                entity_id=eid,
                name=attrs.get("friendly_name", eid),
                area=area,
                value=value,
                unit=unit,
                kind=kind,
                status=status,
                status_text=status_text,
            ))
    return out


@app.get("/api/health", response_model=HealthDataOut)
def health(profile_id: str = Query(...), include_demo: bool = Query(False, description="Include seeded demo rows")):
    """Pixel Watch health metrics via the HA Companion App. Entity IDs come from profile.watch."""
    profile = _load_profile(profile_id)
    watch_cfg = profile.watch
    if not watch_cfg:
        raise HTTPException(status_code=404, detail="No watch configured for this profile")

    try:
        states = states_as_dict()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")

    def _state(key: str):
        eid = watch_cfg.get(key)
        return states.get(eid, {}) if eid else {}

    def _val(key: str):
        return _state(key).get("state")

    def _float(key: str) -> Optional[float]:
        try:
            return float(_val(key))
        except (ValueError, TypeError):
            return None

    def _bool_sensor(key: str) -> Optional[bool]:
        v = _val(key)
        if v is None:
            return None
        return str(v).lower() in ("on", "true", "yes", "1")

    def _unit(key: str) -> str:
        return _state(key).get("attributes", {}).get("unit_of_measurement", "")

    on_body = _bool_sensor("on_body")
    battery = _float("battery_level")
    hr = _float("heart_rate")
    steps = _float("steps_today")
    cals = _float("calories")
    dist = _float("distance")
    sleep_conf = _float("sleep_confidence")

    return HealthDataOut(
        watch_name="Smartwatch",
        connected=on_body is True and battery is not None,
        heart_rate=hr,
        heart_rate_unit=_unit("heart_rate") or "bpm",
        steps_today=int(steps) if steps is not None else None,
        calories=round(cals, 1) if cals is not None else None,
        distance=round(dist, 1) if dist is not None else None,
        distance_unit=_unit("distance") or "ft",
        battery_level=int(battery) if battery is not None else None,
        battery_state=_val("battery_state"),
        on_body=on_body,
        activity_state=_val("activity_state"),
        phone_activity=_val("phone_activity"),
        sleep_confidence=round(sleep_conf, 1) if sleep_conf is not None else None,
        last_updated=_state("heart_rate").get("last_changed"),
    )


@app.get("/api/profiles", response_model=list[ProfileOut])
def list_profiles():
    """Available patient profiles (for a profile switcher in the client)."""
    out = []
    for p in sorted(PROFILES_DIR.glob("*.yaml")):
        if p.stem.startswith("suggested"):
            continue
        try:
            prof = Profile.load(str(p))
            out.append(ProfileOut(
                profile_id=prof.profile_id,
                patient_name=prof.patient_name,
                caregiver_name=prof.caregiver_name,
            ))
        except Exception:
            continue
    return out


# ── Admin — HA entity list ────────────────────────────────────────────────────

class HAEntityOut(BaseModel):
    entity_id: str
    friendly_name: str
    state: str
    unit: str
    domain: str
    last_changed: Optional[str]


@app.get("/api/ha_entities", response_model=list[HAEntityOut])
def ha_entities(domain: Optional[str] = Query(None, description="Filter by domain e.g. sensor, binary_sensor")):
    """All HA entities, optionally filtered by domain. Used by entity pickers in the admin UI."""
    try:
        states = get_all_states()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")
    out = []
    for s in states:
        eid = s["entity_id"]
        d = eid.split(".")[0]
        if domain and d != domain:
            continue
        attrs = s.get("attributes", {})
        out.append(HAEntityOut(
            entity_id=eid,
            friendly_name=attrs.get("friendly_name", eid),
            state=s.get("state", ""),
            unit=attrs.get("unit_of_measurement", ""),
            domain=d,
            last_changed=s.get("last_changed"),
        ))
    return sorted(out, key=lambda x: x.entity_id)


# ── Admin — Watch config CRUD ─────────────────────────────────────────────────

@app.get("/api/watch_config")
def get_watch_config(profile_id: str = Query(...)):
    """Return the watch entity mapping for a profile."""
    profile = _load_profile(profile_id)
    return profile.watch


@app.put("/api/watch_config")
def put_watch_config(
    profile_id: str = Query(...),
    body: dict = Body(...),
):
    """Replace the watch entity mapping. Pass {} to clear."""
    profile = _load_profile(profile_id)
    profile.watch = {k: v for k, v in body.items() if isinstance(v, str) and v.strip()}
    _save_profile(profile)
    return profile.watch


# ── Admin — Rules CRUD ────────────────────────────────────────────────────────

class TimeWindowIn(BaseModel):
    start: str
    end: str


class RuleIn(BaseModel):
    name: str
    enabled: bool = True
    category: str
    severity: str
    trigger_type: str
    message: str
    zone: Optional[str] = None
    entity_id: Optional[str] = None
    duration_minutes: Optional[int] = None
    no_return_minutes: Optional[int] = None
    operator: Optional[str] = None
    value: Optional[float] = None
    metric: Optional[str] = None
    unit: Optional[str] = None
    time_window: Optional[TimeWindowIn] = None
    cooldown_minutes: int = 10
    modes: Optional[list[str]] = None


class RuleOut(BaseModel):
    id: str
    name: str
    enabled: bool
    category: str
    severity: str
    trigger_type: str
    message: str
    zone: Optional[str]
    entity_id: Optional[str]
    duration_minutes: Optional[int]
    no_return_minutes: Optional[int]
    operator: Optional[str]
    value: Optional[float]
    metric: Optional[str] = None
    unit: Optional[str] = None
    time_window: Optional[dict]
    cooldown_minutes: int
    modes: Optional[list[str]] = None      # as stored (None = trigger default)
    effective_modes: list[str] = []        # what the engine actually uses


def _rule_to_out(r: Rule) -> RuleOut:
    return RuleOut(
        id=r.id, name=r.name, enabled=r.enabled, category=r.category,
        severity=r.severity, trigger_type=r.trigger_type, message=r.message,
        zone=r.zone, entity_id=r.entity_id,
        duration_minutes=r.duration_minutes, no_return_minutes=r.no_return_minutes,
        operator=r.operator, value=r.value, metric=r.metric, unit=r.unit,
        time_window={"start": r.time_window.start, "end": r.time_window.end} if r.time_window else None,
        cooldown_minutes=r.cooldown_minutes,
        modes=r.modes, effective_modes=care_mode.rule_modes(r),
    )


@app.get("/api/rules", response_model=list[RuleOut])
def get_rules(profile_id: str = Query(...)):
    """List all rules for a profile."""
    profile = _load_profile(profile_id)
    return [_rule_to_out(r) for r in profile.rules]


@app.post("/api/rules", response_model=RuleOut, status_code=201)
def create_rule(profile_id: str = Query(...), body: RuleIn = Body(...)):
    """Append a new rule to a profile."""
    profile = _load_profile(profile_id)
    tw = TimeWindow(start=body.time_window.start, end=body.time_window.end) if body.time_window else None
    rule = Rule(
        id=str(uuid.uuid4())[:8],
        name=body.name, enabled=body.enabled, category=body.category,
        severity=body.severity, trigger_type=body.trigger_type, message=body.message,
        zone=body.zone, entity_id=body.entity_id,
        duration_minutes=body.duration_minutes, no_return_minutes=body.no_return_minutes,
        operator=body.operator, value=body.value, metric=body.metric, unit=body.unit,
        time_window=tw,
        cooldown_minutes=body.cooldown_minutes, modes=body.modes,
    )
    profile.rules.append(rule)
    _save_profile(profile)
    return _rule_to_out(rule)


@app.put("/api/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, profile_id: str = Query(...), body: RuleIn = Body(...)):
    """Replace a rule by id."""
    profile = _load_profile(profile_id)
    idx = next((i for i, r in enumerate(profile.rules) if r.id == rule_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    tw = TimeWindow(start=body.time_window.start, end=body.time_window.end) if body.time_window else None
    rule = Rule(
        id=rule_id,
        name=body.name, enabled=body.enabled, category=body.category,
        severity=body.severity, trigger_type=body.trigger_type, message=body.message,
        zone=body.zone, entity_id=body.entity_id,
        duration_minutes=body.duration_minutes, no_return_minutes=body.no_return_minutes,
        operator=body.operator, value=body.value, metric=body.metric, unit=body.unit,
        time_window=tw,
        cooldown_minutes=body.cooldown_minutes, modes=body.modes,
    )
    profile.rules[idx] = rule
    _save_profile(profile)
    return _rule_to_out(rule)


@app.patch("/api/rules/{rule_id}/toggle", response_model=RuleOut)
def toggle_rule(rule_id: str, profile_id: str = Query(...)):
    """Toggle a rule's enabled state."""
    profile = _load_profile(profile_id)
    rule = next((r for r in profile.rules if r.id == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    rule.enabled = not rule.enabled
    _save_profile(profile)
    return _rule_to_out(rule)


@app.delete("/api/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, profile_id: str = Query(...)):
    """Delete a rule by id."""
    profile = _load_profile(profile_id)
    before = len(profile.rules)
    profile.rules = [r for r in profile.rules if r.id != rule_id]
    if len(profile.rules) == before:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    _save_profile(profile)


# ── Care mode ────────────────────────────────────────────────────────────────

class CareModeIn(BaseModel):
    mode: str                                  # alone | with_others
    duration_minutes: Optional[int] = None     # with_others: revert to alone after this;
                                               # None = until switched back


class CareModeOut(BaseModel):
    mode: str
    until: Optional[str]
    changed_at: Optional[str]
    paused_rules: list[str]      # enabled rules not running in this mode
    active_rules: int


def _care_mode_out(profile: Profile, m: dict) -> CareModeOut:
    enabled = [r for r in profile.rules if r.enabled]
    paused = [r.name for r in enabled if not care_mode.rule_active_in(r, m["mode"])]
    return CareModeOut(mode=m["mode"], until=m["until"], changed_at=m["changed_at"],
                       paused_rules=paused, active_rules=len(enabled) - len(paused))


@app.get("/api/care_mode", response_model=CareModeOut)
def get_care_mode(profile_id: str = Query(...)):
    """Home alone vs. with others, and which alert rules the current mode pauses."""
    profile = _load_profile(profile_id)
    return _care_mode_out(profile, care_mode.get(profile_id))


@app.get("/api/care_mode/preview", response_model=CareModeOut)
def preview_care_mode(profile_id: str = Query(...), mode: str = Query(...)):
    """What switching to `mode` would pause, without switching."""
    if mode not in care_mode.MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {care_mode.MODES}")
    profile = _load_profile(profile_id)
    return _care_mode_out(profile, {"mode": mode, "until": None, "changed_at": None})


@app.put("/api/care_mode", response_model=CareModeOut)
def put_care_mode(profile_id: str = Query(...), body: CareModeIn = Body(...)):
    """Switch mode. The change is also written to the activity timeline."""
    if body.mode not in care_mode.MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {care_mode.MODES}")
    profile = _load_profile(profile_id)
    until = None
    if body.mode == care_mode.WITH_OTHERS and body.duration_minutes:
        until = datetime.now(timezone.utc) + timedelta(minutes=body.duration_minutes)
    m = care_mode.set_mode(profile_id, body.mode, until)
    from dari.activity_engine.models import ActivityEvent
    detail = "set by caregiver"
    if until:
        detail += f" · until {until.astimezone():%I:%M %p}".replace("until 0", "until ")
    activity_store.insert(ActivityEvent.create(
        profile_id, "care_mode_alone" if body.mode == care_mode.ALONE else "care_mode_with_others",
        detail=detail, source="caregiver"))
    return _care_mode_out(profile, m)


@app.get("/api/ha_areas")
def ha_areas():
    """HA area names + their entity lists — used by sensor browser/history filters."""
    try:
        areas = get_areas()
        by_area = get_sensors_by_area()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")
    area_names = [a["name"] for a in areas]
    return {"areas": area_names, "by_area": by_area}


@app.get("/api/sensor_history")
def sensor_history(
    entity_ids: str = Query(..., description="Comma-separated entity_ids"),
    hours: float = Query(24, ge=0.1, le=168, description="How many hours back (max 7 days)"),
    start: Optional[str] = Query(None, description="ISO-8601 UTC start override"),
    end: Optional[str] = Query(None, description="ISO-8601 UTC end override"),
):
    """Historical state records for one or more entities. Returns {entity_id: [{state, last_changed}]}."""
    ids = [e.strip() for e in entity_ids.split(",") if e.strip()]
    if not ids:
        return {}
    now = datetime.now(timezone.utc)
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else now
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else end_dt - timedelta(hours=hours)
    try:
        return get_history(ids, start_dt, end_dt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")


@app.get("/api/cameras")
def list_cameras():
    """Return camera entities from HA with their area assignments."""
    try:
        entities = _ws_call({"type": "config/entity_registry/list"})
        devices = get_device_registry()
        areas = get_areas()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {exc}")

    area_by_id = {a["area_id"]: a["name"] for a in areas}
    device_area = {d["id"]: d.get("area_id") for d in devices}

    try:
        states = states_as_dict()
    except Exception:
        states = {}

    cams = []
    for ent in entities:
        eid = ent.get("entity_id", "")
        if not eid.startswith("camera."):
            continue
        dev_id = ent.get("device_id", "")
        area_id = ent.get("area_id") or device_area.get(dev_id, "")
        area_name = area_by_id.get(area_id, "") if area_id else ""
        # friendly_name lives in state attributes, not the entity registry entry
        friendly_name = (
            states.get(eid, {}).get("attributes", {}).get("friendly_name")
            or ent.get("name")
            or eid
        )
        cams.append({
            "entity_id": eid,
            "friendly_name": friendly_name,
            "area": area_name,
        })

    # Fall back to states if entity registry gave no results (older HA versions)
    if not cams:
        try:
            states = get_all_states()
            for s in states:
                if s["entity_id"].startswith("camera."):
                    cams.append({
                        "entity_id": s["entity_id"],
                        "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                        "area": "",
                    })
        except Exception:
            pass

    return cams


@app.get("/api/camera_proxy/{entity_id:path}")
def camera_proxy(entity_id: str):
    """Proxy a single JPEG snapshot from HA so the browser never needs HA credentials."""
    from dari.rule_engine.ha_client import HA_URL, HEADERS
    url = f"{HA_URL}/api/camera_proxy/{entity_id}"
    try:
        resp = _requests.get(url, headers=HEADERS, timeout=10, stream=True)
        resp.raise_for_status()
    except _requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Camera unavailable: {exc}")
    content_type = resp.headers.get("content-type", "image/jpeg")
    return StreamingResponse(resp.iter_content(chunk_size=8192), media_type=content_type)


@app.get("/api/camera_stream/{entity_id:path}")
def camera_stream(entity_id: str):
    """Proxy the MJPEG live stream from HA."""
    from dari.rule_engine.ha_client import HA_URL, HEADERS
    url = f"{HA_URL}/api/camera_proxy_stream/{entity_id}"
    try:
        resp = _requests.get(url, headers=HEADERS, stream=True, timeout=30)
        resp.raise_for_status()
    except _requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Stream unavailable: {exc}")
    content_type = resp.headers.get("content-type", "multipart/x-mixed-replace; boundary=ffmpeg")
    return StreamingResponse(resp.iter_content(chunk_size=8192), media_type=content_type)


@app.get("/")
def root():
    return {"service": "DARI Alerts + Activity API", "docs": "/docs"}
