"""Check the push-notification path for a profile.

By default this is a DRY RUN — it prints the exact payload that would go to each phone
and sends nothing. Pass --send to actually deliver a test notification.

    python scripts/test_notify.py --profile config/profiles/patient_001.yaml
    python scripts/test_notify.py --profile config/profiles/patient_001.yaml --send
"""
from __future__ import annotations
import json
import sys
from argparse import ArgumentParser

from dotenv import load_dotenv

from dari.paths import DEFAULT_PROFILE
from dari.rule_engine.alert_store import make_alert
from dari.rule_engine.models import Profile
from dari.rule_engine.notifier import NotifyConfig, build_payload, notify_alert

load_dotenv()


def main() -> None:
    ap = ArgumentParser(description="Test the HA push-notification path")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--severity", default="HIGH",
                    choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"])
    ap.add_argument("--send", action="store_true",
                    help="Actually deliver to the phone (default: dry run)")
    args = ap.parse_args()

    profile = Profile.load(args.profile)
    cfg = NotifyConfig.from_dict(profile.notify)

    print(f"profile      : {profile.profile_id} ({profile.patient_name})")
    print(f"notify block : enabled={cfg.enabled} min_severity={cfg.min_severity}")
    print(f"services     : {cfg.services or '— none configured —'}")
    print()

    alert = make_alert(
        profile_id=profile.profile_id, rule_id="test-rule", rule_name="Push test",
        severity=args.severity, category="Safety",
        message=f"Test {args.severity} alert from scripts/test_notify.py",
        zone="Living room",
    )

    print("payload that would be sent:")
    print(json.dumps(build_payload(alert, profile.patient_name), indent=2))
    print()

    print(f"would send at {args.severity}? {cfg.should_send(args.severity)}")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        print(f"   {sev:9} -> {'send' if cfg.should_send(sev) else 'suppress'}")
    print()

    if not args.send:
        print("DRY RUN — nothing sent. Re-run with --send to deliver for real.")
        # Exercise the real code path with delivery stubbed out.
        notify_alert(alert, profile.patient_name, cfg, dry_run=True)
        return

    if not cfg.should_send(args.severity):
        print("Notify config would suppress this alert; nothing to send.", file=sys.stderr)
        sys.exit(1)

    delivered = notify_alert(alert, profile.patient_name, cfg, dry_run=False)
    print("delivered to:", delivered or "— nothing —")


if __name__ == "__main__":
    main()
