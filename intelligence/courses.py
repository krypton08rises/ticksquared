"""Course runner: turns courses/*.yaml curricula into scheduled candidates.

A course is a phased curriculum (phases -> steps). Each step needs `sessions`
focus slots of work. Progress is a PURE FUNCTION of the history log: a step is
complete once it has accumulated `sessions` worth of 'done' events tagged with
its course_ref. The active step is the first incomplete step in phase/step
order; a gated checkpoint naturally blocks everything after it until it's done.

Nothing here mutates state — history.jsonl stays the single source of truth, so
course progress can never desync from what actually happened. Drop a YAML file
in courses/ (see courses/finance.yaml for the shape) and it starts driving the
matching scheduler category the next morning. No file? This module returns
nothing and the planner behaves exactly as before.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

import intelligence.history as history

COURSES_DIR = Path(__file__).parent.parent / "courses"


@dataclass
class Step:
    id: str
    title: str
    sessions: int = 1
    kind: str = ""          # reading | exercise | checkpoint | habit (descriptive)
    gate: bool = False      # a gate checkpoint blocks the rest of the course until done
    resource: str = ""
    detail: str = ""


@dataclass
class Course:
    id: str
    title: str
    category: str           # which scheduler category this course feeds
    subproject: str         # tags the candidate "[<subproject>] ..." like /add does
    ticktick_list: str
    steps: list[Step] = field(default_factory=list)   # flattened across phases, in order
    priority: int = 100     # lower = surfaces first when several courses share a category

    def ref(self, step: Step) -> str:
        return f"{self.id}/{step.id}"

    def active_step(self, done: dict[str, int]) -> Step | None:
        """First step whose required sessions aren't all done yet, in order.
        A gate checkpoint that isn't done stops the walk, locking later phases."""
        for st in self.steps:
            if done.get(self.ref(st), 0) < max(1, st.sessions):
                return st
        return None


# --- loading ---------------------------------------------------------------
def load_courses(courses_dir: Path = COURSES_DIR) -> list[Course]:
    courses: list[Course] = []
    if not courses_dir.exists():
        return courses
    for path in sorted(courses_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except Exception as e:  # noqa: BLE001 — one bad file must not break planning
            print(f"[courses] failed to parse {path.name}: {e}")
            continue
        steps: list[Step] = []
        for phase in raw.get("phases", []):
            for st in phase.get("steps", []):
                steps.append(Step(
                    id=st.get("id", ""),
                    title=st.get("title", "(untitled step)"),
                    sessions=int(st.get("sessions", 1) or 1),
                    kind=st.get("kind", ""),
                    gate=bool(st.get("gate", False)),
                    resource=st.get("resource", ""),
                    detail=st.get("detail", ""),
                ))
        courses.append(Course(
            id=raw.get("id", path.stem),
            title=raw.get("title", path.stem),
            category=raw.get("category", "projects"),
            subproject=raw.get("subproject", ""),
            ticktick_list=raw.get("ticktick_list", "Projects"),
            steps=steps,
            priority=int(raw.get("priority", 100)),
        ))
    return courses


# --- progress (derived purely from history) --------------------------------
def done_counts(events: list[dict[str, Any]] | None = None) -> dict[str, int]:
    """Map course_ref -> number of completed sessions, read from the log."""
    if events is None:
        events = history.load_events()
    counts: dict[str, int] = {}
    for e in events:
        if e.get("outcome") == "done":
            ref = e.get("course_ref")
            if ref:
                counts[ref] = counts.get(ref, 0) + 1
    return counts


def _candidate(course: Course, step: Step) -> dict[str, Any]:
    prefix = f"[{course.subproject}] " if course.subproject else ""
    return {
        "title": f"{prefix}{step.title}",
        "task_id": "",
        "project_id": "",
        "course_ref": course.ref(step),
    }


def candidates_for(
    category: str,
    done: dict[str, int] | None = None,
    courses: list[Course] | None = None,
) -> list[dict[str, Any]]:
    """The active step of every course feeding `category`, as planner candidates
    (one per course, priority-ordered). These lead the candidate pool so a course
    drives its slot; the user can still reshuffle to manual tasks."""
    if courses is None:
        courses = load_courses()
    if done is None:
        done = done_counts()
    out: list[dict[str, Any]] = []
    for c in sorted(courses, key=lambda c: (c.priority, c.id)):
        if c.category != category:
            continue
        step = c.active_step(done)
        if step:
            out.append(_candidate(c, step))
    return out


def _step_by_ref(ref: str, courses: list[Course] | None = None) -> tuple[Course, Step] | None:
    if courses is None:
        courses = load_courses()
    cid, _, sid = ref.partition("/")
    for c in courses:
        if c.id == cid:
            for st in c.steps:
                if st.id == sid:
                    return c, st
    return None


def is_final_session(ref: str, events: list[dict[str, Any]] | None = None) -> bool:
    """Would completing one more session finish this step? If so the TickTick
    task should be closed; otherwise it stays open to resurface tomorrow.

    Pass the history *before* recording the current done event. Non-course
    refs (empty string) always return True, so ordinary tasks complete on done
    exactly as before."""
    if not ref:
        return True
    found = _step_by_ref(ref)
    if not found:
        return True
    _, step = found
    return done_counts(events).get(ref, 0) + 1 >= max(1, step.sessions)


def progress_report(events: list[dict[str, Any]] | None = None) -> str:
    """Markdown summary for the /courses command."""
    courses = load_courses()
    if not courses:
        return "No courses loaded. Drop a curriculum YAML in `courses/` to begin."
    done = done_counts(events)
    lines = ["*Course progress*", ""]
    for c in sorted(courses, key=lambda c: (c.priority, c.id)):
        total = len(c.steps)
        completed = sum(1 for s in c.steps if done.get(c.ref(s), 0) >= max(1, s.sessions))
        sub = f" · _{c.subproject}_" if c.subproject else ""
        lines.append(f"*{c.title}*{sub}")
        step = c.active_step(done)
        if step:
            d = done.get(c.ref(step), 0)
            gate = " 🔒" if step.gate else ""
            lines.append(f"  ▸ now: {step.title}{gate}  ({d}/{step.sessions} sessions)")
            lines.append(f"  ☑ {completed}/{total} steps")
        else:
            lines.append(f"  ✔ complete — {total}/{total} steps")
        lines.append("")
    return "\n".join(lines).rstrip()
