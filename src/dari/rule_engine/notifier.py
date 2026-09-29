"""Push caregiver alerts to phones through Home Assistant's notify services.

The HA Companion App is already installed on the caregiver's phone and already holds a
push token, so alerts can reach a locked phone today without standing up FCM, a push
server or an app release. When the Android app ships its own push channel this module is
the seam to swap — the engine only calls `notify_alert`.

Configured per profile:

    notify:
      enabled: true
      min_severity: MEDIUM          # CRITICAL | HIGH | MEDIUM | LOW
      services:
        - notify.mobile_app_<caregiver_phone>

Delivery is best-effort: a phone that is off, unreachable or has revoked the token must
never stall or crash the rule engine, so every failure is logged and swallowed.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

from .ha_client import call_service
from .models import Alert

log = logging.getLogger(__name__)

# Highest first — an alert is sent when its severity is at least `min_severity`.
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# Android notification channel per severity. Channels are created on the phone the first
# time they're used, and the user can tune each one in Android's own notification
# settings — which is why CRITICAL gets its own channel rather than a priority flag.
_CHANNEL = {
    "CRITICAL": ("DARI Critical", "high", "#c1272d"),
    "HIGH":     ("DARI High",     "high", "#e07a2f"),
    "MEDIUM":   ("DARI Medium",   "default", "#c9a227"),
    "LOW":      ("DARI Low",      "low", "#2e8b57"),
}


def _rank(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index((severity or "").upper())
    except ValueError:
        return len(SEVERITY_ORDER)


@dataclass
class NotifyConfig:
    """A profile's `notify:` block."""
    enabled: bool = False
    min_severity: str = "MEDIUM"
    services: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "NotifyConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            min_severity=str(data.get("min_severity", "MEDIUM")).upper(),
            services=list(data.get("services") or []),
        )

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "min_severity": self.min_severity,
                "services": list(self.services)}

    def should_send(self, severity: str) -> bool:
        if not self.enabled or not self.services:
            return False
        return _rank(severity) <= _rank(self.min_severity)


def build_payload(alert: Alert, patient_name: str) -> dict:
    """The HA notify payload for one alert.

    `tag` is keyed on the rule so a repeat of the same alert replaces the previous
    notification instead of stacking a fresh one on every cooldown expiry.
    """
    channel, importance, color = _CHANNEL.get(
        (alert.severity or "").upper(), _CHANNEL["MEDIUM"])
    critical = (alert.severity or "").upper() == "CRITICAL"

    data: dict = {
        "channel": channel,
        "importance": importance,
        "color": color,
        "tag": f"dari-{alert.rule_id}",
        "notification_icon": "mdi:home-heart",
        # Survive Doze: a safety alert is worthless if it lands an hour late.
        "ttl": 0,
        "priority": "high",
    }
    if critical:
        # Bypass Do Not Disturb and stay on screen until acknowledged.
        data["sticky"] = "true"
        data["alert_once"] = False

    return {
        "title": f"{patient_name}: {alert.rule_name}",
        "message": alert.message,
        "data": data,
    }


def notify_alert(alert: Alert, patient_name: str, cfg: NotifyConfig,
                 dry_run: bool = False) -> list[str]:
    """Push one alert to every configured notify service.

    Returns the services it was delivered to. Never raises — the rule engine must keep
    evaluating even when a phone is unreachable.
    """
    if not cfg.should_send(alert.severity):
        return []

    payload = build_payload(alert, patient_name)
    delivered: list[str] = []

    for svc in cfg.services:
        # Accept "notify.mobile_app_x" or bare "mobile_app_x".
        domain, _, service = svc.partition(".")
        if not service:
            domain, service = "notify", domain

        if dry_run:
            log.info("[dry-run] would notify %s.%s: %s", domain, service, payload["title"])
            delivered.append(svc)
            continue

        try:
            call_service(domain, service, payload)
            delivered.append(svc)
            log.info("📱 pushed to %s: %s", svc, payload["title"])
        except Exception as exc:
            log.warning("push to %s failed: %s", svc, exc)

    return delivered
