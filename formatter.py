from typing import Optional
from zoneinfo import ZoneInfo

from leetcode import (
    DIFFICULTY_EMOJI,
    fetch_question_difficulties,
    filter_today_accepted,
    get_snapshot,
)


async def format_summary(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
    snapshot_label: str = "today",
) -> str:
    if not profiles:
        return "No users are being tracked. Use /add_user <username> to add one."

    # Collect all slugs from today's submissions across all users to batch-fetch difficulties
    all_slugs: set[str] = set()
    user_today_subs: dict[str, list[dict]] = {}
    user_cutoffs: dict[str, int] = {}
    for username, profile in profiles.items():
        if profile is None:
            continue

        # Get snapshot to determine cutoff time
        snapshot_data = get_snapshot(chat_id, username, tz)
        cutoff_ts = snapshot_data["timestamp"] if snapshot_data else None

        subs = filter_today_accepted(profile["recent"], tz, cutoff_ts)
        user_today_subs[username] = subs
        if cutoff_ts:
            user_cutoffs[username] = cutoff_ts

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
        snapshot_data = get_snapshot(chat_id, username, tz)

        if snapshot_data is None:
            total = sum(counts.values())
            diff_parts = _emoji_counts(counts)
            lines.append(
                f"*{_esc(username)}*: {total} total solved "
                f"\\({diff_parts}\\)"
            )
            lines.append(f"  _No baseline yet \\- tracking starts tomorrow_\n")
            continue

        today_subs = user_today_subs.get(username, [])

        # Derive count and difficulty breakdown from the actual submissions list
        # to avoid latency in LeetCode's aggregate acSubmissionNum stat
        diff_from_subs = {"Easy": 0, "Medium": 0, "Hard": 0}
        for sub in today_subs:
            slug = sub.get("titleSlug", "")
            difficulty = difficulties.get(slug, "")
            if difficulty in diff_from_subs:
                diff_from_subs[difficulty] += 1
        solved_today = sum(diff_from_subs.values())

        header = f"*{_esc(username)}*: *{solved_today}* solved {snapshot_label}"
        if solved_today > 0:
            header += f" \\({_emoji_counts(diff_from_subs)}\\)"

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
