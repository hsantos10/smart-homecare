from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import yaml
import uuid


@dataclass
class TimeWindow:
    start: str  # "HH:MM"
    end: str    # "HH:MM"

    def spans_midnight(self) -> bool:
        return self.start > self.end


@dataclass
class Rule:
    id: str
    name: str
    enabled: bool
    category: str        # Safety | Activity | Environment
    severity: str        # CRITICAL | HIGH | MEDIUM | LOW
    trigger_type: str    # fall | door_opened | room_inactivity | global_inactivity |
                         # night_wandering | long_stay | sensor_threshold |
                         # env_threshold | vital_threshold
    message: str         # {{patient_name}} {{zone}} {{time}} {{duration}} {{value}} {{sensor}}

    zone: Optional[str] = None          # room area_id from HA (None = any)
    entity_id: Optional[str] = None     # door_opened / sensor_threshold; optional pin for fall,
                                        # env_threshold and vital_threshold
    duration_minutes: Optional[int] = None  # threshold rules: condition must hold this long
    no_return_minutes: Optional[int] = None
    operator: Optional[str] = None      # "gt" | "lt" | "gte" | "lte"
    value: Optional[float] = None
    metric: Optional[str] = None        # env_threshold: temperature|humidity|co2|pm25|co|voc
                                        # vital_threshold: a profile.watch key, e.g. heart_rate
    unit: Optional[str] = None          # unit `value` is written in ("°C"); readings converted
    time_window: Optional[TimeWindow] = None
    cooldown_minutes: int = 10          # min gap between repeated fires
    modes: Optional[list[str]] = None   # care modes it runs in: ["alone", "with_others"];
                                        # None = default for its trigger (care_mode.rule_modes)

    @classmethod
    def from_dict(cls, d: dict) -> Rule:
        tw = None
        if d.get("time_window"):
            tw = TimeWindow(
                start=str(d["time_window"]["start"]),
                end=str(d["time_window"]["end"]),
            )
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d["name"],
            enabled=d.get("enabled", True),
            category=d["category"],
            severity=d["severity"],
            trigger_type=d["trigger_type"],
            message=d["message"],
            zone=d.get("zone"),
            entity_id=d.get("entity_id"),
            duration_minutes=d.get("duration_minutes"),
            no_return_minutes=d.get("no_return_minutes"),
            operator=d.get("operator"),
            value=d.get("value"),
            metric=d.get("metric"),
            unit=d.get("unit"),
            time_window=tw,
            cooldown_minutes=d.get("cooldown_minutes", 10),
            modes=d.get("modes"),
        )

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "category": self.category,
            "severity": self.severity,
            "trigger_type": self.trigger_type,
            "message": self.message,
        }
        for key in ("zone", "entity_id", "duration_minutes", "no_return_minutes",
                    "operator", "value", "metric", "unit"):
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        if self.time_window:
            d["time_window"] = {"start": self.time_window.start, "end": self.time_window.end}
        if self.cooldown_minutes != 10:
            d["cooldown_minutes"] = self.cooldown_minutes
        if self.modes is not None:
            d["modes"] = self.modes
        return d


@dataclass
class Profile:
    profile_id: str
    patient_name: str
    caregiver_name: str
    rules: list[Rule] = field(default_factory=list)
    watch: dict = field(default_factory=dict)  # entity_id map from profile YAML
    notify: dict = field(default_factory=dict)  # HA notify services — see rule_engine.notifier
    appliances: dict = field(default_factory=dict)  # plug power entity_id → {name, kind, area, on_watts, off_watts}

    @classmethod
    def load(cls, path: str) -> Profile:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = [Rule.from_dict(r) for r in data.get("rules", [])]
        return cls(
            profile_id=data["profile_id"],
            patient_name=data["patient_name"],
            caregiver_name=data["caregiver_name"],
            rules=rules,
            watch=data.get("watch") or {},
            notify=data.get("notify") or {},
            appliances=data.get("appliances") or {},
        )

    def save(self, path: str) -> None:
        data = {
            "profile_id": self.profile_id,
            "patient_name": self.patient_name,
            "caregiver_name": self.caregiver_name,
            "rules": [r.to_dict() for r in self.rules],
        }
        if self.watch:
            data["watch"] = self.watch
        if self.notify:
            data["notify"] = self.notify
        if self.appliances:
            data["appliances"] = self.appliances
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    @property
    def active_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.enabled]


@dataclass
class Alert:
    id: str
    profile_id: str
    rule_id: str
    rule_name: str
    severity: str
    category: str
    message: str
    zone: Optional[str]
    timestamp: str
    acknowledged: bool = False
    source: str = "heuristic"
