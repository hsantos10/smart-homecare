---
title: "DARI Smart Homecare — Alert Rule Book"
subtitle: "Suggested Rules for Caregiver Configuration"
author: "DARI Smart Homecare"
---

# DARI Smart Homecare — Alert Rule Book

**Version 1.1**

---

## What Are Alert Rules?

The Smart Homecare Digital Twin (SHDT) monitors the home continuously using IoT sensors — presence radars, door sensors, and environmental sensors — all connected through a central Home Assistant hub. Raw sensor data alone doesn't tell a caregiver what matters. **Alert rules** translate sensor signals into clinically meaningful notifications.

A rule says: *"When this condition is true for this long during these hours, send this message."* Because every patient's home layout, daily routine, and risk profile is different, rules are **fully configurable per patient**. This document provides a library of **18 suggested rules** organized by category, along with guidance on how to adapt them.

---

## How Rules Work

Each rule has five components:

| Component | Description |
|---|---|
| **Trigger type** | The category of sensor condition (fall, door, inactivity, etc.) |
| **Parameters** | Room, duration, threshold value — specific to the trigger type |
| **Time window** | When the rule is active (all day, night only, morning only, etc.) |
| **Severity** | How urgent the alert is: Critical / High / Medium / Low |
| **Message** | The text shown to the caregiver (supports variables like the patient name and time) |

Rules are evaluated against live sensor data in real time. To prevent repeated notifications, each rule has a **cooldown period** (default: 10 minutes) — once fired, it won't fire again until the cooldown expires.

---

## Trigger Types

The rule builder supports seven trigger types:

| Trigger | What it monitors |
|---|---|
| **Fall Detected** | FP2 ceiling radar fires a fall event |
| **Door Opened** | A door/window sensor opens, with optional no-return timeout |
| **Room Inactivity** | No presence detected in a specific room for N minutes |
| **Global Inactivity** | No movement detected anywhere in the home for N minutes |
| **Night Wandering** | Any movement detected during a specified nighttime window |
| **Long Stay in Room** | Patient present in same room continuously for > N minutes |
| **Sensor Threshold** | A numeric sensor (temperature, humidity, CO₂) crosses a value |
| **Environment Threshold** | Any sensor measuring temperature, humidity, CO₂, PM2.5, CO or VOC stays past a value for N minutes (optionally in one room) |
| **Health Threshold (watch)** | A smartwatch vital sign (heart rate) stays past a value for N minutes while the watch is worn and the person is at rest |

---

## Section 1 — Safety Rules

Safety rules carry the highest priority and should always be enabled. They cover fall detection, exit/elopement, and situations where the patient may be at immediate risk.

---

### S-01 · Fall Detected (any room)

| Setting | Value |
|---|---|
| Trigger | Fall Detected |
| Room | Any room |
| Severity | **CRITICAL** |
| Time window | All day |

**What it monitors:** Ceiling-mounted radar sensors (e.g. Aqara FP2) configured for fall detection. When the radar detects a sudden downward trajectory followed by a floor-level posture, it fires a fall event.

**Why it matters:** Falls are the leading cause of injury-related hospitalization in older adults. People with dementia are 2–3× more likely to fall than cognitively intact peers and may be unable to call for help afterward. Immediate detection is critical.

**Suggested message:** `Fall detected in {{zone}} at {{time}}`

**Note:** FP2 radar fall detection may miss "soft" falls (slow slides). Camera footage should be reviewed to confirm. Sensitivity can be adjusted in the Aqara Home app.

---

### S-02 · Night Exit — Front Door

| Setting | Value |
|---|---|
| Trigger | Door Opened |
| Door | Front Door |
| No-return timeout | 5 minutes |
| Severity | **HIGH** |
| Time window | 8:00 PM – 8:00 AM |

**What it monitors:** The magnetic door sensor detects when the front door opens. If the patient does not return indoors within 5 minutes (detected by any presence sensor going active), the alert fires.

**Why it matters:** Nighttime elopement is a major risk in dementia — patients may leave the home confused, disoriented, or seeking a place they no longer live. Even brief unsupervised time outside at night can result in injury, hypothermia, or getting lost.

**Suggested message:** `Front door opened at {{time}} — {{patient_name}} may have left`

