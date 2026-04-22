import html
import random
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from leetcode import (
    DIFFICULTY_EMOJI,
    _strip_html,
    _to_superscript,
    compute_diff,
    extract_constraints,
    extract_description,
    extract_examples,
    extract_images,
    fetch_question_difficulties,
    filter_month_accepted,
    filter_today_accepted,
    filter_week_accepted,
    get_month_snapshot,
    get_snapshot,
    get_week_daily_counts,
    get_week_snapshot,
)


async def format_daily(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
    bot_username: Optional[str] = None,
) -> str:
    """Format detailed daily progress view, sorted by problems solved."""
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    # Collect all slugs from today's submissions across all users to batch-fetch difficulties
    all_slugs: set[str] = set()
    user_rows: list[tuple[str, Optional[dict], int, dict[str, int], list[dict], Optional[dict]]] = []

    for username, profile in profiles.items():
        if profile is None:
            user_rows.append((username, None, 0, {}, [], None))
            continue

        # Get snapshot to determine cutoff time
        snapshot_data = get_snapshot(chat_id, username, tz)
        cutoff_ts = snapshot_data["timestamp"] if snapshot_data else None

        subs = filter_today_accepted(profile["recent"], tz, cutoff_ts)

        for sub in subs:
            slug = sub.get("titleSlug")
            if slug:
                all_slugs.add(slug)

        # Count from submissions (what's visible in recent[])
        solved_today = len(subs)
        # Build difficulty breakdown from submissions
        diff_breakdown = {"Easy": 0, "Medium": 0, "Hard": 0}

        user_rows.append((username, profile, solved_today, diff_breakdown, subs, snapshot_data))

    difficulties = await fetch_question_difficulties(list(all_slugs))

    # Populate difficulty breakdown for each user from their submissions
    for i, (username, profile, solved_today, diff_breakdown, subs, snapshot_data) in enumerate(user_rows):
        if profile is not None and diff_breakdown is not None:  # Only for users with data
            for sub in subs:
                slug = sub.get("titleSlug", "")
                difficulty = difficulties.get(slug, "")
                if difficulty in diff_breakdown:
                    diff_breakdown[difficulty] += 1

    # Sort: by solved_today descending, then alphabetically. Users with no snapshot sort to bottom.
    user_rows.sort(key=lambda x: (0 if x[5] is not None else 1, -x[2], x[0].lower()))

    lines = ["*Daily Progress*\n"]

    for username, profile, solved_today, diff_from_subs, subs, snapshot_data in user_rows:
        if profile is None:
            lines.append(f"*{_esc(username)}*: _failed to fetch \\(private or invalid\\)_\n")
            continue

        if snapshot_data is None:
            counts = profile["counts"]
            total = sum(counts.values())
            diff_parts = _emoji_counts(counts)
            lines.append(
                f"*{_esc(username)}*: {total} total solved "
                f"\\({diff_parts}\\)"
            )
            lines.append(f"  _No baseline yet \\- tracking starts tomorrow_\n")
            continue

        # Build difficulty breakdown from submissions themselves
        subs_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
        for sub in subs:
            slug = sub.get("titleSlug", "")
            difficulty = difficulties.get(slug, "")
            if difficulty in subs_diff:
                subs_diff[difficulty] += 1

        header = f"*{_esc(username)}*: *{solved_today}* solved today"
        if solved_today > 0:
            header += f" \\({_emoji_counts(subs_diff)}\\)"

        lines.append(header)

        if subs:
            for sub in subs:
                title = _esc(sub.get("title", "Unknown"))
                slug = sub.get("titleSlug", "")
                emoji = DIFFICULTY_EMOJI.get(difficulties.get(slug, ""), "")
                prefix = f"{emoji} " if emoji else ""
                if bot_username:
                    problem_link = f"https://t.me/{bot_username}?start=problem_{slug}"
                else:
                    problem_link = f"https://leetcode.com/problems/{slug}/"
                lines.append(f"  {prefix}[{title}]({problem_link})")

            # Overflow note if snapshot diff shows more solved than captured in recent[]
            if snapshot_data:
                snapshot_diff = compute_diff(profile["counts"], snapshot_data["counts"])
                snapshot_diff_total = sum(snapshot_diff.values())
                if snapshot_diff_total > len(subs):
                    overflow = snapshot_diff_total - len(subs)
                    lines.append(f"  _\\+{overflow} more not shown_")

        lines.append("")

    # Append bar chart
    chart = _bar_chart_text(user_rows)
    if chart:
        lines.append("\n📊 *Chart*")
        lines.append(f"```\n{chart}\n```")

    return "\n".join(lines)


