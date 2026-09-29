"""
Offline checks for the fall / appliance / environment / heart-rate additions.
No Home Assistant needed — every case runs on synthetic entity states.

    python scripts/test_alert_rules.py
"""
from __future__ import annotations
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Keep the care-mode checks off the real data/alerts.db.
os.environ["DARI_DATA_DIR"] = tempfile.mkdtemp(prefix="dari_test_")

from dari.env_metrics import env_metric, normalize_temp
from dari.rule_engine.evaluators import (
    eval_env_threshold, eval_fall, eval_sensor_threshold, eval_vital_threshold, render_message,
)
from dari.rule_engine.models import Profile, Rule
from dari.activity_engine.state import build_sensor_index, build_world_state
from dari.activity_engine.detectors import detect_discrete, resolve_activity

sys.stdout.reconfigure(encoding="utf-8")
NOW = datetime.now(timezone.utc)
FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


def st(state, unit="", ago_min=0.0, **attrs):
    ts = (NOW - timedelta(minutes=ago_min)).isoformat()
    return {"state": str(state), "last_changed": ts, "last_updated": ts,
            "attributes": {"unit_of_measurement": unit, **attrs}}


def rule(**kw) -> Rule:
    base = dict(id="t", name="t", category="Environment", severity="MEDIUM", message="m")
    base.update(kw)
    return Rule.from_dict(base)


def backdate(ctx, minutes):
    """Pretend every running condition started `minutes` ago."""
    for k in ctx.get("cond_since", {}):
        ctx["cond_since"][k] = NOW - timedelta(minutes=minutes)


# ── env_metric ───────────────────────────────────────────────────────────────
print("env_metric")
cases = {
    "sensor.apollo_air_1_sen55_temperature": "temperature",
    "sensor.apollo_air_1_sen55_humidity": "humidity",
    "sensor.apollo_air_1_co2": "co2",
    "sensor.apollo_air_1_pm_2_5_m_weight_concentration": "pm25",
    "sensor.apollo_air_1_pm_10_m_weight_concentration": None,
    "sensor.apollo_air_1_carbon_monoxide": "co",
    "sensor.apollo_air_1_sen55_voc": "voc",
    "sensor.apollo_air_1_sen55_nox": None,
    "sensor.bedroom_weather_temperature": "temperature",
    "sensor.smartwatch_battery_temperature": None,
    "sensor.coffee_maker_power": None,
    "binary_sensor.apollo_air_1_co2": None,
}
for eid, want in cases.items():
    check(f"{eid} -> {want}", env_metric(eid) == want)
check("device_class wins", env_metric("sensor.air_thing_3", "carbon_monoxide") == "co")
check("90 °F = 32.2 °C", abs(normalize_temp(90, "°F", "°C") - 32.22) < 0.01)

# ── env_threshold ────────────────────────────────────────────────────────────
print("env_threshold")
ctx = {"entity_area": {"sensor.apollo_air_1_co2": "Living room",
                       "sensor.bedroom_weather_temperature": "Bedroom"}}
co2 = rule(trigger_type="env_threshold", metric="co2", operator="gt", value=1000, duration_minutes=5)
state = {"sensor.apollo_air_1_co2": st(1200, "ppm")}
check("not yet sustained", eval_env_threshold(co2, state, ctx) == (False, None))
backdate(ctx, 6)
fired, zone = eval_env_threshold(co2, state, ctx)
check("fires after duration, zone from area map", fired and zone == "Living room")
check("value var", ctx["render_vars"]["t"]["value"] == "1200 ppm")
state["sensor.apollo_air_1_co2"] = st("unavailable")
check("unavailable resets", eval_env_threshold(co2, state, ctx) == (False, None)
      and not ctx["cond_since"])

heat = rule(trigger_type="env_threshold", metric="temperature", operator="gt", value=31,
            unit="°C", duration_minutes=0)
check("°F sensor converted (90 °F > 31 °C)",
      eval_env_threshold(heat, {"sensor.bedroom_weather_temperature": st(90, "°F")}, ctx)[0])
check("°F sensor converted (85 °F < 31 °C)",
      not eval_env_threshold(heat, {"sensor.bedroom_weather_temperature": st(85, "°F")}, ctx)[0])
heat_lr = rule(trigger_type="env_threshold", metric="temperature", operator="gt", value=31,
               unit="°C", zone="Living room")
check("zone filter excludes other rooms",
      not eval_env_threshold(heat_lr, {"sensor.bedroom_weather_temperature": st(95, "°F")}, ctx)[0])
