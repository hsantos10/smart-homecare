# Running the Stack

> **See [README.md](README.md) for the full guide** — architecture, file structure, API reference, and porting notes.

## TL;DR — start everything

```powershell
.\launch.ps1
```

Before starting anything, this kills whatever's already holding port 8000 (API) or 5173
(caregiver app), plus any leftover `activity_engine.engine` / `rule_engine.engine` process
(they don't bind a port, so they're matched by command line instead) — checked against the
live process list every time, not a saved PID file, so it catches stragglers no matter how
they were started (crashed terminal, closed window, a previous run you forgot to stop).
Every service always comes up on the same fixed port — the Vite dev server also has
`strictPort: true` set in `vite.config.ts` so it fails loudly instead of silently drifting to
a different port if something's still holding theirs.

```powershell
.\launch.ps1 -Status   # check what's currently running
.\launch.ps1 -Stop     # kill everything
```

Flags on start: `-SkipEngine`, `-SkipRuleEngine`, `-SkipApp` to leave one service alone.

- → http://localhost:5173          (caregiver view)
- → http://localhost:5173?mode=admin  (admin panel — rules + watch config)

### Manual start (equivalent, one service at a time)

```bash
# 1. Backend API  (required by all other services) — always :8000
conda run -n LLMs python -m uvicorn dari.api_server.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Activity engine  (infers what patient is doing, logs timeline)
conda run -n LLMs python -m dari.activity_engine.engine --profile config/profiles/patient_001.yaml

# 3. Rule engine  (fires threshold/event alerts)
conda run -n LLMs python -m dari.rule_engine.engine --profile config/profiles/patient_001.yaml

# 4. Caregiver web app — always :5173 (strictPort — fails rather than drifting)
cd apps/caregiver_web && npm run dev
```

## Optional

```bash
# Seed demo timeline for UI demos (no live HA needed)
conda run -n LLMs python scripts/seed_demo.py

# Streamlit rule builder (legacy, kept as fallback)
conda run -n LLMs streamlit run src/dari/admin_streamlit/app.py
# → http://localhost:8501
```

## Checking the alert rules

```bash
# Offline: every alert trigger, appliance detection and care mode on synthetic states
conda run -n LLMs python scripts/test_alert_rules.py

# Live (HA reachable): what each rule is bound to; --watch streams readings for test scenarios
conda run -n LLMs python scripts/check_alert_readiness.py
conda run -n LLMs python scripts/check_alert_readiness.py --watch 10 --csv data/env_test.csv
```

Restart the rule engine after editing rules — it reads the profile at startup. The care
mode (home alone / with others) is read live and needs no restart.
