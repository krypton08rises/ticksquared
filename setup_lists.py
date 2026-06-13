"""One-shot: create the TickTick Lists named in config.yaml and seed them.

Run once (after `python auth.py`):
    python setup_lists.py            # create lists + seed items
    python setup_lists.py --no-seed  # create empty lists only

Idempotent: re-running won't duplicate a list, and only seeds an empty list.
"""
from __future__ import annotations

import sys

import yaml
from dotenv import load_dotenv

from ticktick import TickTickClient

COLORS = {
    "Projects":     "#E25241",
    "Study":        "#4A90D9",
    "Admin":        "#7ED321",
    "Reading Queue":"#F5A623",
}


def collect_lists(config: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cat in config.get("categories", {}).values():
        name = cat.get("ticktick_list")
        if name:
            out[name] = cat.get("items", [])
    commute = config.get("commute", {})
    if commute.get("ticktick_list"):
        out[commute["ticktick_list"]] = commute.get("items", [])
    return out


def main() -> None:
    load_dotenv()
    seed = "--no-seed" not in sys.argv

    config = yaml.safe_load(open("config.yaml"))
    client = TickTickClient()
    lists = collect_lists(config)

    for name, items in lists.items():
        proj = client.get_or_create_project(name, color=COLORS.get(name))
        pid = proj["id"]
        status = "exists" if proj.get("existed") else "CREATED"
        print(f"[{status:7}] {name}  (id={pid})")

        if not seed:
            continue

        existing = client.get_incomplete_tasks(name)
        if existing:
            print(f"          ↳ already has {len(existing)} task(s), skipping seed")
            continue
        for title in items:
            client.create_task(title=title, project_id=pid)
            print(f"          ↳ + {title}")

    print("\nDone. Open TickTick — your Lists are ready.")


if __name__ == "__main__":
    main()
