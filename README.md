# DARI Smart Homecare Digital Twin

Smart-home monitoring for people living with dementia: a Home Assistant sensor network
(presence radar, door contacts, smart plugs, air-quality sensors, a smartwatch) feeds an
activity engine and an alert-rule engine, and a caregiver app shows what is happening at
home and pushes alerts to the caregiver's phone.

---

## Architecture

```
Home Assistant (live sensors, <HA-IP>:8123)
        │
        ├── src/dari/rule_engine/      → safety / environment / health rules → alerts → data/alerts.db
        │                                 (+ push to the caregiver's phone via HA notify)
        ├── src/dari/activity_engine/  → infers what patient is doing → activity_log
        │
        └── src/dari/api_server/ (FastAPI :8000) ── single REST contract ──┬── apps/caregiver_web/ (React)
                                                                          └── Android (Capacitor shell)
```

- **The API is the single source of truth.** All inference happens server-side; clients are display-only.
- **No ML required** — activity labels use deterministic heuristic rules. `src/dari/activity_engine/classifier.py` has a pluggable ML hook for when labelled activity data exists.
- **Caregiver app + Admin** are the same Vite build. `?mode=admin` in the URL switches to the admin panel.

---

## Fresh Install (new machine)

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda | any | Python environment manager |
| Python | 3.11 | installed inside conda env (see below) |
| [Node.js](https://nodejs.org/) | 18 LTS or 20 LTS | caregiver web app |
| [Tailscale](https://tailscale.com/) | any | remote access to the HA hub (optional for local-only dev) |

### 1 — Clone the repo

```bash
git clone <repo-url> dari
cd dari
```

### 2 — Create the conda environment

```bash
conda create -n LLMs python=3.11 -y
conda activate LLMs
pip install -e .           # installs the dari package in editable mode
pip install -r requirements.txt
```

> All subsequent `conda run -n LLMs` commands target this environment.  
> Never use a global `pip install` — it will not be found by the engines.

### 3 — Configure environment variables

Copy the template and fill in your HA credentials:

```bash
# repo root — used by Python services
cp .env.example .env
```

Edit `.env`:

```
HA_URL=http://<HA-IP>:8123         # your Home Assistant IP (local or Tailscale)
HA_TOKEN=<long-lived access token> # HA → Profile → Long-Lived Access Tokens → Create Token
```

For the caregiver web app production build:

```bash
# apps/caregiver_web/ — used by npm run build
echo "VITE_API_BASE=http://127.0.0.1:8000" > apps/caregiver_web/.env.production.local
```

### 4 — Install web app dependencies

```bash
cd apps/caregiver_web
npm install
cd ../..
```

---

## Quick Start

All Python runs in the **`LLMs`** conda environment.

### 0. Install the package (once)

The engines, API and notebooks all import `dari.*`. Install it in editable mode so those
imports resolve from anywhere without `sys.path` juggling:

```bash
conda run -n LLMs pip install -e .
```

### 1. Backend API (required by all clients)

```bash
conda run -n LLMs python -m uvicorn dari.api_server.main:app --host 0.0.0.0 --port 8000 --reload
```

Docs at `http://127.0.0.1:8000/docs`

### 2. Activity engine (logs the patient timeline)

```bash
conda run -n LLMs python -m dari.activity_engine.engine --profile config/profiles/patient_001.yaml
```

Run this alongside the rule engine. It subscribes to HA WebSocket, infers activities, and writes to `alerts.db`.

### 3. Rule engine (fires threshold alerts)

```bash
conda run -n LLMs python -m dari.rule_engine.engine --profile config/profiles/patient_001.yaml
```

### 4. Caregiver web app

```bash
cd apps/caregiver_web
npm install          # first time only
npm run dev          # http://localhost:5173  (proxies /api → :8000)
```

Open `http://localhost:5173` for the caregiver view.  
Open `http://localhost:5173?mode=admin` for the admin panel.

### 5. Admin panel (rules + watch config)

Accessible from the caregiver app via the **gear icon** (top-left), or directly at `?mode=admin`.  
Requires the API (step 1) to be running — loads rules and watch config live from HA.

### 6. Streamlit rule builder (legacy admin tool)

```bash
conda run -n LLMs streamlit run src/dari/admin_streamlit/app.py
# → http://localhost:8501
```

The React admin panel (step 5) is the preferred interface. The Streamlit tool is kept as a fallback.

### Demo data (optional)

Seed a realistic timeline for UI demos without a live HA connection:

```bash
conda run -n LLMs python scripts/seed_demo.py          # add demo rows
conda run -n LLMs python scripts/seed_demo.py --clear  # remove demo rows
```

---

## Project Structure

```
DARI/
│
├── src/dari/                       ← ALL Python source lives here (one installable package)
│   ├── paths.py                    Canonical locations (repo root, DB, profiles, reports)
│   ├── env_metrics.py              Which IAQ quantity a sensor measures (temp/RH/CO₂/PM2.5/CO/VOC)
│   │
│   ├── api_server/                 (was api/)
│   │   └── main.py                 FastAPI app — all REST endpoints
│   │
│   ├── rule_engine/                Threshold/event rules → alerts
│   │   ├── models.py               Profile, Rule, Alert dataclasses
│   │   ├── ha_client.py            HA REST + WebSocket client
│   │   ├── evaluators.py           Rule evaluators (9 trigger types — see "Alert Rules")
│   │   ├── alert_store.py          SQLite alerts table
│   │   ├── notifier.py             Push alerts to phones via HA notify services
│   │   ├── care_mode.py            Home alone / with others — which rules run in each
│   │   └── engine.py               Main loop — WS listener + 60s poller
│   │
│   ├── activity_engine/            "What is the patient doing right now?"
│   │   ├── models.py               ActivityEvent, CurrentStatus, WorldState, ACTIVITY_CATALOG
│   │   ├── zones.py                Token-based semantic zone classification (bed ≠ bedroom)
│   │   ├── state.py                HA state → WorldState converter
│   │   ├── detectors.py            Heuristic activity inference (priority chain)
│   │   ├── classifier.py           Pluggable ML hook (default: HeuristicClassifier)
│   │   ├── activity_store.py       SQLite activity_log table
│   │   ├── service.py              Cached sensor index + get_status() for API
│   │   └── engine.py               Main loop — WS listener + 60s poller, 25s debounce
│   │
│   └── admin_streamlit/            (was rule_builder/) legacy Streamlit admin, 6 pages
│
├── apps/                           ← ALL client applications
│   └── caregiver_web/              (was caregiver_app/) Vite + React + TS + Tailwind
│       ├── src/lib/types.ts        Shared API contract
│       ├── src/lib/api.ts          REST client — the ONLY backend boundary
│       ├── src/pages/              Summary · Alerts · Room · Activity · Health · Environment
│       ├── src/pages/admin/        Rules · WatchConfig · SensorBrowser · SensorHistory
│       ├── src/components/         TopBar · BottomNav · FloorMap · StatusHero · Timeline
│       └── android/                Capacitor native shell → APK/AAB
│
├── notebooks/                      ← Analysis notebooks, nothing importable (not published)
│
├── config/                         ← Inputs you edit, not code
│   ├── profiles/patient_001.yaml   Example profile — 17 alert rules, watch entity IDs, notify, appliances
│   ├── profiles/suggested_rules.yaml  Rule templates (not loaded by code)
│   ├── automations/                HA automations (watch sensor refresh)
│   └── rulebook/rulebook.md        Every rule with its rationale, thresholds and sources
│
├── data/
│   └── alerts.db                   SQLite — alerts table + activity_log table (gitignored)
│
├── docs/                           ← Project reports and presentations (not published)
│
├── scripts/                        Operational one-offs — see "Scripts" below
│
├── pyproject.toml                  Package metadata — `pip install -e .`
└── launch.ps1                      Start/stop API + engines + web app together
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/current_status` | Live location + inferred activity + risk level |
| GET | `/api/patient_state` | Current zone, active alerts, presence summary |
| GET | `/api/activity_log` | Activity timeline (filters: category, since, until, limit) |
| GET | `/api/activity_summary` | Aggregated counts by category/day/hour for charts |
| GET | `/api/activity_patterns` | Daily-routine patterns: wake/bed/meal times, night bathroom trips, outings |
| GET | `/api/alerts` | Alert list (filters: category, severity, acknowledged) |
| POST | `/api/alerts/{id}/acknowledge` | Acknowledge an alert |
| GET | `/api/environment` | Temperature / humidity / CO₂ / PM2.5 / CO / VOC by room, each with an `ok`/`warn`/`alert` status from the profile's environment rules |
| GET | `/api/health` | Pixel Watch metrics via HA Companion App |
| GET | `/api/profiles` | List patient profiles |
| GET | `/api/ha_entities` | All HA entities (admin — entity pickers) |
| GET | `/api/watch_config` | Read watch entity mapping |
| PUT | `/api/watch_config` | Update watch entity mapping |
| GET | `/api/rules` | List alert rules |
| POST | `/api/rules` | Create rule |
| PUT | `/api/rules/{id}` | Update rule |
| PATCH | `/api/rules/{id}/toggle` | Toggle rule enabled/disabled |
| DELETE | `/api/rules/{id}` | Delete rule |
| GET | `/api/care_mode` | Home alone / with others, its end time, and which rules it pauses |
| GET | `/api/care_mode/preview?mode=` | What switching to a mode would pause, without switching |
| PUT | `/api/care_mode` | Switch mode (`{mode, duration_minutes}`); logged to the timeline |
| GET | `/api/ha_areas` | HA areas with their sensors (admin) |
| GET | `/api/sensor_history` | HA recorder history for chosen entities (admin) |
| GET | `/api/cameras` · `/api/camera_proxy/{id}` · `/api/camera_stream/{id}` | Camera list, snapshot and stream proxy |

Full interactive docs: `http://127.0.0.1:8000/docs`

---

## Patient Profile (`config/profiles/patient_001.yaml`)

```
profile_id:     patient-001
patient_name:   Patient A
caregiver_name: Caregiver A
rules:          17 alert rules — 6 safety/activity, 9 environment, 2 heart rate
notify:         HA notify services + minimum severity for phone pushes (off by default)
watch:          Smartwatch entity IDs (heart rate, steps, battery, on-body, etc.)
appliances:     optional per-plug overrides (name, kind, area, wattages)
```

Editing rules in the admin panel saves the profile through the API, which rewrites the YAML
and drops its comments. Restart the rule engine after changing rules; it reads the profile
at startup.

Entity IDs in the example profile are placeholders — replace them with your own from HA
(Developer Tools → States, or the admin panel's Sensor Browser). To add a second patient,
copy `patient_001.yaml`, change `profile_id` / names, and update the rules.

---

---

## Supported Sensors

Anything Home Assistant exposes works; sensors are classified by entity id, name and
device class rather than hard-coded ids.

| Sensor type | Used for |
|---|---|
| mmWave presence radar (e.g. Aqara FP2), with sub-zones | Room presence + sub-zones (bed, sofa, desk, shower, toilet, dining); fall entity if the device exposes one |
| Door / window contacts | Front door (exits, away detection), fridge, cabinet |
| Temperature, humidity, CO₂, PM2.5, CO, VOC (e.g. Apollo AIR-1, Aqara weather) | Environment page + environment alert rules |
| Smart plugs with power metering | Appliance on/off events and "Cooking" |
| Vibration sensor on the toilet flush | "Toilet flushed" events |
| Smartwatch + phone via the HA Companion App | Heart rate, steps, on-body, activity state, sleep confidence |

The authoritative list for a home is whatever `build_sensor_index()` resolves at runtime.

---

## Alert Rules

The rule engine (`src/dari/rule_engine/`) evaluates the profile's rules on every HA state
change (fall, door, night wandering) and every 60 s (everything time-based). A fired rule is
written to `alerts.db`, shown in the app, and pushed to the caregiver's phone if its severity
reaches `notify.min_severity`. Each rule has a cooldown so a persistent condition doesn't
repeat. Rationale, sources and test procedures for every rule are in
[`config/rulebook/rulebook.md`](config/rulebook/rulebook.md).

| Trigger type | Fires when | Used by |
|---|---|---|
| `fall` | A fall entity reports a fall. Binds to every entity HA buckets as "fall", or to one pinned `entity_id`; silent when there is none | rule-001 |
| `door_opened` | A door stays open past `no_return_minutes` inside the time window | rule-002 |
| `room_inactivity` | A room has no presence for `duration_minutes` | rule-003 |
| `long_stay` | Continuous presence in one room past `duration_minutes` | rule-004 |
| `night_wandering` | Any presence inside the night window | rule-005 |
| `global_inactivity` | No presence change anywhere for `duration_minutes` | rule-006 |
| `sensor_threshold` | One sensor (`entity_id`) past a value, optionally for `duration_minutes` — e.g. an appliance left on | template `tmpl-e05` |
| `env_threshold` | Any sensor measuring `metric` (temperature, humidity, co2, pm25, co, voc), optionally in one room, past a value for `duration_minutes`. °F readings are converted to the rule's `unit` | env-* (9 rules) |
| `vital_threshold` | A `profile.watch` signal (`metric: heart_rate`) past a value for `duration_minutes`, only while the reading is fresh, the watch is on the wrist and, for a high reading, the person isn't moving | vital-hr-high, vital-hr-low |

**Environment thresholds** (sources in the rulebook): heat > 31 °C and cold ≤ 18 °C (HIGH),
comfort > 26 °C / < 20 °C (LOW), RH > 60 %, CO₂ > 1000 ppm, PM2.5 > 35 µg/m³, VOC index ≥ 250
(MEDIUM), CO > 70 ppm (CRITICAL). A reading has to hold for 5 min (15 for comfort, 1 for CO)
before it alerts.

**Health thresholds** follow the Minder dementia home-monitoring cohort
([JMIR Aging 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10037178/), Table S2). The Pixel
Watch only exposes heart rate to HA, so SpO₂, temperature, blood pressure and weight criteria
can't be implemented yet. Heart rate > 99 or < 55 bpm for 10 min; the low-rate rule runs
08:00–21:00 only.

### Care mode — home alone vs. with others

The presence sensors can't tell people apart. With a caregiver or visitor in the house, the
rules that treat any movement as the patient's would fire on someone else, so the caregiver
sets the mode on the Summary screen:

| Mode | Rules that run |
|---|---|
| **Home alone** (default) | All of them |
| **With others** | All except the presence-attributed ones — room/global inactivity, night wandering, long stay. Fall, door, environment and heart-rate rules keep running (the watch is on the patient) |

A rule can override the default with `modes: [alone, with_others]` in the profile, or the
"Active when" checkboxes in the admin panel. Because forgetting to switch back would leave
alerts paused while the person is alone, "with others" asks for a duration (1–8 h, default
2 h; "until I switch back" is allowed with a warning) and then reverts to home alone on its
own; an amber banner with a one-tap "Home alone" button stays on every screen meanwhile.
Anything unreadable counts as home alone. The mode lives in `alerts.db` (shared by the API
and both engines; the rule engine rereads it every 15 s), and every change, including the
timer running out, is written to the activity timeline.

Operators are `gt`, `gte`, `lt`, `lte`. Message templates take `{{patient_name}}`, `{{zone}}`,
`{{time}}`, `{{duration}}`, and for threshold rules `{{value}}` and `{{sensor}}`.

Checking and testing rules:

```bash
python scripts/test_alert_rules.py                     # offline: every trigger on synthetic states
python scripts/check_alert_readiness.py                # live: what each rule is bound to right now
python scripts/check_alert_readiness.py --watch 10 --csv data/env_test.csv   # live readings for test scenarios
```

---

## Activity Inference — How It Works

### Capture pipeline

```
Home Assistant (raw entity states)
        │
        ▼
build_sensor_index()   ← runs once at startup (+ refreshed periodically)
  reads rule_engine.ha_client.get_sensors_by_area() (HA area/device/entity registry)
  classifies every relevant entity by keyword into:
    presence_by_area · zone_of (bed/sofa/desk/shower/toilet) · doors (kind: front/fridge/
    cabinet/window) · plugs + plug_area · falls · watch (profile.watch entity map)
        │
        ▼
build_world_state()    ← runs on every tick (WS state_changed event, or 60s poll)
  turns raw "on"/"off"/numeric HA states + the static index into a WorldState:
    area_occupied{area:bool} (ALL known areas, not just occupied ones) · zone_occupied
    {bed/sofa/desk/shower/toilet:bool} · door_open · plug_power_by_area · fall_active ·
    current_area (most-recently-active occupied area) · any_presence · last_movement ·
    heart_rate / sleep_confidence / steps_delta / on_body / watch_stale (wearable, gated
    by a 30-min freshness check — see Wearable corroboration below)
        │
        ▼
resolve_activity()     ← priority chain, ONE label for "what's happening right now"
  away? → no presence? → shower zone? → bathroom (toilet vs general)? →
  kitchen (cooking via plug_power_by_area / meal-time window)? →
  bedroom (sleeping vs in_bed, corroborated by sleep_confidence)? →
  living room (sofa vs desk)? → in_room fallback → active/inactive
        │                                    ┌── detect_discrete() in parallel:
        ▼                                    │   front_door_opened · fridge_left_open ·
25s dwell filter (engine.py MIN_DWELL_SEC)    │   fall_detected — logged immediately,
  only logs a STATE CHANGE once the new       │   each with its own cooldown
  activity has held for ≥25s (debounces       │
  FP2 flicker)                                ▼
        │                              activity_log (SQLite, alerts.db)
        ▼                                    │
activity_log (SQLite, alerts.db)              │
        └──────────────┬───────────────────┘
                        ▼
              api/main.py (FastAPI) ──── /api/current_status, /api/activity_log ────
                        ▼
              apps/caregiver_web (Summary / Room / Activity / Health screens)
```

`/api/current_status` (polled every 5s by the app) does **not** read the persistent engine's
in-memory state — it independently rebuilds a fresh `WorldState` from live HA on every
request (`activity_engine/service.py::get_status`), sharing only `alerts.db` with the
long-running `activity_engine.engine` process. Both paths use the same `resolve_activity()`
logic, so they agree, but the API path has no dwell filter — it reflects the instant a
sensor changes, while `activity_log` reflects the debounced, committed history.

### Sensor → Activity mapping

| What we want to know | HA signal used | Code |
|---|---|---|
| Which room | `binary_sensor` entities classified `presence`/`fp2`/`occupancy` in each HA area, `PRESENCE_HOLD_SEC=90s` hold to survive real FP2 dropout gaps | `state.py::build_world_state` |
| Sleeping vs. resting in bed | `bed` sub-zone occupied + time-of-night (21:00–08:00), confidence boosted/dampened by wearable `sleep_confidence` if fresh | `detectors.py::resolve_activity` |
| In the bathroom / using the toilet | `Bedroom Bathroom` area occupied; `toilet` sub-zone for the specific "using_toilet" label | `detectors.py`, `zones.py::classify_zone` |
| In the shower | `shower` sub-zone occupied (any area — takes priority over bathroom/toilet) | `detectors.py` |
| Sitting vs. at the desk | `sofa` sub-zone → `sitting`; `desk` sub-zone → `at_desk`, both within `living` role areas | `detectors.py`, `zones.py::area_role` |
| Cooking / meals | Kitchen-role area occupied + a smart plug in that area ≥150W (`COOKING_WATTS`) **or** any plug whose appliance kind is a cooking one (microwave, kettle, stove, …) switched on; else a meal-time window (breakfast 6–10, lunch 11–14, dinner 17–20) | `detectors.py`, `state.py` |
| Appliance on / off (event) | A plug's power rises to ≥25 W → "Appliance on"; stays ≤8 W for 30 s → "Appliance off" with run time. Name, kind and area from HA, overridable per plug under `appliances:` in the profile | `state.py::build_world_state`, `detectors.py::detect_discrete` |
| Away from home | Front door (`door_kind()=="front"`) opened + no presence anywhere for ≥3 min (`AWAY_GRACE_MIN`); corroborated by wearable `on_body`+`heart_rate` if fresh | `detectors.py::refine_home` |
| Inactive / no movement | No presence anywhere for ≥30 min (`INACTIVITY_MIN`) while still "home"; corroborated by wearable `steps_delta` if fresh (steps climbing but no room sensor firing → lower confidence, likely a coverage blind spot) | `detectors.py` |
| Front door opened (event) | Door entity where `door_kind()` matches "front"/"entry"/"entrance"/"main" | `detectors.py::detect_discrete` |
| Fridge left open (event) | Door entity where `door_kind()` matches "fridge"/"refrigerator"/"refriger" (abbreviated real-world naming), open ≥2 min (`FRIDGE_OPEN_MIN`) | `detectors.py::detect_discrete` |
| Fall detected (event) | A binary_sensor entity whose **own entity_id/friendly_name** (not just its device's display name) contains "fall"; the fall *alert* rule can also be pinned to any entity | `rule_engine/ha_client.py::get_sensors_by_area`, `detectors.py::detect_discrete` |

Zone/room classification is **token-based**, not substring-based, to avoid false matches —
`"bed"` and `"bedroom"` are different tokens, so `binary_sensor.bedroom_fp2` resolves to the
bedroom *area*, not the `bed` sub-zone (`zones.py::classify_zone`).

### Tunable thresholds

| Constant | Value | Where | Notes |
|---|---|---|---|
| `PRESENCE_HOLD_SEC` | 90s | `state.py` | Raised from 10s after measuring real FP2 off-gaps on a live afternoon (p50=16s, p90=82s, p99=116s) — the old value cleared "occupied" through most real flicker. |
| `MIN_DWELL_SEC` | 25s | `engine.py` | A resolved activity must persist this long before being logged, on top of the presence hold above. |
| `INACTIVITY_MIN` | 30 min | `detectors.py` | |
| `AWAY_GRACE_MIN` | 3 min | `detectors.py` | |
| `COOKING_WATTS` | 150W | `detectors.py` | Not yet calibrated against a real cooking appliance. |
| `APPLIANCE_ON_WATTS` / `APPLIANCE_OFF_WATTS` | 25 W / 8 W | `state.py` | Hysteresis for appliance on/off. The gap keeps a part-power microwave (magnetron cycling, fan still running) from flapping. Per plug via `appliances:`. |
| `APPLIANCE_OFF_HOLD_SEC` | 30 s | `state.py` | Power must stay ≤ off watts this long before "Appliance off". |
| `FRIDGE_OPEN_MIN` | 2 min | `detectors.py` | |
| `WATCH_STALE_MIN` | 5 min | `state.py` | Wearable readings older than this are ignored entirely. Set to match the `command_update_sensors` push cadence (`config/automations/watch_sensor_refresh.yaml`). |
| Discrete cooldowns | `front_door_opened` 120s · `fall_detected` 60s · `fridge_left_open` 600s · `appliance_on`/`off` 30s per plug | `engine.py` | Minimum gap between repeated momentary-event log entries. |

### Wearable corroboration

`profile.watch` (Pixel Watch/phone entity IDs) feeds `heart_rate`, `sleep_confidence`,
`steps_delta`, `on_body`, `activity_state`, `phone_activity` into `WorldState` — but only
if the reading is fresher than `WATCH_STALE_MIN`. These signals **corroborate, never
replace** the room-sensor heuristics: they shift `ActivityCandidate.confidence` up or down
(e.g. `sleeping` confidence 0.8→0.9 when `sleep_confidence≥50`, →0.65 when it disputes),
they never change *which* activity is chosen. This keeps the system explainable — every
decision still traces to a specific rule — while making room for wearable data once
labelled ADL data exists to train a real classifier
(`src/dari/activity_engine/classifier.py`).

### Known limitations

- **One person at a time.** The engine infers ONE `current_zone`/`current_activity` for the
  whole house; presence sensors can't tell people apart. Use the care mode ("with others")
  when someone else is home. The wearable is the only signal tied to one individual.
- **Overlapping sensor coverage.** A radar whose field of view reaches into the next room
  can keep that room looking "most recently entered"; aim sensors so rooms don't overlap.
- **Fall detection needs a fall entity in HA.** Many radar units detect falls in their own
  app but don't expose it to HA; fall rules stay silent until an entity reports falls.
- **Wear OS sensors update on the watch's own schedule.** `command_update_sensors` refreshes
  phone sensors but not watch sensors, so `watch_stale` gates heart-rate/on-body
  corroboration whenever the watch hasn't reported for `WATCH_STALE_MIN`.

### Field-testing accuracy

`scripts/field_test_logger.py` polls `/api/current_status` on an interval and writes a CSV
of `(wall_clock, zone, activity, presence_by_zone)` — walk a known route (sit on the sofa,
move to the desk, go to bed, shower, leave via the front door, …), note your actual
start times, and diff them against the CSV to check real predictions against ground truth.
Expect the debounce delays above (up to ~90s+25s) between an action and its logged change.

---

## Constraints

| Constraint | Detail |
|------------|--------|
| Network | Sensors must share a subnet with the HA hub. Enterprise Wi-Fi often blocks this — use a local router during setup. |
| Camera | Post-event caregiver review only. No face recognition or model training. |
| Alerts | Rule-based / threshold only. No ML/prediction for alert triggers. |
| Cellular | Alerts must work without full internet — HA + rule engine run locally. |

---

## Android app (Capacitor)

The Android app **is** the web app: Capacitor wraps the same `dist/` build in a native
shell, so there is one codebase and the two clients cannot drift. `apps/caregiver_web/android/`
is a real Gradle project that produces an installable APK/AAB.

### Prerequisites (one-time, command line — no Android Studio)

Capacitor 8 compiles against **JDK 21** (`android/app/capacitor.build.gradle` pins
`VERSION_21`) and SDK platform 36.

```powershell
winget install Microsoft.OpenJDK.21        # JDK 21
winget install Google.PlatformTools        # adb
# Android SDK command-line tools are not on winget: download commandlinetools-win-*_latest.zip
# from https://developer.android.com/studio#command-line-tools-only and unzip so that
# C:\Android\sdk\cmdline-tools\latest\bin\sdkmanager.bat exists, then:
sdkmanager --licenses
sdkmanager "platforms;android-36" "build-tools;36.0.0"
```

Set user env vars `JAVA_HOME` (the OpenJDK folder) and `ANDROID_HOME=C:\Android\sdk`, and
put `%ANDROID_HOME%\platform-tools` and `%ANDROID_HOME%\cmdline-tools\latest\bin` on PATH.
Alternatively write `apps/caregiver_web/android/local.properties` (gitignored) with
`sdk.dir=C:\\Android\\sdk`.

### Build and install

```powershell
.\scripts\build_android.ps1            # npm build → cap sync → gradlew assembleDebug
.\scripts\build_android.ps1 -Install   # ...then adb install -r and launch on the phone
```

(`npm run android:apk` inside `apps/caregiver_web` runs the same script.) The debug APK
lands at `apps/caregiver_web/android/app/build/outputs/apk/debug/app-debug.apk`.
`-Release` builds the release variant, which needs a signing config (none is committed).

**Phone side, once:** Settings → About phone → tap *Build number* 7× → Developer options →
enable *USB debugging*. Install Tailscale from the Play Store and sign in to the same
tailnet as the API host. Then connect `adb` to the phone one of two ways:

- **USB:** plug in, set the USB mode to *File transfer* (Moto defaults to charge-only, and
  Windows then sees no device at all), accept the "Allow USB debugging?" prompt.
- **Wireless over Tailscale** (what we actually use — no cable, works from anywhere):
  Developer options → *Wireless debugging* → on → *Pair device with pairing code*. Use the
  phone's **tailnet IP** (`tailscale status` on the PC) with the ports the phone shows:
  ```powershell
  adb pair    <phone-tailnet-ip>:<pairing-port> <6-digit-code>   # once per PC
  adb connect <phone-tailnet-ip>:<connect-port>                   # connect-port is on the main Wireless debugging screen
  ```
  Pairing persists; the connect port changes each time Wireless debugging is toggled.

`adb devices` must show the phone as `device`, not `unauthorized`. A wireless device is
listed twice (ip:port and an `_adb-tls-connect` mDNS alias); the build script ignores the alias.

### Pointing the app at the API

This is the one thing that always bites. Inside the APK, `127.0.0.1` is *the phone*, not
the machine running the API. Two things have to be true:

1. **The API must bind all interfaces.** `launch.ps1`, and the manual start above, use
   `--host 0.0.0.0`. Bound to `127.0.0.1` the phone gets connection-refused and the app
   silently shows demo data. If the phone still cannot connect, Windows Firewall is the
   usual culprit — allow inbound TCP 8000 (elevated PowerShell):
   `New-NetFirewallRule -DisplayName "DARI API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`
2. **The app must know the address.** It resolves its API base at runtime:
   a URL saved in-app (localStorage) → `VITE_API_BASE` baked in at build time → `""`
   (same-origin / the Vite dev proxy). `build_android.ps1` bakes its `-ApiBase`
   (default: the dev machine's MagicDNS name on the **project tailnet**, the one the HA hub and
   the phones are on — if the PC is also enrolled in a personal tailnet, check `tailscale status`
   shows the project account; `tailscale ip -4` gives the raw IP if DNS misbehaves) so a fresh install
   works on first launch. To change it later, tap the **server icon** in the top bar (shown
   in the native app, and in the web app whenever the API is unreachable), enter the new
   address and test it — no rebuild needed. The phone must be on the tailnet.

Cleartext HTTP is enabled in `capacitor.config.ts` because the API does not terminate
TLS. Revisit that if the API is ever exposed beyond the tailnet.

### Notifications

Alerts reach the caregiver's phone through the **HA Companion App** today — see
"Alert notifications" below. That path needs no APK, no FCM project and no store release,
so it works before and independently of the Android build. Swapping in the app's own FCM
channel later means changing `src/dari/rule_engine/notifier.py` only.

---

## Alert notifications

When a rule fires, the rule engine records the alert **and** can push it to the caregiver's
phone through Home Assistant's `notify` services — i.e. the HA Companion App the phone
already has. No FCM project, no push server, no app release required.

Configured per profile (`config/profiles/patient_001.yaml`):

```yaml
notify:
  enabled: false            # ← off by default, see the warning below
  min_severity: HIGH        # CRITICAL | HIGH | MEDIUM | LOW
  services:
    - notify.mobile_app_caregiver_phone
```

Severity maps to an Android notification channel, so the caregiver can tune each level in
the phone's own settings; CRITICAL is sticky and bypasses Do Not Disturb. Repeats of the
same rule reuse a `tag`, so a re-fire replaces the old notification instead of stacking.
Delivery is best-effort — an unreachable phone never blocks or crashes the engine.

Check the payload without sending anything:

```bash
python scripts/test_notify.py --profile config/profiles/patient_001.yaml
python scripts/test_notify.py --send        # actually deliver a test push
```

The engine also accepts `--dry-run-notify` to log pushes instead of sending them.

> **`enabled` is `false` by default.** Turn it on once the notify service names match
> the caregiver's phone. `eval_fall` stays silent without a real fall entity, so push
> won't send false fall alarms. With `min_severity: HIGH`, the rules that would push are fall, night
> exit, long bathroom stay, indoor heat/cold and carbon monoxide.

---

## Environment Variables

Create `apps/caregiver_web/.env.production.local` (already exists, do not commit):

```
VITE_API_BASE=http://127.0.0.1:8000
```

This is baked into the production build so the static server (port 4173) reaches the API directly.  
In dev mode (`npm run dev`) this file is ignored — Vite's proxy handles `/api` transparently.

Create a `.env` in the repo root for Python services:

```
HA_URL=http://<HA-IP>:8123
HA_TOKEN=<your long-lived access token>
```

---

## Scripts

| Script | What it does |
|---|---|
| `test_alert_rules.py` | Offline checks for every alert trigger and appliance detection (no HA needed) |
| `check_alert_readiness.py` | Live: fall entities, plugs, IAQ sensors and watch readings each rule binds to; `--watch` for test scenarios |
| `test_notify.py` | Preview or send a test push notification |
| `test_health.py` · `check_watch.py` | Pixel Watch data checks |
| `field_test_logger.py` | Poll `/api/current_status` to CSV during a field test |
| `transcribe_audio.py` | Transcribe a field-test voice memo locally (faster-whisper) |
| `measure_latency.py` | Sensor → alert latency probe (profile `latency_probe.yaml`) |
| `sensor_report.py` | HTML sensor coverage report |
| `seed_demo.py` | Seed / clear demo timeline rows |
| `build_android.ps1` | Build (and optionally install) the Android APK |
