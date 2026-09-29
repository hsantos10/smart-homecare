#!/usr/bin/env python3
"""
DARI Sensor Report — self-contained HTML report of ALL HA sensor data.

All 255 HA entities appear in the summary table.
Binary and numeric sensor entities are charted and grouped by type / numerical range.

Usage:
    conda run -n LLMs python scripts/sensor_report.py
    conda run -n LLMs python scripts/sensor_report.py --hours 48
"""
from __future__ import annotations
import sys, base64, io, argparse, webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path


import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches

from dari.rule_engine.ha_client import get_history, get_all_states
from dari.paths import REPORTS_DIR

# ── Constants ────────────────────────────────────────────────────────────────

ON_STATES   = {"on", "true", "home", "detected", "occupied", "open"}
SKIP_STATES = {"unavailable", "unknown"}

COLORS = [
    "#6366f1", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#f97316", "#84cc16",
    "#ec4899", "#14b8a6", "#a855f7", "#eab308",
]

# ── Sensor classification ─────────────────────────────────────────────────────

# Domains that are interesting to the report but NOT graphable
SUMMARY_ONLY_DOMAINS = {
    "automation", "camera", "device_tracker", "group", "input_boolean",
    "input_number", "input_select", "input_text", "light", "media_player",
    "person", "remote", "scene", "script", "select", "sun", "switch",
    "timer", "update", "weather", "zone", "persistent_notification",
    "conversation", "stt", "tts", "wake_word",
}

# Keywords that identify junk device-diagnostic sensors (skip from charts)
DIAG_EXCLUDE = (
    "battery", "rssi", "lqi", "signal_strength", "device_temperature",
    "upload_speed", "download_speed", "voltage", "current", "frequency",
    "reboot", "uptime", "firmware", "memory", "cpu",
)

# Binary sensor classification — order matters, first match wins
BINARY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Presence",    ("presence_sensor", "fp2", "occupancy")),
    ("Fall",        ("fall",)),
    ("Door/Entry",  ("door", "opening", "contact", "window", "magnet",
                     "cabin", "refriger")),
    ("Motion & AI", ("motion", "person", "animal", "baby")),
    ("Vibration",   ("vibration",)),
]

# Numeric sensor grouping — order matters, first match wins
# Each entry: (group_label, [keyword_list], unit_hint)
NUMERIC_GROUP_RULES: list[tuple[str, list[str], str]] = [
    ("Illuminance",   ["illuminance", "light_level", "light_sensor"],  "lx"),
    ("Temperature",   ["temperature"],                                  "°F"),
    ("Humidity",      ["humidity"],                                     "%"),
    ("CO₂",           ["co2", "carbon_dioxide"],                       "ppm"),
    ("VOC / TVOC",    ["voc", "tvoc"],                                 ""),
    ("PM2.5",         ["pm25", "pm2_5"],                               "µg/m³"),
    ("Pressure",      ["pressure"],                                     "psi"),
    ("Power",         ["power"],                                        "W"),
    ("Energy",        ["summation", "energy", "kwh"],                  "kWh"),
]


def classify_binary(eid: str) -> str:
    """Return binary category label, or 'Other Binary' if no rule matches."""
    eid_l = eid.lower()
    for label, keywords in BINARY_RULES:
        if any(kw in eid_l for kw in keywords):
            return label
    return "Other Binary"


def classify_numeric(eid: str) -> str:
    """Return numeric group label, or 'Other Numeric' if no rule matches."""
    eid_l = eid.lower()
    for label, keywords, _ in NUMERIC_GROUP_RULES:
        if any(kw in eid_l for kw in keywords):
            return label
    return "Other Numeric"


def is_diag(eid: str) -> bool:
    """True if this looks like a device-diagnostic sensor (battery, RSSI, etc.)."""
    eid_l = eid.lower()
    return any(kw in eid_l for kw in DIAG_EXCLUDE)


# ── Data helpers ─────────────────────────────────────────────────────────────