**Tip:** Reduce the no-return timeout to 2–3 minutes for patients with known elopement history.

---

### S-03 · Daytime Exit — Extended Absence

| Setting | Value |
|---|---|
| Trigger | Door Opened |
| Door | Front Door |
| No-return timeout | 20 minutes |
| Severity | **MEDIUM** |
| Time window | 8:00 AM – 8:00 PM |

**What it monitors:** Same as S-02 but during daytime with a longer grace period to allow short trips (mailbox, garden, brief errands).

**Why it matters:** Daytime exits are more expected but can still become problematic if the patient loses track of how long they've been out or where they intended to go.

**Suggested message:** `Front door opened at {{time}} — {{patient_name}} has been outside for {{duration}} min`

---

### S-04 · Prolonged Bathroom Stay

| Setting | Value |
|---|---|
| Trigger | Long Stay in Room |
| Room | Bedroom Bathroom |
| Maximum stay | 20 minutes |
| Severity | **HIGH** |
| Time window | All day |

**What it monitors:** The bathroom has two FP2 presence sensors (ceiling and wall). If the patient is continuously present for more than 20 minutes, the alert fires.

**Why it matters:** Bathrooms are the most common location for fall injuries in the home. A patient who has fallen in the bathroom may be unable to call for help. Prolonged stays may also indicate confusion, getting stuck (e.g., door lock), or medical distress.

**Suggested message:** `{{patient_name}} has been in the bathroom for {{duration}} min`

---

### S-05 · Night Wandering

| Setting | Value |
|---|---|
| Trigger | Night Wandering |
| Severity | **MEDIUM** |
| Time window | 12:00 AM – 6:00 AM |

**What it monitors:** Any presence sensor activation between midnight and 6am triggers this alert.

**Why it matters:** Nocturnal wandering is prevalent in mid-to-late stage dementia. It disrupts sleep, increases fall risk, and may precede elopement attempts. Caregivers are often unaware of nighttime activity.

**Suggested message:** `Movement detected at {{time}} in {{zone}} — possible night wandering`

---

### S-06 · No Presence Detected (Extended Daytime)

| Setting | Value |
|---|---|
| Trigger | Global Inactivity |
| Duration | 180 minutes |
| Severity | **MEDIUM** |
| Time window | 8:00 AM – 8:00 PM |

**What it monitors:** No presence sensor fires anywhere in the home for 3 consecutive hours during daytime.

**Why it matters:** Extended undetected inactivity may mean the patient has fallen in a sensor blind spot, is unwell and unable to move, or has left the home without triggering a door alert. It is a catch-all safety check.

**Suggested message:** `No movement detected anywhere for {{duration}} min — check on {{patient_name}}`

---

## Section 2 — Daily Activity Rules

Activity rules track the patient's routine and flag deviations. They are lower urgency than safety rules but are valuable for detecting gradual decline and maintaining caregiver awareness.

---

### A-01 · Morning Living Area Inactivity

| Setting | Value |
|---|---|
| Trigger | Room Inactivity |
| Room | Living room |
| Duration | 60 minutes |
| Severity | **MEDIUM** |
| Time window | 7:00 AM – 11:00 AM |

**What it monitors:** No presence in the living room/kitchen area during the morning window.

**Why it matters:** Skipping breakfast is common in dementia and is associated with hypoglycemia, medication timing errors, and weight loss. Morning routine disruption can also signal illness or mood decline.

**Suggested message:** `No living room activity for {{duration}} min — {{patient_name}} may have missed breakfast`

---

### A-02 · Bedroom Occupied Mid-Morning

| Setting | Value |
|---|---|
| Trigger | Long Stay in Room |
| Room | Bedroom |
| Maximum stay | 30 minutes |
| Severity | **LOW** |
| Time window | 10:00 AM – 1:00 PM |

**What it monitors:** Patient still in the bedroom after 10am, continuously, for more than 30 minutes.

**Why it matters:** Oversleeping or excessive daytime rest can indicate depression, medication effects, infection, or fatigue. In dementia, it may also reflect disrupted circadian rhythms.

**Suggested message:** `{{patient_name}} is still in the bedroom at {{time}} — possible oversleeping or fatigue`

---

### A-03 · Daytime Global Inactivity

