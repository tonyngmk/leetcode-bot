from zoneinfo import ZoneInfo

from leetcode import (
    DIFFICULTY_EMOJI,
    compute_diff,
    fetch_question_difficulties,
    filter_today_accepted,
    get_snapshot,
)


async def format_summary(
    chat_id: str,
    profiles: dict[str, dict | None],
    tz: ZoneInfo,
    snapshot_label: str = "today",
) -> str:
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    # Collect all slugs from today's submissions across all users to batch-fetch difficulties
    all_slugs: set[str] = set()
    user_today_subs: dict[str, list[dict]] = {}
    for username, profile in profiles.items():
        if profile is None:
            continue
        subs = filter_today_accepted(profile["recent"], tz)
        user_today_subs[username] = subs
        for sub in subs:
            slug = sub.get("titleSlug")
            if slug:
                all_slugs.add(slug)

    difficulties = await fetch_question_difficulties(list(all_slugs))

    lines = ["*Today's LeetCode Progress*\n"]

    for username, profile in sorted(profiles.items(), key=lambda x: x[0].lower()):
        if profile is None:
            lines.append(f"*{_esc(username)}*: _failed to fetch \\(private or invalid\\)_\n")
            continue

        counts = profile["counts"]
        snapshot = get_snapshot(chat_id, username, tz)

        if snapshot is None:
            total = sum(counts.values())
            diff_parts = _emoji_counts(counts)
            lines.append(
                f"*{_esc(username)}*: {total} total solved "
                f"\\({diff_parts}\\)"
            )
            lines.append(f"  _No baseline yet \\(since bot restart\\)_\n")
            continue

        diff = compute_diff(counts, snapshot)
        solved_today = sum(diff.values())

        today_subs = user_today_subs.get(username, [])

        header = f"*{_esc(username)}*: *{solved_today}* solved {snapshot_label}"
        if solved_today > 0:
            header += f" \\({_emoji_counts(diff)}\\)"

        lines.append(header)

        if today_subs:
            for sub in today_subs:
                title = _esc(sub.get("title", "Unknown"))
                slug = sub.get("titleSlug", "")
                emoji = DIFFICULTY_EMOJI.get(difficulties.get(slug, ""), "")
                prefix = f"{emoji} " if emoji else ""
                lines.append(f"  {prefix}[{title}](https://leetcode.com/problems/{slug}/)")

        lines.append("")

    return "\n".join(lines)


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