async def format_leaderboard(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
    ac_submissions: Optional[dict[str, Optional[list[dict]]]] = None,
) -> str:
    """Format compact leaderboard (daily + weekly + monthly + all-time)."""
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    # Collect all slugs for batch fetching difficulties
    all_slugs: set[str] = set()

    # Compute counts using submissions-based approach (consistent with /daily and /weekly)
    daily_data: list[tuple[str, list[dict]]] = []  # (username, subs)
    weekly_data: list[tuple[str, list[dict]]] = []  # (username, subs)
    monthly_data: list[tuple[str, Optional[list[dict]]]] = []  # (username, subs or None)

    for username, profile in sorted(profiles.items(), key=lambda x: x[0].lower()):
        if profile is None:
            continue

        # Daily: count from today's submissions
        snapshot_data = get_snapshot(chat_id, username, tz)
        cutoff_ts = snapshot_data["timestamp"] if snapshot_data else None
        daily_subs = filter_today_accepted(profile["recent"], tz, cutoff_ts)
        daily_data.append((username, daily_subs))

        for sub in daily_subs:
            slug = sub.get("titleSlug", "")
            if slug:
                all_slugs.add(slug)

        # Weekly: count from week's submissions
        week_snapshot = get_week_snapshot(chat_id, username, tz)
        if week_snapshot:
            week_start_ts = week_snapshot["timestamp"]
            weekly_subs = filter_week_accepted(profile["recent"], week_start_ts)
        else:
            weekly_subs = []

        weekly_data.append((username, weekly_subs))

        for sub in weekly_subs:
            slug = sub.get("titleSlug", "")
            if slug:
                all_slugs.add(slug)

        # Monthly: from AC submissions if available
        if ac_submissions:
            month_snapshot = get_month_snapshot(chat_id, username, tz)
            ac_subs = ac_submissions.get(username) or []
            if month_snapshot:
                month_start_ts = month_snapshot["timestamp"]
                month_subs = filter_month_accepted(ac_subs, month_start_ts)
            else:
                month_subs = None
            monthly_data.append((username, month_subs))

            if month_subs:
                for sub in month_subs:
                    slug = sub.get("titleSlug", "")
                    if slug:
                        all_slugs.add(slug)

    # Batch fetch difficulties
    difficulties = await fetch_question_difficulties(list(all_slugs))

    # Build processed lists with difficulty breakdowns
    daily_users_processed: list[tuple[str, int, dict[str, int]]] = []
    weekly_users_processed: list[tuple[str, Optional[int], dict[str, int]]] = []

    for username, daily_subs in daily_data:
        daily_count = len(daily_subs)
        daily_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
        for sub in daily_subs:
            slug = sub.get("titleSlug", "")
            difficulty = difficulties.get(slug, "")
            if difficulty in daily_diff:
                daily_diff[difficulty] += 1
        daily_users_processed.append((username, daily_count, daily_diff))

    for username, weekly_subs in weekly_data:
        weekly_count = len(weekly_subs) if weekly_subs else None
        weekly_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
        for sub in weekly_subs:
            slug = sub.get("titleSlug", "")
            difficulty = difficulties.get(slug, "")
            if difficulty in weekly_diff:
                weekly_diff[difficulty] += 1
        weekly_users_processed.append((username, weekly_count, weekly_diff))

    monthly_users_processed: list[tuple[str, Optional[int], dict[str, int]]] = []
    for username, month_subs in monthly_data:
        if month_subs is None:
            monthly_users_processed.append((username, None, {}))
        else:
            monthly_count = len(month_subs)
            month_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
            for sub in month_subs:
                slug = sub.get("titleSlug", "")
                difficulty = difficulties.get(slug, "")
                if difficulty in month_diff:
                    month_diff[difficulty] += 1
            monthly_users_processed.append((username, monthly_count, month_diff))

    # All-time: from profile counts directly
    alltime_users: list[tuple[str, int, dict[str, int]]] = []
    for username, profile in profiles.items():
        if profile is None:
            continue
        counts = profile["counts"]
        total = sum(counts.values())
        alltime_users.append((username, total, counts))

    # Sort each section independently by count
    daily_users_processed.sort(key=lambda x: (-x[1], x[0].lower()))
    weekly_users_processed.sort(key=lambda x: (-x[1] if x[1] is not None else float('inf'), x[0].lower()))
    monthly_users_processed.sort(key=lambda x: (-x[1] if x[1] is not None else float('inf'), x[0].lower()))
    alltime_users.sort(key=lambda x: (-x[1], x[0].lower()))

    # === BUILD OUTPUT ===
    lines = ["*Leaderboard*\n", "*Today*"]
    for i, (username, count, diff_from_subs) in enumerate(daily_users_processed, 1):
        if count == 0:
            lines.append(f"{i}\\. {_esc(username)} — *0*")
        else:
            emoji_part = f" \\({_emoji_counts(diff_from_subs)}\\)"
            lines.append(f"{i}\\. {_esc(username)} — *{count}*{emoji_part}")

    lines.append("\n*This Week*")
    for i, (username, weekly_count, week_diff) in enumerate(weekly_users_processed, 1):
        if weekly_count is None:
            lines.append(f"{i}\\. {_esc(username)} — *\\?*")
        elif weekly_count == 0:
            lines.append(f"{i}\\. {_esc(username)} — *0*")
        else:
            emoji_part = f" \\({_emoji_counts(week_diff)}\\)"
            lines.append(f"{i}\\. {_esc(username)} — *{weekly_count}*{emoji_part}")

    if monthly_users_processed:
        month_name = datetime.now(tz).strftime("%B")
        lines.append(f"\n*This Month \\({_esc(month_name)}\\)*")
        for i, (username, monthly_count, month_diff) in enumerate(monthly_users_processed, 1):
            if monthly_count is None:
                lines.append(f"{i}\\. {_esc(username)} — *\\?*")
            elif monthly_count == 0:
                lines.append(f"{i}\\. {_esc(username)} — *0*")
            else:
                emoji_part = f" \\({_emoji_counts(month_diff)}\\)"
                lines.append(f"{i}\\. {_esc(username)} — *{monthly_count}*{emoji_part}")

    lines.append("\n*All\\-Time*")
    for i, (username, total, counts) in enumerate(alltime_users, 1):
        emoji_part = f" \\({_emoji_counts(counts)}\\)"
        lines.append(f"{i}\\. {_esc(username)} — *{total}*{emoji_part}")

    return "\n".join(lines)


