import json
import logging
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import CREDENTIALS_FILE, DEFAULT_TIMEZONE, STATE_FILE

logger = logging.getLogger(__name__)


def _load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load state file")
        return {}


def _save(data: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _ensure_chat(data: dict, chat_id: str) -> dict:
    if chat_id not in data:
        data[chat_id] = {"users": [], "interval": "off", "timezone": DEFAULT_TIMEZONE}
    return data[chat_id]


def get_chat(chat_id: str) -> dict:
    data = _load()
    return _ensure_chat(data, chat_id)


def get_all_chats() -> dict:
    return _load()


def add_user(chat_id: str, username: str) -> bool:
    """Add a user. Returns False if already tracked."""
    data = _load()
    chat = _ensure_chat(data, chat_id)
    lower_users = [u.lower() for u in chat["users"]]
    if username.lower() in lower_users:
        return False
    chat["users"].append(username)
    _save(data)
    return True


def remove_user(chat_id: str, username: str) -> bool:
    """Remove a user. Returns False if not found."""
    data = _load()
    chat = _ensure_chat(data, chat_id)
    lower_map = {u.lower(): u for u in chat["users"]}
    actual = lower_map.get(username.lower())
    if not actual:
        return False
    chat["users"].remove(actual)
    # Clean up user_links entry if present
    chat.get("user_links", {}).pop(actual, None)
    _save(data)
    return True


def get_users(chat_id: str) -> list[str]:
    return get_chat(chat_id).get("users", [])


def set_interval(chat_id: str, interval: str) -> None:
    data = _load()
    chat = _ensure_chat(data, chat_id)
    chat["interval"] = interval
    _save(data)


def get_interval(chat_id: str) -> str:
    return get_chat(chat_id).get("interval", "off")


def get_timezone(chat_id: str) -> str:
    return get_chat(chat_id).get("timezone", DEFAULT_TIMEZONE)


def link_user(chat_id: str, lc_username: str, telegram_id: int, first_name: str) -> None:
    """Store mapping from LeetCode username to Telegram user info."""
    data = _load()
    chat = _ensure_chat(data, chat_id)
    links = chat.setdefault("user_links", {})
    links[lc_username] = {"telegram_id": telegram_id, "first_name": first_name}
    _save(data)


def get_user_links(chat_id: str) -> dict[str, dict]:
    """Return {lc_username: {'telegram_id': int, 'first_name': str}} for the chat."""
    return get_chat(chat_id).get("user_links", {})


def set_reminder(chat_id: str, enabled: bool) -> None:
    data = _load()
    chat = _ensure_chat(data, chat_id)
    chat["reminder"] = enabled
    _save(data)


def get_reminder(chat_id: str) -> bool:
    """Return whether the 11pm reminder is enabled (default True)."""
    return get_chat(chat_id).get("reminder", True)


def save_snapshot(
    chat_id: str,
    username: str,
    date_str: str,
    counts: dict[str, int],
    timestamp: Optional[int] = None,
) -> None:
    """Persist a snapshot with timestamp.

    If timestamp is not provided, uses current time.
    """
    if timestamp is None:
        timestamp = int(datetime.now().timestamp())

    data = _load()
    chat = _ensure_chat(data, chat_id)
    snapshots = chat.setdefault("snapshots", {})
    day = snapshots.setdefault(date_str, {})
    day[username] = {
        "counts": dict(counts),
        "timestamp": timestamp,
    }
    _save(data)


def load_snapshots(chat_id: str, date_str: str) -> dict[str, dict]:
    """Return {username: {'counts': {...}, 'timestamp': int}} for the given date.

    Handles both old format (just counts dict) and new format (dict with counts/timestamp).
    For old format, uses midnight timestamp for backwards compatibility.
    """
    tz = ZoneInfo(get_timezone(chat_id))
    chat = get_chat(chat_id)
    raw_snapshots = chat.get("snapshots", {}).get(date_str, {})

    result = {}
    for username, data in raw_snapshots.items():
        # Handle old format (just counts dict)
        if isinstance(data, dict) and "timestamp" not in data:
            # Backwards compat: assume midnight for old snapshots
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
            midnight_ts = int(date_obj.timestamp())
            result[username] = {
                "counts": data,  # Old format has counts directly
                "timestamp": midnight_ts,
            }
        else:
            # New format
            result[username] = data

    return result


# ---------------------------------------------------------------------------
# Credentials – per Telegram user, stored in credentials.json
# ---------------------------------------------------------------------------

def _load_credentials() -> dict:
    if not os.path.exists(CREDENTIALS_FILE):
        return {}
    try:
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load credentials file")
        return {}


def _save_credentials(data: dict) -> None:
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_user_credentials(
    telegram_user_id: int,
    leetcode_session: str,
    csrftoken: str,
    username: str,
) -> None:
    """Store LeetCode credentials for a Telegram user."""
    data = _load_credentials()
    data[str(telegram_user_id)] = {
        "leetcode_session": leetcode_session,
        "csrftoken": csrftoken,
        "username": username,
    }
    _save_credentials(data)


def get_user_credentials(telegram_user_id: int) -> Optional[dict]:
    """Return credentials dict or None if not logged in."""
    data = _load_credentials()
    return data.get(str(telegram_user_id))


def delete_user_credentials(telegram_user_id: int) -> bool:
    """Remove stored credentials. Returns False if not found."""
    data = _load_credentials()
    key = str(telegram_user_id)
    if key not in data:
        return False
    del data[key]
    _save_credentials(data)
    return True