cold = rule(trigger_type="env_threshold", metric="temperature", operator="lte", value=18, unit="°C")
check("lte boundary", eval_env_threshold(cold, {"sensor.x_temperature": st(18.0, "°C")}, {})[0])
msg = render_message("{{zone}} is {{value}}", "P", "Bedroom", None, value="32.2 °C")
check("message renders value", msg == "Bedroom is 32.2 °C")

# ── sensor_threshold with duration (appliance left on) ───────────────────────
print("sensor_threshold")
ctx = {}
left_on = rule(trigger_type="sensor_threshold", entity_id="sensor.plug_power",
               operator="gt", value=50, duration_minutes=30)
s = {"sensor.plug_power": st(1100, "W")}
check("not before 30 min", not eval_sensor_threshold(left_on, s, ctx)[0])
backdate(ctx, 31)
check("fires after 30 min", eval_sensor_threshold(left_on, s, ctx)[0])
check("old rules (no duration) fire at once",
      eval_sensor_threshold(rule(trigger_type="sensor_threshold", entity_id="sensor.plug_power",
                                 operator="gt", value=50), s, {})[0])

# ── vital_threshold ──────────────────────────────────────────────────────────
print("vital_threshold")
watch = {"heart_rate": "sensor.hr", "on_body": "binary_sensor.body",
         "activity_state": "sensor.act", "steps_today": "sensor.steps"}
hi = rule(trigger_type="vital_threshold", metric="heart_rate", operator="gt", value=99,
          duration_minutes=10)


def vstate(hr=110, hr_ago=0.5, body="on", act="passive", steps_ago=30):
    return {"sensor.hr": st(hr, "bpm", hr_ago), "binary_sensor.body": st(body),
            "sensor.act": st(act), "sensor.steps": st(3000, "steps", steps_ago)}


ctx = {"watch": watch}
eval_vital_threshold(hi, vstate(), ctx)
backdate(ctx, 11)
check("sustained high HR at rest fires", eval_vital_threshold(hi, vstate(), ctx)[0])
for label, kw in [("stale reading", dict(hr_ago=30)), ("watch off wrist", dict(body="off")),
                  ("exercising", dict(act="exercise")), ("steps just counted", dict(steps_ago=1))]:
    ctx = {"watch": watch}
    eval_vital_threshold(hi, vstate(**kw), ctx)
    backdate(ctx, 11)
    check(f"suppressed: {label}", not eval_vital_threshold(hi, vstate(**kw), ctx)[0])
lo = rule(trigger_type="vital_threshold", metric="heart_rate", operator="lt", value=55)
check("low HR not suppressed by walking", eval_vital_threshold(lo, vstate(hr=48, steps_ago=1),
                                                               {"watch": watch})[0])
check("no watch configured -> silent", not eval_vital_threshold(lo, vstate(hr=48), {})[0])

# ── fall ─────────────────────────────────────────────────────────────────────
print("fall")
auto = rule(trigger_type="fall", category="Safety", severity="CRITICAL")
ctx = {"area_sensors": {"Living room": {"fall": ["binary_sensor.lr_fall"]}}}
check("bucketed fall entity fires", eval_fall(auto, {"binary_sensor.lr_fall": st("on")}, ctx)
      == (True, "Living room"))
check("fails closed with no fall entity", not eval_fall(auto, {}, {"area_sensors": {}})[0])
pinned = rule(trigger_type="fall", entity_id="sensor.fp2_state", category="Safety", severity="CRITICAL")
ctx = {"area_sensors": {}, "entity_area": {"sensor.fp2_state": "Bedroom"}}
check("pinned entity, 'detected' state", eval_fall(pinned, {"sensor.fp2_state": st("detected")}, ctx)
      == (True, "Bedroom"))
check("pinned entity idle", not eval_fall(pinned, {"sensor.fp2_state": st("no_fall")}, ctx)[0])

# ── appliances (activity engine) ─────────────────────────────────────────────
print("appliances")
PLUG = "sensor.kitchen_plug_power"
area_sensors = {"Kitchen": {"presence": ["binary_sensor.kitchen_presence"], "all": [PLUG]}}


def hstates(watts, presence="on"):
    return {PLUG: st(watts, "W", friendly_name="Kitchen plug power"),
            "binary_sensor.kitchen_presence": st(presence)}