async def format_weekly(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
    bot_username: Optional[str] = None,
) -> str:
    """Format detailed weekly progress view, sorted by problems solved."""
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    all_week_slugs: set[str] = set()
    user_rows: list[tuple[str, Optional[dict], Optional[int], dict[str, int], list[dict], Optional[int]]] = []

    for username, profile in profiles.items():
        if profile is None:
            user_rows.append((username, None, None, {}, [], None))
            continue

        week_snapshot = get_week_snapshot(chat_id, username, tz)
        if week_snapshot is None:
            user_rows.append((username, profile, None, {}, [], None))
        else:
            week_start_ts = week_snapshot["timestamp"]
            week_subs = filter_week_accepted(profile["recent"], week_start_ts)
            week_diff = compute_diff(profile["counts"], week_snapshot["counts"])
            week_diff_total = sum(week_diff.values())

            for sub in week_subs:
                slug = sub.get("titleSlug", "")
                if slug:
                    all_week_slugs.add(slug)

            # Use submissions-based count (what's visible in recent[])
            count = len(week_subs)
            # Store the snapshot diff for emoji display
            diff_breakdown = week_diff

            user_rows.append((username, profile, count, diff_breakdown, week_subs, week_diff_total))

    # Batch fetch weekly difficulties (for problem titles only)
    week_difficulties = await fetch_question_difficulties(list(all_week_slugs))

    # Sort: by count descending, then alphabetically. Users with no snapshot sort to bottom.
    user_rows.sort(key=lambda x: (0 if x[5] is not None else 1, -(x[2] if x[2] is not None else 0), x[0].lower()))

    lines = ["*Weekly Progress*\n"]

    for username, profile, count, diff_from_subs, subs, compute_diff_total in user_rows:
        if profile is None:
            lines.append(f"*{_esc(username)}*: _failed to fetch_\n")
            continue

        if count is None:
            lines.append(f"*{_esc(username)}*: _No data for this week yet_\n")
            continue

        # Build difficulty breakdown from submissions themselves
        subs_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
        for sub in subs:
            slug = sub.get("titleSlug", "")
            difficulty = week_difficulties.get(slug, "")
            if difficulty in subs_diff:
                subs_diff[difficulty] += 1

        emoji_part = ""
        if count > 0:
            emoji_part = f" \\({_emoji_counts(subs_diff)}\\)"
        lines.append(f"*{_esc(username)}* — *{count}* this week{emoji_part}")

        # Problem list
        if subs:
            for sub in subs:
                title = _esc(sub.get("title", "Unknown"))
                slug = sub.get("titleSlug", "")
                difficulty = week_difficulties.get(slug, "")
                emoji = DIFFICULTY_EMOJI.get(difficulty, "")
                prefix = f"{emoji} " if emoji else ""
                if bot_username:
                    problem_link = f"https://t.me/{bot_username}?start=problem_{slug}"
                else:
                    problem_link = f"https://leetcode.com/problems/{slug}/"
                lines.append(f"  {prefix}[{title}]({problem_link})")

            # Overflow note if snapshot diff shows more solved than captured in recent[]
            if compute_diff_total and compute_diff_total > len(subs):
                overflow = compute_diff_total - len(subs)
                lines.append(f"  _\\+{overflow} more not shown_")

        lines.append("")

    # Append sparkline chart
    per_day = get_week_daily_counts(chat_id, profiles, tz)
    days_elapsed = datetime.now(tz).weekday() + 1  # 1=Monday through 7=Sunday
    chart = _sparkline_text(per_day, days_elapsed)
    if chart:
        lines.append("\n📈 *Trend*")
        lines.append(f"```\n{chart}\n```")

    return "\n".join(lines)


async def format_monthly(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    ac_submissions: dict[str, Optional[list[dict]]],
    tz: ZoneInfo,
    bot_username: Optional[str] = None,
) -> str:
    """Format detailed monthly progress view, sorted by problems solved."""
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    all_slugs: set[str] = set()
    user_rows: list[tuple[str, Optional[dict], Optional[int], list[dict], Optional[int]]] = []

    for username, profile in profiles.items():
        if profile is None:
            user_rows.append((username, None, None, [], None))
            continue

        month_snapshot = get_month_snapshot(chat_id, username, tz)
        ac_subs = ac_submissions.get(username) or []

        if month_snapshot is None:
            user_rows.append((username, profile, None, [], None))
        else:
            month_start_ts = month_snapshot["timestamp"]
            month_subs = filter_month_accepted(ac_subs, month_start_ts)
            month_diff = compute_diff(profile["counts"], month_snapshot["counts"])
            month_diff_total = sum(month_diff.values())

            for sub in month_subs:
                slug = sub.get("titleSlug", "")
                if slug:
                    all_slugs.add(slug)

            count = len(month_subs)
            user_rows.append((username, profile, count, month_subs, month_diff_total))

    difficulties = await fetch_question_difficulties(list(all_slugs))

    # Sort: by count descending, then alphabetically. No-snapshot users at bottom.
    user_rows.sort(key=lambda x: (0 if x[4] is not None else 1, -(x[2] if x[2] is not None else 0), x[0].lower()))

    month_name = datetime.now(tz).strftime("%B")
    lines = [f"*Monthly Progress \\({_esc(month_name)}\\)*\n"]

    for username, profile, count, subs, diff_total in user_rows:
        if profile is None:
            lines.append(f"*{_esc(username)}*: _failed to fetch_\n")
            continue

        if count is None:
            lines.append(f"*{_esc(username)}*: _No data for this month yet_\n")
            continue

        # Build difficulty breakdown from submissions
        subs_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
        for sub in subs:
            slug = sub.get("titleSlug", "")
            difficulty = difficulties.get(slug, "")
            if difficulty in subs_diff:
                subs_diff[difficulty] += 1

        emoji_part = ""
        if count > 0:
            emoji_part = f" \\({_emoji_counts(subs_diff)}\\)"
        lines.append(f"*{_esc(username)}* — *{count}* this month{emoji_part}")

        # Problem list (cap at 15 per user)
        shown_subs = subs[:15]
        if shown_subs:
            for sub in shown_subs:
                title = _esc(sub.get("title", "Unknown"))
                slug = sub.get("titleSlug", "")
                difficulty = difficulties.get(slug, "")
                emoji = DIFFICULTY_EMOJI.get(difficulty, "")
                prefix = f"{emoji} " if emoji else ""
                if bot_username:
                    problem_link = f"https://t.me/{bot_username}?start=problem_{slug}"
                else:
                    problem_link = f"https://leetcode.com/problems/{slug}/"
                lines.append(f"  {prefix}[{title}]({problem_link})")

            # Overflow note
            if diff_total and diff_total > len(shown_subs):
                overflow = diff_total - len(shown_subs)
                lines.append(f"  _\\+{overflow} more not shown_")

        lines.append("")

    return "\n".join(lines)


