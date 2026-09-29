"""
DARI Rule Builder — Streamlit web UI
Run with:  streamlit run src/dari/admin_streamlit/app.py
"""
import sys
import uuid
from pathlib import Path

import base64
import json
import altair as alt
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from dari.rule_engine.models import Profile, Rule, TimeWindow
from dari.rule_engine.ha_client import get_all_states, get_areas, get_sensors_by_area, get_door_entities, get_history
from dari.rule_engine.alert_store import init_db, query as query_alerts, acknowledge
from dari.paths import PROFILES_DIR
TRIGGER_LABELS = {
    "fall":              "Fall Detected",
    "door_opened":       "Door Opened",
    "room_inactivity":   "Room Inactivity",
    "global_inactivity": "Global Inactivity (whole home)",
    "night_wandering":   "Night Wandering",
    "long_stay":         "Long Stay in Room",
    "sensor_threshold":  "Sensor Threshold",
}
SEVERITY_COLORS = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🟢",
}

st.set_page_config(page_title="DARI Rule Builder", page_icon="🏠", layout="wide")
init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_ha_data():
    try:
        areas   = get_areas()
        by_area = get_sensors_by_area()
        states  = {s["entity_id"]: s for s in get_all_states()}
        doors   = get_door_entities()
        numeric = [s for s in states.values()
                   if s["entity_id"].split(".")[0] == "sensor"
                   and _is_numeric(s["state"])]
        return {
            "areas": [a["name"] for a in areas],
            "by_area": by_area,
            "states": states,
            "doors": doors,
            "numeric": numeric,
            "ok": True,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "areas": [], "doors": [], "numeric": []}


