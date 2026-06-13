from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Slot:
    start: str                         # "HH:MM"
    end: str                           # "HH:MM"
    kind: str                          # "fixed" or "focus"
    label: str = ""                    # for fixed blocks
    category: str = ""                 # for focus/commute slots
    task_title: str = ""               # chosen task
    task_id: str = ""                  # TickTick id, if drawn from a real task
    project_id: str = ""               # TickTick list id of the task
    candidates: list[dict] = field(default_factory=list)  # alternatives for reshuffle

    @property
    def is_focus(self) -> bool:
        return self.kind == "focus" or self.category == "commute"
