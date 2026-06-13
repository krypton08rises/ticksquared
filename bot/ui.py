"""Pure rendering layer: text formatting and keyboard builders.

No side effects — every function takes data, returns Telegram objects or strings.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from scheduler.models import Slot

_MARKS = {"done": "✅", "skip": "⏭️", "drop": "❌"}
_MARK_NONE = "·"


async def safe_edit(query, text: str, reply_markup=None) -> None:
    """Edit a message, swallowing Telegram's harmless 'not modified' error."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def focus_slots(slots: list[Slot]) -> list[tuple[int, Slot]]:
    return [(i, s) for i, s in enumerate(slots) if s.is_focus]


# --- plan UI ---------------------------------------------------------------
def render_plan(slots: list[Slot]) -> str:
    lines = ["*Today's plan*", ""]
    n = 0
    for s in slots:
        if s.kind == "fixed" and not s.category:
            lines.append(f"`{s.start}-{s.end}`  {s.label}")
        else:
            n += 1
            lines.append(f"`{s.start}-{s.end}`  *[{n}] {s.category.capitalize()}* — {s.task_title}")
    if n:
        lines += ["", "_Tap a slot number to cycle its task, then Confirm to sync._"]
    return "\n".join(lines)


def plan_keyboard(slots: list[Slot]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for n, (i, _) in enumerate(focus_slots(slots), start=1):
        row.append(InlineKeyboardButton(f"🔄 {n}", callback_data=f"swap:{i}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✅ Confirm & sync", callback_data="confirm"),
        InlineKeyboardButton("😴 Day off", callback_data="off"),
    ])
    return InlineKeyboardMarkup(rows)


# --- /add UI ---------------------------------------------------------------
# First-level menu. Each button maps a category to its TickTick list. The two
# "add_only" capture lists (Work, Quick/Inbox) sit alongside the schedulable
# ones so everything is reachable in one tap.
def add_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📚 Reading", callback_data="add:cat:reading"),
            InlineKeyboardButton("🗂 Projects", callback_data="add:cat:projects"),
        ],
        [
            InlineKeyboardButton("📖 Study", callback_data="add:cat:study"),
            InlineKeyboardButton("🧹 Admin", callback_data="add:cat:admin"),
        ],
        [
            InlineKeyboardButton("💼 Work", callback_data="add:cat:work"),
            InlineKeyboardButton("⚡ Quick", callback_data="add:cat:inbox"),
        ],
        [InlineKeyboardButton("✖ Cancel", callback_data="add:cancel")],
    ])


def add_subproject_keyboard(subprojects: list[str]) -> InlineKeyboardMarkup:
    """Second level shown after tapping Projects: one button per sub-project,
    addressed by index so names with spaces/punctuation are safe in callbacks."""
    rows, row = [], []
    for i, name in enumerate(subprojects):
        row.append(InlineKeyboardButton(name, callback_data=f"add:proj:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="add:cancel")])
    return InlineKeyboardMarkup(rows)


def context_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Work (home)", callback_data="ctx:home"),
            InlineKeyboardButton("🏢 Work (office)", callback_data="ctx:office"),
        ],
        [InlineKeyboardButton("🌟 Free day (full focus)", callback_data="ctx:free")],
        [InlineKeyboardButton("😴 Day off / GF / vacation", callback_data="ctx:rest")],
    ])


# --- review UI -------------------------------------------------------------
def render_review(slots: list[Slot], outcomes: dict[str, str]) -> str:
    lines = ["*Evening review* — how did today's slots go?", ""]
    n = 0
    for i, s in enumerate(slots):
        if not s.is_focus:
            continue
        n += 1
        mark = _MARKS.get(outcomes.get(str(i), ""), _MARK_NONE)
        lines.append(f"{mark} *[{n}]* `{s.start}-{s.end}` {s.task_title}")
    lines += [
        "",
        "✅ done   ⏭️ didn't get to   ❌ drop",
        "_Mark each, then Submit. 'Didn't get to' bubbles up tomorrow._",
    ]
    return "\n".join(lines)


def review_keyboard(slots: list[Slot]) -> InlineKeyboardMarkup:
    rows = []
    n = 0
    for i, s in enumerate(slots):
        if not s.is_focus:
            continue
        n += 1
        rows.append([
            InlineKeyboardButton(f"{n} ✅", callback_data=f"evr:{i}:done"),
            InlineKeyboardButton("⏭️", callback_data=f"evr:{i}:skip"),
            InlineKeyboardButton("❌", callback_data=f"evr:{i}:drop"),
        ])
    rows.append([InlineKeyboardButton("💾 Submit review", callback_data="evsubmit")])
    return InlineKeyboardMarkup(rows)