# Chart constants
SPARKS = "▁▂▃▄▅▆▇█"
DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"]


def _bar_chart_text(user_rows: list, max_width: int = 10) -> str:
    """Build monospace horizontal bar chart for daily solved counts."""
    valid = [
        (u, solved, diff)
        for (u, profile, solved, diff, subs, snap) in user_rows
        if profile is not None and snap is not None
    ]

    if not valid or all(c == 0 for _, c, _ in valid):
        return ""

    max_count = max(c for _, c, _ in valid)
    max_name_len = max(len(u) for u, _, _ in valid)

    rows = []
    for username, count, diff in sorted(valid, key=lambda x: (-x[1], x[0].lower())):
        filled = round(count / max_count * max_width) if max_count else 0
        bar = "█" * filled + "░" * (max_width - filled)
        parts = [
            f"{DIFFICULTY_EMOJI[d]}{n}"
            for d in ("Easy", "Medium", "Hard")
            if (n := diff.get(d, 0))
        ]
        suffix = "  " + " ".join(parts) if parts else ""
        rows.append(f"{username.ljust(max_name_len)}  {bar}  {count}{suffix}")

    return "\n".join(rows)


def _sparkline_text(per_day_counts: dict[str, list], days_elapsed: int) -> str:
    """Build monospace sparkline chart for weekly trends."""
    if not per_day_counts:
        return ""

    all_values = [
        c
        for counts in per_day_counts.values()
        for c in counts
        if c is not None and c > 0
    ]
    max_val = max(all_values) if all_values else 0
    max_name_len = max(len(u) for u in per_day_counts) if per_day_counts else 0

    labels = DAY_LABELS[:days_elapsed] + ["·"] * (7 - days_elapsed)
    header = " " * (max_name_len + 2) + "  ".join(labels)

    rows = [header]
    for username, counts in sorted(
        per_day_counts.items(),
        key=lambda x: (-(sum(c for c in x[1] if c) or 0), x[0].lower()),
    ):
        chars = []
        for i in range(7):
            if i >= days_elapsed:
                chars.append("·")  # future days
            elif i >= len(counts) or counts[i] is None:
                chars.append("?")  # missing snapshot
            elif counts[i] == 0:
                chars.append("░")
            else:
                idx = (
                    min(7, max(0, round(counts[i] / max_val * 7.5) - 1))
                    if max_val
                    else 0
                )
                chars.append(SPARKS[idx])

        rows.append(f"{username.ljust(max_name_len)}  {'  '.join(chars)}")

    return "\n".join(rows)


def _emoji_counts(counts: dict[str, int]) -> str:
    """Format difficulty counts as emoji string like '🟢1 🟠2 🔴3'."""
    parts = []
    for diff in ("Easy", "Medium", "Hard"):
        n = counts.get(diff, 0)
        if n:
            parts.append(f"{DIFFICULTY_EMOJI[diff]}{n}")
    return " ".join(parts)


def _esc(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    text = text or ""  # Handle None gracefully
    special = r"_*[]()~`>#+-=|{}.!"
    out = []
    for ch in text:
        if ch in special:
            out.append(f"\\{ch}")
        else:
            out.append(ch)
    return "".join(out)


def _esc_preserve_code(text: str) -> str:
    """Escape MarkdownV2 special characters but preserve backtick code formatting.

    Backticks from _strip_html (e.g., `code` and ```code blocks```) are preserved
    and not escaped so they render correctly as monospace in Telegram.
    """
    text = text or ""  # Handle None gracefully
    # Temporarily replace backticks with safe Unicode placeholders (not null bytes which break Telegram parser)
    triple_placeholder = "\uFFF0TRIPLE\uFFF1"
    single_placeholder = "\uFFF0SINGLE\uFFF1"
    # Preserve both inline code (single backticks) and code blocks (triple backticks)
    # Do triple first to avoid double-replacement
    text = text.replace("```", triple_placeholder)
    text = text.replace("`", single_placeholder)

    # Now escape everything else
    text = _esc(text)

    # Restore backticks
    text = text.replace(triple_placeholder, "```")
    text = text.replace(single_placeholder, "`")

    return text


def format_problems(result: dict, filters_desc: str, page: int = 0, page_size: int = 20, bot_username: Optional[str] = None, solved_slugs: Optional[set[str]] = None) -> str:
    """Format problem list response."""
    if not result:
        return "Failed to fetch problems."

    total = result.get("total", 0)
    questions = result.get("questions", [])

    if not questions:
        return f"No problems found{f' matching {filters_desc}' if filters_desc else ''}."

    filter_part = f"\\({filters_desc} — {total} total\\)" if filters_desc else f"\\({total} total\\)"
    lines = [f"*Problem List* {filter_part}"]
    lines.append("")

    for q in questions:
        frontend_id = q.get("questionFrontendId", "?")
        title = _esc(q.get("title", "Unknown"))
        slug = q.get("titleSlug", "")
        difficulty = q.get("difficulty", "")
        emoji = DIFFICULTY_EMOJI.get(difficulty, "")
        ac_rate = q.get("acRate", 0)
        tags = q.get("topicTags", [])
        tags_str = " ".join(f"\\#{_esc(t['name'])}" for t in tags[:3])  # Limit to 3 tags

        ac_rate_str = _esc(f"{ac_rate:.1f}%") if ac_rate else "?%"

        # Use deep link to bot's /problem command if bot username available
        if bot_username:
            problem_link = f"https://t.me/{bot_username}?start=problem_{slug}"
        else:
            problem_link = f"https://leetcode.com/problems/{slug}/"

        solved_mark = "\u2705 " if solved_slugs and slug in solved_slugs else ""
        line = f"{solved_mark}{emoji} *{frontend_id}\\.*  [{title}]({problem_link}) `{slug}` · {ac_rate_str}"
        if tags_str:
            line += f" · {tags_str}"
        lines.append(line)

    lines.append("")
    start = page * page_size + 1
    end = page * page_size + len(questions)
    lines.append(f"_Showing {start}–{end} of {total}\\. Use /problem \\<slug\\> for details\\._")

    return "\n".join(lines)


def format_solved_page(
    username: str,
    submissions: list[dict],
    difficulties: dict[str, str],
    total: int,
    bot_username: Optional[str] = None,
    tz: Optional[ZoneInfo] = None,
) -> str:
    """Format a user's recent accepted problems in MarkdownV2.

    Submissions are in descending solve datetime order (most recent first).
    """
    lines = [f"*Solved by {_esc(username)}* \\({total} total\\)\n"]

    for i, sub in enumerate(submissions, start=1):
        title = _esc(sub.get("title", "Unknown"))
        slug = sub.get("titleSlug", "")
        difficulty = difficulties.get(slug, "")
        emoji = DIFFICULTY_EMOJI.get(difficulty, "")
        prefix = f"{emoji} " if emoji else ""
        if bot_username:
            problem_link = f"https://t.me/{bot_username}?start=problem_{slug}"
        else:
            problem_link = f"https://leetcode.com/problems/{slug}/"

        # Format solve datetime
        ts = int(sub.get("timestamp", 0))
        if ts and tz:
            dt = datetime.fromtimestamp(ts, tz=tz)
            date_str = _esc(dt.strftime("%d %b %Y, %H:%M"))
        elif ts:
            dt = datetime.fromtimestamp(ts)
            date_str = _esc(dt.strftime("%d %b %Y, %H:%M"))
        else:
            date_str = ""

        line = f"{i}\\. {prefix}[{title}]({problem_link})"
        if date_str:
            line += f" — _{date_str}_"
        lines.append(line)

    lines.append(f"\n_Showing {len(submissions)} most recent_")

    return "\n".join(lines)


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    text = text or ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def _convert_backticks_to_html(text: str) -> str:
    """Convert backtick pairs to HTML <code> tags.

    Handles both inline code (`code`) and code blocks (```code```).
    """
    if not text:
        return text

    # Replace code blocks first: ```code``` → <pre>code</pre>
    text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)

    # Then replace inline code: `code` → <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    return text


