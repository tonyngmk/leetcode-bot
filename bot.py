import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import storage
from config import BOT_TOKEN, VALID_INTERVALS
from formatter import format_summary
from leetcode import fetch_all_users, fetch_user_profile, take_snapshot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

JOB_PREFIX = "summary_"
MIDNIGHT_JOB_PREFIX = "midnight_"


# --- Helpers ---

def _chat_id(update: Update) -> str:
    return str(update.effective_chat.id)


def _tz(chat_id: str) -> ZoneInfo:
    return ZoneInfo(storage.get_timezone(chat_id))


async def _take_initial_snapshots(chat_id: str, usernames: list[str]) -> None:
    """Take snapshots, reusing any persisted snapshots for today."""
    tz = _tz(chat_id)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    existing = storage.load_snapshots(chat_id, today)

    # Only fetch users who don't already have a snapshot for today
    need_fetch = [u for u in usernames if u not in existing]
    if not need_fetch:
        logger.info("Chat %s: all %d snapshots loaded from storage", chat_id, len(existing))
        return

    logger.info(
        "Chat %s: %d snapshots from storage, fetching %d",
        chat_id, len(existing), len(need_fetch),
    )
    profiles = await fetch_all_users(need_fetch)
    for username, profile in profiles.items():
        if profile:
            take_snapshot(chat_id, username, profile["counts"], tz)


async def _midnight_snapshot(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Take fresh snapshots at midnight for the new day."""
    chat_id = str(context.job.chat_id)
    users = storage.get_users(chat_id)
    if not users:
        return

    tz = _tz(chat_id)
    profiles = await fetch_all_users(users)
    for username, profile in profiles.items():
        if profile:
            take_snapshot(chat_id, username, profile["counts"], tz)
    logger.info("Midnight snapshots taken for chat %s (%d users)", chat_id, len(users))


async def _send_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(context.job.chat_id)
    users = storage.get_users(chat_id)
    if not users:
        return
    tz = _tz(chat_id)
    profiles = await fetch_all_users(users)
    text = await format_summary(chat_id, profiles, tz)
    await context.bot.send_message(
        chat_id=int(chat_id), text=text, parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


def _schedule_job(app_or_queue, chat_id: str, interval_key: str) -> None:
    """Schedule or remove the recurring summary job for a chat."""
    job_queue = getattr(app_or_queue, "job_queue", app_or_queue)
    job_name = f"{JOB_PREFIX}{chat_id}"

    # Remove existing jobs for this chat
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    seconds = VALID_INTERVALS.get(interval_key)
    if seconds is None:
        return

    job_queue.run_repeating(
        _send_summary,
        interval=seconds,
        first=seconds,
        chat_id=int(chat_id),
        name=job_name,
    )


def _schedule_midnight_job(app_or_queue, chat_id: str) -> None:
    """Schedule a daily midnight job to take fresh snapshots."""
    job_queue = getattr(app_or_queue, "job_queue", app_or_queue)
    job_name = f"{MIDNIGHT_JOB_PREFIX}{chat_id}"

    # Remove existing midnight jobs for this chat
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    tz = _tz(chat_id)
    job_queue.run_daily(
        _midnight_snapshot,
        time=time(0, 0, tzinfo=tz),
        chat_id=int(chat_id),
        name=job_name,
    )


# --- Command Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_help(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*LeetCode Tracker Bot*\n\n"
        "/add\\_user \\<username\\> \\- Track a LeetCode user\n"
        "/remove\\_user \\<username\\> \\- Stop tracking a user\n"
        "/users \\- List tracked users\n"
        "/summary \\- Show today's progress\n"
        "/interval \\<30m\\|1h\\|2h\\|6h\\|1d\\|off\\> \\- Auto summary interval\n"
        "/help \\- Show this message"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /add_user <leetcode_username>")
        return

    username = context.args[0]
    chat_id = _chat_id(update)

    await update.message.reply_text(f"Looking up {username} on LeetCode...")

    profile = await fetch_user_profile(username)
    if profile is None:
        await update.message.reply_text(
            f"Could not find user '{username}' on LeetCode (invalid or private profile)."
        )
        return

    # Use the canonical username from LeetCode
    canonical = profile["username"]

    if not storage.add_user(chat_id, canonical):
        await update.message.reply_text(f"{canonical} is already being tracked.")
        return

    tz = _tz(chat_id)
    take_snapshot(chat_id, canonical, profile["counts"], tz)
    total = sum(profile["counts"].values())
    await update.message.reply_text(
        f"Now tracking {canonical} ({total} problems solved)."
    )


async def cmd_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /remove_user <username>")
        return

    username = context.args[0]
    chat_id = _chat_id(update)

    if storage.remove_user(chat_id, username):
        await update.message.reply_text(f"Stopped tracking {username}.")
    else:
        await update.message.reply_text(f"{username} is not being tracked.")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = storage.get_users(_chat_id(update))
    if not users:
        await update.message.reply_text("No users tracked. Use /add_user <username> to add one.")
        return
    listing = "\n".join(f"- {u}" for u in users)
    await update.message.reply_text(f"Tracked users:\n{listing}")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    users = storage.get_users(chat_id)
    if not users:
        await update.message.reply_text("No users tracked. Use /add_user <username> to add one.")
        return

    tz = _tz(chat_id)
    profiles = await fetch_all_users(users)
    text = await format_summary(chat_id, profiles, tz)
    await update.message.reply_text(
        text, parse_mode="MarkdownV2", disable_web_page_preview=True,
    )


async def cmd_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or context.args[0] not in VALID_INTERVALS:
        options = ", ".join(VALID_INTERVALS.keys())
        await update.message.reply_text(f"Usage: /interval <{options}>")
        return

    interval_key = context.args[0]
    chat_id = _chat_id(update)

    storage.set_interval(chat_id, interval_key)
    _schedule_job(context.job_queue, chat_id, interval_key)

    if interval_key == "off":
        await update.message.reply_text("Automatic summaries disabled.")
    else:
        await update.message.reply_text(f"Automatic summary set to every {interval_key}.")


# --- Startup ---

async def post_init(app: Application) -> None:
    """Restore scheduled jobs and take initial snapshots on startup."""
    all_chats = storage.get_all_chats()
    for chat_id, chat_data in all_chats.items():
        users = chat_data.get("users", [])
        if users:
            await _take_initial_snapshots(chat_id, users)
            _schedule_midnight_job(app, chat_id)

        interval = chat_data.get("interval", "off")
        if interval != "off":
            _schedule_job(app, chat_id, interval)
            logger.info("Restored %s interval for chat %s", interval, chat_id)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Set LEETCODE_BOT_TOKEN environment variable.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("add_user", cmd_add_user))
    app.add_handler(CommandHandler("remove_user", cmd_remove_user))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("interval", cmd_interval))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
