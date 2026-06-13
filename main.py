"""Entry point. Run `python main.py` to start the always-on bot.

Helpers:
  python main.py --whoami   Print the chat id of whoever messages the bot, then exit.
  python main.py --now      Send today's planning message immediately (test the flow).
  python main.py --review   Send tonight's review message immediately (test the flow).
"""
from __future__ import annotations

import os
import sys

import yaml
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from bot import build_application, evening_job, morning_job

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def run_whoami(token: str) -> None:
    async def echo(update: Update, _ctx) -> None:
        cid = update.effective_chat.id
        print(f"chat_id = {cid}")
        await update.message.reply_text(
            f"Your chat id is {cid}\nPut this in .env as TELEGRAM_CHAT_ID."
        )

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.ALL, echo))
    print("Message your bot now; its chat id will print here. Ctrl-C to stop.")
    app.run_polling()


def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN missing — copy .env.example to .env and fill it in.")

    if "--whoami" in sys.argv:
        run_whoami(token)
        return

    config = load_config()
    chat_id_raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    chat_id = int(chat_id_raw) if chat_id_raw else None

    app = build_application(config, token, chat_id)

    if "--now" in sys.argv:
        if chat_id is None:
            sys.exit("--now needs TELEGRAM_CHAT_ID set in .env.")
        app.job_queue.run_once(morning_job, when=2, chat_id=chat_id, name="now")

    if "--review" in sys.argv:
        if chat_id is None:
            sys.exit("--review needs TELEGRAM_CHAT_ID set in .env.")
        app.job_queue.run_once(evening_job, when=2, chat_id=chat_id, name="review-now")

    print("Bot running (long-polling). Ctrl-C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
