import json
import logging
import os

from config import DEFAULT_TIMEZONE, STATE_FILE

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


def save_snapshot(chat_id: str, username: str, date_str: str, counts: dict[str, int]) -> None:
    """Persist a snapshot under snapshots.<date>.<username> for the chat."""
    data = _load()
    chat = _ensure_chat(data, chat_id)
    snapshots = chat.setdefault("snapshots", {})
    day = snapshots.setdefault(date_str, {})
    day[username] = dict(counts)
    _save(data)


def load_snapshots(chat_id: str, date_str: str) -> dict[str, dict[str, int]]:
    """Return {username: {Easy, Medium, Hard}} for the given date, or {} if none."""
    chat = get_chat(chat_id)
    return chat.get("snapshots", {}).get(date_str, {})