| Setting | Value |
|---|---|
| Trigger | Global Inactivity |
| Duration | 120 minutes |
| Severity | **MEDIUM** |
| Time window | 9:00 AM – 6:00 PM |

**What it monitors:** No zone changes anywhere for 2 hours during active hours.

**Why it matters:** Healthy older adults move between rooms multiple times per hour. Extended stillness during waking hours may indicate discomfort, fatigue, or passive behavioral changes associated with cognitive decline.

**Suggested message:** `No movement anywhere for {{duration}} min during active hours`

---

### A-04 · Very Early Wake-Up

| Setting | Value |
|---|---|
| Trigger | Night Wandering |
| Severity | **LOW** |
| Time window | 4:00 AM – 6:00 AM |

**What it monitors:** Any movement between 4–6am, which represents an unusually early wake-up but not deep-night wandering.

**Why it matters:** Early morning awakening is common in dementia and can precede agitated or confused episodes. Distinguishing this from the midnight–4am window allows caregivers to respond differently.

**Suggested message:** `{{patient_name}} is up very early ({{time}}) — may be confused about time of day`

---

### A-05 · Long Living Room Stay (Sedentary Alert)

| Setting | Value |
|---|---|
| Trigger | Long Stay in Room |
| Room | Living room |
| Maximum stay | 240 minutes |
| Severity | **LOW** |
| Time window | 9:00 AM – 8:00 PM |

**What it monitors:** Patient in the living room for 4+ continuous hours.

**Why it matters:** Prolonged sedentary behavior is associated with increased fall risk, muscle deconditioning, and depression. It may also indicate the patient is watching TV without engaging in any other activity.

**Suggested message:** `{{patient_name}} has been in the living room for {{duration}} min without a break`

---

### A-06 · Bedroom Inactivity at Night (Sleep Monitor)

| Setting | Value |
|---|---|
| Trigger | Room Inactivity |
| Room | Bedroom |
| Duration | 30 minutes |
| Severity | **LOW** |
| Time window | 10:00 PM – 6:00 AM |

**What it monitors:** No presence in the bedroom for 30+ minutes during expected sleep hours.

**Why it matters:** If the patient is not in the bedroom during expected sleep hours, they may be awake and wandering, or have fallen asleep in another room (chair, couch), which carries fall and comfort risks.

**Suggested message:** `{{patient_name}} is not in the bedroom at {{time}} during sleep hours`

---

## Section 3 — Environmental Rules

Thresholds come from the published guidance cited in each row. Each rule uses the
**Environment Threshold** trigger, which binds by *what* is measured rather than by one sensor
id: a rule covers every matching sensor in the home (Apollo AIR-1, Aqara weather sensor, …) and
names the room in its message. A reading must stay past the threshold for the rule's
"must hold for" time before it alerts, so a brief spike — a hair dryer blast, someone breathing
on the sensor — doesn't page anyone. Temperature rules are written in °C; °F sensors are
converted. The Environment page colours each reading with these same rules.