def _convert_leetcode_html_to_telegram(html_text: str) -> str:
    """Convert LeetCode HTML to Telegram-compatible HTML, preserving formatting.

    Converts: <strong>→<b>, <em>→<i>, <code>, <ul>/<li>→bullets, <p>→newlines.
    Strips all other HTML tags, then escapes bare &, <, > not part of Telegram tags.
    """
    if not html_text:
        return ""

    text = html_text

    # 0. Replace &nbsp; with regular space (must happen before placeholder protection
    # in step 7, otherwise &nbsp; inside <code> tags would be captured literally
    # and never unescaped, since Telegram doesn't recognize &nbsp;)
    text = text.replace('&nbsp;', ' ')

    # 1. Convert <sup> to Unicode superscript (e.g. 10<sup>4</sup> → 10⁴)
    text = re.sub(r'<sup>(.*?)</sup>', lambda m: _to_superscript(m.group(1)), text, flags=re.DOTALL)

    # 2. Convert code blocks: <pre><code>...</code></pre> → <pre>...</pre>
    text = re.sub(r'<pre><code>(.*?)</code></pre>', r'<pre>\1</pre>', text, flags=re.DOTALL)

    # 3. Convert formatting tags to Telegram equivalents
    text = re.sub(r'<strong[^>]*>', '<b>', text)
    text = text.replace('</strong>', '</b>')
    text = re.sub(r'<em[^>]*>', '<i>', text)
    text = text.replace('</em>', '</i>')

    # 4. Convert bullet lists: <ul>/<li> → • prefixed lines
    text = re.sub(r'</?ul[^>]*>', '', text)
    text = re.sub(r'</?ol[^>]*>', '', text)
    text = re.sub(r'<li[^>]*>', '\n• ', text)
    text = text.replace('</li>', '')

    # 5. Convert paragraphs to single newlines
    text = re.sub(r'<p[^>]*>', '\n', text)
    text = text.replace('</p>', '')

    # 6. Convert <br> variants to newline
    text = re.sub(r'<br\s*/?>', '\n', text)

    # 7. Temporarily protect Telegram-safe tags with placeholders
    safe_tags = {}
    counter = 0
    safe_tag_patterns = [
        r'<pre>(.*?)</pre>',
        r'<code>(.*?)</code>',
        r'<b>(.*?)</b>',
        r'<i>(.*?)</i>',
    ]
    for pattern in safe_tag_patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            placeholder = f"\uFFF0TG_TAG_{counter}\uFFF1"
            safe_tags[placeholder] = match.group(0)
            text = text.replace(match.group(0), placeholder, 1)
            counter += 1

    # 8. Strip all remaining HTML tags (now safe — Telegram tags are placeholders)
    text = re.sub(r'<[^>]+>', '', text)

    # 9. Unescape HTML entities (&lt; → <, etc.)
    text = html.unescape(text)

    # 10. Escape bare &, <, > for Telegram HTML mode
    text = _html_escape(text)

    # 11. Restore Telegram-safe tags (iterate until all nested placeholders resolved)
    # Do NOT html.unescape() the tag content — entities like &lt; must stay escaped
    # in Telegram HTML mode even inside <code>/<pre> tags.
    max_iterations = 10
    for _ in range(max_iterations):
        replaced = False
        for placeholder, tag in safe_tags.items():
            if placeholder in text:
                text = text.replace(placeholder, tag)
                replaced = True
        if not replaced:
            break

    # 12. Convert backtick pairs to code tags (for any backtick-style code in source)
    text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 13. Normalize whitespace: collapse 3+ newlines to 2, strip leading/trailing
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def _truncate_by_visible_length(html_text: str, max_len: int) -> str:
    """Truncate HTML text by visible character count, properly closing open tags."""
    if not html_text:
        return html_text

    visible_count = 0
    i = 0
    open_tags = []
    in_tag = False
    current_tag = ""

    while i < len(html_text):
        ch = html_text[i]

        if ch == '<':
            in_tag = True
            current_tag = ""
            i += 1
            continue

        if in_tag:
            if ch == '>':
                in_tag = False
                tag_content = current_tag.strip()
                # Track open/close tags
                if tag_content.startswith('/'):
                    tag_name = tag_content[1:].strip().lower()
                    if open_tags and open_tags[-1] == tag_name:
                        open_tags.pop()
                elif not tag_content.endswith('/'):
                    tag_name = re.split(r'\s', tag_content)[0].lower()
                    if tag_name in ('b', 'i', 'code', 'pre'):
                        open_tags.append(tag_name)
            else:
                current_tag += ch
            i += 1
            continue

        # Count visible character (handle HTML entities as single char)
        if ch == '&':
            entity_match = re.match(r'&[a-zA-Z]+;|&#\d+;', html_text[i:])
            if entity_match:
                visible_count += 1
                if visible_count > max_len:
                    result = html_text[:i] + "…"
                    for tag in reversed(open_tags):
                        result += f"</{tag}>"
                    return result
                i += len(entity_match.group(0))
                continue

        visible_count += 1
        if visible_count > max_len:
            result = html_text[:i] + "…"
            for tag in reversed(open_tags):
                result += f"</{tag}>"
            return result

        i += 1

    return html_text


