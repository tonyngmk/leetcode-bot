from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from leetcode import (
    DIFFICULTY_EMOJI,
    compute_diff,
    fetch_question_difficulties,
    filter_today_accepted,
    filter_week_accepted,
    get_snapshot,
    get_week_daily_counts,
    get_week_snapshot,
)


async def format_daily(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
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
        # Store snapshot diff for emoji display (computed in render loop)
        diff_breakdown = None  # Will compute from snapshot in render

        user_rows.append((username, profile, solved_today, diff_breakdown, subs, snapshot_data))

    difficulties = await fetch_question_difficulties(list(all_slugs))

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
                lines.append(f"  {prefix}[{title}](https://leetcode.com/problems/{slug}/)")

            # Overflow note if snapshot diff shows more solved than captured in recent[]
            if snapshot_data:
                snapshot_diff = compute_diff(profile["counts"], snapshot_data["counts"])
                snapshot_diff_total = sum(snapshot_diff.values())
                if snapshot_diff_total > len(subs):
                    overflow = snapshot_diff_total - len(subs)
                    lines.append(f"  _\+{overflow} more not shown_")

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
) -> str:
    """Format compact dual-ranking leaderboard (daily + weekly) with submissions-based counts."""
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    # Collect all slugs for batch fetching difficulties
    all_slugs: set[str] = set()

    # Compute counts using submissions-based approach (consistent with /daily and /weekly)
    daily_data: list[tuple[str, list[dict]]] = []  # (username, subs)
    weekly_data: list[tuple[str, list[dict]]] = []  # (username, subs)

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

    # Sort each section independently by count
    daily_users_processed.sort(key=lambda x: (-x[1], x[0].lower()))
    weekly_users_processed.sort(key=lambda x: (-x[1] if x[1] is not None else float('inf'), x[0].lower()))

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

    return "\n".join(lines)


async def format_weekly(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
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
                lines.append(f"  {prefix}[{title}](https://leetcode.com/problems/{slug}/)")

            # Overflow note if snapshot diff shows more solved than captured in recent[]
            if compute_diff_total and compute_diff_total > len(subs):
                overflow = compute_diff_total - len(subs)
                lines.append(f"  _\+{overflow} more not shown_")

        lines.append("")

    # Append sparkline chart
    per_day = get_week_daily_counts(chat_id, profiles, tz)
    days_elapsed = datetime.now(tz).weekday() + 1  # 1=Monday through 7=Sunday
    chart = _sparkline_text(per_day, days_elapsed)
    if chart:
        lines.append("\n📈 *Trend*")
        lines.append(f"```\n{chart}\n```")

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
    special = r"_*[]()~`>#+-=|{}.!"
    out = []
    for ch in text:
        if ch in special:
            out.append(f"\\{ch}")
        else:
            out.append(ch)
    return "".join(out)