idx = build_sensor_index(area_sensors, hstates(1), appliances={PLUG: {"name": "Microwave"}})
app = idx["appliances"][PLUG]
check("profile name + inferred kind", app["name"] == "Microwave" and app["kind"] == "microwave")
idx2 = build_sensor_index(area_sensors, hstates(1))
check("unlisted plug tracked under HA name", idx2["appliances"][PLUG]["name"] == "Kitchen plug")

events: list[str] = []
prev = None
t = NOW
# standby → running (magnetron cycling 1100 W / 60 W) → off
for sec, watts in [(0, 2), (10, 1100), (25, 60), (40, 1100), (55, 60), (70, 1100),
                   (130, 3), (140, 3), (175, 3), (200, 3)]:
    now = t + timedelta(seconds=sec)
    w = build_world_state(hstates(watts), idx, prev, now)
    for c in detect_discrete(prev, w, idx, {}):
        events.append(f"{c.activity}:{c.detail}")
    if sec == 70:
        check("cooking while microwave runs in kitchen",
              resolve_activity(w, {}, None).activity == "cooking")
    prev = w
check("one on, one off, despite power cycling", [e.split(":")[0] for e in events]
      == ["appliance_on", "appliance_off"])
check("on detail has name + watts", events[0] == "appliance_on:Microwave · 1100 W")
check("off detail has run time", events[1].startswith("appliance_off:Microwave · ran"))

# ── Environment page status (API) ────────────────────────────────────────────
print("environment page status")
from dari.api_server.main import _env_status
rules = Profile.load("config/profiles/patient_001.yaml").rules
check("22 °C normal", _env_status(rules, "temperature", "Bedroom", "sensor.t", 22, "°C") == ("ok", None))
check("90 °F -> heat alert", _env_status(rules, "temperature", "Bedroom", "sensor.t", 90, "°F")
      == ("alert", "Indoor heat — danger"))
check("27 °C -> warm (LOW) is warn", _env_status(rules, "temperature", None, "sensor.t", 27, "°C")[0] == "warn")
check("CO 80 ppm -> alert", _env_status(rules, "co", None, "sensor.co", 80, "ppm")[0] == "alert")
check("uncovered kind -> None", _env_status(rules, "other", None, "sensor.x", 5, "") == (None, None))

# ── care mode ────────────────────────────────────────────────────────────────
print("care mode")
from dari.rule_engine import care_mode
PID = "test-profile"
check("default is alone", care_mode.get(PID)["mode"] == "alone")
care_mode.set_mode(PID, "with_others", NOW + timedelta(hours=2))
check("with_others until set", care_mode.get(PID)["mode"] == "with_others")
check("expired timer reads alone", care_mode.get(PID, NOW + timedelta(hours=3))
      == {"mode": "alone", "until": None, "changed_at": care_mode.get(PID)["until"], "expired": True})
care_mode.set_mode(PID, "with_others")
check("no timer = until switched back", care_mode.get(PID, NOW + timedelta(days=2))["mode"] == "with_others")
care_mode.set_mode(PID, "alone", NOW + timedelta(hours=1))
check("alone ignores a timer", care_mode.get(PID)["until"] is None)
prof = Profile.load("config/profiles/patient_001.yaml")
paused = {r.id for r in prof.active_rules if not care_mode.rule_active_in(r, "with_others")}
check("with others pauses presence-attributed rules",
      paused == {"rule-003", "rule-004", "rule-005", "rule-006"})
check("fall / door / env / vital keep running", all(
    care_mode.rule_active_in(r, "with_others") for r in prof.active_rules
    if r.trigger_type in ("fall", "door_opened", "env_threshold", "vital_threshold")))
check("per-rule override", care_mode.rule_active_in(
    rule(trigger_type="night_wandering", modes=["alone", "with_others"]), "with_others"))
check("alone runs everything", all(care_mode.rule_active_in(r, "alone") for r in prof.active_rules))

# ── shipped profile ──────────────────────────────────────────────────────────
print("profile")
p = Profile.load("config/profiles/patient_001.yaml")
ids = {r.id for r in p.rules}
check("all IAQ + vital rules present", {"env-heat", "env-warm", "env-cold", "env-cool", "env-humid",
                                        "env-co2", "env-pm25", "env-co", "env-voc",
                                        "vital-hr-high", "vital-hr-low"} <= ids)
check("metric rules are well formed", all(r.metric and r.operator and r.value is not None
                                          for r in p.rules if r.trigger_type.endswith("_threshold")
                                          and r.trigger_type != "sensor_threshold"))

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    sys.exit(1)
print("all passed")
