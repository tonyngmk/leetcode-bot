import asyncio
import logging
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

import storage
from config import FETCH_DELAY_SECONDS, LEETCODE_GRAPHQL_URL, USER_PROFILE_QUERY

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


async def fetch_all_users(usernames: list[str]) -> dict[str, Optional[dict]]:
    """Fetch profiles for multiple users with rate-limiting delay."""
    results = {}
    for i, username in enumerate(usernames):
        if i > 0:
            await asyncio.sleep(FETCH_DELAY_SECONDS)
        results[username] = await fetch_user_profile(username)
    return results