def history_to_df(history: dict) -> pd.DataFrame:
    rows = []
    for eid, records in history.items():
        for rec in records:
            state = rec.get("state", "")
            if state.lower() in SKIP_STATES:
                continue
            rows.append({
                "entity_id":  eid,
                "state":      state,
                "changed_at": rec.get("last_changed", ""),
            })
    if not rows:
        return pd.DataFrame(columns=["entity_id", "state", "changed_at"])
    df = pd.DataFrame(rows)
    df["changed_at"] = pd.to_datetime(df["changed_at"], utc=True, format="ISO8601")
    return df.sort_values(["entity_id", "changed_at"]).reset_index(drop=True)


def fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def slabel(eid: str, friendly: dict, maxlen: int = 45) -> str:
    name = friendly.get(eid, eid.split(".")[-1].replace("_", " ").title())
    return name if len(name) <= maxlen else name[:maxlen - 1] + "…"


# ── Chart functions ───────────────────────────────────────────────────────────

def chart_gantt(df, entity_ids, title, friendly, x_start, x_end):
    eids = [e for e in entity_ids if e in df["entity_id"].values]
    if not eids:
        return None
    n = len(eids)
    fig, axes = plt.subplots(n, 1, figsize=(16, max(2.0, n * 0.85)), sharex=True)
    if n == 1:
        axes = [axes]
    fig.suptitle(title, fontsize=12, fontweight="bold")
    for ax, eid in zip(axes, eids):
        edf = df[df["entity_id"] == eid].sort_values("changed_at")
        raw_times  = list(edf["changed_at"])
        raw_states = list(edf["state"])
        if not raw_states:
            ax.set_facecolor("#f3f4f6")
        else:
            if not raw_times or raw_times[0] > x_start:
                raw_times  = [x_start] + raw_times
                raw_states = ["__unknown__"] + raw_states
            for t0, t1, state in zip(raw_times, raw_times[1:] + [x_end], raw_states):
                t0 = max(t0, x_start); t1 = min(t1, x_end)
                if t1 <= t0:
                    continue
                if state == "__unknown__":
                    color = "#e5e7eb"
                elif state.lower() in ON_STATES:
                    color = "#22c55e"
                else:
                    color = "#e5e7eb"
                w = mdates.date2num(t1.to_pydatetime()) - mdates.date2num(t0.to_pydatetime())
                ax.barh(0, w, left=mdates.date2num(t0.to_pydatetime()),
                        height=0.65, color=color, edgecolor="none")
        ax.set_yticks([0])
        ax.set_yticklabels([slabel(eid, friendly)], fontsize=7.5)
        ax.set_ylim(-0.5, 0.5)
        ax.xaxis_date()
        ax.set_xlim(mdates.date2num(x_start.to_pydatetime()),
                    mdates.date2num(x_end.to_pydatetime()))
        ax.tick_params(left=False)
        ax.spines[["top", "right", "left"]].set_visible(False)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M"))
    plt.setp(axes[-1].xaxis.get_majorticklabels(), fontsize=8)
    patches = [mpatches.Patch(color="#22c55e", label="Detected / On"),
               mpatches.Patch(color="#e5e7eb", label="Clear / Off")]
    fig.legend(handles=patches, loc="lower center", ncol=2,
               fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.06))
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


def chart_ticks(df, entity_ids, title, friendly, x_start, x_end, tick_min=12):
    eids = [e for e in entity_ids if e in df["entity_id"].values]
    if not eids:
        return None
    n = len(eids)
    tick_w = tick_min / (24 * 60)
    fig, axes = plt.subplots(n, 1, figsize=(16, max(1.8, n * 0.75)), sharex=True)
    if n == 1:
        axes = [axes]
    fig.suptitle(title, fontsize=12, fontweight="bold")
    for ax, eid in zip(axes, eids):
        edf   = df[df["entity_id"] == eid].sort_values("changed_at")
        ons   = edf[edf["state"].str.lower().isin(ON_STATES)]
        count = len(ons)
        ax.set_facecolor("#f9fafb")
        ax.set_xlim(mdates.date2num(x_start.to_pydatetime()),
                    mdates.date2num(x_end.to_pydatetime()))
        for _, row in ons.iterrows():
            t = row["changed_at"]
            if x_start <= t <= x_end:
                ax.barh(0, tick_w, left=mdates.date2num(t.to_pydatetime()),
                        height=0.6, color="#6366f1", edgecolor="none")
        ax.set_yticks([0])
        ax.set_yticklabels([slabel(eid, friendly)], fontsize=7.5)
        ax.set_ylim(-0.5, 0.5)
        ax.xaxis_date()
        ax.tick_params(left=False)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.text(0.997, 0.5, f"{count} events", transform=ax.transAxes,
                ha="right", va="center", fontsize=7, color="#9ca3af")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M"))
    plt.setp(axes[-1].xaxis.get_majorticklabels(), fontsize=8)
    plt.tight_layout()
    return fig


