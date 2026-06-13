"""Per-day JSON state + a small persistent meta file.

No database needed at this scale. State survives bot restarts so a tapped
button still works if the process was bounced.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from scheduler.models import Slot

STATE_DIR = Path(__file__).parent.parent / "state"
META_PATH = STATE_DIR / "meta.json"


def _ensure_dir() -> None:
    STATE_DIR.mkdir(exist_ok=True)


def day_path(day: date) -> Path:
    return STATE_DIR / f"{day.isoformat()}.json"


def save_day(day: date, slots: list[Slot], context: dict[str, Any]) -> None:
    _ensure_dir()
    payload = {
        "date": day.isoformat(),
        "context": context,
        "slots": [asdict(s) for s in slots],
    }
    day_path(day).write_text(json.dumps(payload, indent=2))


def load_day(day: date) -> dict[str, Any] | None:
    p = day_path(day)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    data["slots"] = [Slot(**s) for s in data["slots"]]
    return data


def get_meta() -> dict[str, Any]:
    _ensure_dir()
    if META_PATH.exists():
        return json.loads(META_PATH.read_text())
    return {"rotation_offset": 0}


def set_meta(meta: dict[str, Any]) -> None:
    _ensure_dir()
    META_PATH.write_text(json.dumps(meta, indent=2))
