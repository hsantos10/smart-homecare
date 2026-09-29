"""
Pluggable activity classifier — research hook for (optional) simple ML.

WHY THIS IS A STUB, NOT A MODEL (yet)
─────────────────────────────────────
Supervised activity recognition needs *labelled* sensor data (e.g. from scripted ADL/fall
simulations), and a caregiving setting favours explainable, rule-based logic over opaque
prediction anyway. So the default classifier is
the deterministic heuristic in detectors.py.

This module exists so a model can be dropped in later WITHOUT touching the engine or API:
both call `classify(world, ctx, profile)`, which returns the same `ActivityCandidate` the
heuristics do. Swap `ACTIVE_CLASSIFIER` to an MLClassifier once a model is trained.

SIMPLE ML OPTIONS WORTH EVALUATING (in rough order of effort)
─────────────────────────────────────
1. Decision Tree / Random Forest (scikit-learn) on per-tick features
   (which zones occupied, time-of-day, recent transition counts, plug power). Cheap,
   explainable (you can print the tree), runs locally — fits the "no cloud" constraint.
2. Hidden Markov Model (hmmlearn) over the zone-occupancy sequence. Naturally models
   "states" (sleeping → bathroom → kitchen) and smooths out flapping FP2 readings.
   Good fit because daily routines are sequential.
3. Lightweight temporal model — a short sliding window + logistic regression, or a tiny
   1D-CNN/LSTM, only if 1–2 prove insufficient. Likely overkill for ~5 rooms.

Recommended path: collect labelled simulation data → start with a Decision Tree for
per-tick labels, add an HMM smoothing layer over its output. Keep the heuristic as the
fallback/baseline to compare accuracy against (it doubles as ground-truth sanity check).

Feature extraction below is ML-ready today, so labelled data can be turned into a training
matrix immediately once it exists.
"""
from __future__ import annotations
import importlib.util
from datetime import datetime
from typing import Optional

from .models import WorldState
from .detectors import resolve_activity, ActivityCandidate
from .zones import area_role


def extract_features(world: WorldState) -> dict:
    """WorldState → flat feature dict. Stable keys = a training matrix once labels exist."""
    now = world.timestamp
    local = now.astimezone()
    feats: dict = {
        "hour": local.hour,
        "minute_of_day": local.hour * 60 + local.minute,
        "is_weekend": 1 if local.weekday() >= 5 else 0,
        "any_presence": int(world.any_presence),
        "home": int(world.home),
        "fall_active": int(world.fall_active),
        "n_areas_occupied": sum(1 for v in world.area_occupied.values() if v),
        "max_plug_power": max(world.plug_power.values(), default=0.0),
        "n_doors_open": sum(1 for v in world.door_open.values() if v),
        "watch_stale": int(world.watch_stale),
        "heart_rate": world.heart_rate or 0.0,
        "sleep_confidence": world.sleep_confidence or 0.0,
        "steps_delta": world.steps_delta or 0.0,
        "on_body": int(world.on_body) if world.on_body is not None else -1,
        "activity_state": world.activity_state or "",
        "phone_activity": world.phone_activity or "",
    }
    for area, occ in world.area_occupied.items():
        feats[f"area::{area}"] = int(occ)
        feats[f"role::{area_role(area)}"] = 1
    for (zone_area, zone), occ in world.zone_occupied.items():
        feats[f"zone::{zone_area}::{zone}"] = int(occ)
    return feats


class ActivityClassifier:
    """Interface: world → ActivityCandidate."""
    def predict(self, world: WorldState, ctx: dict, profile=None) -> ActivityCandidate:
        raise NotImplementedError


class HeuristicClassifier(ActivityClassifier):
    """Default. Wraps the deterministic resolver so it satisfies the same interface."""
    def predict(self, world: WorldState, ctx: dict, profile=None) -> ActivityCandidate:
        return resolve_activity(world, ctx, profile)


class MLClassifier(ActivityClassifier):
    """Loads a trained scikit-learn model (joblib). Falls back to heuristics until trained."""
    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self._fallback = HeuristicClassifier()
        self._labels: list[str] = []
        if model_path and importlib.util.find_spec("joblib") and importlib.util.find_spec("sklearn"):
            try:
                import joblib
                bundle = joblib.load(model_path)
                self.model = bundle["model"]
                self._labels = bundle.get("labels", [])
            except Exception:
                self.model = None

    def predict(self, world: WorldState, ctx: dict, profile=None) -> ActivityCandidate:
        if self.model is None:
            return self._fallback.predict(world, ctx, profile)
        # Align features to the model's expected columns, predict + take probability.
        feats = extract_features(world)
        cols = getattr(self.model, "feature_names_in_", list(feats.keys()))
        row = [[feats.get(c, 0) for c in cols]]
        pred = self.model.predict(row)[0]
        conf = 1.0
        if hasattr(self.model, "predict_proba"):
            conf = float(max(self.model.predict_proba(row)[0]))
        return ActivityCandidate(str(pred), zone=world.current_area, confidence=conf, source="ml")


# Default classifier used by the engine + API. Swap to MLClassifier(path) when a model exists.
ACTIVE_CLASSIFIER: ActivityClassifier = HeuristicClassifier()


def classify(world: WorldState, ctx: dict, profile=None) -> ActivityCandidate:
    return ACTIVE_CLASSIFIER.predict(world, ctx, profile)
