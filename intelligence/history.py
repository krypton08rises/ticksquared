"""Append-only outcome log — the durable record of what was offered, chosen,
and how it turned out. This is the permanent artifact: the future recommender
trains on exactly these events. Nothing here is throwaway.

One JSON object per line (JSONL) so it's append-cheap and easy to stream/replay.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HISTORY_PATH = Path(__file__).parent.parent / "state" / "history.jsonl"


def append_event(event: dict[str, Any]) -> None:
    """Append one outcome event. `event` should carry at least:
    date, day_type, slot_index, start, end, category, task_title, task_id,
    project_id, offered_alternatives (list[str]), outcome.
    """
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    event.setdefault("logged_at", datetime.now().isoformat(timespec="seconds"))
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


def load_events(since_days: int | None = None) -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    events: list[dict[str, Any]] = []
    cutoff = (
        datetime.now() - timedelta(days=since_days) if since_days is not None else None
    )
    for line in HISTORY_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff is not None:
            stamp = ev.get("logged_at")
            if stamp and datetime.fromisoformat(stamp) < cutoff:
                continue
        events.append(ev)
    return events
