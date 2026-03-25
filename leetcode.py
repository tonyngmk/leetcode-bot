import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, time
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

import storage
from config import (
    DAILY_CHALLENGE_QUERY,
    FETCH_DELAY_SECONDS,
    LEETCODE_GRAPHQL_URL,
    PROBLEM_DETAIL_QUERY,
    PROBLEMS_QUERY,
    USER_PROFILE_QUERY,
)

DIFFICULTY_EMOJI = {"Easy": "\U0001f7e2", "Medium": "\U0001f7e0", "Hard": "\U0001f534"}

logger = logging.getLogger(__name__)


def _parse_ac_counts(ac_submission_num: list[dict]) -> dict[str, int]:
    counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    for item in ac_submission_num:
        if item["difficulty"] in counts:
            counts[item["difficulty"]] = item["count"]
    return counts


async def fetch_user_profile(username: str) -> Optional[dict]:
    """Fetch a user's profile and recent submissions from LeetCode.

    Returns None if the user doesn't exist or profile is private.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LEETCODE_GRAPHQL_URL,
                json={"query": USER_PROFILE_QUERY, "variables": {"username": username}},
                headers={
                    "Content-Type": "application/json",
                    "Referer": "https://leetcode.com",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            matched = data.get("matchedUser")
            if not matched:
                return None

            ac_nums = matched.get("submitStats", {}).get("acSubmissionNum", [])
            counts = _parse_ac_counts(ac_nums)

            recent = data.get("recentSubmissionList") or []

            return {
                "username": matched["username"],
                "counts": counts,
                "recent": recent,
            }
    except Exception:
        logger.exception("Failed to fetch profile for %s", username)
        return None


def _today_str(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


def take_snapshot(chat_id: str, username: str, counts: dict[str, int], tz: ZoneInfo) -> None:
    """Take a snapshot with current timestamp."""
    date_str = _today_str(tz)
    timestamp = int(datetime.now(tz).timestamp())
    storage.save_snapshot(chat_id, username, date_str, counts, timestamp)


def get_snapshot(chat_id: str, username: str, tz: ZoneInfo) -> Optional[dict]:
    """Return snapshot dict with 'counts' and 'timestamp' keys, or None."""
    date_str = _today_str(tz)
    snapshots = storage.load_snapshots(chat_id, date_str)
    return snapshots.get(username)


def get_week_snapshot(chat_id: str, username: str, tz: ZoneInfo) -> Optional[dict]:
    """Find the oldest snapshot this week (Mon-today) for the user, or None.

    This is used as the baseline for weekly count calculations.
    """
    now = datetime.now(tz)
    days_since_monday = now.weekday()  # 0=Monday, 6=Sunday
    for days_back in range(days_since_monday, -1, -1):
        date_str = (now.date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        snapshots = storage.load_snapshots(chat_id, date_str)
        if username in snapshots:
            return snapshots[username]
    return None


def compute_diff(current: dict[str, int], snapshot: dict[str, int]) -> dict[str, int]:
    return {d: current[d] - snapshot.get(d, 0) for d in ("Easy", "Medium", "Hard")}


async def fetch_question_difficulties(slugs: list[str]) -> dict[str, str]:
    """Batch-fetch difficulty for multiple questions using aliased GraphQL."""
    if not slugs:
        return {}
    aliases = "\n".join(
        f'  q{i}: question(titleSlug: "{slug}") {{ difficulty }}'
        for i, slug in enumerate(slugs)
    )
    query = f"query {{\n{aliases}\n}}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LEETCODE_GRAPHQL_URL,
                json={"query": query},
                headers={
                    "Content-Type": "application/json",
                    "Referer": "https://leetcode.com",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            result = {}
            for i, slug in enumerate(slugs):
                q = data.get(f"q{i}")
                if q:
                    result[slug] = q["difficulty"]
            return result
    except Exception:
        logger.exception("Failed to fetch question difficulties")
        return {}


def filter_today_accepted(recent: list[dict], tz: ZoneInfo, cutoff_ts: Optional[int] = None) -> list[dict]:
    """Return deduplicated accepted submissions from cutoff time onwards.

    If cutoff_ts is not provided, defaults to midnight of current day.
    """
    if cutoff_ts is None:
        now = datetime.now(tz)
        today_start = datetime.combine(now.date(), time.min, tzinfo=tz)
        cutoff_ts = int(today_start.timestamp())

    seen = set()
    result = []
    for sub in recent:
        if sub.get("statusDisplay") != "Accepted":
            continue
        if int(sub.get("timestamp", 0)) < cutoff_ts:
            continue
        slug = sub.get("titleSlug")
        if slug in seen:
            continue
        seen.add(slug)
        result.append(sub)
    return result


def filter_week_accepted(recent: list[dict], week_start_ts: int) -> list[dict]:
    """Return deduplicated accepted submissions from week_start_ts onwards.

    The caller is responsible for providing the week_start_ts (from snapshot timestamp or computed).
    """
    seen = set()
    result = []
    for sub in recent:
        if sub.get("statusDisplay") != "Accepted":
            continue
        if int(sub.get("timestamp", 0)) < week_start_ts:
            continue
        slug = sub.get("titleSlug")
        if slug in seen:
            continue
        seen.add(slug)
        result.append(sub)
    return result


def get_week_daily_counts(
    chat_id: str,
    profiles: dict[str, Optional[dict]],
    tz: ZoneInfo,
) -> dict[str, list[Optional[int]]]:
    """Return per-day solved counts for each user this week (Mon→today).

    Returns: {username: [count_mon, count_tue, ..., count_today]}
    Each count is int (may be 0) or None (missing snapshot).
    List length = days elapsed this week (1 on Monday, 7 on Sunday).
    """
    now = datetime.now(tz)
    days_since_monday = now.weekday()  # 0=Monday, 6=Sunday

    # Load snapshots for each day Mon→today
    day_snapshots = []
    for days_back in range(days_since_monday, -1, -1):
        date_str = (now.date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        day_snapshots.append(storage.load_snapshots(chat_id, date_str))

    result = {}
    for username, profile in profiles.items():
        if profile is None:
            result[username] = [None] * (days_since_monday + 1)
            continue

        daily_counts = []
        for i in range(len(day_snapshots)):
            snap = day_snapshots[i].get(username)
            if i < len(day_snapshots) - 1:
                # Past day: diff between this day's snapshot and next day's snapshot
                snap_next = day_snapshots[i + 1].get(username)
                if snap and snap_next:
                    diff = compute_diff(snap_next["counts"], snap["counts"])
                    daily_counts.append(max(0, sum(diff.values())))
                else:
                    daily_counts.append(None)
            else:
                # Today: diff between today's snapshot and current live counts
                if snap:
                    diff = compute_diff(profile["counts"], snap["counts"])
                    daily_counts.append(max(0, sum(diff.values())))
                else:
                    daily_counts.append(None)

        result[username] = daily_counts

    return result


async def fetch_all_users(usernames: list[str]) -> dict[str, Optional[dict]]:
    """Fetch profiles for multiple users with rate-limiting delay."""
    results = {}
    for i, username in enumerate(usernames):
        if i > 0:
            await asyncio.sleep(FETCH_DELAY_SECONDS)
        results[username] = await fetch_user_profile(username)
    return results


def _strip_html(text: str) -> str:
    """Strip HTML tags and unescape entities. Crucially: unescape LAST.

    The order matters! If we unescape first, &lt;= becomes real < which then gets
    matched by the HTML-stripping regex <[^>]+> as a fake tag, truncating content.
    So we:
    1. Convert <sup> to ^n notation (preserves exponents)
    2. Process code blocks and inline code
    3. Strip remaining HTML tags (safe — no unescaped < yet)
    4. THEN unescape entities (&lt; → <, etc.)
    """
    text = text or ""
    # FIRST: Convert <sup> to ^n notation before anything else (e.g. 10<sup>4</sup> → 10^4)
    text = re.sub(r'<sup>(.*?)</sup>', r'^\1', text, flags=re.DOTALL)
    # Replace code blocks: <pre><code>...</code></pre> → ```...```
    text = re.sub(r'<pre><code>(.*?)</code></pre>', r'```\1```', text, flags=re.DOTALL)
    # Replace inline code: <code>...</code> → `...`
    text = re.sub(r'<code>(.*?)</code>', r'`\1`', text)
    # Remove remaining HTML tags (safe now — entities still encoded as &lt; etc.)
    text = re.sub(r'<[^>]+>', '', text)
    # LAST: NOW unescape HTML entities (&lt; → <, etc.)
    # This happens AFTER tag stripping, so <= comparison operators won't be mistaken for tags
    text = html.unescape(text).strip()
    return text


def extract_constraints(content: str) -> list[str]:
    """Extract constraint list items from HTML content."""
    constraints = []
    if not content:
        return constraints
    # Find <li> list items (typically within <ul> or <ol>)
    pattern = r'<li>(.*?)</li>'
    for match in re.finditer(pattern, content, re.DOTALL):
        constraint_html = match.group(1)
        # Strip HTML from constraint text
        constraint = _strip_html(constraint_html)
        if constraint:
            constraints.append(constraint)
    return constraints


def extract_description(content: str) -> str:
    """Extract only the problem description, removing examples and constraints sections.

    LeetCode's content has: description → examples → constraints → follow-up.
    We only want the description part (everything before Example/Constraint headings).
    """
    if not content:
        return ""
    # Stop at the first marker for Example, Constraint, or Follow-up
    # This handles various HTML structures like <strong>Example, <p><strong>Example, etc.
    match = re.search(
        r'<(?:p>)?<strong>(?:Example|Constraint|Follow[\s\-]?up)',
        content,
        re.IGNORECASE
    )
    if match:
        content = content[:match.start()]
    return content


def extract_examples(content: str) -> list[str]:
    """Extract formatted examples from <pre> blocks in content HTML.

    LeetCode's content field contains <pre> blocks with:
      Input: nums = [2,7,11,15], target = 9
      Output: [0,1]
      Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].
    """
    if not content:
        return []
    examples = []
    pattern = r'<pre>(.*?)</pre>'
    for match in re.finditer(pattern, content, re.DOTALL):
        pre_content = match.group(1)
        # Unwrap <strong> tags while keeping the text (e.g., <strong>Input:</strong> → Input:)
        pre_content = re.sub(r'<strong>(.*?)</strong>', r'\1', pre_content)
        # Convert <sup> to ^n notation before stripping
        pre_content = re.sub(r'<sup>(.*?)</sup>', r'^\1', pre_content)
        # Strip remaining HTML tags
        pre_content = re.sub(r'<[^>]+>', '', pre_content)
        # Unescape HTML entities after HTML is removed
        pre_content = html.unescape(pre_content)
        # Normalize whitespace: trim each line, remove empty lines
        lines = [line.strip() for line in pre_content.split('\n')]
        pre_content = '\n'.join(line for line in lines if line)
        if pre_content:
            examples.append(pre_content)
    return examples


async def fetch_problems(
    difficulty: Optional[str] = None,
    tags: Optional[list[str]] = None,
    limit: int = 20,
    skip: int = 0,
) -> Optional[dict]:
    """Fetch problem list with optional difficulty/tag filters.

    Args:
        difficulty: "EASY" | "MEDIUM" | "HARD" (uppercase)
        tags: list of tag slugs e.g. ["array", "dynamic-programming"]
        limit: number of problems to fetch (default 20)

    Returns:
        {"total": int, "questions": [...]} or None on failure
    """
    filters = {}
    if difficulty:
        filters["difficulty"] = difficulty
    if tags:
        filters["tags"] = tags

    variables = {"categorySlug": "", "skip": skip, "limit": limit, "filters": filters}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LEETCODE_GRAPHQL_URL,
                json={"query": PROBLEMS_QUERY, "variables": variables},
                headers={"Content-Type": "application/json", "Referer": "https://leetcode.com"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data.get("problemsetQuestionList")
    except Exception:
        logger.exception("Failed to fetch problems")
        return None


async def fetch_problem(slug: str) -> Optional[dict]:
    """Fetch full detail for a single problem by slug."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LEETCODE_GRAPHQL_URL,
                json={"query": PROBLEM_DETAIL_QUERY, "variables": {"titleSlug": slug.lower().replace(" ", "-")}},
                headers={"Content-Type": "application/json", "Referer": "https://leetcode.com"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data.get("question")
    except Exception:
        logger.exception("Failed to fetch problem %s", slug)
        return None


async def fetch_daily_challenge() -> Optional[dict]:
    """Fetch today's daily coding challenge."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LEETCODE_GRAPHQL_URL,
                json={"query": DAILY_CHALLENGE_QUERY},
                headers={"Content-Type": "application/json", "Referer": "https://leetcode.com"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data.get("activeDailyCodingChallengeQuestion")
    except Exception:
        logger.exception("Failed to fetch daily challenge")
        return None