def _esc_preserve_html_tags(text: str) -> str:
    """Escape HTML special characters but preserve safe HTML tags like <code>.

    This is useful for content that already contains HTML formatting from the source.
    Preserves: <code></code>, <strong></strong>, <em></em>, <b></b>, <i></i>
    Escapes everything else.
    """
    if not text:
        return text

    # Store safe HTML tags temporarily
    safe_tags = {}
    counter = 0

    # Match safe HTML tags: <code>...</code>, <strong>...</strong>, etc.
    safe_patterns = [
        r'<code>(.*?)</code>',
        r'<strong>(.*?)</strong>',
        r'<em>(.*?)</em>',
        r'<b>(.*?)</b>',
        r'<i>(.*?)</i>',
    ]

    for pattern in safe_patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            placeholder = f"\uFFF0SAFE_TAG_{counter}\uFFF1"
            safe_tags[placeholder] = match.group(0)
            text = text.replace(match.group(0), placeholder, 1)
            counter += 1

    # Now escape all HTML special characters
    text = _html_escape(text)

    # Restore safe tags
    for placeholder, tag in safe_tags.items():
        text = text.replace(placeholder, tag)

    return text


def _clean_description_text(text: str) -> str:
    """Remove constraint and example-like text from problem description.

    Removes paragraphs/sentences that mention:
    - Assumptions (You may assume, Note that)
    - Return instructions (You can return, Return the)
    - Examples (For example, Example:)
    - Constraints prose
    """
    if not text:
        return text

    # Patterns that indicate constraint/example text to remove
    skip_patterns = [
        r'you\s+(may\s+assume|can\s+return)',
        r'note\s+that',
        r'for\s+example',
        r'example\s*:',
        r'constraints?:',
        r'follow.up',
        r'follow-up',
        r'^input:',
        r'^output:',
        r'^explanation:',
    ]

    # Split by periods (handling cases with backticks)
    sentences = re.split(r'(?<=[.!?])\s*', text)

    filtered = []
    for sent in sentences:
        if not sent or not sent.strip():
            continue
        sent_lower = sent.lower()
        # Keep only sentences that don't match skip patterns
        if not any(re.search(pattern, sent_lower) for pattern in skip_patterns):
            filtered.append(sent.strip())

    # Join back with proper spacing
    result = ' '.join(filtered)
    # Clean up spacing around punctuation
    result = re.sub(r'\s+([.!?])', r'\1', result)
    result = result.strip()

    if result and not result.endswith(('.', '!', '?')):
        result += '.'

    return result


def format_problem_detail(question: dict, *, has_solution: bool = False, bot_username: Optional[str] = None, solved: Optional[str] = None) -> str:
    """Format full problem detail for HTML mode (avoids MarkdownV2 parsing issues)."""
    if not question:
        return "Problem not found."

    frontend_id = question.get("questionFrontendId", "?")
    title = _html_escape(question.get("title", "Unknown"))
    difficulty = question.get("difficulty", "")
    emoji = DIFFICULTY_EMOJI.get(difficulty, "")
    slug = question.get("titleSlug", "")
    content = question.get("content", "")
    likes = question.get("likes", 0)
    dislikes = question.get("dislikes", 0)
    tags = question.get("topicTags", [])
    hints = question.get("hints", [])
    is_paid = question.get("isPaidOnly", False)

    solved_badge = ""
    if solved == "ac":
        solved_badge = "\u2705 "
    elif solved == "notac":
        solved_badge = "\u274c "
    lines = [f"{solved_badge}{emoji} <b>{frontend_id}. {title}</b> · <code>{slug}</code>"]

    # Tags
    if tags:
        tags_str = " · ".join(_html_escape(t["name"]) for t in tags)
        lines.append(f"<b>Tags:</b> {tags_str}")

    # Engagement metrics
    lines.append(f"👍 {likes}  👎 {dislikes}")

    # Description: extract paragraphs and convert to Telegram HTML (preserving formatting)
    description_html = extract_description(content)
    if description_html:
        telegram_desc = _convert_leetcode_html_to_telegram(description_html)
        if telegram_desc.strip():
            telegram_desc = _truncate_by_visible_length(telegram_desc, 600)
            lines.append(f"\n{telegram_desc}")

    # Examples: extract from <pre> blocks or <p> tags in content HTML
    examples = extract_examples(content)
    if examples:
        for i, example in enumerate(examples[:3], 1):
            lines.append(f"\n<b>Example {i}:</b>")
            escaped_example = _html_escape(example)
            lines.append(f"<blockquote>{escaped_example}</blockquote>")

    # Constraints: extract from HTML and format as bullet points with rich formatting
    constraints_html = extract_constraints(content, preserve_html=True)
    if constraints_html:
        lines.append("\n<b>Constraints:</b>")
        for constraint in constraints_html[:5]:
            escaped_constraint = _convert_leetcode_html_to_telegram(constraint)
            lines.append(f"• {escaped_constraint}")

    # Hints: as individual spoilers (using Telegram's tg-spoiler tag)
    if hints and len(hints) > 0:
        lines.append("\n<b>Hints:</b>")
        for hint in hints[:3]:
            # Preserve existing HTML tags (like <code>) while escaping other content
            escaped_hint = _esc_preserve_html_tags(hint)
            # Also convert any backticks to code tags (for backtick-style code)
            escaped_hint = _convert_backticks_to_html(escaped_hint)
            lines.append(f"• <tg-spoiler>{escaped_hint}</tg-spoiler>")

    # Solution deep-link (only if solution exists)
    if has_solution and bot_username:
        solution_link = f"https://t.me/{bot_username}?start=solution_{slug}"
        lines.append(f'\n💡 <a href="{solution_link}">View Solution</a>')

    # Premium badge
    if is_paid:
        lines.append("\n⚠️ <i>Premium only</i>")

    # Link to LeetCode
    lines.append(f"\n<a href=\"https://leetcode.com/problems/{slug}/\">Open on LeetCode</a>")

    return "\n".join(lines)


