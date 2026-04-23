import asyncio
import logging
import os
import shlex
import time as _time_mod
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

# Load .env before importing config
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

import storage
from analytics import log_event
from config import BOT_TOKEN, VALID_INTERVALS
from config import LEETCODE_LANG_SLUGS
from formatter import (
    LANGUAGE_DISPLAY,
    _esc,
    format_code_prompt,
    format_daily,
    format_daily_challenge,
    format_leaderboard,
    format_monthly,
    format_problem_detail,
    format_problems,
    format_reminder,
    format_solution_detail,
    format_solved_page,
    format_submit_result,
    format_test_result,
    format_weekly,
)
from leetcode import (
    check_result,
    extract_images,
    fetch_all_users,
    fetch_all_users_ac,
    fetch_daily_challenge,
    fetch_problem,
    fetch_problem_status,
    fetch_problems,
    fetch_problems_status,
    fetch_question_difficulties,
    fetch_recent_ac_submissions,
    fetch_user_profile,
    filter_today_accepted,
    get_cached_solution,
    get_snapshot,
    interpret_solution,
    map_images_to_examples,
    submit_solution,
    take_snapshot,
    validate_credentials,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

JOB_PREFIX = "summary_"
MIDNIGHT_JOB_PREFIX = "midnight_"
REMINDER_JOB_PREFIX = "reminder_"

# Store bot username for generating deep links
_bot_username = None

# ConversationHandler states
TEST_LANG, TEST_CODE = range(2)
SUBMIT_LANG, SUBMIT_CODE = range(2, 4)


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


async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send an 11pm reminder tagging users who solved 0 questions today."""
    chat_id = str(context.job.chat_id)

    if not storage.get_reminder(chat_id):
        return

    users = storage.get_users(chat_id)
    if not users:
        return

    tz = _tz(chat_id)
    profiles = await fetch_all_users(users)
    user_links = storage.get_user_links(chat_id)

    zero_users = []
    for username, profile in profiles.items():
        if profile is None:
            continue
        snapshot_data = get_snapshot(chat_id, username, tz)
        if snapshot_data is None:
            continue
        cutoff_ts = snapshot_data["timestamp"]
        subs = filter_today_accepted(profile["recent"], tz, cutoff_ts)
        if len(subs) == 0:
            zero_users.append(username)

    if not zero_users:
        return

    text = format_reminder(zero_users, user_links)
    await context.bot.send_message(
        chat_id=int(chat_id), text=text, parse_mode="MarkdownV2",
    )
    logger.info("Sent 11pm reminder for chat %s (%d users tagged)", chat_id, len(zero_users))


def _schedule_reminder_job(app_or_queue, chat_id: str) -> None:
    """Schedule or remove the daily 11pm reminder job for a chat."""
    job_queue = getattr(app_or_queue, "job_queue", app_or_queue)
    job_name = f"{REMINDER_JOB_PREFIX}{chat_id}"

    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    if not storage.get_reminder(chat_id):
        return

    tz = _tz(chat_id)
    job_queue.run_daily(
        _send_reminder,
        time=time(23, 0, tzinfo=tz),
        chat_id=int(chat_id),
        name=job_name,
    )


# --- Command Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await cmd_help(update, context)
        return

    payload = context.args[0]

    # Deep link: problem_ → show problem detail
    if payload.startswith("problem_"):
        slug = payload[8:]
        question = await fetch_problem(slug)
        if question is None:
            await update.message.reply_text(f"Problem '{slug}' not found.")
            return
        has_solution = get_cached_solution(slug) is not None
        text = format_problem_detail(question, has_solution=has_solution, bot_username=_bot_username)
        await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

        content = question.get("content", "")
        await _send_problem_images(update, content)
        return

    # Deep link: solution_ → show solution with inline keyboard
    if payload.startswith("solution_"):
        slug = payload[9:]
        solution_data = get_cached_solution(slug)
        if solution_data is None:
            await update.message.reply_text(f"Solution for '{slug}' does not exist.")
            return
        approaches = solution_data.get("approaches", [])
        if not approaches:
            await update.message.reply_text(f"Solution for '{slug}' has no approaches.")
            return
        approach = approaches[0]
        lang = "python"
        available_langs = list((approach.get("code") or {}).keys())
        if lang not in available_langs and available_langs:
            lang = available_langs[0]
        text = format_solution_detail(slug, approach, lang)
        keyboard = _build_solution_keyboard(slug, approaches, 0, lang)
        await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)
        return

    # Normal /start → show help
    await cmd_help(update, context)


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Debug command to show chat info."""
    chat_id = _chat_id(update)
    users = storage.get_users(chat_id)
    stored_chats = list(storage.get_all_chats().keys())
    await update.message.reply_text(
        f"Debug info:\n"
        f"- This chat_id: {chat_id}\n"
        f"- Users in this chat: {users}\n"
        f"- All stored chats: {stored_chats}\n"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*LeetCode Tracker Bot*\n\n"
        "*Tracking:*\n"
        "/add\\_user \\<username\\> \\- Track a LeetCode user\n"
        "/remove\\_user \\<username\\> \\- Stop tracking a user\n"
        "/users \\- List tracked users\n"
        "/summary \\- Full leaderboard \\(daily/weekly/monthly/all\\-time\\)\n"
        "/daily \\- Today's problems per user\n"
        "/weekly \\- This week's problems per user\n"
        "/monthly \\- This month's problems per user\n"
        "/solved \\[username\\] \\- View accepted problems\n"
        "/interval \\<30m\\|1h\\|2h\\|6h\\|1d\\|off\\> \\- Auto summary interval\n"
        "/reminder \\<on\\|off\\> \\- Toggle 11pm daily reminder\n\n"
        "*Browsing:*\n"
        "/problems \\[difficulty\\] \\[tags\\] \\- Browse problems\n"
        "  Examples: /problems  /problems easy  /problems easy array\n"
        "  Multi\\-word tags: /problems \"dynamic programming\" easy\n"
        "/problem \\<slug\\> \\- Problem details \\(e\\.g\\. /problem two\\-sum\\)\n"
        "/solution \\<slug\\> \\- View solution \\(e\\.g\\. /solution two\\-sum\\)\n"
        "/challenge \\- Today's daily challenge\n\n"
        "*Account \\(requires /login\\):*\n"
        "/login \\<session\\> \\<csrf\\> \\- Authenticate \\(DM only\\)\n"
        "/logout \\- Clear credentials\n"
        "/test \\<slug\\> \\- Test code against examples\n"
        "/submit \\<slug\\> \\- Submit solution to LeetCode\n"
        "/cancel \\- Cancel current test/submit\n\n"
        "/help \\- Show this message"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


# --- Authentication ---

async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /login <LEETCODE_SESSION> <csrftoken> — DM only."""
    if update.effective_chat.type != "private":
        bot_link = f"https://t.me/{_bot_username}" if _bot_username else "the bot's DM"
        await update.message.reply_text(
            f"For security, please use /login in a private chat with me.\n{bot_link}"
        )
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /login <LEETCODE_SESSION> <csrftoken>\n\n"
            "To get these values:\n"
            "1. Log in to leetcode.com in your browser\n"
            "2. Open DevTools (F12) → Application → Cookies → leetcode.com\n"
            "3. Copy the values of LEETCODE_SESSION and csrftoken"
        )
        return

    # Delete the message containing cookies for security
    try:
        await update.message.delete()
    except Exception:
        logger.warning("Could not delete login message (missing permissions)")

    leetcode_session = context.args[0]
    csrftoken = context.args[1]

    status_msg = await update.effective_chat.send_message("Validating your credentials...")

    username = await validate_credentials(leetcode_session, csrftoken)
    if username:
        storage.save_user_credentials(
            update.effective_user.id, leetcode_session, csrftoken, username,
        )
        await status_msg.edit_text(f"Logged in as {username}.")
    else:
        await status_msg.edit_text(
            "Invalid or expired credentials. Please check your LEETCODE_SESSION and csrftoken values."
        )


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /logout — clear stored credentials."""
    removed = storage.delete_user_credentials(update.effective_user.id)
    if removed:
        await update.message.reply_text("Logged out. Your LeetCode credentials have been cleared.")
    else:
        await update.message.reply_text("You are not logged in.")


# --- Test / Submit helpers ---

def _strip_code_fences(text: str) -> str:
    """Strip markdown code block fences from user-submitted code."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _get_credentials(user_id: int) -> Optional[dict]:
    """Get credentials or None. Convenience wrapper."""
    return storage.get_user_credentials(user_id)


# --- /test conversation ---

async def cmd_test_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: /test <slug>"""
    creds = _get_credentials(update.effective_user.id)
    if not creds:
        await update.message.reply_text("You need to /login first.")
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text("Usage: /test <title-slug>  e.g. /test two-sum")
        return ConversationHandler.END

    slug = context.args[0].lower().replace(" ", "-")
    status_msg = await update.message.reply_text(f"Fetching problem {slug}...")

    question = await fetch_problem(slug, require_snippets=True)
    if question is None:
        await status_msg.edit_text(f"Problem '{slug}' not found.")
        return ConversationHandler.END

    question_id = question.get("questionId")
    if not question_id:
        await status_msg.edit_text("Could not get problem ID. Try again later.")
        return ConversationHandler.END

    test_cases = question.get("exampleTestcases", "")
    code_snippets = {s["langSlug"]: s["code"] for s in (question.get("codeSnippets") or [])}

    context.user_data["test_slug"] = slug
    context.user_data["test_question_id"] = question_id
    context.user_data["test_cases"] = test_cases
    context.user_data["test_snippets"] = code_snippets

    # Build language selection keyboard
    buttons = []
    row = []
    for lang_slug in code_snippets:
        display = LEETCODE_LANG_SLUGS.get(lang_slug, lang_slug)
        row.append(InlineKeyboardButton(display, callback_data=f"tl:{lang_slug}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await status_msg.edit_text(
        "Select a language:", reply_markup=InlineKeyboardMarkup(buttons),
    )
    return TEST_LANG


async def cmd_test_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle language selection callback for /test."""
    query = update.callback_query
    await query.answer()
    lang = query.data[3:]  # Strip "tl:" prefix

    context.user_data["test_lang"] = lang
    snippet = context.user_data.get("test_snippets", {}).get(lang, "")
    slug = context.user_data.get("test_slug", "")

    text = format_code_prompt(slug, snippet, lang)
    await query.edit_message_text(text, parse_mode="HTML")
    return TEST_CODE


async def cmd_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle code message for /test."""
    creds = _get_credentials(update.effective_user.id)
    if not creds:
        await update.message.reply_text("Session expired. Please /login again.")
        return ConversationHandler.END

    code = _strip_code_fences(update.message.text)
    slug = context.user_data.get("test_slug", "")
    question_id = context.user_data.get("test_question_id", "")
    lang = context.user_data.get("test_lang", "")
    test_cases = context.user_data.get("test_cases", "")

    status_msg = await update.message.reply_text("Running tests...")

    interpret_id = await interpret_solution(
        slug, question_id, lang, code, test_cases,
        creds["leetcode_session"], creds["csrftoken"],
    )
    if not interpret_id:
        await status_msg.edit_text("Failed to submit test. Your session may have expired — try /login again.")
        return ConversationHandler.END

    result = await check_result(interpret_id, creds["leetcode_session"], creds["csrftoken"])
    if not result:
        await status_msg.edit_text("Timed out waiting for test results. Please try again.")
        return ConversationHandler.END

    text = format_test_result(result, lang, slug)
    await status_msg.edit_text(text, parse_mode="HTML")
    return ConversationHandler.END


# --- /submit conversation ---

async def cmd_submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: /submit <slug>"""
    creds = _get_credentials(update.effective_user.id)
    if not creds:
        await update.message.reply_text("You need to /login first.")
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text("Usage: /submit <title-slug>  e.g. /submit two-sum")
        return ConversationHandler.END

    slug = context.args[0].lower().replace(" ", "-")
    status_msg = await update.message.reply_text(f"Fetching problem {slug}...")

    question = await fetch_problem(slug, require_snippets=True)
    if question is None:
        await status_msg.edit_text(f"Problem '{slug}' not found.")
        return ConversationHandler.END

    question_id = question.get("questionId")
    if not question_id:
        await status_msg.edit_text("Could not get problem ID. Try again later.")
        return ConversationHandler.END

    code_snippets = {s["langSlug"]: s["code"] for s in (question.get("codeSnippets") or [])}

    context.user_data["submit_slug"] = slug
    context.user_data["submit_question_id"] = question_id
    context.user_data["submit_snippets"] = code_snippets

    # Build language selection keyboard
    buttons = []
    row = []
    for lang_slug in code_snippets:
        display = LEETCODE_LANG_SLUGS.get(lang_slug, lang_slug)
        row.append(InlineKeyboardButton(display, callback_data=f"sl:{lang_slug}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await status_msg.edit_text(
        "Select a language:", reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SUBMIT_LANG


async def cmd_submit_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle language selection callback for /submit."""
    query = update.callback_query
    await query.answer()
    lang = query.data[3:]  # Strip "sl:" prefix

    context.user_data["submit_lang"] = lang
    snippet = context.user_data.get("submit_snippets", {}).get(lang, "")
    slug = context.user_data.get("submit_slug", "")

    text = format_code_prompt(slug, snippet, lang)
    await query.edit_message_text(text, parse_mode="HTML")
    return SUBMIT_CODE


async def cmd_submit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle code message for /submit."""
    creds = _get_credentials(update.effective_user.id)
    if not creds:
        await update.message.reply_text("Session expired. Please /login again.")
        return ConversationHandler.END

    code = _strip_code_fences(update.message.text)
    slug = context.user_data.get("submit_slug", "")
    question_id = context.user_data.get("submit_question_id", "")
    lang = context.user_data.get("submit_lang", "")

    status_msg = await update.message.reply_text("Submitting solution...")

    submission_id = await submit_solution(
        slug, question_id, lang, code,
        creds["leetcode_session"], creds["csrftoken"],
    )
    if not submission_id:
        await status_msg.edit_text("Failed to submit. Your session may have expired — try /login again.")
        return ConversationHandler.END

    result = await check_result(submission_id, creds["leetcode_session"], creds["csrftoken"])
    if not result:
        await status_msg.edit_text("Timed out waiting for submission results. Please try again.")
        return ConversationHandler.END

    text = format_submit_result(result, lang, slug)
    await status_msg.edit_text(text, parse_mode="HTML")
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current conversation (test or submit)."""
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# --- Tracking Commands ---

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

    # Auto-link caller's Telegram ID to this LeetCode username
    tg_user = update.effective_user
    if tg_user:
        storage.link_user(chat_id, canonical, tg_user.id, tg_user.first_name or canonical)

    tz = _tz(chat_id)
    take_snapshot(chat_id, canonical, profile["counts"], tz)
    _schedule_midnight_job(context.application, chat_id)
    _schedule_reminder_job(context.application, chat_id)
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
    profiles, ac_subs = await asyncio.gather(fetch_all_users(users), fetch_all_users_ac(users))
    text = await format_leaderboard(chat_id, profiles, tz, ac_submissions=ac_subs)
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


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    users = storage.get_users(chat_id)
    if not users:
        await update.message.reply_text("No users tracked. Use /add_user <username> to add one.")
        return

    tz = _tz(chat_id)
    profiles, ac_subs = await asyncio.gather(fetch_all_users(users), fetch_all_users_ac(users))
    text = await format_monthly(chat_id, profiles, ac_subs, tz, bot_username=_bot_username)
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


async def cmd_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)

    if not context.args or context.args[0] not in ("on", "off"):
        status = "enabled" if storage.get_reminder(chat_id) else "disabled"
        await update.message.reply_text(
            f"Daily 11pm reminder is currently {status}.\nUsage: /reminder <on|off>"
        )
        return

    enabled = context.args[0] == "on"
    storage.set_reminder(chat_id, enabled)
    _schedule_reminder_job(context.application, chat_id)

    if enabled:
        await update.message.reply_text(
            "✅ Daily reminder enabled. Users with 0 questions will be tagged at 11pm."
        )
    else:
        await update.message.reply_text("❌ Daily reminder disabled.")


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

    # Check solved status if user is logged in
    solved_slugs = None
    creds = _get_credentials(update.effective_user.id)
    if creds:
        slugs = [q["titleSlug"] for q in result.get("questions", []) if q.get("titleSlug")]
        statuses = await fetch_problems_status(slugs, creds["leetcode_session"], creds["csrftoken"])
        solved_slugs = {s for s, st in statuses.items() if st == "ac"}

    total = result.get("total", 0)
    filters_desc = " · ".join(filter(None, ([difficulty.capitalize()] if difficulty else []) + tags))
    text = format_problems(result, _esc(filters_desc), page=0, page_size=PAGE_SIZE, bot_username=_bot_username, solved_slugs=solved_slugs)
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

    # Check solved status if user is logged in
    solved_slugs = None
    creds = _get_credentials(update.effective_user.id)
    if creds:
        slugs = [q["titleSlug"] for q in result.get("questions", []) if q.get("titleSlug")]
        statuses = await fetch_problems_status(slugs, creds["leetcode_session"], creds["csrftoken"])
        solved_slugs = {s for s, st in statuses.items() if st == "ac"}

    total = result.get("total", 0)
    filters_desc = " · ".join(filter(None, ([difficulty.capitalize()] if difficulty else []) + tags))
    text = format_problems(result, _esc(filters_desc), page=page, page_size=PAGE_SIZE, bot_username=_bot_username, solved_slugs=solved_slugs)
    keyboard = _build_problems_keyboard(page, total, PAGE_SIZE, difficulty, tags)
    try:
        await query.edit_message_text(
            text, parse_mode="MarkdownV2", disable_web_page_preview=True, reply_markup=keyboard,
        )
    except Exception:
        pass  # Ignore "Message is not modified" on rapid double-taps


# ---------------------------------------------------------------------------
# /solved command — recent 20 accepted problems
# ---------------------------------------------------------------------------

async def cmd_solved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /solved [username] — show 20 most recent accepted problems."""
    if context.args:
        username = context.args[0]
    else:
        # Fall back to linked LeetCode account
        chat_id = _chat_id(update)
        links = storage.get_user_links(chat_id)
        tg_id = update.effective_user.id
        linked = None
        for lc_user, info in links.items():
            if info.get("telegram_id") == tg_id:
                linked = lc_user
                break
        if linked:
            username = linked
        else:
            await update.message.reply_text("Usage: /solved <username>")
            return

    msg = await update.message.reply_text(f"Fetching solved problems for {username}...")

    subs, profile = await asyncio.gather(
        fetch_recent_ac_submissions(username, limit=20),
        fetch_user_profile(username),
    )
    if subs is None:
        await msg.edit_text(f"Failed to fetch data for '{username}'.")
        return
    if not subs:
        await msg.edit_text(f"No accepted submissions found for '{username}'.")
        return

    total = sum(profile["counts"].values()) if profile else len(subs)
    slugs = [s.get("titleSlug", "") for s in subs if s.get("titleSlug")]
    difficulties = await fetch_question_difficulties(slugs)

    chat_tz = _tz(_chat_id(update))
    text = format_solved_page(
        username, subs, difficulties, total=total,
        bot_username=_bot_username, tz=chat_tz,
    )
    await msg.edit_text(
        text, parse_mode="MarkdownV2", disable_web_page_preview=True,
    )


async def cmd_problem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /problem <title-slug>  e.g. /problem two-sum")
        return

    slug = context.args[0].lower().replace(" ", "-")
    question = await fetch_problem(slug)
    if question is None:
        await update.message.reply_text(f"Problem '{slug}' not found.")
        return

    # Check solved status if user is logged in
    solved = None
    creds = _get_credentials(update.effective_user.id)
    if creds:
        solved = await fetch_problem_status(slug, creds["leetcode_session"], creds["csrftoken"])

    has_solution = get_cached_solution(slug) is not None
    text = format_problem_detail(question, has_solution=has_solution, bot_username=_bot_username, solved=solved)
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

    content = question.get("content", "")
    await _send_problem_images(update, content)


# ---------------------------------------------------------------------------
# /solution command with inline keyboard navigation
# ---------------------------------------------------------------------------

def _encode_solution_callback(slug: str, approach_idx: int, lang: str) -> str:
    """Encode solution nav state: `s:<slug>:<idx>:<lang>` (≤64 bytes)."""
    payload = f"s:{slug}:{approach_idx}:{lang}"
    # Truncate slug if needed to stay within 64-byte limit
    while len(payload.encode()) > 64:
        slug = slug[:-1]
        payload = f"s:{slug}:{approach_idx}:{lang}"
    return payload


def _decode_solution_callback(data: str) -> tuple:
    """Parse callback: (slug, approach_idx, lang)."""
    parts = data.split(":", 3)
    return parts[1], int(parts[2]), parts[3]


def _build_solution_keyboard(
    slug: str, approaches: list[dict], current_idx: int, current_lang: str,
) -> InlineKeyboardMarkup:
    """Build approach + language inline keyboard rows."""
    # Row 1: approach buttons
    approach_buttons = []
    for i, approach in enumerate(approaches):
        name = approach.get("name", f"Approach {i + 1}")
        # Truncate long names
        if len(name) > 18:
            name = name[:16] + ".."
        label = f"✓ {name}" if i == current_idx else name
        approach_buttons.append(
            InlineKeyboardButton(label, callback_data=_encode_solution_callback(slug, i, current_lang))
        )

    # Row 2: language buttons (only languages available in current approach)
    current_approach = approaches[current_idx] if current_idx < len(approaches) else {}
    available_langs = list((current_approach.get("code") or {}).keys())
    lang_buttons = []
    for lang in available_langs:
        display = LANGUAGE_DISPLAY.get(lang, lang)
        label = f"✓ {display}" if lang == current_lang else display
        lang_buttons.append(
            InlineKeyboardButton(label, callback_data=_encode_solution_callback(slug, current_idx, lang))
        )

    rows = []
    if len(approaches) > 1:
        rows.append(approach_buttons)
    if lang_buttons:
        rows.append(lang_buttons)
    return InlineKeyboardMarkup(rows)


async def cmd_solution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /solution <title-slug>  e.g. /solution two-sum")
        return

    slug = context.args[0].lower().replace(" ", "-")
    solution_data = get_cached_solution(slug)
    if solution_data is None:
        await update.message.reply_text(f"Solution for '{slug}' does not exist.")
        return

    approaches = solution_data.get("approaches", [])
    if not approaches:
        await update.message.reply_text(f"Solution for '{slug}' has no approaches.")
        return

    # Default: first approach, python
    approach = approaches[0]
    lang = "python"
    # If python not available, use first available language
    available_langs = list((approach.get("code") or {}).keys())
    if lang not in available_langs and available_langs:
        lang = available_langs[0]

    text = format_solution_detail(slug, approach, lang)
    keyboard = _build_solution_keyboard(slug, approaches, 0, lang)
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)


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


# /solution callback handler
async def cmd_solution_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approach/language button presses for /solution."""
    query = update.callback_query
    await query.answer()

    slug, approach_idx, lang = _decode_solution_callback(query.data)
    solution_data = get_cached_solution(slug)
    if solution_data is None:
        await query.answer("Solution no longer available.", show_alert=True)
        return

    approaches = solution_data.get("approaches", [])
    if approach_idx >= len(approaches):
        await query.answer("Invalid approach.", show_alert=True)
        return

    approach = approaches[approach_idx]
    text = format_solution_detail(slug, approach, lang)
    keyboard = _build_solution_keyboard(slug, approaches, approach_idx, lang)
    try:
        await query.edit_message_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)
    except Exception:
        pass


# /visualise command with step navigation
# ---------------------------------------------------------------------------

def _encode_visualise_callback(slug: str, approach_idx: int, step_idx: int) -> str:
    """Encode visualisation nav state: `v:<slug>:<approach_idx>:<step_idx>`."""
    return f"v:{slug}:{approach_idx}:{step_idx}"


def _decode_visualise_callback(data: str) -> tuple:
    """Parse callback: (slug, approach_idx, step_idx)."""
    parts = data.split(":", 3)
    return parts[1], int(parts[2]), int(parts[3])


def _format_visualisation_step(slug: str, approach: dict, approach_idx: int, step_idx: int) -> str:
    """Format a single visualisation step with array visualization."""
    vis = approach.get("visualisation", {})
    if not vis:
        return "No visualisation available for this approach."

    steps = vis.get("steps", [])
    if step_idx < 0 or step_idx >= len(steps):
        return "Invalid step."

    step = steps[step_idx]
    step_text = step.get("text", "")
    highlight = step.get("highlight", [])
    result = step.get("result")
    vis_map = step.get("map", {})
    pass_desc = step.get("pass")

    time_complexity = approach.get("time_complexity", "")
    space_complexity = approach.get("space_complexity", "")

    lines = []
    lines.append(f"💡 <b>Visualise:</b> <code>{_esc(slug)}</code>")
    lines.append(f"Approach: <b>{_esc(approach.get('name', 'Approach'))}</b>")

    explanation = approach.get("explanation", "")
    if explanation:
        lines.append(f"_{explanation}_")

    lines.append(f"Step {step_idx + 1}/{len(steps)}")

    input_data = vis.get("input", {})
    nums = input_data.get("nums", [])
    target = input_data.get("target")

    if nums:
        arr_display = []
        for i, num in enumerate(nums):
            if i in highlight:
                arr_display.append(f"[<b>{num}</b>]")
            else:
                arr_display.append(f"[{num}]")
        lines.append("Array: " + " ".join(arr_display))
        if target is not None:
            lines.append(f"Target: {target}")

    if vis_map:
        map_parts = [f"{k}→{v}" for k, v in vis_map.items()]
        lines.append(f"Map: {{{', '.join(map_parts)}}}")

    if pass_desc:
        lines.append(f"📌 <b>Pass:</b> {pass_desc}")

    lines.append("")

    lines.append(step_text)

    if result is not None:
        lines.append("")
        lines.append(f"<b>✓ Result: {result}</b>")

    if time_complexity or space_complexity:
        parts = []
        if time_complexity:
            parts.append(f"Time: {time_complexity}")
        if space_complexity:
            parts.append(f"Space: {space_complexity}")
        lines.append("")
        lines.append(" · ".join(parts))

    lines.append("")
    lines.append(f"<a href=\"https://leetcode.com/problems/{slug}/\">Open on LeetCode</a>")

    return "\n".join(lines)


def _build_visualise_keyboard(slug: str, approaches: list[dict], approach_idx: int, step_idx: int) -> InlineKeyboardMarkup:
    """Build approach + step navigation keyboard."""
    current_approach = approaches[approach_idx] if approach_idx < len(approaches) else {}
    vis = current_approach.get("visualisation", {})
    steps = vis.get("steps", []) if vis else []

    rows = []

    if len(approaches) > 1:
        approach_buttons = []
        for i, approach in enumerate(approaches):
            name = approach.get("name", f"Approach {i + 1}")[:18]
            label = f"✓ {name}" if i == approach_idx else name
            approach_buttons.append(
                InlineKeyboardButton(label, callback_data=_encode_visualise_callback(slug, i, 0))
            )
        rows.append(approach_buttons)

    if steps:
        step_buttons = []
        if step_idx > 0:
            step_buttons.append(
                InlineKeyboardButton("⬅ Prev", callback_data=_encode_visualise_callback(slug, approach_idx, step_idx - 1))
            )
        if step_idx < len(steps) - 1:
            step_buttons.append(
                InlineKeyboardButton("Next ➡", callback_data=_encode_visualise_callback(slug, approach_idx, step_idx + 1))
            )
        if step_buttons:
            rows.append(step_buttons)

    return InlineKeyboardMarkup(rows) if rows else None


async def cmd_visualise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /visualise <title-slug>  e.g. /visualise two-sum")
        return

    slug = context.args[0].lower().replace(" ", "-")
    solution_data = get_cached_solution(slug)
    if solution_data is None:
        await update.message.reply_text(f"Visualisation for '{slug}' does not exist.")
        return

    approaches = solution_data.get("approaches", [])
    if not approaches:
        await update.message.reply_text(f"No approaches available for '{slug}'.")
        return

    first_with_vis = None
    for i, approach in enumerate(approaches):
        if approach.get("visualisation"):
            first_with_vis = i
            break

    if first_with_vis is None:
        await update.message.reply_text(f"No visualisation available for '{slug}' yet.")
        return

    approach_idx = first_with_vis
    approach = approaches[approach_idx]
    text = _format_visualisation_step(slug, approach, approach_idx, 0)
    keyboard = _build_visualise_keyboard(slug, approaches, approach_idx, 0)
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)


