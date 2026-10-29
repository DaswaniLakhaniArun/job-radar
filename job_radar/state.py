"""Remember which offers were already sent, so each email only has new ones.

The file lives in the GitHub Actions cache (not in the repo), so it is never public.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

KEEP_DAYS = 120


def load(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(path: Path, seen: dict[str, str]) -> None:
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    recent = {k: v for k, v in seen.items() if v >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recent, indent=0, sort_keys=True))