LANGUAGE_DISPLAY = {
    "python": "Python",
    "python3": "Python3",
    "java": "Java",
    "cpp": "C++",
    "c": "C",
    "csharp": "C#",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "golang": "Go",
    "ruby": "Ruby",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "rust": "Rust",
    "scala": "Scala",
    "php": "PHP",
    "dart": "Dart",
    "racket": "Racket",
    "erlang": "Erlang",
    "elixir": "Elixir",
}


def format_solution_detail(slug: str, approach: dict, language: str) -> str:
    """Format a single solution approach for HTML mode."""
    name = _html_escape(approach.get("name", "Unknown"))
    explanation = _html_escape(approach.get("explanation", ""))
    time_c = _html_escape(approach.get("time_complexity", ""))
    space_c = _html_escape(approach.get("space_complexity", ""))
    code = approach.get("code", {}).get(language, "")
    lang_display = LANGUAGE_DISPLAY.get(language, language)

    lines = [f"💡 <b>Solution: <code>{_html_escape(slug)}</code></b> · <code>{_html_escape(lang_display)}</code>"]
    lines.append(f"<b>Approach:</b> {name}")

    if explanation:
        lines.append(f"\n{explanation}")

    if code:
        lines.append(f"\n<pre><code>{_html_escape(code)}</code></pre>")

    if time_c or space_c:
        parts = []
        if time_c:
            parts.append(f"Time: <code>{time_c}</code>")
        if space_c:
            parts.append(f"Space: <code>{space_c}</code>")
        lines.append(" · ".join(parts))

    lines.append(f"\n<a href=\"https://leetcode.com/problems/{slug}/\">Open on LeetCode</a>")

    return "\n".join(lines)


def format_daily_challenge(challenge: dict) -> str:
    """Format today's daily challenge in HTML mode."""
    if not challenge:
        return "Failed to fetch daily challenge."

    date = _html_escape(challenge.get("date", ""))
    question = challenge.get("question", {})

    lines = [f"📅 <b>Daily Challenge — {date}</b>\n"]
    lines.append(format_problem_detail(question))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Daily 11pm reminder
# ---------------------------------------------------------------------------

_REMINDER_TEMPLATES = [
    "🚨 *Oi\\!* {mentions} — zero LeetCode questions today\\! ⏰ You've got 1 hour before midnight, let's go\\! 💪",
    "😱 {mentions} — your LeetCode today: absolutely nothing\\! 🫠 There's still time\\.\\.\\. 1 hour left, chop chop\\! 🏃",
    "👀 {mentions} haven't touched LeetCode today\\! 🧊 Don't let the streak die — 1 hour to redeem yourselves\\! 🔥",
    "🫵 {mentions} — 0 questions done today\\?\\! 😤 The clock's ticking\\.\\.\\. 1 problem before midnight, you got this\\! ⚡",
    "📢 Friendly nudge for {mentions} — LeetCode counter is still at 0 today\\! 🥶 1 hour left, make it count\\! 🎯",
]


def format_reminder(zero_users: list[str], user_links: dict[str, dict]) -> str:
    """Build a MarkdownV2 reminder message tagging users with 0 questions today."""
    if not zero_users:
        return ""

    mentions = []
    for username in zero_users:
        link = user_links.get(username)
        if link:
            name = _esc(link["first_name"])
            mentions.append(f"[{name}](tg://user?id={link['telegram_id']})")
        else:
            mentions.append(_esc(username))

    mention_str = ", ".join(mentions)
    return random.choice(_REMINDER_TEMPLATES).format(mentions=mention_str)


# ---------------------------------------------------------------------------
# Test / Submit result formatters (HTML mode)
# ---------------------------------------------------------------------------

_STATUS_EMOJI = {
    10: "\u2705",   # Accepted
    11: "\u274c",   # Wrong Answer
    12: "\u274c",   # Memory Limit Exceeded
    13: "\u274c",   # Output Limit Exceeded
    14: "\u23f0",   # Time Limit Exceeded
    15: "\U0001f4a5",  # Runtime Error
    20: "\U0001f6ab",  # Compile Error
}


