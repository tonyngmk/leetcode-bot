"""Lightweight analytics: log every Telegram interaction to daily CSV files."""

import csv
import os
from datetime import datetime, timezone
from typing import Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

ANALYTICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics")

CSV_COLUMNS = [
    "timestamp",
    "user_id",
    "username",
    "first_name",
    "last_name",
    "language_code",
    "chat_id",
    "chat_type",
    "command",
    "arguments",
]


def _get_csv_path() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(ANALYTICS_DIR, f"{today}.csv")


def _extract_command(update: Update) -> Tuple[Optional[str], Optional[str]]:
    """Extract command name and arguments from an Update.

    Returns (command, arguments) or (None, None) for non-command updates.
    """
    # Regular command messages (e.g. /help, /problem two-sum)
    if update.message and update.message.entities:
        for entity in update.message.entities:
            if entity.type == "bot_command" and entity.offset == 0:
                raw = update.message.text[: entity.length]
                # Strip leading / and @botname suffix
                cmd = raw.lstrip("/").split("@")[0]
                args = update.message.text[entity.length :].strip() or None
                return cmd, args

    # Callback queries from inline keyboards
    if update.callback_query and update.callback_query.data:
        data = update.callback_query.data
        if data.startswith("p:"):
            return "callback:problems_page", data
        if data.startswith("s:"):
            return "callback:solution_nav", data
        if data.startswith("tl:"):
            return "callback:test_lang", data
        if data.startswith("sl:"):
            return "callback:submit_lang", data
        return "callback:unknown", data

    return None, None


async def log_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """TypeHandler callback: append one row to today's CSV for every interaction."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    command, arguments = _extract_command(update)
    if command is None:
        return

    csv_path = _get_csv_path()
    file_exists = os.path.exists(csv_path)

    os.makedirs(ANALYTICS_DIR, exist_ok=True)

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user.id,
                "username": user.username or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "language_code": user.language_code or "",
                "chat_id": chat.id,
                "chat_type": chat.type,
                "command": command,
                "arguments": arguments or "",
            }
        )
