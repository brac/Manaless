"""Canonical filesystem locations, resolved relative to the project root.

Centralised so the cache and data directories have one definition. Both are
created lazily by their consumers (the disk cache makes its own subdirs).
"""

from pathlib import Path

# src/manaless/paths.py -> src/manaless -> src -> project root.
# NOTE: this assumes the package runs from the source checkout (the intended mode:
# `./run.ps1`/`./run.sh` from the repo). If manaless were ever `pip install`ed
# non-editable, parents[2] would resolve cache/ and data/ into site-packages —
# switch to platformdirs before shipping the package as a distributable.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Runtime cache for API responses (gitignored). See architecture.md caching table.
CACHE_DIR = PROJECT_ROOT / "cache"

# Committed/pulled data: game-changers list, precon calibration set, collection file.
DATA_DIR = PROJECT_ROOT / "data"