def format_test_result(result: dict, lang: str, slug: str) -> str:
    """Format interpret (test) result for HTML mode."""
    from config import STATUS_CODES

    status_code = result.get("status_code", -1)
    status_msg = STATUS_CODES.get(status_code, result.get("status_msg", "Unknown"))
    emoji = _STATUS_EMOJI.get(status_code, "\u2753")
    lang_display = LANGUAGE_DISPLAY.get(lang, lang)

    lines = [f"{emoji} <b>Test Result: {_html_escape(slug)}</b> · <code>{_html_escape(lang_display)}</code>"]
    lines.append(f"<b>Status:</b> {_html_escape(status_msg)}")

    # Compile error
    if status_code == 20:
        compile_err = result.get("full_compile_error") or result.get("compile_error", "")
        if compile_err:
            lines.append(f"\n<b>Compile Error:</b>\n<pre>{_html_escape(compile_err)}</pre>")
        return "\n".join(lines)

    # Runtime error
    if status_code == 15:
        runtime_err = result.get("full_runtime_error") or result.get("runtime_error", "")
        if runtime_err:
            lines.append(f"\n<b>Runtime Error:</b>\n<pre>{_html_escape(runtime_err)}</pre>")

    # Test case results
    code_answer = result.get("code_answer", [])
    expected_answer = result.get("expected_code_answer", [])
    total = max(len(code_answer), len(expected_answer))

    if total > 0:
        passed = 0
        lines.append("")
        for i in range(total):
            actual = code_answer[i] if i < len(code_answer) else "N/A"
            expected = expected_answer[i] if i < len(expected_answer) else "N/A"
            if actual == expected:
                passed += 1
                lines.append(f"\u2705 Test {i + 1}: <code>{_html_escape(str(actual))}</code>")
            else:
                lines.append(f"\u274c Test {i + 1}:")
                lines.append(f"  Expected: <code>{_html_escape(str(expected))}</code>")
                lines.append(f"  Got: <code>{_html_escape(str(actual))}</code>")
        lines.append(f"\n<b>Passed:</b> {passed}/{total}")

    # Runtime & memory
    status_runtime = result.get("status_runtime")
    status_memory = result.get("status_memory")
    if status_runtime or status_memory:
        perf_parts = []
        if status_runtime:
            perf_parts.append(f"Runtime: {_html_escape(status_runtime)}")
        if status_memory:
            perf_parts.append(f"Memory: {_html_escape(status_memory)}")
        lines.append(" · ".join(perf_parts))

    return "\n".join(lines)


def format_submit_result(result: dict, lang: str, slug: str) -> str:
    """Format submission result for HTML mode."""
    from config import STATUS_CODES

    status_code = result.get("status_code", -1)
    status_msg = STATUS_CODES.get(status_code, result.get("status_msg", "Unknown"))
    emoji = _STATUS_EMOJI.get(status_code, "\u2753")
    lang_display = LANGUAGE_DISPLAY.get(lang, lang)

    lines = [f"{emoji} <b>Submission: {_html_escape(slug)}</b> · <code>{_html_escape(lang_display)}</code>"]
    lines.append(f"<b>Status:</b> {_html_escape(status_msg)}")

    total_correct = result.get("total_correct")
    total_testcases = result.get("total_testcases")
    if total_correct is not None and total_testcases is not None:
        lines.append(f"<b>Test Cases:</b> {total_correct}/{total_testcases}")

    # Compile error
    if status_code == 20:
        compile_err = result.get("full_compile_error") or result.get("compile_error", "")
        if compile_err:
            lines.append(f"\n<b>Compile Error:</b>\n<pre>{_html_escape(compile_err)}</pre>")
        return "\n".join(lines)

    # Runtime error
    if status_code == 15:
        runtime_err = result.get("full_runtime_error") or result.get("runtime_error", "")
        if runtime_err:
            lines.append(f"\n<b>Runtime Error:</b>\n<pre>{_html_escape(runtime_err)}</pre>")

    # For wrong answer, show failing test case
    if status_code == 11:
        last_input = result.get("input_formatted") or result.get("last_testcase", "")
        expected = result.get("expected_output", "")
        actual = result.get("code_output", "")
        if last_input:
            lines.append(f"\n<b>Failing Input:</b>\n<pre>{_html_escape(last_input)}</pre>")
        if expected:
            lines.append(f"<b>Expected:</b> <code>{_html_escape(expected)}</code>")
        if actual:
            lines.append(f"<b>Got:</b> <code>{_html_escape(actual)}</code>")

    # Performance (for accepted)
    status_runtime = result.get("status_runtime")
    status_memory = result.get("status_memory")
    if status_runtime or status_memory:
        perf_parts = []
        if status_runtime:
            percentile_rt = result.get("runtime_percentile")
            rt_str = _html_escape(status_runtime)
            if percentile_rt:
                rt_str += f" (beats {percentile_rt:.1f}%)"
            perf_parts.append(f"Runtime: {rt_str}")
        if status_memory:
            percentile_mem = result.get("memory_percentile")
            mem_str = _html_escape(status_memory)
            if percentile_mem:
                mem_str += f" (beats {percentile_mem:.1f}%)"
            perf_parts.append(f"Memory: {mem_str}")
        lines.append("\n" + "\n".join(perf_parts))

    lines.append(f"\n<a href=\"https://leetcode.com/problems/{slug}/\">Open on LeetCode</a>")

    return "\n".join(lines)


def format_code_prompt(slug: str, code_snippet: Optional[str], lang: str) -> str:
    """Format the prompt asking user to send their code."""
    lang_display = LANGUAGE_DISPLAY.get(lang, lang)
    lines = [f"\U0001f4dd <b>Send your {_html_escape(lang_display)} code for <code>{_html_escape(slug)}</code></b>"]

    if code_snippet:
        lines.append(f"\n<b>Function signature:</b>\n<pre>{_html_escape(code_snippet)}</pre>")

    lines.append("\nPaste your complete solution as a message. Code blocks (```) are supported.")
    lines.append("Use /cancel to abort.")

    return "\n".join(lines)
