import asyncio
import logging
from datetime import datetime, time
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


async def fetch_user_profile(username: str) -> dict | None:
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
    date_str = _today_str(tz)
    storage.save_snapshot(chat_id, username, date_str, counts)


def get_snapshot(chat_id: str, username: str, tz: ZoneInfo) -> dict[str, int] | None:
    date_str = _today_str(tz)
    snaps = storage.load_snapshots(chat_id, date_str)
    return snaps.get(username)


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


def filter_today_accepted(recent: list[dict], tz: ZoneInfo) -> list[dict]:
    """Return deduplicated accepted submissions from today."""
    now = datetime.now(tz)
    today_start = datetime.combine(now.date(), time.min, tzinfo=tz)
    today_ts = int(today_start.timestamp())

    seen = set()
    result = []
    for sub in recent:
        if sub.get("statusDisplay") != "Accepted":
            continue
        if int(sub.get("timestamp", 0)) < today_ts:
            continue
        slug = sub.get("titleSlug")
        if slug in seen:
            continue
        seen.add(slug)
        result.append(sub)
    return result


async def fetch_all_users(usernames: list[str]) -> dict[str, dict | None]:
    """Fetch profiles for multiple users with rate-limiting delay."""
    results = {}
    for i, username in enumerate(usernames):
        if i > 0:
            await asyncio.sleep(FETCH_DELAY_SECONDS)
        results[username] = await fetch_user_profile(username)
    return results