async def cmd_visualise_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle step navigation button presses for /visualise."""
    query = update.callback_query
    await query.answer()

    slug, approach_idx, step_idx = _decode_visualise_callback(query.data)
    solution_data = get_cached_solution(slug)
    if solution_data is None:
        await query.answer("Visualisation no longer available.", show_alert=True)
        return

    approaches = solution_data.get("approaches", [])
    if approach_idx >= len(approaches):
        await query.answer("Invalid approach.", show_alert=True)
        return

    approach = approaches[approach_idx]
    vis = approach.get("visualisation", {})
    steps = vis.get("steps", []) if vis else []

    if step_idx < 0 or step_idx >= len(steps):
        await query.answer("Invalid step.", show_alert=True)
        return

    text = _format_visualisation_step(slug, approach, approach_idx, step_idx)
    keyboard = _build_visualise_keyboard(slug, approaches, approach_idx, step_idx)
    try:
        await query.edit_message_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)
    except Exception:
        pass


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
            _schedule_reminder_job(app, chat_id)

        interval = chat_data.get("interval", "off")
        if interval != "off":
            _schedule_job(app, chat_id, interval)
            logger.info("Restored %s interval for chat %s", interval, chat_id)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Set LEETCODE_BOT_TOKEN environment variable.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(TypeHandler(Update, log_event), group=-1)

    # ConversationHandlers must be added before simple CommandHandlers
    test_conv = ConversationHandler(
        entry_points=[CommandHandler("test", cmd_test_start)],
        states={
            TEST_LANG: [CallbackQueryHandler(cmd_test_lang, pattern=r"^tl:")],
            TEST_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_test_code)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
        conversation_timeout=300,
    )
    app.add_handler(test_conv)

    submit_conv = ConversationHandler(
        entry_points=[CommandHandler("submit", cmd_submit_start)],
        states={
            SUBMIT_LANG: [CallbackQueryHandler(cmd_submit_lang, pattern=r"^sl:")],
            SUBMIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_submit_code)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
        conversation_timeout=300,
    )
    app.add_handler(submit_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("add_user", cmd_add_user))
    app.add_handler(CommandHandler("remove_user", cmd_remove_user))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("solved", cmd_solved))
    app.add_handler(CommandHandler("interval", cmd_interval))
    app.add_handler(CommandHandler("reminder", cmd_reminder))
    app.add_handler(CommandHandler("problems", cmd_problems))
    app.add_handler(CallbackQueryHandler(cmd_problems_page, pattern=r"^p:"))
    app.add_handler(CommandHandler("problem", cmd_problem))
    app.add_handler(CommandHandler("challenge", cmd_challenge))
    app.add_handler(CommandHandler("solution", cmd_solution))
    app.add_handler(CallbackQueryHandler(cmd_solution_nav, pattern=r"^s:"))
    app.add_handler(CommandHandler("visualise", cmd_visualise))
    app.add_handler(CallbackQueryHandler(cmd_visualise_nav, pattern=r"^v:"))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
