"""All Telegram handler coroutines plus scheduling jobs."""
from __future__ import annotations

import datetime as dt
import logging
import re
import zoneinfo
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

import intelligence.history as history
import storage.state as state
from intelligence import courses
from bot.ui import (
    _MARKS,
    add_menu_keyboard,
    add_subproject_keyboard,
    context_keyboard,
    focus_slots,
    plan_keyboard,
    render_plan,
    render_review,
    review_keyboard,
    safe_edit,
)
from scheduler import Slot, build_plan, isodate_with_offset
from ticktick.client import TickTickClient

log = logging.getLogger(__name__)


# --- timezone helpers ------------------------------------------------------
def _tz(config: dict[str, Any]) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(config["timezone"])


def _tz_offset(config: dict[str, Any], day: dt.date) -> str:
    tz = _tz(config)
    off = dt.datetime.combine(day, dt.time(12, 0), tzinfo=tz).utcoffset() or dt.timedelta()
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}{(total % 3600) // 60:02d}"


# --- error handler ---------------------------------------------------------
async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Handler error", exc_info=ctx.error)


# --- commands --------------------------------------------------------------
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot is live. /plan to plan today, or wait for the morning ping.\n"
        f"Your chat id is `{update.effective_chat.id}`.",
        parse_mode="Markdown",
    )


async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _ask_context(ctx, update.effective_chat.id)


async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_review(ctx, update.effective_chat.id)


