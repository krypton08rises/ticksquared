"""Assembles the Telegram Application: registers handlers and schedules jobs."""
from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import (
    cmd_add,
    cmd_courses,
    cmd_plan,
    cmd_review,
    cmd_start,
    evening_job,
    morning_job,
    on_add_text,
    on_callback_guard,
    on_error,
)
from ticktick.client import TickTickAuthError, TickTickClient


def _tz(config: dict[str, Any]) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(config["timezone"])


def build_application(config: dict[str, Any], token: str, chat_id: int | None) -> Application:
    app = Application.builder().token(token).build()
    app.bot_data["config"] = config

    try:
        app.bot_data["ticktick"] = TickTickClient()
    except TickTickAuthError as e:
        print(f"[bot] TickTick not connected: {e}")
        app.bot_data["ticktick"] = None

    me = filters.Chat(chat_id=chat_id) if chat_id is not None else filters.ALL
    if chat_id is None:
        print("[bot] WARNING: TELEGRAM_CHAT_ID not set — bot responds to anyone.")

    app.bot_data["allowed_chat_id"] = chat_id

    app.add_handler(CommandHandler("start",  cmd_start,  filters=me))
    app.add_handler(CommandHandler("plan",   cmd_plan,   filters=me))
    app.add_handler(CommandHandler("review", cmd_review, filters=me))
    app.add_handler(CommandHandler("courses", cmd_courses, filters=me))
    app.add_handler(CommandHandler("add",    cmd_add,    filters=me))
    # Captures the free-text reply after a category is picked in the /add menu.
    # No-ops unless an add is pending, so it never hijacks other messages.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & me, on_add_text))
    app.add_handler(CallbackQueryHandler(on_callback_guard))
    app.add_error_handler(on_error)

    if chat_id is not None:
        hh, mm = config["morning_trigger"].split(":")
        app.job_queue.run_daily(
            morning_job,
            time=dt.time(int(hh), int(mm), tzinfo=_tz(config)),
            chat_id=chat_id,
            name="morning",
        )
        ehh, emm = config.get("evening_trigger", "22:30").split(":")
        app.job_queue.run_daily(
            evening_job,
            time=dt.time(int(ehh), int(emm), tzinfo=_tz(config)),
            chat_id=chat_id,
            name="evening",
        )
    return app
