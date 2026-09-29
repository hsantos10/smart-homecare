"""Check live HA for Pixel Watch / companion app entities."""
import sys
from datetime import datetime, timezone

from dari.rule_engine.ha_client import get_all_states

states = get_all_states()
keywords = ('pixel', 'watch', 'heart', 'step', 'wear', 'on_body', 'companion', 'google', 'health')
watch = [s for s in states if any(k in s['entity_id'].lower() for k in keywords)]
if watch:
    for s in watch:
        unit = s.get('attributes', {}).get('unit_of_measurement', '')
        changed = s.get('last_changed', '?')
        age_min = None
        try:
            dt = datetime.fromisoformat(changed.replace('Z', '+00:00'))
            age_min = round((datetime.now(timezone.utc) - dt).total_seconds() / 60, 1)
        except (ValueError, AttributeError):
            pass
        print(f"{s['entity_id']} = {s['state']} {unit}  (last_changed {changed}, age {age_min} min)")
else:
    print("No watch/companion entities found yet.")

print(f"\nTotal entities in HA: {len(states)}")
