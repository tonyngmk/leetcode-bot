import logging
import shlex
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import storage
from config import BOT_TOKEN, VALID_INTERVALS
from formatter import (
    _esc,
    format_daily,
    format_daily_challenge,
    format_leaderboard,
    format_problem_detail,
    format_problems,
    format_weekly,
)
from leetcode import (
    extract_images,
    fetch_all_users,
    fetch_daily_challenge,
    fetch_problem,
    fetch_problems,
    fetch_user_profile,
    map_images_to_examples,
    take_snapshot,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

JOB_PREFIX = "summary_"
MIDNIGHT_JOB_PREFIX = "midnight_"

# Store bot username for generating deep links
_bot_username = None


# --- Helpers ---

def _chat_id(update: Update) -> str:
    return str(update.effective_chat.id)


def _tz(chat_id: str) -> ZoneInfo:
    return ZoneInfo(storage.get_timezone(chat_id))


async def _send_problem_images(update: Update, content: str) -> None:
    """Send problem images as separate photo messages with example captions."""
    images = extract_images(content)  # Filters to .jpeg by default
    image_mapping = map_images_to_examples(content)  # Map images to example numbers
    for image_url in images[:3]:  # Limit to 3 images
        try:
            example_num = image_mapping.get(image_url)
            if example_num:
                caption = f"Example {example_num}"
            else:
                caption = None
            await update.message.reply_photo(image_url, caption=caption)
        except Exception as e:
            logger.warning(f"Failed to send image {image_url}: {e}")


async def _take_initial_snapshots(chat_id: str, usernames: list[str]) -> None:
    """Take snapshots for all users."""
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
    text = await format_leaderboard(chat_id, profiles, tz)
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
    # Check for problem_ payload from deep link
    if context.args and context.args[0].startswith("problem_"):
        slug = context.args[0][8:]  # Remove "problem_" prefix
        question = await fetch_problem(slug)
        if question is None:
            await update.message.reply_text(f"Problem '{slug}' not found.")
            return
        text = format_problem_detail(question)
        # format_problem_detail outputs HTML, not MarkdownV2
        await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

        content = question.get("content", "")
        await _send_problem_images(update, content)
        return

    # Normal /start → show help
    await cmd_help(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*LeetCode Tracker Bot*\n\n"
        "*Tracking:*\n"
        "/add\\_user \\<username\\> \\- Track a LeetCode user\n"
        "/remove\\_user \\<username\\> \\- Stop tracking a user\n"
        "/users \\- List tracked users\n"
        "/summary \\- Daily \\+ weekly leaderboard\n"
        "/daily \\- Today's problems per user\n"
        "/weekly \\- This week's problems per user\n"
        "/interval \\<30m\\|1h\\|2h\\|6h\\|1d\\|off\\> \\- Auto summary interval\n\n"
        "*Browsing:*\n"
        "/problems \\[difficulty\\] \\[tags\\] \\- Browse problems\n"
        "  Examples: /problems  /problems easy  /problems easy array\n"
        "  Multi\\-word tags: /problems \"dynamic programming\" easy\n"
        "/problem \\<slug\\> \\- Problem details \\(e\\.g\\. /problem two\\-sum\\)\n"
        "/challenge \\- Today's daily challenge\n\n"
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
    text = await format_leaderboard(chat_id, profiles, tz)
    await update.message.reply_text(
        text, parse_mode="MarkdownV2", disable_web_page_preview=True,
    )


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    users = storage.get_users(chat_id)
    if not users:
        await update.message.reply_text("No users tracked. Use /add_user <username> to add one.")
        return

    tz = _tz(chat_id)
    profiles = await fetch_all_users(users)
    text = await format_daily(chat_id, profiles, tz, bot_username=_bot_username)
    await update.message.reply_text(
        text, parse_mode="MarkdownV2", disable_web_page_preview=True,
    )


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    users = storage.get_users(chat_id)
    if not users:
        await update.message.reply_text("No users tracked. Use /add_user <username> to add one.")
        return

    tz = _tz(chat_id)
    profiles = await fetch_all_users(users)
    text = await format_weekly(chat_id, profiles, tz, bot_username=_bot_username)
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


# --- Pagination Helpers for /problems ---

PAGE_SIZE = 20


def _encode_problems_callback(page: int, difficulty: Optional[str], tags: list[str]) -> str:
    """Encode state into ≤64-byte callback string: `p:{page}:{diff}:{tags}`."""
    diff_map = {"EASY": "E", "MEDIUM": "M", "HARD": "H"}
    diff_char = diff_map.get(difficulty or "", "")
    tags_str = ",".join(tags)
    payload = f"p:{page}:{diff_char}:{tags_str}"
    # Guard: truncate tags to stay within Telegram's 64-byte limit
    while len(payload.encode()) > 64 and tags_str:
        tags_str = tags_str.rsplit(",", 1)[0]
        payload = f"p:{page}:{diff_char}:{tags_str}"
    return payload


def _decode_problems_callback(data: str) -> tuple:  # (int, Optional[str], list[str])
    """Parse callback string back to (page, difficulty, tags)."""
    parts = data.split(":", 3)
    page = int(parts[1])
    diff_map = {"E": "EASY", "M": "MEDIUM", "H": "HARD"}
    difficulty = diff_map.get(parts[2]) or None
    tags = [t for t in parts[3].split(",") if t] if len(parts) > 3 and parts[3] else []
    return page, difficulty, tags


def _build_problems_keyboard(
    page: int, total: int, page_size: int,
    difficulty: Optional[str], tags: list[str],
) -> Optional[InlineKeyboardMarkup]:
    """Build Prev/Next inline keyboard, or return None if no buttons are needed."""
    has_prev = page > 0
    has_next = (page + 1) * page_size < total
    if not has_prev and not has_next:
        return None
    buttons = []
    if has_prev:
        buttons.append(InlineKeyboardButton("⬅ Prev", callback_data=_encode_problems_callback(page - 1, difficulty, tags)))
    if has_next:
        buttons.append(InlineKeyboardButton("Next ➡", callback_data=_encode_problems_callback(page + 1, difficulty, tags)))
    return InlineKeyboardMarkup([buttons])


async def cmd_problems(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Parse raw message text with shlex to support quoted multi-word tags
    text = update.message.text
    parts = text.split(None, 1)  # Split at first space only
    if len(parts) < 2:
        args = []
    else:
        try:
            args = shlex.split(parts[1])  # Preserves quoted strings
        except ValueError:
            await update.message.reply_text("Invalid command format (mismatched quotes)")
            return

    args = [a.lower() for a in args]
    difficulty = None
    tags = []
    for arg in args:
        if arg in ("easy", "medium", "hard"):
            difficulty = arg.upper()
        else:
            # Convert spaces to hyphens to match LeetCode tag slugs
            # e.g., "dynamic programming" → "dynamic-programming"
            tags.append(arg.replace(" ", "-"))

    result = await fetch_problems(difficulty=difficulty, tags=tags or None, skip=0, limit=PAGE_SIZE)
    if result is None:
        await update.message.reply_text("Failed to fetch problems.")
        return

    total = result.get("total", 0)
    filters_desc = " · ".join(filter(None, ([difficulty.capitalize()] if difficulty else []) + tags))
    text = format_problems(result, _esc(filters_desc), page=0, page_size=PAGE_SIZE, bot_username=_bot_username)
    keyboard = _build_problems_keyboard(0, total, PAGE_SIZE, difficulty, tags)
    await update.message.reply_text(
        text, parse_mode="MarkdownV2", disable_web_page_preview=True, reply_markup=keyboard,
    )


async def cmd_problems_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Prev/Next button presses for /problems pagination."""
    query = update.callback_query
    await query.answer()

    page, difficulty, tags = _decode_problems_callback(query.data)
    result = await fetch_problems(
        difficulty=difficulty, tags=tags or None,
        skip=page * PAGE_SIZE, limit=PAGE_SIZE,
    )
    if result is None:
        await query.answer("Failed to fetch problems.", show_alert=True)
        return

    total = result.get("total", 0)
    filters_desc = " · ".join(filter(None, ([difficulty.capitalize()] if difficulty else []) + tags))
    text = format_problems(result, _esc(filters_desc), page=page, page_size=PAGE_SIZE, bot_username=_bot_username)
    keyboard = _build_problems_keyboard(page, total, PAGE_SIZE, difficulty, tags)
    try:
        await query.edit_message_text(
            text, parse_mode="MarkdownV2", disable_web_page_preview=True, reply_markup=keyboard,
        )
    except Exception:
        pass  # Ignore "Message is not modified" on rapid double-taps


async def cmd_problem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /problem <title-slug>  e.g. /problem two-sum")
        return

    slug = context.args[0]
    question = await fetch_problem(slug)
    if question is None:
        await update.message.reply_text(f"Problem '{slug}' not found.")
        return

    text = format_problem_detail(question)
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

    content = question.get("content", "")
    await _send_problem_images(update, content)


async def cmd_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    challenge = await fetch_daily_challenge()
    if challenge is None:
        await update.message.reply_text("Failed to fetch daily challenge.")
        return

    text = format_daily_challenge(challenge)
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

    question = challenge.get("question", {})
    content = question.get("content", "")
    await _send_problem_images(update, content)


# --- Startup ---

async def post_init(app: Application) -> None:
    """Restore scheduled jobs, take initial snapshots, and store bot username on startup."""
    global _bot_username
    _bot_username = app.bot.username

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
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("interval", cmd_interval))
    app.add_handler(CommandHandler("problems", cmd_problems))
    app.add_handler(CallbackQueryHandler(cmd_problems_page, pattern=r"^p:"))
    app.add_handler(CommandHandler("problem", cmd_problem))
    app.add_handler(CommandHandler("challenge", cmd_challenge))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
