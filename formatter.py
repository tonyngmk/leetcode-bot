import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from leetcode import (
    DIFFICULTY_EMOJI,
    _strip_html,
    compute_diff,
    extract_constraints,
    extract_description,
    extract_examples,
    extract_images,
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


def format_problems(result: dict, filters_desc: str, page: int = 0, page_size: int = 20, bot_username: Optional[str] = None) -> str:
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

        line = f"{emoji} *{frontend_id}\\. [{title}]({problem_link}) `{slug}` · {ac_rate_str}"
        if tags_str:
            line += f" · {tags_str}"
        lines.append(line)

    lines.append("")
    start = page * page_size + 1
    end = page * page_size + len(questions)
    lines.append(f"_Showing {start}–{end} of {total}\\. Use /problem \\<slug\\> for details\\._")

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


def format_problem_detail(question: dict) -> str:
    """Format full problem detail for HTML mode (avoids MarkdownV2 parsing issues).

    Note: Hints are excluded and should be sent separately via format_hint_spoiler().
    """
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
    is_paid = question.get("isPaidOnly", False)

    lines = [f"{emoji} <b>{frontend_id}. {title}</b> <code>{slug}</code>"]

    # Tags
    if tags:
        tags_str = " · ".join(_html_escape(t["name"]) for t in tags)
        lines.append(f"<b>Tags:</b> {tags_str}")

    # Engagement metrics
    lines.append(f"👍 {likes}  👎 {dislikes}")

    # Description: extract only the first paragraph (core problem statement)
    description_html = extract_description(content)
    clean_content = _strip_html(description_html)
    if clean_content:
        clean_content = clean_content.strip()
        # Truncate if too long
        if len(clean_content) > 600:
            clean_content = clean_content[:600] + "…"
        # Escape HTML special chars first
        escaped_content = _html_escape(clean_content)
        # Then convert backticks to proper HTML code tags
        escaped_content = _convert_backticks_to_html(escaped_content)
        lines.append(f"\n{escaped_content}")

    # Examples: extract from <pre> blocks in content HTML
    examples = extract_examples(content)
    if examples:
        for i, example in enumerate(examples[:3], 1):
            lines.append(f"\n<b>Example {i}:</b>")
            # In HTML mode, use <pre> for preformatted code (no escaping of = etc)
            escaped_example = _html_escape(example)
            lines.append(f"<pre>{escaped_example}</pre>")

    # Constraints: extract from HTML and format as bullet points
    constraints = extract_constraints(content)
    if constraints:
        lines.append("\n<b>Constraints:</b>")
        for constraint in constraints[:5]:
            escaped_constraint = _html_escape(constraint)
            # Convert backticks to code tags for consistency
            escaped_constraint = _convert_backticks_to_html(escaped_constraint)
            lines.append(f"• {escaped_constraint}")

    # Premium badge
    if is_paid:
        lines.append("\n⚠️ <i>Premium only</i>")

    # Link to LeetCode
    lines.append(f"\n<a href=\"https://leetcode.com/problems/{slug}/\">Open on LeetCode</a>")

    return "\n".join(lines)


def format_hint_spoiler(hint: str) -> str:
    """Format a single hint as an individual spoiler for sending as a separate message."""
    escaped_hint = _html_escape(hint)
    escaped_hint = _convert_backticks_to_html(escaped_hint)
    return f"<tg-spoiler>{escaped_hint}</tg-spoiler>"


def format_daily_challenge(challenge: dict) -> str:
    """Format today's daily challenge in HTML mode."""
    if not challenge:
        return "Failed to fetch daily challenge."

    date = _html_escape(challenge.get("date", ""))
    question = challenge.get("question", {})

    lines = [f"📅 <b>Daily Challenge — {date}</b>\n"]
    lines.append(format_problem_detail(question))

    return "\n".join(lines)