def _is_numeric(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def load_profile_names() -> list[str]:
    return [p.stem for p in sorted(PROFILES_DIR.glob("*.yaml"))
            if not p.stem.startswith("suggested")]


def load_profile(name: str) -> Profile:
    return Profile.load(str(PROFILES_DIR / f"{name}.yaml"))


def save_profile(profile: Profile, name: str) -> None:
    profile.save(str(PROFILES_DIR / f"{name}.yaml"))


def severity_badge(s: str) -> str:
    return f"{SEVERITY_COLORS.get(s, '')} {s}"


# ── Sidebar navigation ────────────────────────────────────────────────────────

st.sidebar.title("🏠 DARI Rule Builder")
page = st.sidebar.radio("Navigate", ["Rule List", "Alert History", "Sensor Browser", "Sensor History", "Floor Map", "Watch Config"])

profile_names = load_profile_names()
if not profile_names:
    st.error("No profile YAML files found in `profiles/`.")
    st.stop()

selected_profile_name = st.sidebar.selectbox("Patient profile", profile_names)
profile = load_profile(selected_profile_name)

st.sidebar.markdown("---")
st.sidebar.caption(f"Patient: **{profile.patient_name}**")
st.sidebar.caption(f"Caregiver: **{profile.caregiver_name}**")
st.sidebar.caption(f"Active rules: **{len(profile.active_rules)}** / {len(profile.rules)}")

ha = load_ha_data()
if not ha["ok"]:
    st.sidebar.warning(f"⚠️ HA connection issue: {ha.get('error','')}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Rule List
# ══════════════════════════════════════════════════════════════════════════════

if page == "Rule List":
    st.title(f"Rules — {profile.patient_name}")

    col_new, col_hint = st.columns([1, 4])
    with col_new:
        if st.button("➕  Add new rule", type="primary"):
            st.session_state["editing_rule_id"] = "__new__"

    if profile.rules:
        st.subheader("Current rules")
        for i, rule in enumerate(profile.rules):
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([3, 2, 1.5, 1, 1])
                c1.markdown(f"**{rule.name}**")
                c2.markdown(TRIGGER_LABELS.get(rule.trigger_type, rule.trigger_type))
                c3.markdown(severity_badge(rule.severity))
                enabled = c4.toggle("On", value=rule.enabled, key=f"tog_{rule.id}")
                if enabled != rule.enabled:
                    profile.rules[i].enabled = enabled
                    save_profile(profile, selected_profile_name)
                    st.rerun()
                if c5.button("Edit", key=f"edit_{rule.id}"):
                    st.session_state["editing_rule_id"] = rule.id
    else:
        st.info("No rules yet. Add one above.")

    # ── Rule Editor ──────────────────────────────────────────────────────────
    editing_id = st.session_state.get("editing_rule_id")
    if not editing_id:
        st.stop()

    is_new = editing_id == "__new__"
    existing: Rule | None = None if is_new else next(
        (r for r in profile.rules if r.id == editing_id), None
    )

    st.divider()
    st.subheader("✏️  Rule Editor" if not is_new else "➕  New Rule")

    with st.form("rule_form"):
        name = st.text_input("Rule name",
                             value="" if is_new else existing.name)

        col_cat, col_sev = st.columns(2)
        category = col_cat.selectbox(
            "Category", ["Safety", "Activity", "Environment"],
            index=0 if is_new else ["Safety", "Activity", "Environment"].index(existing.category)
        )
        severity = col_sev.selectbox(
            "Severity", ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
            index=0 if is_new else ["CRITICAL", "HIGH", "MEDIUM", "LOW"].index(existing.severity)
        )

        trigger_keys  = list(TRIGGER_LABELS.keys())
        trigger_names = list(TRIGGER_LABELS.values())
        trig_idx = 0 if is_new else trigger_keys.index(existing.trigger_type)
        trigger_label = st.selectbox("Trigger type", trigger_names, index=trig_idx)
        trigger_type  = trigger_keys[trigger_names.index(trigger_label)]

        st.markdown("##### Trigger parameters")

        zone        = None
        entity_id   = None
        duration_min = None
        no_return   = None
        operator    = None
        value       = None
        tw_start    = None
        tw_end      = None
        use_window  = False

        rooms = ha["areas"] or ["Kitchen", "Bedroom", "Bathroom", "Living Room"]

        # ── Dynamic fields ────────────────────────────────────────────────────

        if trigger_type == "fall":
            room_opts = ["Any room"] + rooms
            sel = st.selectbox("Room", room_opts,
                               index=0 if is_new or not existing.zone
                               else (room_opts.index(existing.zone) if existing.zone in room_opts else 0))
            zone = None if sel == "Any room" else sel

        elif trigger_type == "door_opened":
            door_opts = [f"{d['attributes'].get('friendly_name', d['entity_id'])} ({d['entity_id']})"
                         for d in ha.get("doors", [])]
            door_ids  = [d["entity_id"] for d in ha.get("doors", [])]
            if door_opts:
                def_idx = 0
                if not is_new and existing.entity_id in door_ids:
                    def_idx = door_ids.index(existing.entity_id)
                sel_door = st.selectbox("Door sensor", door_opts, index=def_idx)
                entity_id = door_ids[door_opts.index(sel_door)]
            else:
                entity_id = st.text_input("Door entity_id (manual)",
                                          value="" if is_new else (existing.entity_id or ""))
            no_return = st.number_input(
                "No-return timeout (minutes, 0 = alert immediately)",
                min_value=0, max_value=60,
                value=0 if is_new else (existing.no_return_minutes or 0)
            )
            use_window = st.checkbox("Restrict to time window",
                                     value=False if is_new else bool(existing.time_window))
            if use_window:
                col_s, col_e = st.columns(2)
                tw_start = col_s.text_input("Start (HH:MM)",
                                            value="20:00" if is_new else (existing.time_window.start if existing.time_window else "20:00"))
                tw_end   = col_e.text_input("End (HH:MM)",
                                            value="08:00" if is_new else (existing.time_window.end if existing.time_window else "08:00"))

        elif trigger_type == "room_inactivity":
            zone = st.selectbox("Room", rooms,
                                index=0 if is_new or not existing.zone
                                else (rooms.index(existing.zone) if existing.zone in rooms else 0))
            duration_min = st.number_input("Inactivity duration (minutes)", min_value=5,
                                           value=30 if is_new else (existing.duration_minutes or 30))
            use_window = st.checkbox("Restrict to time window",
                                     value=False if is_new else bool(existing.time_window))
            if use_window:
                col_s, col_e = st.columns(2)
                tw_start = col_s.text_input("Start (HH:MM)",
                                            value="07:00" if is_new else (existing.time_window.start if existing.time_window else "07:00"))
                tw_end   = col_e.text_input("End (HH:MM)",
                                            value="11:00" if is_new else (existing.time_window.end if existing.time_window else "11:00"))

        elif trigger_type == "global_inactivity":
            duration_min = st.number_input("Inactivity duration (minutes)", min_value=15,
                                           value=120 if is_new else (existing.duration_minutes or 120))
            use_window = st.checkbox("Restrict to time window",
                                     value=False if is_new else bool(existing.time_window))
            if use_window:
                col_s, col_e = st.columns(2)
                tw_start = col_s.text_input("Start (HH:MM)",
                                            value="08:00" if is_new else (existing.time_window.start if existing.time_window else "08:00"))
                tw_end   = col_e.text_input("End (HH:MM)",
                                            value="20:00" if is_new else (existing.time_window.end if existing.time_window else "20:00"))

        elif trigger_type == "night_wandering":
            col_s, col_e = st.columns(2)
            tw_start = col_s.text_input("Window start (HH:MM)",
                                        value="00:00" if is_new else (existing.time_window.start if existing.time_window else "00:00"))
            tw_end   = col_e.text_input("Window end (HH:MM)",
                                        value="06:00" if is_new else (existing.time_window.end if existing.time_window else "06:00"))
            use_window = True

        elif trigger_type == "long_stay":
            zone = st.selectbox("Room", rooms,
                                index=0 if is_new or not existing.zone
                                else (rooms.index(existing.zone) if existing.zone in rooms else 0))
            duration_min = st.number_input("Maximum stay (minutes)", min_value=5,
                                           value=20 if is_new else (existing.duration_minutes or 20))
            use_window = st.checkbox("Restrict to time window",
                                     value=False if is_new else bool(existing.time_window))
            if use_window:
                col_s, col_e = st.columns(2)
                tw_start = col_s.text_input("Start (HH:MM)",
                                            value="00:00" if is_new else (existing.time_window.start if existing.time_window else "00:00"))
                tw_end   = col_e.text_input("End (HH:MM)",
                                            value="23:59" if is_new else (existing.time_window.end if existing.time_window else "23:59"))

        elif trigger_type == "sensor_threshold":
            numeric_opts = [
                f"{s['attributes'].get('friendly_name', s['entity_id'])} "
                f"[{s['state']} {s['attributes'].get('unit_of_measurement','')}]"
                for s in ha.get("numeric", [])
            ]
            numeric_ids = [s["entity_id"] for s in ha.get("numeric", [])]
            if numeric_opts:
                def_idx = 0
                if not is_new and existing.entity_id in numeric_ids:
                    def_idx = numeric_ids.index(existing.entity_id)
                sel_sen = st.selectbox("Sensor", numeric_opts, index=def_idx)
                entity_id = numeric_ids[numeric_opts.index(sel_sen)]
            else:
                entity_id = st.text_input("Sensor entity_id (manual)",
                                          value="" if is_new else (existing.entity_id or ""))
            col_op, col_val = st.columns(2)
            operator = col_op.selectbox(
                "Condition", ["gt", "lt"],
                format_func=lambda x: "Above (>)" if x == "gt" else "Below (<)",
                index=0 if is_new else (0 if existing.operator == "gt" else 1)
            )
            value = col_val.number_input(
                "Threshold value",
                value=float(existing.value) if not is_new and existing.value is not None else 0.0
            )

        st.markdown("##### Alert message")
        st.caption("Available variables: `{{patient_name}}` `{{zone}}` `{{time}}` `{{duration}}`")
        message = st.text_area("Message",
                               value="" if is_new else existing.message,
                               height=80)

        cooldown = st.number_input(
            "Cooldown (min between repeated alerts)", min_value=1,
            value=10 if is_new else existing.cooldown_minutes
        )

        col_save, col_del, col_cancel = st.columns([2, 1, 1])
        submitted = col_save.form_submit_button("💾  Save rule", type="primary")
        delete    = col_del.form_submit_button("🗑️  Delete", type="secondary") if not is_new else False
        cancel    = col_cancel.form_submit_button("Cancel")

    if cancel:
        del st.session_state["editing_rule_id"]
        st.rerun()

    if delete and not is_new:
        profile.rules = [r for r in profile.rules if r.id != editing_id]
        save_profile(profile, selected_profile_name)
        del st.session_state["editing_rule_id"]
        st.success("Rule deleted.")
        st.rerun()

    if submitted:
        if not name.strip():
            st.error("Rule name is required.")
        elif not message.strip():
            st.error("Alert message is required.")
        else:
            tw = TimeWindow(start=tw_start, end=tw_end) if use_window and tw_start and tw_end else None
            new_rule = Rule(
                id=str(uuid.uuid4())[:8] if is_new else existing.id,
                name=name.strip(),
                enabled=True,
                category=category,
                severity=severity,
                trigger_type=trigger_type,
                message=message.strip(),
                zone=zone,
                entity_id=entity_id,
                duration_minutes=int(duration_min) if duration_min is not None else None,
                no_return_minutes=int(no_return) if no_return else None,
                operator=operator,
                value=float(value) if value is not None and trigger_type == "sensor_threshold" else None,
                time_window=tw,
                cooldown_minutes=int(cooldown),
            )
            if is_new:
                profile.rules.append(new_rule)
            else:
                profile.rules = [new_rule if r.id == editing_id else r for r in profile.rules]
            save_profile(profile, selected_profile_name)
            del st.session_state["editing_rule_id"]
            st.success(f"Rule '**{name}**' saved.")
            load_ha_data.clear()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Alert History
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Alert History":
    st.title(f"Alert History — {profile.patient_name}")

    col_cat, col_sev, col_ack = st.columns(3)
    cat_filter = col_cat.selectbox("Category", ["All", "Safety", "Activity", "Environment"])
    sev_filter = col_sev.selectbox("Severity", ["All", "CRITICAL", "HIGH", "MEDIUM", "LOW"])
    ack_filter = col_ack.selectbox("Status", ["All", "Unacknowledged", "Acknowledged"])

    alerts = query_alerts(
        profile_id=profile.profile_id,
        category=None if cat_filter == "All" else cat_filter,
        severity=None if sev_filter == "All" else sev_filter,
        acknowledged=None if ack_filter == "All" else (ack_filter == "Acknowledged"),
        limit=100,
    )

    if not alerts:
        st.info("No alerts found matching the current filters.")
    else:
        for a in alerts:
            with st.container(border=True):
                c1, c2, c3 = st.columns([5, 2, 1])
                c1.markdown(
                    f"{SEVERITY_COLORS.get(a.severity, '')} **{a.rule_name}** — {a.message}"
                )
                c2.caption(f"{a.timestamp[:19].replace('T', ' ')} UTC")
                if not a.acknowledged:
                    if c3.button("✓ Ack", key=f"ack_{a.id}"):
                        acknowledge(a.id)
                        st.rerun()
                else:
                    c3.caption("✓ Done")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Sensor Browser
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Sensor Browser":
    st.title("Sensor Browser — Live HA State")

    if not ha["ok"]:
        st.error(f"Cannot connect to Home Assistant: {ha.get('error')}")
        st.stop()

    states_list = list(ha["states"].values())
    domain_opts = sorted({s["entity_id"].split(".")[0] for s in states_list})
    col_d, col_r, col_q = st.columns(3)
    sel_domain = col_d.selectbox("Domain", ["All"] + domain_opts)
    sel_room   = col_r.selectbox("Room / Area", ["All"] + ha["areas"])
    query_txt  = col_q.text_input("Search entity_id or name")

    by_area = ha.get("by_area", {})
    if sel_room != "All":
        room_entities = set(by_area.get(sel_room, {}).get("all", []))
    else:
        room_entities = None

    rows = []
    for s in states_list:
        eid = s["entity_id"]
        if sel_domain != "All" and eid.split(".")[0] != sel_domain:
            continue
        if room_entities is not None and eid not in room_entities:
            continue
        fn = s.get("attributes", {}).get("friendly_name", "")
        if query_txt and query_txt.lower() not in eid.lower() and query_txt.lower() not in fn.lower():
            continue
        unit = s.get("attributes", {}).get("unit_of_measurement", "")
        rows.append({
            "entity_id":    eid,
            "friendly_name": fn,
            "state":        f"{s['state']} {unit}".strip(),
            "last_changed": s.get("last_changed", "")[:19].replace("T", " "),
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=600)
        st.caption(f"{len(rows)} entities shown.")
    else:
        st.info("No entities match the current filters.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Sensor History
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Sensor History":
    st.title("Sensor History")

    if not ha["ok"]:
        st.error(f"Cannot connect to Home Assistant: {ha.get('error')}")
        st.stop()

    # Domains that produce no useful state history
    _NOISY_DOMAINS = frozenset({
        "camera", "automation", "scene", "script", "update", "button",
        "input_button", "image", "media_player", "tts", "stt", "todo",
        "calendar", "persistent_notification", "select", "text", "number",
    })
    _USEFUL_DOMAINS = frozenset({
        "sensor", "binary_sensor", "person", "device_tracker",
        "climate", "weather", "input_boolean", "switch", "light",
    })

    states_list = list(ha["states"].values())
    entity_labels = {
        s["entity_id"]: s["attributes"].get("friendly_name", s["entity_id"])
        for s in states_list
    }

    # ── Filters ───────────────────────────────────────────────────────────────
    col_area, col_domain, col_all = st.columns([2, 2, 1])
    area_filter   = col_area.selectbox("Filter by area", ["All"] + ha["areas"], key="hist_area")
    all_domains   = sorted({s["entity_id"].split(".")[0] for s in states_list})
    useful_domains = [d for d in all_domains if d not in _NOISY_DOMAINS]
    domain_filter  = col_domain.selectbox("Filter by domain", ["All"] + useful_domains, key="hist_domain")
    show_all       = col_all.checkbox("Show all\nentity types", value=False, key="hist_show_all")

    by_area = ha.get("by_area", {})
    filtered_ids = list(entity_labels.keys())

    if not show_all:
        filtered_ids = [e for e in filtered_ids
                        if e.split(".")[0] in _USEFUL_DOMAINS]
    if area_filter != "All":
        area_entities = set(by_area.get(area_filter, {}).get("all", []))
        filtered_ids = [e for e in filtered_ids if e in area_entities]
    if domain_filter != "All":
        filtered_ids = [e for e in filtered_ids if e.split(".")[0] == domain_filter]

    # Clear stale results when filters change
    filter_key = (area_filter, domain_filter, show_all)
    if st.session_state.get("_hist_filter_key") != filter_key:
        st.session_state.pop("hist_data", None)
        st.session_state["_hist_filter_key"] = filter_key

    selected_ids = st.multiselect(
        "Sensors to query",
        options=filtered_ids,
        format_func=lambda x: f"{entity_labels.get(x, x)}  ({x})",
        placeholder="Choose one or more sensors…",
        key="hist_entities",
    )

    # ── Time range ────────────────────────────────────────────────────────────
    st.markdown("##### Time range")
    quick = st.radio(
        "Quick range",
        ["Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days", "Custom"],
        horizontal=True,
        key="hist_quick",
    )

    now_utc = datetime.now(timezone.utc)
    if quick == "Last 1 hour":
        start_dt, end_dt = now_utc - timedelta(hours=1), now_utc
    elif quick == "Last 6 hours":
        start_dt, end_dt = now_utc - timedelta(hours=6), now_utc
    elif quick == "Last 24 hours":
        start_dt, end_dt = now_utc - timedelta(hours=24), now_utc
    elif quick == "Last 7 days":
        start_dt, end_dt = now_utc - timedelta(days=7), now_utc
    else:
        col_sd, col_st, col_ed, col_et = st.columns(4)
        start_date = col_sd.date_input("Start date", value=(now_utc - timedelta(hours=24)).date(), key="hist_sd")
        start_time = col_st.time_input("Start time", value=dtime(0, 0), key="hist_st")
        end_date   = col_ed.date_input("End date",   value=now_utc.date(),                       key="hist_ed")
        end_time   = col_et.time_input("End time",   value=dtime(23, 59),                        key="hist_et")
        start_dt   = datetime.combine(start_date, start_time, tzinfo=timezone.utc)
        end_dt     = datetime.combine(end_date,   end_time,   tzinfo=timezone.utc)

    # ── Query ─────────────────────────────────────────────────────────────────
    if st.button("🔍  Query history", type="primary", disabled=not selected_ids):
        with st.spinner("Fetching history from Home Assistant…"):
            try:
                st.session_state["hist_data"]  = get_history(selected_ids, start_dt, end_dt)
                st.session_state["hist_labels"] = {k: entity_labels.get(k, k) for k in selected_ids}
            except Exception as exc:
                st.error(f"History fetch failed: {exc}")

    # ── Results ───────────────────────────────────────────────────────────────
    if "hist_data" not in st.session_state:
        st.stop()

    history = st.session_state["hist_data"]
    labels  = st.session_state.get("hist_labels", {})

    if not history:
        st.info("No data returned — the sensors may have no state changes in this window.")
        st.stop()

    rows = []
    for eid, records in history.items():
        name = labels.get(eid, eid)
        for rec in records:
            rows.append({
                "sensor":    name,
                "entity_id": eid,
                "time":      pd.to_datetime(rec["last_changed"], utc=True),
                "state":     rec["state"],
            })

    df = pd.DataFrame(rows)

    numeric_ids = [
        eid for eid, recs in history.items()
        if any(_is_numeric(r["state"]) for r in recs)
    ]
    binary_ids = [eid for eid in history if eid not in numeric_ids]

    # Numeric line chart
    if numeric_ids:
        st.subheader("Numeric sensors")
        num_df = df[df["entity_id"].isin(numeric_ids)].copy()
        num_df["value"] = pd.to_numeric(num_df["state"], errors="coerce")
        chart = (
            alt.Chart(num_df)
            .mark_line()
            .encode(
                x=alt.X("time:T", title="Time"),
                y=alt.Y("value:Q", title="Value"),
                color=alt.Color("sensor:N", title="Sensor"),
                tooltip=["sensor:N", alt.Tooltip("time:T", format="%Y-%m-%d %H:%M:%S"), "value:Q"],
            )
            .interactive()
        )
        st.altair_chart(chart, use_container_width=True)

    # Binary / state step chart
    if binary_ids:
        st.subheader("State / binary sensors")
        bin_df = df[df["entity_id"].isin(binary_ids)].copy()
        STATE_NUM = {"on": 1, "off": 0, "open": 1, "closed": 0,
                     "home": 1, "not_home": 0, "true": 1, "false": 0, "detected": 1}
        bin_df["value"] = bin_df["state"].str.lower().map(STATE_NUM).fillna(0.5)
        chart = (
            alt.Chart(bin_df)
            .mark_line(interpolate="step-after")
            .encode(
                x=alt.X("time:T", title="Time"),
                y=alt.Y("value:Q",
                        title="State",
                        scale=alt.Scale(domain=[-0.1, 1.1]),
                        axis=alt.Axis(values=[0, 1], labelExpr="datum.value === 1 ? 'on' : 'off'")),
                color=alt.Color("sensor:N", title="Sensor"),
                tooltip=["sensor:N", alt.Tooltip("time:T", format="%Y-%m-%d %H:%M:%S"), "state:N"],
            )
            .interactive()
        )
        st.altair_chart(chart, use_container_width=True)

    with st.expander("Raw data table"):
        st.dataframe(
            df[["sensor", "time", "state"]].sort_values("time"),
            use_container_width=True,
            height=400,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Floor Map
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Floor Map":
    FLOORPLAN_CFG = Path(__file__).resolve().parent / "floorplan.json"
    FLOORPLAN_IMG = Path(__file__).resolve().parent / "assets" / "floorplan.png"

    DEFAULT_FP = {
        "canvas": {"width": 100, "height": 87},
        "rooms": [
            {"name": "Bedroom",          "x0":  6, "y0":  7, "x1": 37, "y1": 87},
            {"name": "Bedroom Bathroom", "x0":  6, "y0":  7, "x1": 22, "y1": 38},
            {"name": "Living room",      "x0": 37, "y0":  7, "x1": 93, "y1": 87},
        ],
    }

    fp = json.loads(FLOORPLAN_CFG.read_text()) if FLOORPLAN_CFG.exists() else DEFAULT_FP

    st.title("Floor Map")
    if not ha["ok"]:
        st.error(f"Cannot connect to Home Assistant: {ha.get('error')}")
        st.stop()

    by_area = ha.get("by_area", {})
    states  = ha.get("states", {})
    cw      = fp["canvas"]["width"]
    ch      = fp["canvas"]["height"]

    def _room_is_occupied(area: str) -> bool:
        ids = (by_area.get(area, {}).get("presence", [])
               + by_area.get(area, {}).get("fall", []))
        return any(states.get(e, {}).get("state") == "on" for e in ids)

    # ── Build Plotly figure ───────────────────────────────────────────────────
    fig = go.Figure()

    # Background floor plan image
    if FLOORPLAN_IMG.exists():
        img_b64 = base64.b64encode(FLOORPLAN_IMG.read_bytes()).decode()
        fig.add_layout_image(
            source=f"data:image/png;base64,{img_b64}",
            xref="x", yref="y",
            x=0, y=ch,           # anchor at top-left in data coords
            xanchor="left", yanchor="top",
            sizex=cw, sizey=ch,
            sizing="stretch",
            layer="below",
            opacity=1.0,
        )

    occupied_rooms = []
    for r in fp["rooms"]:
        occ = _room_is_occupied(r["name"])
        if occ:
            occupied_rooms.append(r["name"])
        cx = (r["x0"] + r["x1"]) / 2
        cy = ch - (r["y0"] + r["y1"]) / 2   # flip to bottom-up for Plotly

        # Room overlay rectangle
        fig.add_shape(
            type="rect",
            x0=r["x0"], x1=r["x1"],
            y0=ch - r["y1"], y1=ch - r["y0"],   # convert top-down → bottom-up
            xref="x", yref="y",
            fillcolor="rgba(27,94,32,0.45)" if occ else "rgba(55,71,79,0.30)",
            line=dict(color="rgba(255,255,255,0.85)", width=2),
        )

        # Room label
        fig.add_annotation(
            x=cx, y=cy + 2,
            text=r["name"],
            showarrow=False,
            font=dict(color="white", size=13, family="Arial Black"),
            xref="x", yref="y",
            bgcolor="rgba(0,0,0,0.35)",
            borderpad=3,
        )

        # Person marker in occupied rooms
        if occ:
            fig.add_trace(go.Scatter(
                x=[cx], y=[cy - 4],
                mode="markers+text",
                marker=dict(size=24, color="#A5D6A7",
                            line=dict(color="white", width=2)),
                text=["person detected"],
                textposition="bottom center",
                textfont=dict(color="#A5D6A7", size=10),
                showlegend=False,
                hovertemplate=f"<b>{r['name']}</b><br>Presence: on<extra></extra>",
            ))

    fig.update_xaxes(range=[0, cw], showgrid=False, showticklabels=False,
                     zeroline=False, fixedrange=True)
    fig.update_yaxes(range=[0, ch], showgrid=False, showticklabels=False,
                     zeroline=False, fixedrange=True)
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=480,
        dragmode=False,
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    col_map, col_panel = st.columns([3, 1])

    with col_map:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with col_panel:
        st.markdown("### Room Status")
        for r in fp["rooms"]:
            occ  = _room_is_occupied(r["name"])
            icon = "🟢" if occ else "⬜"
            st.markdown(f"{icon} **{r['name']}**")
            for eid in by_area.get(r["name"], {}).get("door", []):
                s  = states.get(eid, {})
                fn = s.get("attributes", {}).get("friendly_name", eid)
                st.caption(f"{'🚪' if s.get('state') == 'on' else '🔒'} {fn}")
            for eid in by_area.get(r["name"], {}).get("numeric", [])[:3]:
                s    = states.get(eid, {})
                fn   = s.get("attributes", {}).get("friendly_name", eid)
                val  = s.get("state", "?")
                unit = s.get("attributes", {}).get("unit_of_measurement", "")
                st.caption(f"📊 {fn}: {val} {unit}")

        st.divider()
        if occupied_rooms:
            st.success(f"Person in: {', '.join(occupied_rooms)}")
        else:
            st.info("No presence detected")
        if st.button("🔄 Refresh", key="map_refresh"):
            load_ha_data.clear()
            st.rerun()

    # ── Layout editor ─────────────────────────────────────────────────────────
    with st.expander("⚙️  Edit floor plan zones"):
        st.caption(
            "Coordinates are 0–100 (x) and 0–87 (y), top-left origin. "
            "Area names must match Home Assistant exactly."
        )
        updated = []
        for i, r in enumerate(fp["rooms"]):
            c1, c2, c3, c4, c5 = st.columns([2.5, 1, 1, 1, 1])
            name = c1.text_input("Area name", r["name"], key=f"fp_n_{i}")
            x0   = c2.number_input("x0", float(r["x0"]), step=1.0, key=f"fp_x0_{i}")
            y0   = c3.number_input("y0", float(r["y0"]), step=1.0, key=f"fp_y0_{i}")
            x1   = c4.number_input("x1", float(r["x1"]), step=1.0, key=f"fp_x1_{i}")
            y1   = c5.number_input("y1", float(r["y1"]), step=1.0, key=f"fp_y1_{i}")
            updated.append({"name": name, "x0": x0, "y0": y0, "x1": x1, "y1": y1})

        col_add, col_cw, col_ch, col_save = st.columns([1, 1, 1, 1])
        if col_add.button("➕ Add room"):
            updated.append({"name": "New Room", "x0": 10.0, "y0": 10.0, "x1": 40.0, "y1": 50.0})
        cw2 = col_cw.number_input("Canvas W", float(cw), step=1.0, key="fp_cw")
        ch2 = col_ch.number_input("Canvas H", float(ch), step=1.0, key="fp_ch")
        if col_save.button("💾 Save zones", type="primary"):
            FLOORPLAN_CFG.write_text(
                json.dumps({"canvas": {"width": cw2, "height": ch2}, "rooms": updated}, indent=2)
            )
            st.success("Floor plan zones saved.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Watch Config
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Watch Config":
    st.title(f"Watch & Health Config — {profile.patient_name}")
    st.caption(
        "Map each health metric to its Home Assistant entity. "
        "Entity IDs come from the HA Companion App installed on the patient's phone/watch. "
        "Changes are saved to the patient profile YAML and take effect immediately."
    )

    if not ha["ok"]:
        st.warning(f"⚠️ HA unavailable — showing saved values only. ({ha.get('error','')})")
        states = {}
    else:
        states = ha.get("states", {})

    # All sensor / binary_sensor entity IDs for the dropdowns
    sensor_ids     = sorted(e for e in states if e.startswith("sensor."))
    bin_ids        = sorted(e for e in states if e.startswith("binary_sensor."))
    tracker_ids    = sorted(e for e in states if e.startswith("device_tracker."))
    all_sensor_ids = sensor_ids + bin_ids + tracker_ids

    WATCH_KEYS = [
        ("heart_rate",      "Heart Rate",        "sensor",        "bpm"),
        ("steps_today",     "Steps Today",       "sensor",        "steps"),
        ("battery_level",   "Battery Level",     "sensor",        "%"),
        ("battery_state",   "Battery State",     "sensor",        ""),
        ("on_body",         "On Body",           "binary_sensor", "on/off"),
        ("activity_state",  "Activity State",    "sensor",        ""),
        ("calories",        "Calories",          "sensor",        "cal"),
        ("distance",        "Distance",          "sensor",        "ft/m"),
        ("phone_activity",  "Phone Activity",    "sensor",        ""),
        ("sleep_confidence","Sleep Confidence",  "sensor",        "%"),
    ]

    current_watch = dict(profile.watch)  # copy so we can edit

    # ── Live value helper ─────────────────────────────────────────────────────
    def _live(eid: str) -> str:
        if not eid or eid not in states:
            return "—"
        s    = states[eid]
        val  = s.get("state", "—")
        unit = s.get("attributes", {}).get("unit_of_measurement", "")
        age  = s.get("last_changed", "")
        age_str = ""
        if age:
            try:
                dt  = datetime.fromisoformat(age.replace("Z", "+00:00"))
                min = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
                age_str = f" ({min}m ago)" if min < 60 else f" ({min // 60}h ago)"
            except Exception:
                pass
        return f"{val} {unit}{age_str}".strip()

    # ── Per-metric rows ───────────────────────────────────────────────────────
    st.subheader("Entity mapping")
    changed = False

    for key, label, domain, hint in WATCH_KEYS:
        with st.container(border=True):
            col_label, col_entity, col_live = st.columns([2, 4, 2])
            col_label.markdown(f"**{label}**")
            col_label.caption(f"key: `{key}`  hint: {hint}")

            saved_eid  = current_watch.get(key, "")
            candidates = (sensor_ids if domain == "sensor" else bin_ids) + [""]
            # Prepend the saved value if it's not in the list (e.g. after re-pair)
            if saved_eid and saved_eid not in candidates:
                candidates = [saved_eid] + candidates

            # Find keyword-filtered suggestions for the selectbox
            kw_filter = key.replace("_", " ")
            suggestions = [e for e in candidates if key.replace("_", "") in e.replace("_", "")]
            ordered = suggestions + [e for e in candidates if e not in suggestions]

            sel_idx = ordered.index(saved_eid) if saved_eid in ordered else 0
            new_eid = col_entity.selectbox(
                "Entity",
                ordered,
                index=sel_idx,
                format_func=lambda e: (
                    f"{states[e].get('attributes', {}).get('friendly_name', e)}  ({e})"
                    if e and e in states else e or "— not set —"
                ),
                key=f"wc_{key}",
                label_visibility="collapsed",
            )
            if new_eid != saved_eid:
                current_watch[key] = new_eid
                changed = True

            col_live.markdown("**Live value**")
            col_live.caption(_live(new_eid or saved_eid))

    st.divider()

    # ── Watch device info panel ───────────────────────────────────────────────
    watch_battery_eid = current_watch.get("battery_level", "")
    if watch_battery_eid and watch_battery_eid in states:
        fn = states[watch_battery_eid].get("attributes", {}).get("friendly_name", watch_battery_eid)
        # Guess device name from friendly name e.g. "Smartwatch Battery Level" → "Smartwatch"
        device_name = fn.replace("Battery Level", "").replace("Battery level", "").strip(" -–")
        if device_name:
            st.info(f"ℹ️  Detected device: **{device_name}**")

    # ── Save ─────────────────────────────────────────────────────────────────
    col_save, col_reset, col_refresh = st.columns([2, 1, 1])
    if col_save.button("💾  Save watch config", type="primary"):
        # Remove empty entries before saving
        profile.watch = {k: v for k, v in current_watch.items() if v}
        save_profile(profile, selected_profile_name)
        st.success("Watch config saved to profile YAML.")
        load_ha_data.clear()
        st.rerun()
    if col_reset.button("↩️  Reset"):
        st.rerun()
    if col_refresh.button("🔄  Refresh HA"):
        load_ha_data.clear()
        st.rerun()

    # ── Quick test panel ──────────────────────────────────────────────────────
    with st.expander("🔍  Quick test — fetch all current values"):
        rows = []
        for key, label, _, _ in WATCH_KEYS:
            eid = current_watch.get(key, "")
            rows.append({
                "Metric":    label,
                "Entity ID": eid or "—",
                "Live Value": _live(eid) if eid else "—",
                "Saved?":    "✓" if eid else "✗",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
