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
    if snapshots is None:
        return None
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
        if snapshots and username in snapshots:
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
    """Extract all description paragraphs, stopping at assumptions or section headers.

    Includes multiple paragraphs that make up the core problem statement, but excludes
    assumption text (You may assume, Note that, You can return) and formal section
    headers (Constraints, Example, etc).
    """
    if not content:
        return ""

    # Find the position of the first section header (Constraints, Example, Assumptions, etc.)
    section_pattern = r'<p><strong[^>]*>(Constraints|Example|Assumptions|Follow[- ]?up|Note:)'
    section_match = re.search(section_pattern, content, re.IGNORECASE)

    # Determine where description ends
    description_end = len(content) if not section_match else section_match.start()
    description_section = content[:description_end]

    # Extract all <p> tags from the description section, excluding assumptions
    paragraphs = []
    pattern = r'<p>(.*?)</p>'
    for match in re.finditer(pattern, description_section, re.DOTALL):
        para_content = match.group(1)
        if not para_content.strip():
            continue

        # Check if this paragraph looks like an assumption/note (stop here if so)
        para_lower = para_content.lower()
        skip_patterns = [
            r'you\s+(may\s+assume|can\s+return)',
            r'note\s+that',
            r'you\s+can\s+modify',
        ]
        if any(re.search(pattern, para_lower) for pattern in skip_patterns):
            break  # Stop at assumptions, don't include them or anything after

        paragraphs.append(f"<p>{para_content}</p>")

    return "\n".join(paragraphs) if paragraphs else ""


def extract_examples(content: str) -> list[str]:
    """Extract formatted examples from content HTML.

    Handles three formats:
    1. <pre> blocks (traditional format):
       <pre><strong>Input:</strong> nums = [2,7,11,15]
       <strong>Output:</strong> [0,1]</pre>

    2. <div class="example-block"> format (with images):
       <p><strong class="example">Example 1:</strong></p>
       <div class="example-block">
         <p><strong>Input:</strong> <span class="example-io">grid = [[1,4],[2,3]]</span></p>
         <p><strong>Output:</strong> <span class="example-io">true</span></p>
       </div>

    3. <p> tag format (when images are present):
       <p><strong>Input:</strong> grid = [[1,4],[2,3]]</p>
       <p><strong>Output:</strong> true</p>
    """
    if not content:
        return []
    examples = []

    # First try: extract from <pre> blocks (traditional format)
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

    # Second try: extract from <div class="example-block"> (format with images)
    if not examples:
        # Match example headers with class attribute: <strong class="example">Example N:</strong>
        example_pattern = r'<p><strong class="example">Example \d+:</strong></p>'
        matches = list(re.finditer(example_pattern, content, re.IGNORECASE))

        for match_idx, match in enumerate(matches):
            start_pos = match.end()
            # Find the next example header or constraint section
            if match_idx + 1 < len(matches):
                end_pos = matches[match_idx + 1].start()
            else:
                # For last example, look for Constraints section
                constraints_match = re.search(r'<p><strong[^>]*>Constraints', content[start_pos:], re.IGNORECASE)
                if constraints_match:
                    end_pos = start_pos + constraints_match.start()
                else:
                    end_pos = len(content)

            example_section = content[start_pos:end_pos]

            # Extract Input, Output, Explanation from <p> tags within example-block
            example_lines = []
            p_pattern = r'<p>(.*?)</p>'
            for p_match in re.finditer(p_pattern, example_section, re.DOTALL):
                p_content = p_match.group(1)

                # Skip image tags and list items
                if '<img' in p_content or p_content.strip().startswith('<ul'):
                    continue

                # Unwrap tags (including span tags with classes)
                p_content = re.sub(r'<span[^>]*>(.*?)</span>', r'\1', p_content)
                p_content = re.sub(r'<strong[^>]*>(.*?)</strong>', r'\1', p_content)
                p_content = re.sub(r'<sup>(.*?)</sup>', r'^\1', p_content)
                p_content = re.sub(r'<code>(.*?)</code>', r'\1', p_content)
                p_content = re.sub(r'<[^>]+>', '', p_content)
                p_content = html.unescape(p_content)
                p_content = p_content.strip()

                # Only include lines that start with Input, Output, Explanation
                if any(p_content.startswith(prefix) for prefix in ['Input', 'Output', 'Explanation']):
                    example_lines.append(p_content)

            if example_lines:
                examples.append('\n'.join(example_lines))

    return examples


def extract_images(content: str, image_types: Optional[list[str]] = None) -> list[str]:
    """Extract image URLs from <img> tags in content HTML.

    Args:
        content: HTML content to extract images from
        image_types: List of allowed file extensions (e.g., ["jpeg", "jpg", "png"])
                     If None, defaults to ["jpeg", "jpg"]

    Matches: <img src="url" ...> or <img ... src="url" ...>
    Returns: list of absolute URLs matching the specified types
    """
    if not content:
        return []
    if image_types is None:
        image_types = ["jpeg", "jpg"]

    images = []
    # Pattern matches <img> tags with src attribute anywhere
    pattern = r'<img\s+[^>]*src="([^"]+)"[^>]*>'
    for match in re.finditer(pattern, content, re.IGNORECASE):
        url = match.group(1)
        if url:
            # Filter by file extension
            url_lower = url.lower()
            if any(url_lower.endswith(f".{ext}") for ext in image_types):
                images.append(url)
    return images


def map_images_to_examples(content: str, image_types: Optional[list[str]] = None) -> dict[str, Optional[int]]:
    """Map image URLs to their corresponding example numbers based on HTML position.

    Args:
        content: HTML content to analyze
        image_types: List of allowed file extensions (default: ["jpeg", "jpg"])

    Returns:
        Dict mapping image URLs to example numbers (1-indexed), or None if not associated with an example.
        Example: {"https://...image1.jpeg": 1, "https://...image2.jpeg": 2}
    """
    if not content:
        return {}
    if image_types is None:
        image_types = ["jpeg", "jpg"]

    # Find all <pre> blocks (examples) with their positions
    examples = []
    pre_pattern = r'<pre>(.*?)</pre>'
    for match in re.finditer(pre_pattern, content, re.DOTALL):
        examples.append({
            'start': match.start(),
            'end': match.end(),
            'content': match.group(1)
        })

    # Find all <img> tags with their positions and URLs
    images_with_pos = []
    img_pattern = r'<img\s+[^>]*src="([^"]+)"[^>]*>'
    for match in re.finditer(img_pattern, content, re.IGNORECASE):
        url = match.group(1)
        if url:
            url_lower = url.lower()
            if any(url_lower.endswith(f".{ext}") for ext in image_types):
                images_with_pos.append({
                    'url': url,
                    'pos': match.start()
                })

    # Map each image to the closest example
    mapping = {}
    for img in images_with_pos:
        closest_example_num = None
        closest_distance = float('inf')

        for i, example in enumerate(examples, 1):
            # Distance to the end of the example (prefer images right after)
            distance = abs(img['pos'] - example['end'])
            if distance < closest_distance:
                closest_distance = distance
                closest_example_num = i

        mapping[img['url']] = closest_example_num

    return mapping


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
