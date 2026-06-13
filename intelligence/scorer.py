"""The scoring seam.

`score_candidates` is the ONLY thing the future smart-recommender will replace.
Everything else (scheduler, evening loop, Telegram UI, the history log) stays
put. Today its body is a transparent deterministic heuristic; later it becomes
a learned scorer trained on history.jsonl. The signature is the contract:

    score_candidates(category, candidates, history) -> ordered candidates

`candidates` is a list of {title, task_id, project_id} in TickTick priority
order. `history` is the list of past outcome events (see intelligence/history.py).
"""
from __future__ import annotations

from typing import Any

_CARRYOVER_WINDOW_DAYS = 7
_DROP_WINDOW_DAYS = 14


def _recent_titles(history: list[dict[str, Any]], category: str, outcome: str) -> set[str]:
    return {
        e.get("task_title", "")
        for e in history
        if e.get("category") == category and e.get("outcome") == outcome
    }


def score_candidates(
    category: str,
    candidates: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return candidates reordered by a simple, explainable heuristic:

      1. tasks you marked 'didn't get to' recently float to the top,
      2. then everything in its existing TickTick priority order,
      3. tasks you explicitly 'dropped' recently sink to the bottom.

    Stable within each tier. When this becomes a learned model, only this
    function body changes.
    """
    if not candidates:
        return candidates

    skipped = _recent_titles(history, category, "skip")
    dropped = _recent_titles(history, category, "drop")

    def tier(c: dict[str, Any]) -> int:
        title = c.get("title", "")
        if title in skipped:
            return 0
        if title in dropped:
            return 2
        return 1

    return [c for _, c in sorted(enumerate(candidates), key=lambda ic: (tier(ic[1]), ic[0]))]
