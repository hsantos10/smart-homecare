"""
Home Assistant REST + WebSocket client.
Credentials loaded from .env (HA_URL, HA_TOKEN).
"""
from __future__ import annotations
import os
import re
import json
import asyncio
from datetime import datetime, timezone
from urllib.parse import quote
import requests
import websockets
from dotenv import load_dotenv

from dari.env_metrics import env_metric

load_dotenv()

HA_URL   = os.getenv("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_WS    = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

_ws_id = 0


# ── REST helpers ─────────────────────────────────────────────────────────────

def get_all_states() -> list[dict]:
    """Return all HA entity states as a list of dicts."""
    resp = requests.get(f"{HA_URL}/api/states", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_numeric_states() -> list[dict]:
    """Return only entities with a numeric state (sensors)."""
    states = get_all_states()
    result = []
    for s in states:
        try:
            float(s["state"])
            result.append(s)
        except (ValueError, TypeError):
            pass
    return result


def get_binary_states() -> list[dict]:
    """Return only binary_sensor and switch entities."""
    return [s for s in get_all_states()
            if s["entity_id"].split(".")[0] in ("binary_sensor", "switch")]


def states_as_dict(states: list[dict] | None = None) -> dict[str, dict]:
    """Convert states list to {entity_id: state_dict} for fast lookup."""
    if states is None:
        states = get_all_states()
    return {s["entity_id"]: s for s in states}


def call_service(domain: str, service: str, data: dict | None = None) -> list | dict:
    """Call an HA service via REST, e.g.
    call_service("notify", "mobile_app_<phone>", {"message": "command_update_sensors"})."""
    resp = requests.post(
        f"{HA_URL}/api/services/{domain}/{service}",
        headers=HEADERS, json=data or {}, timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── WebSocket helpers ─────────────────────────────────────────────────────────

async def _ws_call_async(payload: dict) -> list | dict:
    """Open a one-shot WebSocket connection, authenticate, send payload, return result."""
    global _ws_id
    _ws_id += 1
    msg_id = _ws_id

    async with websockets.connect(HA_WS, open_timeout=10) as ws:
        # 1. Expect auth_required
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected HA WS greeting: {msg}")

        # 2. Authenticate
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") != "auth_ok":
            raise RuntimeError(f"HA WS auth failed: {msg}")

        # 3. Send command
        cmd = {"id": msg_id, **payload}
        await ws.send(json.dumps(cmd))

        # 4. Read until we get our result (id matches)
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == msg_id:
                if not msg.get("success", True):
                    raise RuntimeError(f"HA WS command error: {msg}")
                return msg.get("result", [])


def _ws_call(payload: dict) -> list | dict:
    """Synchronous wrapper around _ws_call_async."""
    return asyncio.run(_ws_call_async(payload))


# ── Area / entity registry ────────────────────────────────────────────────────

def get_areas() -> list[dict]:
    """Return list of HA areas: [{area_id, name, aliases, ...}]"""
    return _ws_call({"type": "config/area_registry/list"})


def get_entity_registry() -> list[dict]:
    """Return full entity registry: [{entity_id, area_id, device_id, ...}]"""
    return _ws_call({"type": "config/entity_registry/list"})


def get_device_registry() -> list[dict]:
    """Return device registry: [{id, area_id, name, ...}]"""
    return _ws_call({"type": "config/device_registry/list"})


def get_sensors_by_area() -> dict[str, dict]:
    """
    Returns {area_name: {"presence": [...], "door": [...], "numeric": [...], "fall": [...], "all": [...]}}
    by combining entity registry (entity→area) with device registry (device→area).

    - "presence": binary_sensor entities for room occupancy (FP2 or similar)
    - "door": binary_sensor entities for door/window opening detection
    - "fall": binary_sensor entities whose device name contains "fall" (FP2 fall detection)
    - "numeric": sensor entities for environmental readings (temp, humidity, CO2, etc.)
    """
    areas_raw   = get_areas()
    entities    = get_entity_registry()
    devices     = get_device_registry()

    area_by_id   = {a["area_id"]: a["name"] for a in areas_raw}
    device_area  = {d["id"]: d.get("area_id") for d in devices}
    device_name  = {d["id"]: (d.get("name_by_user") or d.get("name") or "").lower()
                    for d in devices}

    # Numeric sensor keywords that indicate meaningful environmental readings
    NUMERIC_KEYWORDS = ("temperature", "humidity", "co2", "pm25", "pressure",
                        "illuminance", "light_level", "voc", "tvoc")
    # Numeric keywords to exclude (device/system metrics)
    NUMERIC_EXCLUDE  = ("battery", "rssi", "lqi", "device_temperature",
                        "upload", "download", "power", "energy", "voltage",
                        "current", "frequency")

    result: dict[str, dict] = {}

    for ent in entities:
        eid = ent.get("entity_id", "")
        dev_id = ent.get("device_id", "")
        # Resolve area: entity-level first, then device-level
        area_id = ent.get("area_id") or device_area.get(dev_id, "")
        if not area_id or area_id not in area_by_id:
            continue
        area_name = area_by_id[area_id]
        bucket = result.setdefault(area_name, {
            "presence": [], "door": [], "fall": [], "numeric": [], "all": []
        })
        bucket["all"].append(eid)
        domain    = eid.split(".")[0]
        eid_lower = eid.lower()
        dev_lower = device_name.get(dev_id, "")
        ent_name  = (ent.get("name") or ent.get("original_name") or "").lower()

        if domain == "binary_sensor":
            is_presence = (
                "presence_sensor" in eid_lower
                or "fp2" in eid_lower
                or "occupancy" in eid_lower
                or "presence_sensor" in dev_lower
            )
            is_door = (
                any(kw in eid_lower for kw in ("opening", "contact", "window", "magnet"))
                and "presence" not in eid_lower
            )
            # A *dedicated* fall entity is one that says "fall" in its own entity_id,
            # or in its entity name while NOT being one of the generic per-target
            # occupancy entities. Aqara names those "..._presence_sensor_1".."_5" even
            # on a unit the user labelled "Ceiling Fall" — they only report presence,
            # so matching the device's display name alone would bucket a plain presence
            # sensor as "fall" and turn every step into a CRITICAL. `eval_fall` fails
            # closed when this bucket is empty, so a fall-mode FP2 that isn't yet
            # publishing a fall entity in HA simply leaves fall rules inactive.
            name_says_fall = "fall" in ent_name and not (
                re.search(r"presence_sensor_\d+$", eid_lower)
                or eid_lower.endswith(("_presence", "_occupancy", "_presence_sensor"))
            )
            is_fall_device = "fall" in eid_lower or name_says_fall

            if is_fall_device:
                bucket["fall"].append(eid)
            elif is_presence:
                bucket["presence"].append(eid)
            elif is_door:
                bucket["door"].append(eid)
        elif domain == "sensor":
            eid_l = eid_lower
            dev_class = ent.get("device_class") or ent.get("original_device_class")
            if env_metric(eid, dev_class) or (
                    any(kw in eid_l for kw in NUMERIC_KEYWORDS)
                    and not any(ex in eid_l for ex in NUMERIC_EXCLUDE)):
                bucket["numeric"].append(eid)

    return result


def get_fall_entities() -> list[str]:
    """
    Return entity_ids of binary_sensors whose device is configured for fall detection.
    These are FP2 units mounted on the ceiling with fall mode enabled.
    """
    sensors_by_area = get_sensors_by_area()
    falls = []
    for buckets in sensors_by_area.values():
        falls.extend(buckets.get("fall", []))
    return falls


def get_history(
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict]]:
    """
    Fetch HA state history for the given entity_ids between start and end (UTC).
    Returns {entity_id: [{"state": ..., "last_changed": ...}, ...]}.
    """
    start_str = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    end_str   = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    # The timestamp sits in the URL path: a bare "+" decodes to a space and HA answers 400.
    resp = requests.get(
        f"{HA_URL}/api/history/period/{quote(start_str, safe='')}",
        headers=HEADERS,
        params={
            "end_time": end_str,
            "filter_entity_id": ",".join(entity_ids),
            "minimal_response": "true",
            "no_attributes": "true",
            "significant_changes_only": "true",
        },
        timeout=30,
    )
    resp.raise_for_status()
    result: dict[str, list[dict]] = {}
    for entity_history in resp.json():
        if entity_history:
            eid = entity_history[0]["entity_id"]
            result[eid] = entity_history
    return result


def get_door_entities() -> list[dict]:
    """Return binary_sensor entities for door/window opening detection."""
    states = get_all_states()
    return [
        s for s in states
        if s["entity_id"].split(".")[0] == "binary_sensor"
        and any(kw in s["entity_id"].lower()
                for kw in ("opening", "contact", "door", "window", "magnet"))
        and "presence" not in s["entity_id"].lower()
    ]
