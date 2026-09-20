"""Telegram bot: handlers, reminders, and the 30-minute eat notification."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import BASE_DIR, Config
from .sheets import SheetsLogger

logger = logging.getLogger(__name__)

TAKE_PREFIX = "take"
SKIP_PREFIX = "skip"
CHATS_FILE = BASE_DIR / "known_chats.json"


def schedule_daily(
    app: Application,
    config: Config,
    chats: ChatRegistry,
    handled: set[tuple[int, str]],
    sheets: SheetsLogger,
) -> None:
    """Register one apscheduler 'cron' job per schedule entry at the configured time."""
    for idx, entry in enumerate(config.schedule):
        job_time = dtime(entry.hour, entry.minute, tzinfo=ZoneInfo(config.timezone))
        app.job_queue.run_daily(
            _daily_job(app, config, chats, idx), time=job_time, name=f"daily_{idx}"
        )
        logger.info(
            "Scheduled daily reminder #%d (%s) at %s %s",
            idx,
            entry.pill_key,
            entry.time,
            config.timezone,
        )


def _daily_job(
    app: Application, config: Config, chats: ChatRegistry, idx: int
):
    async def run(context: ContextTypes.DEFAULT_TYPE) -> None:
        # If the bot is locked to specific chats, send reminders only to them;
        # otherwise send to every chat that has interacted with the bot.
        targets = config.allowed_chat_ids or list(chats.chats)
        for cid in targets:
            await _send_reminder(app, config, chats, cid, idx)

    return run


def _today(config: Config):
    return datetime.now(ZoneInfo(config.timezone)).date()


_WEEKDAYS_RU = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]
_MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _format_date_ru(day) -> str:
    return f"{_WEEKDAYS_RU[day.weekday()]}, {day.day} {_MONTHS_RU[day.month - 1]} {day.year}"


def _looks_like_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


async def _send_reminder(
    app: Application, config: Config, chats: ChatRegistry, chat_id: int, idx: int
) -> None:
    entry = config.schedule[idx]
    pill = config.pills[entry.pill_key]
    day = _today(config)
    dose = entry.dose_for(day)
    occurrence = f"{entry.pill_key}-{day.strftime('%Y%m%d')}-{idx}"
    text = (
        config.messages["reminder_date"].format(
            weekday=_format_date_ru(day), date=day.strftime("%d.%m.%Y")
        )
        + "\n\n"
        + config.messages["reminder"].format(emoji=pill.emoji)
        + "\n"
        + config.messages["reminder_detail"].format(pill_name=pill.name, dose=dose)
    )
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=await _reminder_markup(occurrence, entry.pill_key),
        )
    except Exception as exc:  # network / deleted chat
        logger.error("Failed to send reminder to %s: %s", chat_id, exc)


async def _reminder_markup(occurrence: str, pill_key: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Принял(а)", callback_data=f"{TAKE_PREFIX}:{pill_key}:{occurrence}"
                ),
                InlineKeyboardButton(
                    "⏭️ Пропуск", callback_data=f"{SKIP_PREFIX}:{pill_key}:{occurrence}"
                ),
            ]
        ]
    )


class ChatRegistry:
    """Persists known chat ids so daily reminders survive bot restarts."""

    def __init__(self, path: Path = CHATS_FILE):
        self.path = path
        self.chats: set[int] = set()
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.chats = set(json.loads(self.path.read_text()))
            except (ValueError, OSError) as exc:
                logger.warning("Could not read %s: %s", self.path, exc)

    def add(self, chat_id: int) -> bool:
        if chat_id in self.chats:
            return False
        self.chats.add(chat_id)
        self._save()
        return True

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(sorted(self.chats)))
        except OSError as exc:
            logger.warning("Could not save %s: %s", self.path, exc)


def _schedule_summary(config: Config) -> str:
    lines = []
    for e in config.schedule:
        pill = config.pills[e.pill_key]
        if e.alternating:
            doses = ", ".join(e.alternating.doses)
            lines.append(
                f"• {pill.emoji} {e.time} — {pill.name} (чередуется: {doses}, "
                f"от {e.alternating.reference_date.isoformat()})"
            )
        else:
            lines.append(f"• {pill.emoji} {e.time} — {pill.name} ({e.dose})")
    return "\n".join(lines)


def build_application(config: Config, sheets: SheetsLogger) -> Application:
    chats = ChatRegistry()
    # Seed from config whitelist so reminders go out even before first message.
    for cid in config.allowed_chat_ids:
        chats.add(cid)

    # Track already-handled occurrences so a button can't be double-clicked.
    handled: set[tuple[int, str]] = set()

    app = Application.builder().token(config.telegram_token).build()

    # Register the daily reminder jobs once the application (and its job
    # queue) exist. Scheduling here avoids depending on an async post_init.
    schedule_daily(app, config, chats, handled, sheets)

    # ---------------------------------------------------------------- helpers
    def _allowed(chat_id: int) -> bool:
        if not config.allowed_chat_ids:
            return True
        return chat_id in config.allowed_chat_ids

    # ------------------------------------------------------------------ fns
    def _handle_take(chat_id: int, pill_key: str, occurrence: str) -> tuple[str, bool]:
        entry = next((e for e in config.schedule if e.pill_key == pill_key), None)
        pill = config.pills[pill_key]
        dose = entry.dose_for(_today(config)) if entry else pill.dose
        key = (chat_id, occurrence)
        if key in handled:
            return config.messages["already_handled"], False
        handled.add(key)
        logged = sheets.log_taken(pill.name, dose)
        now_str = datetime.now(ZoneInfo(config.timezone)).strftime("%H:%M")
        text = config.messages["took_confirm"].format(
            time=now_str, pill_name=pill.name, dose=dose
        )
        if not logged:
            text += "\n⚠️ (Не удалось сохранить в Google Sheets.)"
        return text, True

    def _handle_skip(chat_id: int, pill_key: str, occurrence: str) -> tuple[str, bool]:
        entry = next((e for e in config.schedule if e.pill_key == pill_key), None)
        pill = config.pills[pill_key]
        dose = entry.dose_for(_today(config)) if entry else pill.dose
        key = (chat_id, occurrence)
        if key in handled:
            return config.messages["already_handled"], False
        handled.add(key)
        sheets.log_skipped(pill.name, dose)
        return config.messages["skip_confirm"], True

    async def _schedule_eat_now(chat_id: int, pill_name: str) -> None:
        async def eat_job(context: ContextTypes.DEFAULT_TYPE) -> None:
            try:
                await app.bot.send_message(chat_id, config.messages["eat_now"])
            except Exception as exc:
                logger.error("Failed to send eat-now to %s: %s", chat_id, exc)

        minutes = config.eat_delay_minutes
        app.job_queue.run_once(
            eat_job,
            when=timedelta(minutes=minutes),
            name=f"eat_{chat_id}_{int(time.time())}",
        )
        logger.info("Scheduled eat-now notification for chat %s in %s min", chat_id, minutes)

    # --------------------------------------------------------------- commands
    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        chats.add(chat_id)
        if not _allowed(chat_id):
            await update.message.reply_text(config.messages["unauthorized"])
            return
        entries = _schedule_summary(config)
        await update.message.reply_text(
            f"👋 Привет! Я буду напоминать о приёме таблеток.\n\n"
            f"Расписание:\n{entries}\n\n"
            f"Команды:\n/start — это сообщение\n/stats — статистика\n/test — тестовое напоминание\n/comment — заметка на день"
        )

    async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a sample reminder to this chat so the flow can be tested now."""
        chat_id = update.effective_chat.id
        chats.add(chat_id)
        if not _allowed(chat_id):
            await update.message.reply_text(config.messages["unauthorized"])
            return
        if not config.schedule:
            await update.message.reply_text("Расписание не настроено.")
            return
        await _send_reminder(app, config, chats, chat_id, 0)

    async def cmd_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Set/edit the comment for a day: /comment 2026-09-19 <text> or /comment <text>."""
        chat_id = update.effective_chat.id
        chats.add(chat_id)
        if not _allowed(chat_id):
            await update.message.reply_text(config.messages["unauthorized"])
            return
        args = list(context.args or [])
        comment_date = _today(config).isoformat()
        if args and _looks_like_date(args[0]):
            comment_date = args.pop(0)
        text = " ".join(args).strip()
        if not text:
            await update.message.reply_text(
                "Как добавить заметку:\n"
                "• /comment <текст> — на сегодня\n"
                "• /comment <ГГГГ-ММ-ДД> <текст> — на конкретный день\n"
                "Пример: /comment 2026-09-19 хорошее самочувствие"
            )
            return
        ok = sheets.set_comment(comment_date, text)
        if ok:
            await update.message.reply_text(
                f"✅ Комментарий для {comment_date} сохранён: \"{text}\""
            )
        else:
            await update.message.reply_text(
                "⚠️ Google Sheets не настроен, комментарий не сохранён."
            )

    async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        chats.add(chat_id)
        if not _allowed(chat_id):
            await update.message.reply_text(config.messages["unauthorized"])
            return
        days = 7
        args = context.args
        if args:
            try:
                days = max(1, min(90, int(args[0])))
            except ValueError:
                pass
        stats = sheets.stats(days=days)
        if stats is None:
            await update.message.reply_text(
                "Google Sheets не настроен, статистика недоступна."
            )
            return
        if not stats:
            await update.message.reply_text(
                config.messages["stats_header"].format(days=days)
                + "\n"
                + config.messages["stats_none"]
            )
            return
        lines = [config.messages["stats_header"].format(days=days)]
        total = 0
        for pill_key, pill in config.pills.items():
            taken, skipped = stats.get(pill.name, (0, 0))
            total += taken
            lines.append(
                config.messages["stats_line"].format(
                    pill_name=pill.name, count=taken
                )
            )
        lines.append(config.messages["stats_total"].format(total=total))
        await update.message.reply_text("\n".join(lines))

    async def _register_chat(update: Update) -> None:
        # Any incoming message/query registers the chat for reminders.
        chat_id = update.effective_chat.id
        if chats.add(chat_id):
            logger.info("Registered chat %s for reminders", chat_id)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _register_chat(update)
        if not _allowed(update.effective_chat.id):
            await update.message.reply_text(config.messages["unauthorized"])
            return

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id
        await _register_chat(update)
        if not _allowed(chat_id):
            await query.edit_message_text(config.messages["unauthorized"])
            return

        data = query.data or ""
        parts = data.split(":")
        action = parts[0]
        if len(parts) < 3:
            return
        pill_key = parts[1]
        occurrence = parts[2]

        if action == TAKE_PREFIX:
            text, is_new = _handle_take(chat_id, pill_key, occurrence)
            if is_new:
                await _schedule_eat_now(chat_id, config.pills[pill_key].name)
        elif action == SKIP_PREFIX:
            text, is_new = _handle_skip(chat_id, pill_key, occurrence)
        else:
            return

        try:
            await query.edit_message_text(text)
        except Exception:
            # Message may have been edited already; send as a new message.
            await context.bot.send_message(chat_id, text)

    # --------------------------------------------------------------- wiring
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("comment", cmd_comment))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    return app