| Rule | Condition | Holds for | Severity | Source |
|---|---|---|---|---|
| E-01 Indoor heat — danger | > 31 °C | 5 min | **HIGH** | [Health Canada, upper indoor temperature limits](https://www.canada.ca/en/health-canada/services/publications/healthy-living/guidance-upper-indoor-temperature-limits-protecting-older-adults.html) |
| E-02 Indoor too warm | > 26 °C | 15 min | LOW | Health Canada (≤ 26 °C for 60+); [ASHRAE 55-2023](https://www.ashrae.org/file%20library/about/government%20affairs/advocacy%20toolkit/virtual%20packet/standard-55-fact-sheet.pdf) summer comfort 23–26 °C |
| E-03 Indoor cold — danger | ≤ 18 °C | 5 min | **HIGH** | [WHO Housing and Health Guidelines](https://www.ncbi.nlm.nih.gov/books/NBK535290/) |
| E-04 Indoor too cool | < 20 °C | 15 min | LOW | ASHRAE 55-2023 winter comfort 20–23.5 °C |
| E-05 High humidity | > 60 % RH | 5 min | MEDIUM | [EPA mold guide](https://www.epa.gov/mold/brief-guide-mold-moisture-and-your-home) (ideal 30–50 %) |
| E-06 High CO₂ | > 1000 ppm | 5 min | MEDIUM | [ASHRAE position document on indoor CO₂](https://www.ashrae.org/file%20library/about/position%20documents/pd-on-indoor-carbon-dioxide-english.pdf) — no health limit; 1000 ppm is the common ventilation benchmark |
| E-07 High PM2.5 | > 35 µg/m³ | 5 min | MEDIUM | [EPA NAAQS 2024](https://www.epa.gov/criteria-air-pollutants/naaqs-table) 24-hour standard |
| E-08 Carbon monoxide | > 70 ppm | 1 min | **CRITICAL** | [UL 2034](https://www.cpsc.gov/s3fs-public/pdfs/COAlarmConformanceReportPhaseI.pdf) lowest alarm level |
| E-09 Very abnormal VOC | ≥ 250 (index) | 5 min | MEDIUM | [Sensirion VOC index / Apollo AIR-1](https://devices.esphome.io/devices/apollo-automation-air-1/) "very abnormal" band |

**Caveats worth knowing:**
- **PM2.5** — 35 µg/m³ is a *24-hour average* standard. The rule compares the live reading held for
  5 minutes, so it will fire on cooking smoke that would never breach the 24-hour average. That is
  deliberate for a caregiver alert, but it is not the EPA test.
- **CO** — the AIR-1's gas sensor is not a certified CO alarm. This rule is an extra notification
  channel, not a replacement for a UL 2034 alarm in the home. UL 2034 lets an alarm wait 60–240 min
  at 70 ppm; we alert after 1 minute.
- **VOC** — the Sensirion index is relative to the sensor's own recent baseline (100 = normal), not a
  concentration. It drifts back toward 100 during a long exposure, so a slow, steady source can stop
  reading as abnormal.

**Testing scenarios.** Run `python scripts/check_alert_readiness.py --watch 10 --csv data/env_test.csv`
next to the sensor, then apply the stimulus (hair dryer → temperature; humidifier or hot shower →
humidity; several people in a closed room → CO₂; incense or toast → PM2.5 and VOC). Step 1, the
sensor responds: the value column moves. Step 2, the alert fires: the row shows `BREACH <rule>`, and
after the rule's "must hold for" time the alert appears in Alert History. To shorten a test, lower
the rule's "must hold for" in the admin panel and put it back afterwards.

---

## Section 3b — Health Rules (smartwatch)

The Pixel Watch reaches Home Assistant through the Companion App, which exposes **heart rate only**
— no SpO₂, skin temperature, blood pressure or weight. Of the alert criteria used in the Minder
dementia home-monitoring cohort (*Alzheimer's & Dementia* 2021;
[JMIR Aging 2023, Table S2](https://pmc.ncbi.nlm.nih.gov/articles/PMC10037178/)), only the heart
rate one can be implemented today:

| Minder criterion | Available from the watch? | Rule |
|---|---|---|
| Heart rate < 55 or > 99 bpm | **Yes** | H-01, H-02 |
| SpO₂ < 94 % | No | — |
| Temperature < 35 or > 37.6 °C | No | — |
| Systolic BP < 81 or > 159 mmHg | No | — |
| Diastolic BP < 55 or > 99 mmHg | No | — |
| Body weight change ≥ 5 % | No | — |

| Rule | Condition | Holds for | Severity | Active |
|---|---|---|---|---|
| H-01 High heart rate at rest | > 99 bpm | 10 min | MEDIUM | all day |
| H-02 Low heart rate | < 55 bpm | 10 min | MEDIUM | 08:00–21:00 |

Minder took one spot measurement a day, at rest. A watch samples all day, so the rules are made
conservative to keep that criterion meaningful: no alert off a reading more than 10 minutes old or
while the watch reports it is off the wrist, and **a high rate is ignored while the person is moving**
(watch activity state or phone activity is walking/running/exercise, or steps were counted in the last
5 minutes). The low-rate rule is daytime-only because resting heart rate in sleep often drops below
55 bpm in older adults.

---

## Section 3c — Appliance Use (smart plugs)

Every smart-plug power sensor is tracked as an appliance. The activity timeline logs **Appliance on**
when a plug's draw rises past 25 W and **Appliance off** (with run time) once it has stayed at or
below 8 W for 30 seconds. The wide gap keeps a microwave running at part power — whose magnetron
cycles on and off while the fan and light keep drawing — from logging a burst of on/off pairs. While
someone is in the kitchen and a cooking appliance (microwave, kettle, stove, toaster, …) is on, the
current activity reads **Cooking**.

Plugs appear under their Home Assistant name. To rename one, set its kind, fix its room, or change the
wattages, add it under `appliances:` in the patient profile. An "appliance left on" alert is a
**Sensor Threshold** rule on the plug's power sensor with a "must hold for" time (template
`tmpl-e05` in `suggested_rules.yaml`).

---

## Section 3d — Care Mode (home alone vs. with others)

The sensors see *people*, not *the patient*. When a caregiver, relative or visitor is in the
home, the caregiver switches the app from **Home alone** to **With others**, and the rules that
read any movement as the patient's pause:

| Paused with others | Why |
|---|---|
| S-04 Prolonged bathroom stay | Someone else may be in the bathroom |
| S-05 Night wandering | Anyone getting up at night triggers it |
| A-01 Morning living-area inactivity · A-03 Daytime global inactivity | Another person's movement hides the patient's stillness, and vice versa |

Falls, door exits, all environment rules and the heart-rate rules keep running. Each rule's
"Active when" setting can change this. For example, if a live-in caregiver sleeps at night,
you may want night wandering to stay on in both modes.

"With others" reverts to "Home alone" after the chosen time (default 2 hours), so a forgotten
switch fails toward more alerts, not fewer.

---

## Section 4 — Customizing Rules for Your Home

### Step 1: Identify Your Room Names

In the rule builder, room names are pulled directly from your Home Assistant setup. Open the Sensor Browser page to see which rooms are configured and what sensors are in each room. Use these exact names when selecting a zone in the rule editor.

### Step 2: Adjust Time Windows for Your Patient's Routine

Every person with dementia has a different daily rhythm. A breakfast window of 7–11am may not suit a patient who typically rises at 5am or noon. Review the patient's typical schedule with caregivers and adjust time windows accordingly. Night wandering windows should bracket the hours when the household is actually asleep.

### Step 3: Set Severity Appropriately

| Severity | Meaning | Caregiver action |
|---|---|---|
| **Critical** | Immediate risk — act now | Drop everything and respond |
| **High** | Likely risk — check quickly | Respond within minutes |
| **Medium** | Deviation from routine | Check when convenient |
| **Low** | Informational | Review at end of day |

Avoid alert fatigue: if a caregiver receives too many Medium/Low alerts, they may start ignoring all alerts including Critical ones. Start with fewer, higher-confidence rules and add more as you learn the patient's patterns.

### Step 4: Use the Cooldown Setting

The cooldown (default: 10 minutes) prevents the same rule from firing repeatedly. For fast-changing events (e.g., a door that opens and closes frequently), increase the cooldown. For slow-changing conditions (e.g., temperature), a longer cooldown (30–60 min) avoids repeated notifications for a persistent condition.

### Step 5: Test Before Enabling

Use the Sensor Browser in the rule builder to see live entity states. Trigger the condition manually (e.g., walk into the room, open the door) and watch the Alert History page for the expected alert. Only enable a rule in production after confirming it behaves as expected.

---

## Appendix — Sensor Glossary

| Term | Meaning |
|---|---|
| **FP2** | Aqara FP2 — millimeter-wave radar sensor that detects human presence and zone occupancy without wearables |
| **Presence sensor** | Any sensor that reports whether someone is in a zone (on = occupied, off = empty) |
| **Fall detection** | FP2 operating in Fusion Mode, configured to detect sudden downward movement at floor level |
| **Door/window sensor** | Magnetic contact sensor that reports open (on) or closed (off) state |
| **Entity** | Home Assistant's term for a single data point from a device (e.g., `binary_sensor.front_door_opening`) |
| **Area** | A named room or zone in Home Assistant, to which sensors are assigned |
| **State changed** | A Home Assistant event fired whenever any entity's value changes — the primary input to the rule engine |
| **Cooldown** | Minimum time between repeated firings of the same rule, to prevent alert fatigue |
| **Time window** | The hours of the day during which a rule is active. Windows that span midnight (e.g., 10pm–6am) are supported |
| **Severity** | The urgency level of an alert: Critical / High / Medium / Low |

