"""Standalone sanity test for the course runner. No TickTick, no Telegram, no
writes to the real history log — every function is exercised with synthetic
events. Run:  python test_courses.py
"""
from __future__ import annotations

import datetime as dt

import yaml

from intelligence import courses
from scheduler.planner import build_plan

PASS, FAIL = "✅", "❌"
_fails = 0


def check(label: str, cond: bool) -> None:
    global _fails
    print(f"  {PASS if cond else FAIL} {label}")
    _fails += 0 if cond else 1


def done_events(ref: str, n: int) -> list[dict]:
    return [{"outcome": "done", "course_ref": ref} for _ in range(n)]


print("\n[1] load_courses() reads the real courses/finance.yaml")
cs = courses.load_courses()
fin = next((c for c in cs if c.id == "finance"), None)
check("finance course loaded", fin is not None)
check("category is projects", fin.category == "projects")
check("subproject is Finance", fin.subproject == "Finance")
check("steps flattened across phases (>10)", len(fin.steps) > 10)
p0r1 = fin.steps[0]
check("first step is p0-r1 with 9 sessions", p0r1.id == "p0-r1" and p0r1.sessions == 9)

print("\n[2] active_step walks in order as sessions accumulate")
check("nothing done -> active is p0-r1", fin.active_step({}).id == "p0-r1")
check("p0-r1 partly done (8/9) -> still p0-r1",
      fin.active_step({"finance/p0-r1": 8}).id == "p0-r1")
check("p0-r1 fully done (9/9) -> advances to p0-r2",
      fin.active_step({"finance/p0-r1": 9}).id == "p0-r2")

print("\n[3] candidates_for surfaces active steps, tagged like /add, priority-ordered")
cands = courses.candidates_for("projects", done={})
refs = [c["course_ref"] for c in cands]
check("finance is among the projects candidates", "finance/p0-r1" in refs)
fin_cand = next(c for c in cands if c["course_ref"] == "finance/p0-r1")
check("title is '[Finance] <step>'", fin_cand["title"].startswith("[Finance] "))
check("Forge (priority 1) leads the pool", refs[0] == "hcf/p0-r1")
check("no candidates for an unrelated category", courses.candidates_for("study", done={}) == [])

print("\n[4] is_final_session decides when to close the TickTick task")
check("8 done, sessions=9 -> next is final", courses.is_final_session("finance/p0-r1", done_events("finance/p0-r1", 8)))
check("7 done, sessions=9 -> not final yet", not courses.is_final_session("finance/p0-r1", done_events("finance/p0-r1", 7)))
check("empty ref (ordinary task) -> always final", courses.is_final_session(""))

print("\n[5] a gate checkpoint locks the next phase until done")
# Finish every step in phase 0 EXCEPT the gate checkpoint p0-cp.
done = {"finance/p0-r1": 9, "finance/p0-r2": 4, "finance/p0-e1": 3}
active = fin.active_step(done)
check("active is the gate checkpoint p0-cp", active.id == "p0-cp" and active.gate)
fin_refs = [c["course_ref"] for c in courses.candidates_for("projects", done=done)]
check("phase 1 stays locked (gate surfaced, p1-r1 not)",
      "finance/p0-cp" in fin_refs and "finance/p1-r1" not in fin_refs)
done["finance/p0-cp"] = 1
check("gate cleared -> advances into phase 1 (p1-r1)", fin.active_step(done).id == "p1-r1")

print("\n[6] progress_report renders without error")
rep = courses.progress_report(done_events("finance/p0-r1", 3))
check("report mentions the course", "From Zero" in rep or "Finance" in rep)
check("report shows a session count", "/9 sessions" in rep)

print("\n[7] planner integration: a course leads its category's slots")
config = yaml.safe_load(open("config.yaml").read())
# A weekend ('free') day has several projects slots; client=None -> items fallback.
slots = build_plan(config, dt.date(2026, 6, 21), "free", client=None, history=[])
proj = [s for s in slots if s.category == "projects" and s.task_title]
check("at least one projects slot built", len(proj) > 0)
check("first projects slot is the top-priority course step (Forge)",
      proj[0].course_ref == "hcf/p0-r1" and proj[0].task_title.startswith("[Forge] "))

print(f"\n{'ALL PASSED' if _fails == 0 else str(_fails) + ' FAILED'}")
raise SystemExit(1 if _fails else 0)