async def cmd_courses(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(courses.progress_report(), parse_mode="Markdown")


# --- /add: quick capture into TickTick lists -------------------------------
_URL_RE = re.compile(r"https?://\S+")

_CAT_LABELS = {
    "reading": "Reading",
    "study": "Study",
    "admin": "Admin",
    "work": "Work",
    "inbox": "Inbox",
}


def _list_name(config: dict[str, Any], category: str) -> str | None:
    return config.get("categories", {}).get(category, {}).get("ticktick_list")


async def _add_to_list(
    ctx: ContextTypes.DEFAULT_TYPE,
    list_name: str | None,
    title: str,
    content: str | None = None,
) -> tuple[bool, str | None]:
    client: TickTickClient | None = ctx.application.bot_data.get("ticktick")
    if not client:
        return False, "TickTick not connected — run `python auth.py`."
    if not list_name:
        return False, "No list configured for that category."
    try:
        proj = client.get_or_create_project(list_name)
        client.create_task(title=title, project_id=proj["id"], content=content)
        return True, None
    except Exception as e:  # noqa: BLE001
        log.warning("add_to_list failed: %s", e)
        return False, str(e)


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # One-shot form: `/add buy milk` drops straight into the Inbox.
    if ctx.args:
        config = ctx.application.bot_data["config"]
        text = " ".join(ctx.args).strip()
        ok, err = await _add_to_list(ctx, _list_name(config, "inbox") or "Inbox", text)
        msg = f"➕ Added to *Inbox*:\n{text}" if ok else f"⚠️ Couldn't add: {err}"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    await update.message.reply_text(
        "What do you want to add?", reply_markup=add_menu_keyboard()
    )


async def on_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    config = ctx.application.bot_data["config"]
    parts = query.data.split(":")  # add:cat:<name> | add:proj:<i> | add:cancel
    kind = parts[1]

    if kind == "cancel":
        await query.answer("Cancelled")
        ctx.user_data.pop("pending_add", None)
        await safe_edit(query, "Add cancelled.")
        return

    if kind == "cat":
        cat = parts[2]
        if cat == "projects":
            subs = config["categories"]["projects"].get("subprojects", [])
            await query.answer()
            await safe_edit(query, "Which project?", reply_markup=add_subproject_keyboard(subs))
            return
        label = _CAT_LABELS.get(cat, cat.capitalize())
        ctx.user_data["pending_add"] = {
            "list": _list_name(config, cat),
            "label": label,
            "reading": cat == "reading",
            "prefix": "",
        }
        await query.answer()
        prompt = (
            "Paste a link or paper/blog title 👇"
            if cat == "reading"
            else f"Send the task text for *{label}* 👇"
        )
        await safe_edit(query, prompt)
        return

    if kind == "proj":
        subs = config["categories"]["projects"].get("subprojects", [])
        i = int(parts[2])
        name = subs[i] if 0 <= i < len(subs) else "Projects"
        ctx.user_data["pending_add"] = {
            "list": _list_name(config, "projects"),
            "label": name,
            "reading": False,
            "prefix": f"[{name}] ",
        }
        await query.answer()
        await safe_edit(query, f"Send the task text for *{name}* 👇")


async def on_add_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture the free-text that follows a category pick. No-op unless an /add
    flow is pending, so ordinary messages pass through untouched."""
    pending = ctx.user_data.get("pending_add")
    if not pending:
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    ctx.user_data.pop("pending_add", None)

    title = pending.get("prefix", "") + text
    content = None
    if pending.get("reading"):
        m = _URL_RE.search(text)
        if m:
            content = m.group(0)  # keep the link tappable from the notification

    ok, err = await _add_to_list(ctx, pending.get("list"), title, content)
    if ok:
        await update.message.reply_text(
            f"➕ Added to *{pending['label']}*:\n{title}", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"⚠️ Couldn't add: {err}")


# --- morning flow ----------------------------------------------------------
async def morning_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _ask_context(ctx, ctx.job.chat_id)


async def _ask_context(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await ctx.bot.send_message(
        chat_id,
        f"Good morning ☀️ How's *{dt.datetime.now().strftime('%A %d %b')}* looking?",
        reply_markup=context_keyboard(),
        parse_mode="Markdown",
    )


async def on_context(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":")[1]
    config = ctx.application.bot_data["config"]
    client = ctx.application.bot_data.get("ticktick")
    today = dt.datetime.now(_tz(config)).date()

    meta = state.get_meta()
    past = history.load_events(since_days=14)
    slots = build_plan(
        config, today, mode, client,
        rotation_offset=meta.get("rotation_offset", 0), history=past,
    )
    state.save_day(today, slots, {"work_mode": mode})

    if mode == "rest":
        await safe_edit(query, "Enjoy the day off. 🌴 Nothing scheduled.")
        return
    await safe_edit(query, render_plan(slots), reply_markup=plan_keyboard(slots))


async def on_swap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    config = ctx.application.bot_data["config"]
    today = dt.datetime.now(_tz(config)).date()
    data = state.load_day(today)
    if not data:
        await query.answer("No active plan — run /plan.", show_alert=True)
        return

    slots: list[Slot] = data["slots"]
    idx = int(query.data.split(":")[1])
    slot = slots[idx]
    if not slot.candidates:
        await query.answer("No alternatives for this slot.", show_alert=True)
        return

    cur = next((i for i, c in enumerate(slot.candidates) if c["title"] == slot.task_title), -1)
    nxt = (cur + 1) % len(slot.candidates)
    chosen = slot.candidates[nxt]
    slot.task_title = chosen["title"]
    slot.task_id = chosen["task_id"]
    slot.project_id = chosen["project_id"]
    slot.course_ref = chosen.get("course_ref", "")

    state.save_day(today, slots, data["context"])
    await query.answer(f"→ {chosen['title'][:40]}")
    await safe_edit(query, render_plan(slots), reply_markup=plan_keyboard(slots))


async def on_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    config = ctx.application.bot_data["config"]
    today = dt.datetime.now(_tz(config)).date()
    state.save_day(today, [], {"work_mode": "rest"})
    await safe_edit(query, "Day written off. 🌙 Rest up.")


async def on_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Syncing to TickTick…")
    config = ctx.application.bot_data["config"]
    client: TickTickClient | None = ctx.application.bot_data.get("ticktick")
    today = dt.datetime.now(_tz(config)).date()
    data = state.load_day(today)
    if not data:
        await safe_edit(query, "No active plan to confirm.")
        return

    slots: list[Slot] = data["slots"]
    offset = _tz_offset(config, today)
    created, errors = 0, 0

    if client:
        for s in (sl for sl in slots if sl.is_focus and sl.task_title):
            start = isodate_with_offset(today, s.start, offset)
            end = isodate_with_offset(today, s.end, offset)
            try:
                if s.task_id and s.project_id:
                    # Existing task (e.g. a queued reading link): stamp tonight's
                    # slot time so TickTick fires a reminder for it.
                    client.update_task(s.task_id, s.project_id, start=start, end=end)
                elif not s.task_id:
                    client.create_task(
                        title=s.task_title,
                        start=start,
                        end=end,
                        content=f"Scheduled by bot — {s.category} slot.",
                    )
                created += 1
            except Exception as e:  # noqa: BLE001
                log.warning("sync task failed: %s", e)
                errors += 1

    meta = state.get_meta()
    meta["rotation_offset"] = meta.get("rotation_offset", 0) + len(focus_slots(slots))
    state.set_meta(meta)

    note = "" if not errors else f" ({errors} failed — check logs)"
    tail = "Synced to TickTick." if client else "TickTick not connected — plan saved locally only."
    await safe_edit(query, render_plan(slots) + f"\n\n✅ *Locked in.* {tail}{note}")


# --- evening review --------------------------------------------------------
async def evening_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_review(ctx, ctx.job.chat_id)


async def _send_review(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    config = ctx.application.bot_data["config"]
    today = dt.datetime.now(_tz(config)).date()
    data = state.load_day(today)
    if not data or not focus_slots(data["slots"]):
        await ctx.bot.send_message(chat_id, "Nothing to review tonight. 🌙")
        return
    outcomes = data["context"].get("outcomes", {})
    await ctx.bot.send_message(
        chat_id,
        render_review(data["slots"], outcomes),
        reply_markup=review_keyboard(data["slots"]),
        parse_mode="Markdown",
    )


async def on_review_mark(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    config = ctx.application.bot_data["config"]
    today = dt.datetime.now(_tz(config)).date()
    data = state.load_day(today)
    if not data:
        await query.answer("No plan to review — run /plan first.", show_alert=True)
        return

    _, idx, outcome = query.data.split(":")
    outcomes = data["context"].setdefault("outcomes", {})
    outcomes[idx] = outcome
    state.save_day(today, data["slots"], data["context"])
    await query.answer(f"{_MARKS[outcome]} slot {int(idx)}")
    await safe_edit(query, render_review(data["slots"], outcomes), reply_markup=review_keyboard(data["slots"]))


async def on_review_submit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Saving review…")
    config = ctx.application.bot_data["config"]
    client: TickTickClient | None = ctx.application.bot_data.get("ticktick")
    today = dt.datetime.now(_tz(config)).date()
    data = state.load_day(today)
    if not data:
        await safe_edit(query, "No plan to review.")
        return

    slots: list[Slot] = data["slots"]
    outcomes = data["context"].get("outcomes", {})
    day_type = data["context"].get("work_mode", "")
    counts = {"done": 0, "skip": 0, "drop": 0, "unmarked": 0}
    finished_steps: list[str] = []

    for i, s in enumerate(slots):
        if not s.is_focus:
            continue
        outcome = outcomes.get(str(i))
        if not outcome:
            counts["unmarked"] += 1
            continue
        counts[outcome] += 1

        # For a course-driven slot, this done event is one of N sessions. Decide
        # whether it's the last one BEFORE logging it — only then do we close the
        # TickTick task; otherwise it stays open to resurface for the next session.
        final = courses.is_final_session(s.course_ref) if outcome == "done" else False

        history.append_event({
            "date": today.isoformat(),
            "day_type": day_type,
            "slot_index": i,
            "start": s.start,
            "end": s.end,
            "category": s.category,
            "task_title": s.task_title,
            "task_id": s.task_id,
            "project_id": s.project_id,
            "course_ref": s.course_ref,
            "offered_alternatives": [c["title"] for c in s.candidates],
            "outcome": outcome,
        })

        if outcome == "done" and final and client and s.task_id and s.project_id:
            try:
                client.complete_task(s.project_id, s.task_id)
            except Exception as e:  # noqa: BLE001
                log.warning("complete_task failed: %s", e)
        if outcome == "done" and s.course_ref and final:
            finished_steps.append(s.task_title)

    summary = (
        f"*Review saved.* ✅ {counts['done']}  ⏭️ {counts['skip']}  ❌ {counts['drop']}"
        + (f"  ·{counts['unmarked']} unmarked" if counts["unmarked"] else "")
    )
    tail = "\n_Skipped tasks will float up tomorrow morning._" if counts["skip"] else ""
    if finished_steps:
        tail += "\n📘 Course step complete: " + ", ".join(finished_steps)
    await safe_edit(query, summary + tail)


# --- callback guard + router -----------------------------------------------
_ROUTES = {
    r"^ctx:":      on_context,
    r"^swap:":     on_swap,
    r"^confirm$":  on_confirm,
    r"^off$":      on_off,
    r"^evr:":      on_review_mark,
    r"^evsubmit$": on_review_submit,
    r"^add:":      on_add,
}


async def on_callback_guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Single catch-all for all inline keyboard callbacks.
    Silently drops anything not from the allowed chat, then routes by pattern.
    """
    allowed = ctx.application.bot_data.get("allowed_chat_id")
    if allowed is not None and update.effective_chat.id != allowed:
        return

    data = (update.callback_query.data or "")
    for pattern, handler in _ROUTES.items():
        if re.match(pattern, data):
            await handler(update, ctx)
            return
    await update.callback_query.answer()
