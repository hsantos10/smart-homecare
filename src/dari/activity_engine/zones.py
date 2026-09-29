"""
Semantic zone + area classification.

FP2 sensors report room-level presence and, when configured, sub-zones inside a room
("bed area", "sofa area", "desk"). Home Assistant exposes each as its own binary_sensor.
We can't hard-code entity ids (they differ per deployment), so we classify them by
keyword in the entity_id / friendly_name, with optional per-profile overrides.

Area *roles* let the resolver reason about rooms generically: a home might have
"Living room", "Bedroom", "Bedroom Bathroom", and a "Kitchen" can be added later with no
logic changes.
"""
from __future__ import annotations
import re
from typing import Optional

# Semantic sub-zone -> keywords that may appear in a presence entity's id or name.
# Order matters: more specific zones first.
# NOTE: keywords are matched as whole TOKENS, not substrings — so "bed" matches
# "bedroom_fp2_bed" but NOT the room-level sensor "bedroom_fp2" (where "bed" is only
# part of the word "bedroom").
ZONE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "shower":  ("shower",),
    "toilet":  ("toilet", "wc", "commode"),
    "bed":     ("bed",),
    "sofa":    ("sofa", "couch", "lounge"),
    "desk":    ("desk", "study", "office"),
    "dining":  ("dining", "table"),
    "entry":   ("entry", "entrance", "foyer", "doorway"),
}


def _tokens(entity_id: str, friendly_name: str) -> set[str]:
    """Split id + name into lowercase word tokens (digits/letters), e.g.
    'binary_sensor.bedroom_fp2_bed' + 'Bedroom Bed' → {binary, sensor, bedroom, fp2, bed}."""
    return set(re.split(r"[^a-z0-9]+", f"{entity_id} {friendly_name}".lower())) - {""}


def classify_zone(entity_id: str, friendly_name: str = "") -> Optional[str]:
    """Map a presence entity to a semantic sub-zone, or None if it's just room-level."""
    toks = _tokens(entity_id, friendly_name)
    for zone, kws in ZONE_KEYWORDS.items():
        if any(kw in toks for kw in kws):
            return zone
    return None


def area_role(area_name: str) -> str:
    """Coarse role for a Home Assistant area, inferred from its name.

    Returns one of: bathroom | bedroom | kitchen | living | study | other.
    """
    n = (area_name or "").lower()
    if "bath" in n or "restroom" in n:
        return "bathroom"
    if "bed" in n:
        return "bedroom"
    if "kitchen" in n or "dining" in n:
        return "kitchen"
    if "living" in n or "lounge" in n or "family" in n:
        return "living"
    if "study" in n or "office" in n or "den" in n:
        return "study"
    return "other"


def is_door_entity(entity_id: str, friendly_name: str = "") -> bool:
    text = f"{entity_id} {friendly_name}".lower()
    return (
        any(kw in text for kw in ("door", "opening", "contact", "window", "magnet"))
        and "presence" not in text
    )


def door_kind(entity_id: str, friendly_name: str = "") -> str:
    """Classify a door/contact sensor: front | fridge | cabinet | shower | window | door."""
    text = f"{entity_id} {friendly_name}".lower()
    # Real-world entity naming is often abbreviated/misspelled by whoever set up the
    # device (e.g. a fridge sensor may be named literally "refriger_opening",
    # not "refrigerator...") — match the truncated forms too, not just full words.
    if "fridge" in text or "refrigerator" in text or "refriger" in text:
        return "fridge"
    if "cabinet" in text or "cupboard" in text or "cabin" in text:
        return "cabinet"
    if "shower" in text:
        return "shower"
    if "front" in text or "entry" in text or "entrance" in text or "main" in text:
        return "front"
    if "window" in text:
        return "window"
    return "door"


def is_toilet_vibration_entity(entity_id: str, friendly_name: str = "") -> bool:
    """A vibration sensor on the toilet flush pipe — corroborates 'using_toilet'.

    Identified by keyword on the entity itself, NOT by HA area assignment: in this
    home the toilet vibration sensor ends up tagged under another room (e.g. "Living room")
    in the HA area registry even though it's physically in the bathroom. Trusting area
    tags here would silently drop a real, useful signal.
    """
    text = f"{entity_id} {friendly_name}".lower()
    return "vibration" in text and "toilet" in text
