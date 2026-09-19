"""Configuration loading: environment variables + config.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from the project root if present (local dev convenience).
load_dotenv(BASE_DIR / ".env")


def _env_str(name: str, required: bool = False, default: str = "") -> str:
    value = os.getenv(name)
    if required and not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"See .env.example / SETUP.md."
        )
    return value if value is not None else default


@dataclass
class Pill:
    key: str
    name: str
    emoji: str
    dose: str


@dataclass
class ScheduleEntry:
    time: str  # "HH:MM"
    hour: int
    minute: int
    pill_key: str
    dose: str


@dataclass
class Config:
    telegram_token: str
    google_sheet_id: str
    google_credentials_json: str
    timezone: str
    log_level: str
    pills: dict[str, Pill]
    schedule: list[ScheduleEntry]
    eat_delay_minutes: int
    allowed_chat_ids: list[int]
    messages: dict[str, str]


def _load_messages(raw: dict[str, Any], defaults: dict[str, str]) -> dict[str, str]:
    messages = dict(defaults)
    messages.update({k: str(v) for k, v in (raw.get("messages") or {}).items()})
    return messages


def load_config() -> Config:
    # --- Environment -------------------------------------------------------
    telegram_token = _env_str("TELEGRAM_BOT_TOKEN", required=True)
    google_sheet_id = _env_str("GOOGLE_SHEET_ID")
    google_credentials_json = _env_str("GOOGLE_CREDENTIALS_JSON")
    timezone = _env_str("TIMEZONE", default="UTC")
    log_level = _env_str("LOG_LEVEL", default="INFO")

    credentials_file = _env_str("GOOGLE_CREDENTIALS_FILE", default="service_account.json")
    if not google_credentials_json and credentials_file:
        path = Path(credentials_file)
        if not path.is_absolute():
            path = BASE_DIR / path
        if path.exists():
            google_credentials_json = path.read_text()

    # --- config.yaml -------------------------------------------------------
    config_path = BASE_DIR / "config.yaml"
    if not config_path.exists():
        raise RuntimeError(f"config.yaml not found at {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    pills_raw: dict[str, Any] = raw.get("pills") or {}
    pills: dict[str, Pill] = {}
    for key, data in pills_raw.items():
        data = data or {}
        pills[key] = Pill(
            key=key,
            name=data.get("name", key),
            emoji=data.get("emoji", "💊"),
            dose=data.get("dose", ""),
        )

    schedule_raw: list[Any] = raw.get("schedule") or []
    schedule: list[ScheduleEntry] = []
    for entry in schedule_raw:
        time_str = str(entry.get("time", ""))
        hour, minute = _parse_time(time_str)
        pill_key = str(entry.get("pill", ""))
        if pill_key not in pills:
            raise RuntimeError(
                f"schedule entry at time {time_str!r} references unknown pill {pill_key!r}"
            )
        dose = entry.get("dose") or pills[pill_key].dose
        schedule.append(
            ScheduleEntry(
                time=time_str,
                hour=hour,
                minute=minute,
                pill_key=pill_key,
                dose=dose,
            )
        )

    eat_delay_minutes = int(raw.get("eat_delay_minutes", 30))
    allowed = raw.get("allowed_chat_ids") or []

    default_messages: dict[str, str] = {
        "reminder": "{emoji} It's time to take your pill!",
        "reminder_detail": "{pill_name} — {dose}",
        "took_confirm": "✅ Taken! Logged at {time} ({pill_name}, {dose}).",
        "skip_confirm": "⏭️ Skipped this dose. I won't remind you to eat.",
        "eat_now": "🍽️ 30 minutes have passed — you can eat now!",
        "already_handled": "This reminder was already handled.",
        "unauthorized": "Sorry, you are not allowed to use this bot.",
        "stats_header": "📊 Medication statistics (last {days} days):",
        "stats_none": "No entries recorded yet.",
        "stats_line": "• {pill_name}: {count} taken",
        "stats_total": "Total taken: {total}",
    }
    messages = _load_messages(raw, default_messages)

    if not telegram_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required. See SETUP.md.")

    return Config(
        telegram_token=telegram_token,
        google_sheet_id=google_sheet_id,
        google_credentials_json=google_credentials_json,
        timezone=timezone,
        log_level=log_level,
        pills=pills,
        schedule=schedule,
        eat_delay_minutes=eat_delay_minutes,
        allowed_chat_ids=[int(c) for c in allowed],
        messages=messages,
    )


def _parse_time(time_str: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = time_str.strip().split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError) as exc:
        raise RuntimeError(f"Invalid schedule time: {time_str!r}. Use HH:MM.") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RuntimeError(f"Invalid schedule time: {time_str!r}. Out of range.")
    return hour, minute