def chart_lines(df, entity_ids, title, friendly, units, x_start, x_end):
    eids = [e for e in entity_ids if e in df["entity_id"].values]
    if not eids:
        return None
    fig, ax = plt.subplots(figsize=(16, 4))
    any_data = False
    for i, eid in enumerate(eids):
        sub = df[df["entity_id"] == eid].copy()
        sub["v"] = pd.to_numeric(sub["state"], errors="coerce")
        sub = sub.dropna(subset=["v"])
        if sub.empty:
            continue
        any_data = True
        times  = [x_start] + list(sub["changed_at"]) + [x_end]
        values = [sub["v"].iloc[0]] + list(sub["v"]) + [sub["v"].iloc[-1]]
        ax.step(times, values, where="post",
                label=slabel(eid, friendly),
                color=COLORS[i % len(COLORS)], linewidth=1.5)
    if not any_data:
        plt.close(fig)
        return None
    unit_label = next((units.get(e, "") for e in eids if units.get(e)), "")
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylabel(unit_label, fontsize=9)
    ax.set_xlim(x_start, x_end)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M"))
    plt.setp(ax.xaxis.get_majorticklabels(), fontsize=8)
    ax.legend(fontsize=8, ncol=min(4, len(eids)), loc="upper left", framealpha=0.9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    plt.tight_layout()
    return fig


# ── HTML rendering ────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px; color: #111827;
  max-width: 1300px; margin: 0 auto; padding: 28px 36px;
  background: #fff;
}
h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.meta { color: #6b7280; font-size: 12px; margin-bottom: 28px; }
h2 { font-size: 15px; font-weight: 600; color: #374151;
     margin: 36px 0 12px; padding-bottom: 6px;
     border-bottom: 2px solid #e5e7eb; }
h3 { font-size: 13px; font-weight: 600; color: #6b7280;
     margin: 22px 0 8px; }
img { max-width: 100%; height: auto; border-radius: 6px; }
.no-data { color: #9ca3af; font-size: 13px; padding: 8px 0; }
table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 8px; }
thead th { background: #f3f4f6; text-align: left; padding: 7px 10px;
           font-weight: 600; color: #374151; border-bottom: 1px solid #d1d5db; }
tbody tr:nth-child(even) { background: #f9fafb; }
tbody td { padding: 5px 10px; border-bottom: 1px solid #e5e7eb; }
.b { display:inline-block; padding:2px 7px; border-radius:999px;
     font-size:11px; font-weight:600; }
.on  { background:#dcfce7; color:#166534; }
.off { background:#f3f4f6; color:#6b7280; }
.unk { background:#fef9c3; color:#854d0e; }
@media print {
  body { padding: 12px; }
  img  { break-inside: avoid; page-break-inside: avoid; }
}
"""


def _badge(state: str) -> str:
    s = state.lower()
    cls = "on" if s in ON_STATES else ("unk" if s in SKIP_STATES else "off")
    return f'<span class="b {cls}">{state}</span>'


def render_html(sections, summary_rows, domain_counts, now, hours, win_start):
    ts  = now.strftime("%Y-%m-%d %H:%M UTC")
    wss = win_start.strftime("%Y-%m-%d %H:%M UTC")

    # Domain breakdown pill list
    domain_pills = " · ".join(
        f"<span style='color:#374151'><b>{d}</b> {c}</span>"
        for d, c in sorted(domain_counts.items())
    )

    rows_html = "".join(
        f"<tr>"
        f"<td style='color:#9ca3af;font-size:11px'>{r['domain']}</td>"
        f"<td>{r['area']}</td>"
        f"<td>{r['friendly']}</td>"
        f"<td style='color:#9ca3af;font-size:11px'>{r['entity_id']}</td>"
        f"<td>{_badge(r['state'])}</td>"
        f"<td style='color:#6b7280'>{r['last_changed']}</td>"
        f"</tr>"
        for r in sorted(summary_rows, key=lambda x: (x["domain"], x["area"], x["friendly"]))
    )

    summary = f"""
<h2>Entity Summary &nbsp;<span style='font-weight:400;color:#9ca3af;font-size:13px'>
  {len(summary_rows)} entities · current state</span></h2>
<p class="meta" style="margin-bottom:12px">{domain_pills}</p>
<table>
  <thead>
    <tr><th>Domain</th><th>Area</th><th>Friendly Name</th><th>Entity ID</th>
        <th>State</th><th>Last Changed</th></tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>"""

    charts = ""
    for heading, b64 in sections:
        if b64:
            charts += f'<h2>{heading}</h2><img src="data:image/png;base64,{b64}" alt="{heading}">\n'
        else:
            charts += f'<h2>{heading}</h2><p class="no-data">No data in this window.</p>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DARI Sensor Report — {now.strftime('%Y-%m-%d')}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>DARI Sensor Report</h1>
<p class="meta">Window: {wss} → {ts} &nbsp;({hours}h) &nbsp;·&nbsp; Generated: {ts}</p>
{summary}
{charts}
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()
    hours = args.hours

    now   = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    x_end   = pd.Timestamp(now)
    x_start = pd.Timestamp(start)

    # ── 1. Discover ALL entities ──────────────────────────────────────────────
    print("[1/5] Fetching all HA states …")
    all_states_list = get_all_states()
    state_map = {s["entity_id"]: s for s in all_states_list}

    friendly: dict[str, str] = {}
    units:    dict[str, str] = {}
    entity_area: dict[str, str] = {}

    # Pull area from attributes if HA populates it, otherwise blank
    for s in all_states_list:
        eid   = s["entity_id"]
        attrs = s.get("attributes", {})
        friendly[eid] = attrs.get("friendly_name",
                                   eid.split(".")[-1].replace("_", " ").title())
        units[eid]    = attrs.get("unit_of_measurement", "")
        entity_area[eid] = attrs.get("friendly_name", "")  # placeholder; overwrite below

    # Use entity registry for proper area assignments
    try:
        from dari.rule_engine.ha_client import _ws_call, get_device_registry, get_areas
        entities_reg = _ws_call({"type": "config/entity_registry/list"})
        devices_reg  = get_device_registry()
        areas_reg    = get_areas()
        area_by_id   = {a["area_id"]: a["name"] for a in areas_reg}
        device_area_map = {d["id"]: d.get("area_id") for d in devices_reg}
        for ent in entities_reg:
            eid    = ent.get("entity_id", "")
            dev_id = ent.get("device_id", "")
            aid    = ent.get("area_id") or device_area_map.get(dev_id, "")
            entity_area[eid] = area_by_id.get(aid, "—") if aid else "—"
    except Exception as e:
        print(f"     [warn] area registry unavailable: {e}")
        for eid in state_map:
            entity_area.setdefault(eid, "—")

    # ── 2. Classify every entity ───────────────────────────────────────────────
    binary_groups: dict[str, list[str]] = {}   # category → [entity_ids]
    numeric_groups: dict[str, list[str]] = {}  # group label → [entity_ids]
    diag_ids: list[str] = []

    chart_ids: list[str] = []  # will be fetched from HA history

    for s in all_states_list:
        eid    = s["entity_id"]
        domain = eid.split(".")[0]
        state  = s.get("state", "")

        if domain == "binary_sensor":
            cat = classify_binary(eid)
            binary_groups.setdefault(cat, []).append(eid)
            chart_ids.append(eid)

        elif domain == "sensor":
            if is_diag(eid):
                diag_ids.append(eid)
                continue
            try:
                float(state)  # only numeric sensors get charted
                grp = classify_numeric(eid)
                numeric_groups.setdefault(grp, []).append(eid)
                chart_ids.append(eid)
            except (ValueError, TypeError):
                pass  # text-state sensor — summary table only

    chart_ids = list(dict.fromkeys(chart_ids))

    # Count by category for console output
    print(f"     binary_sensor groups:")
    for cat, eids in sorted(binary_groups.items()):
        print(f"       {cat}: {len(eids)}")
    print(f"     numeric sensor groups:")
    for grp, eids in sorted(numeric_groups.items()):
        print(f"       {grp}: {len(eids)}")
    print(f"     device diagnostics (charted separately): {len(diag_ids)}")
    print(f"     Total entities in HA: {len(all_states_list)}")
    print(f"     Entities to fetch history for: {len(chart_ids)}")

    # ── 3. Fetch history ──────────────────────────────────────────────────────
    print(f"[2/5] Fetching {hours}h history for {len(chart_ids)} entities …")
    history = get_history(chart_ids, start, now)
    df      = history_to_df(history)
    print(f"     {len(df)} records across {df['entity_id'].nunique()} entities")

    # ── 4. Build summary table ────────────────────────────────────────────────
    domain_counts: dict[str, int] = {}
    summary_rows: list[dict] = []

    for s in all_states_list:
        eid    = s["entity_id"]
        domain = eid.split(".")[0]
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        lc = s.get("last_changed", "")
        try:
            lc = datetime.fromisoformat(lc.replace("Z", "+00:00")).strftime("%m/%d %H:%M")
        except Exception:
            pass
        summary_rows.append({
            "entity_id":    eid,
            "domain":       domain,
            "friendly":     friendly.get(eid, eid),
            "area":         entity_area.get(eid, "—"),
            "state":        s.get("state", "—"),
            "last_changed": lc,
        })

    # ── 5. Build charts ───────────────────────────────────────────────────────
    print("[3/5] Rendering charts …")
    sections: list[tuple[str, str | None]] = []

    def add(title, fig):
        sections.append((title, fig_to_b64(fig) if fig else None))

    # Binary sensor charts — in the order defined by BINARY_RULES, then Other
    ordered_binary = [label for label, _ in BINARY_RULES] + ["Other Binary"]
    for cat in ordered_binary:
        eids = binary_groups.get(cat, [])
        if not eids:
            continue
        # Presence → Gantt bars; Motion/AI/Vibration → event ticks
        if cat in ("Motion & AI", "Vibration", "Other Binary"):
            add(cat, chart_ticks(df, eids, f"{cat} ({hours}h)", friendly, x_start, x_end))
        else:
            eids_sorted = sorted(eids, key=lambda e: (entity_area.get(e, ""), e))
            add(cat, chart_gantt(df, eids_sorted, f"{cat} ({hours}h)", friendly, x_start, x_end))

    # Numeric charts — in defined order, then Other Numeric, then Diagnostics
    ordered_numeric = [label for label, _, _ in NUMERIC_GROUP_RULES] + ["Other Numeric"]
    for grp in ordered_numeric:
        eids = numeric_groups.get(grp, [])
        if not eids:
            continue
        unit = next((units.get(e, "") for e in eids if units.get(e)), "")
        title = f"{grp}  ({unit})" if unit else grp
        add(title, chart_lines(df, eids, title, friendly, units, x_start, x_end))

    # Device diagnostics — battery, RSSI, etc. in one combined chart
    if diag_ids:
        # Fetch history for diag sensors too
        diag_hist = get_history(diag_ids, start, now)
        df_diag   = history_to_df(diag_hist)
        df_all    = pd.concat([df, df_diag], ignore_index=True) if not df_diag.empty else df
        add("Device Diagnostics (battery · RSSI · signal)",
            chart_lines(df_all, diag_ids,
                        f"Device Diagnostics ({hours}h)", friendly, units, x_start, x_end))

    # ── 6. Render HTML ────────────────────────────────────────────────────────
    print("[4/5] Building HTML …")
    html = render_html(sections, summary_rows, domain_counts, now, hours, start)

    out_name = f"sensor_report_{now.strftime('%Y%m%d_%H%M')}.html"
    reports_dir = REPORTS_DIR
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / out_name
    out_path.write_text(html, encoding="utf-8")
    size_kb = out_path.stat().st_size // 1024

    print(f"[5/5] Saved  →  {out_path}  ({size_kb} KB)")
    webbrowser.open(out_path.as_uri())
    print("      Opened in default browser.")


if __name__ == "__main__":
    main()
