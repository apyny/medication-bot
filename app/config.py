"""Configuration loading: environment variables + config.yaml."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import date
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
class Alternating:
    """Daily alternating dose, anchored to a reference date.

    doses[0] is taken on reference_date, doses[1] the next day, and so on
    cyclically. E.g. reference 2026-09-19 -> "88 mg", then "100 mg", "88 mg", ...
    """

    reference_date: date
    doses: list[str]


@dataclass
class ScheduleEntry:
    time: str  # "HH:MM"
    hour: int
    minute: int
    pill_key: str
    dose: str
    alternating: Alternating | None = None

    def dose_for(self, day: date) -> str:
        """Return the dose for a given calendar day."""
        if self.alternating:
            offset = (day - self.alternating.reference_date).days
            return self.alternating.doses[offset % len(self.alternating.doses)]
        return self.dose


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
    missed_check_hour: int = 23
    missed_check_minute: int = 30


def _load_messages(raw: dict[str, Any], defaults: dict[str, str]) -> dict[str, str]:
    messages = dict(defaults)
    messages.update({k: str(v) for k, v in (raw.get("messages") or {}).items()})
    return messages


def load_config() -> Config:
    # --- Environment -------------------------------------------------------
    telegram_token = _env_str("TELEGRAM_BOT_TOKEN", required=True)
    google_sheet_id = _env_str("GOOGLE_SHEET_ID")
    google_credentials_json = _env_str("GOOGLE_CREDENTIALS_JSON")
    credentials_b64 = _env_str("GOOGLE_CREDENTIALS_B64")
    timezone = _env_str("TIMEZONE", default="UTC")
    log_level = _env_str("LOG_LEVEL", default="INFO")

    # base64-encoded credentials are the most robust to paste (single line, no
    # newline/whitespace mangling), so they take precedence over raw JSON.
    if credentials_b64:
        try:
            google_credentials_json = base64.b64decode(credentials_b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 is not valid base64.") from exc

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

        alternating = None
        alt_raw = entry.get("alternating")
        if alt_raw:
            try:
                ref_date = date.fromisoformat(str(alt_raw.get("reference_date")))
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid alternating reference_date in schedule entry "
                    f"{time_str!r}: {alt_raw.get('reference_date')!r}. Use YYYY-MM-DD."
                ) from exc
            doses = [str(d) for d in (alt_raw.get("doses") or [])]
            if not doses:
                raise RuntimeError(
                    f"alternating entry {time_str!r} needs a non-empty 'doses' list"
                )
            alternating = Alternating(reference_date=ref_date, doses=doses)

        schedule.append(
            ScheduleEntry(
                time=time_str,
                hour=hour,
                minute=minute,
                pill_key=pill_key,
                dose=dose,
                alternating=alternating,
            )
        )

    eat_delay_minutes = int(raw.get("eat_delay_minutes", 30))
    allowed = raw.get("allowed_chat_ids") or []

    default_messages: dict[str, str] = {
        "reminder_date": "{weekday}",
        "reminder": "{emoji} Пора принять таблетку!",
        "reminder_detail": "Сегодня по расписанию доза – {dose}",
        "took_confirm": "✅ Принято! Записано в {time}\nВыпита таблетка дозировкой {dose}",
        "skip_confirm": "⏭️ Пропущено. Напоминание о еде отправлять не буду.",
        "eat_now": "🍽️ Прошло 30 минут — можно есть!",
        "already_handled": "Это напоминание уже обработано.",
        "unauthorized": "Извините, вам запрещено использовать этого бота.",
        "stats_header": "📊 Статистика приёма таблеток (за {days} дн.):",
        "stats_none": "Записей пока нет.",
        "stats_line": "• {pill_name}: {count} принято",
        "stats_total": "Всего принято: {total}",
    }
    messages = _load_messages(raw, default_messages)

    # Time of day when we auto-record a missed pill if there was no record.
    missed_hour, missed_minute = 23, 30
    missed_raw = raw.get("missed_check_time")
    if missed_raw is not None and str(missed_raw).strip():
        missed_hour, missed_minute = _parse_time(str(missed_raw))

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
        missed_check_hour=missed_hour,
        missed_check_minute=missed_minute,
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