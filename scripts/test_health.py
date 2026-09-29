"""Smoke-test the /api/health data path without running FastAPI."""
from dari.rule_engine.models import Profile
from dari.rule_engine.ha_client import states_as_dict
from dari.paths import DEFAULT_PROFILE

profile = Profile.load(str(DEFAULT_PROFILE))
print("Watch config:", profile.watch)

states = states_as_dict()
for key, eid in profile.watch.items():
    s = states.get(eid, {})
    val = s.get("state", "MISSING")
    unit = s.get("attributes", {}).get("unit_of_measurement", "")
    print(f"  {key:20s} {eid:50s} = {val} {unit}")
