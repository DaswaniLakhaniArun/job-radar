"""What job-radar remembers between weeks (stored on the `state` branch, as hashes and dates only).

- sent:      offers already emailed (key -> date)
- board:     last status seen on the board for each offer (key -> {"status", "since"})
- last_seen: last week an offer on the board still appeared in the search (key -> date)
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

KEEP_DAYS = 120


def empty() -> dict:
    return {"sent": {}, "board": {}, "last_seen": {}}


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return empty()
    if "sent" not in data:  # first version stored only {key: date}
        data = {"sent": data}
    out = empty()
    out.update({k: v for k, v in data.items() if isinstance(v, dict)})
    return out


def save(path: Path, st: dict) -> None:
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    st = dict(st)
    st["sent"] = {k: v for k, v in st.get("sent", {}).items() if v >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=0, sort_keys=True, ensure_ascii=False))
