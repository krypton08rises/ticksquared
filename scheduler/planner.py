"""Builds the day plan: picks a template, fills focus slots with tasks."""
from __future__ import annotations

from datetime import date
from typing import Any

from intelligence.scorer import score_candidates
from scheduler.models import Slot
from ticktick.client import TickTickClient

_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class CandidatePool:
    """Lazily fetches and caches candidate tasks per category from TickTick."""

    def __init__(
        self,
        client: TickTickClient | None,
        config: dict[str, Any],
        history: list[dict] | None = None,
    ):
        self.client = client
        self.config = config
        self.history = history or []
        self._cache: dict[str, list[dict]] = {}

    def for_category(self, category: str) -> list[dict]:
        if category in self._cache:
            return self._cache[category]

        cfg = self._category_cfg(category)
        candidates: list[dict] = []
        list_name = cfg.get("ticktick_list")

        if self.client and list_name:
            try:
                for t in self.client.get_incomplete_tasks(list_name):
                    candidates.append({
                        "title": t.get("title", "(untitled)"),
                        "task_id": t.get("id", ""),
                        "project_id": t.get("projectId", ""),
                    })
            except Exception as e:  # noqa: BLE001
                print(f"[planner] TickTick fetch failed for {category}: {e}")

        if not candidates:
            candidates = [{"title": i, "task_id": "", "project_id": ""}
                          for i in cfg.get("items", [])]

        candidates = score_candidates(category, candidates, self.history)
        self._cache[category] = candidates
        return candidates

    def _category_cfg(self, category: str) -> dict[str, Any]:
        if category == "commute":
            return self.config.get("commute", {})
        return self.config.get("categories", {}).get(category, {})


def select_template(config: dict[str, Any], day: date, work_mode: str) -> dict[str, Any]:
    """work_mode: 'home' | 'office' | 'rest'."""
    templates = config["templates"]
    if work_mode == "rest":
        return templates["rest"]

    key = _WEEKDAY_KEYS[day.weekday()]
    if work_mode == "office" and key in templates["weekday_office"].get("days", []):
        return templates["weekday_office"]
    for name, tpl in templates.items():
        if name in ("rest", "weekday_office"):
            continue
        if key in tpl.get("days", []):
            return tpl
    return templates["weekend"]


def _ordered_categories(config: dict[str, Any]) -> list[str]:
    cats = config.get("categories", {})
    return sorted(cats, key=lambda c: -cats[c].get("weight", 1))


def build_plan(
    config: dict[str, Any],
    day: date,
    work_mode: str,
    client: TickTickClient | None,
    rotation_offset: int = 0,
    history: list[dict] | None = None,
) -> list[Slot]:
    template = select_template(config, day, work_mode)
    pool = CandidatePool(client, config, history)
    strategy = config.get("fill_strategy", "rotation")
    cat_order = _ordered_categories(config)

    used: dict[str, int] = {c: 0 for c in cat_order}
    used["commute"] = 0
    rot = rotation_offset

    slots: list[Slot] = []
    for block in template["blocks"]:
        if block["type"] == "fixed" and not block.get("commute"):
            slots.append(Slot(block["start"], block["end"], "fixed", label=block.get("label", "")))
            continue

        if block.get("commute"):
            category = "commute"
        elif strategy == "priority":
            category = _next_priority_category(cat_order, used, pool)
        else:
            category = cat_order[rot % len(cat_order)] if cat_order else ""
            rot += 1

        candidates = pool.for_category(category)
        idx = used.get(category, 0)
        chosen = candidates[idx] if idx < len(candidates) else (candidates[-1] if candidates else None)
        if candidates:
            used[category] = min(idx + 1, len(candidates) - 1) if len(candidates) > 1 else idx + 1

        slot = Slot(start=block["start"], end=block["end"], kind="focus", category=category, candidates=candidates)
        if chosen:
            slot.task_title = chosen["title"]
            slot.task_id = chosen["task_id"]
            slot.project_id = chosen["project_id"]
        else:
            slot.task_title = "(no candidate — add tasks to this list)"
        slots.append(slot)

    return slots


def _next_priority_category(cat_order, used, pool) -> str:
    for c in cat_order:
        if used.get(c, 0) < len(pool.for_category(c)):
            return c
    return cat_order[0] if cat_order else ""


def isodate_with_offset(day: date, hhmm: str, tz_offset: str) -> str:
    h, m = hhmm.split(":")
    return f"{day.isoformat()}T{int(h):02d}:{int(m):02d}:00{tz_offset}"
