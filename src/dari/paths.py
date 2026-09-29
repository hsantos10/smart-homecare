"""Canonical filesystem locations, resolved once.

Everything that needs the database, a profile, or an output directory imports it from
here. Modules used to walk `Path(__file__).parent.parent` to find the repo root, which
silently pointed at the wrong directory as soon as the package moved.

`DARI_DATA_DIR` overrides the data directory (useful for tests and for pointing a replay
at a copied database).
"""
from __future__ import annotations
import os
from pathlib import Path

# src/dari/paths.py → src/dari → src → <repo root>
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DATA_DIR    = Path(os.getenv("DARI_DATA_DIR", REPO_ROOT / "data"))
CONFIG_DIR  = REPO_ROOT / "config"
DOCS_DIR    = REPO_ROOT / "docs"
NOTEBOOKS   = REPO_ROOT / "notebooks"

PROFILES_DIR = CONFIG_DIR / "profiles"
RULEBOOK_DIR = CONFIG_DIR / "rulebook"

DB_PATH      = DATA_DIR / "alerts.db"
REPORTS_DIR  = DOCS_DIR / "reports"

DEFAULT_PROFILE = PROFILES_DIR / "patient_001.yaml"


def ensure_dirs() -> None:
    """Create the writable directories if they don't exist yet."""
    for d in (DATA_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
