"""Builds the day plan: picks a template, fills focus slots with tasks."""
from __future__ import annotations

from datetime import date
from typing import Any

from intelligence import courses as courses_mod
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
        # Course progress is read from the FULL history (not the windowed slice
        # passed for scoring), so sessions accumulated weeks ago still count.
        self._courses = courses_mod.load_courses()
        self._course_done = courses_mod.done_counts()

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

        candidates = self._lead_with_courses(category, candidates)
        candidates = score_candidates(category, candidates, self.history)
        self._cache[category] = candidates
        return candidates

    def _lead_with_courses(self, category: str, candidates: list[dict]) -> list[dict]:
        """Prepend each feeding course's active step. If that step already exists
        as a real TickTick task (created on a prior day's Confirm), reuse its
        id so the slot updates that one task across sessions instead of spawning
        a duplicate every day."""
        course_cands = courses_mod.candidates_for(category, self._course_done, self._courses)
        if not course_cands:
            return candidates
        by_title = {c["title"]: c for c in candidates}
        front = []
        for cc in course_cands:
            match = by_title.pop(cc["title"], None)
            if match:
                cc["task_id"] = match.get("task_id", "")
                cc["project_id"] = match.get("project_id", "")
            front.append(cc)
        return front + list(by_title.values())

    def _category_cfg(self, category: str) -> dict[str, Any]:
        if category == "commute":
            return self.config.get("commute", {})
        return self.config.get("categories", {}).get(category, {})


def select_template(config: dict[str, Any], day: date, work_mode: str) -> dict[str, Any]:
    """work_mode: 'home' | 'office' | 'free' | 'rest'.

    'free' is a non-work day you still want a full focus plan for (weekend
    template); 'rest' is a total day off with no plan.
    """
    templates = config["templates"]
    if work_mode == "rest":
        return templates["rest"]
    if work_mode == "free":
        return templates["weekend"]

    key = _WEEKDAY_KEYS[day.weekday()]
    if work_mode == "office" and key in templates["weekday_office"].get("days", []):
        return templates["weekday_office"]
    for name, tpl in templates.items():
        if name in ("rest", "weekday_office"):
            continue
        if key in tpl.get("days", []):
            return tpl
    return templates["weekend"]


def _pinned_categories(template: dict[str, Any]) -> set[str]:
    """Categories a template explicitly pins to a focus block (e.g. reading,
    admin). These are placed by the template, so they stay out of the rotation
    pool to avoid doubling up in the generic deep-work slots."""
    return {
        b["category"]
        for b in template.get("blocks", [])
        if b.get("type") == "focus" and b.get("category")
    }


def _ordered_categories(config: dict[str, Any], exclude: set[str] | None = None) -> list[str]:
    """Rotation pool: weight-ordered categories, dropping `add_only` ones
    (capture-only lists the planner must never auto-schedule) and any the
    caller asks to exclude (template-pinned categories)."""
    exclude = exclude or set()
    cats = config.get("categories", {})
    pool = [
        c for c in cats
        if not cats[c].get("add_only", False)
        and not cats[c].get("pinned_only", False)
        and c not in exclude
    ]
    return sorted(pool, key=lambda c: -cats[c].get("weight", 1))


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
    pinned = _pinned_categories(template)
    cat_order = _ordered_categories(config, exclude=pinned)

    used: dict[str, int] = {c: 0 for c in cat_order}
    used["commute"] = 0
    for c in pinned:
        used.setdefault(c, 0)
    rot = rotation_offset

    slots: list[Slot] = []
    for block in template["blocks"]:
        if block["type"] == "fixed" and not block.get("commute"):
            slots.append(Slot(block["start"], block["end"], "fixed", label=block.get("label", "")))
            continue

        if block.get("commute"):
            category = "commute"
        elif block.get("category"):           # template pins this slot
            category = block["category"]
        elif not cat_order:
            category = ""
        elif strategy == "priority":
            category = _next_priority_category(cat_order, used, pool)
        else:
            category = cat_order[rot % len(cat_order)]
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
            slot.course_ref = chosen.get("course_ref", "")
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
