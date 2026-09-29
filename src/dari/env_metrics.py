"""
Which environmental quantity a Home Assistant sensor measures.

One classifier shared by the area map (`ha_client.get_sensors_by_area`), the API's
Environment page and the `env_threshold` rule evaluator, so a sensor that shows up on
the page is the same sensor an alert rule binds to.

HA's `device_class` is trusted first; entity-id tokens are the fallback, because some
readings (e.g. the Sensirion SEN55 VOC *index*, which is unitless) carry no device class.
"""
from __future__ import annotations
import re
from typing import Optional

METRICS = ("temperature", "humidity", "co2", "pm25", "co", "voc")

_DEVICE_CLASS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "carbon_dioxide": "co2",
    "pm25": "pm25",
    "carbon_monoxide": "co",
    "volatile_organic_compounds": "voc",
    "volatile_organic_compounds_parts": "voc",
}

# Device/system metrics that happen to say "temperature" etc. — never room air.
_EXCLUDE = ("battery", "device_temperature", "cpu", "processor", "chip", "watch",
            "phone", "rssi", "lqi")
_EXCLUDE_TOKENS = {"nox"}   # whole token only — "nox" is inside "carbon_monoxide"


def _tokens(entity_id: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", entity_id.lower()) if t]


def env_metric(entity_id: str, device_class: Optional[str] = None) -> Optional[str]:
    """Return one of METRICS for an environmental `sensor.*` entity, else None."""
    if entity_id.split(".")[0] != "sensor":
        return None
    low = entity_id.lower()
    toks = _tokens(entity_id)
    if any(ex in low for ex in _EXCLUDE) or _EXCLUDE_TOKENS & set(toks):
        return None
    if device_class in _DEVICE_CLASS:
        return _DEVICE_CLASS[device_class]

    joined = "_".join(toks)
    if "temperature" in toks:
        return "temperature"
    if "humidity" in toks:
        return "humidity"
    if "co2" in toks or "carbon_dioxide" in joined:
        return "co2"
    # ESPHome names PM2.5 "pm_2_5_..." / "pm_2_5_m_weight_concentration"; others use "pm25".
    if re.search(r"(^|_)pm_?2_?5(_|$)", joined):
        return "pm25"
    if "co" in toks or "carbon_monoxide" in joined:
        return "co"
    if "voc" in toks or "tvoc" in toks:
        return "voc"
    return None


def normalize_temp(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between °C and °F. Anything else passes through unchanged."""
    f = (from_unit or "").upper().endswith("F")
    t = (to_unit or "").upper().endswith("F")
    if f and not t:
        return (value - 32) * 5 / 9
    if t and not f and (from_unit or "").upper().endswith("C"):
        return value * 9 / 5 + 32
    return value
