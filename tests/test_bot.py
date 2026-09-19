"""Tests for config parsing and Sheets stats logic."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.config import load_config


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        # Isolate from any real .env / credentials on the machine.
        self.env_patcher = patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKEN": "123:test",
                "GOOGLE_CREDENTIALS_FILE": "",
                "GOOGLE_CREDENTIALS_JSON": "{}",
                "TIMEZONE": "Europe/Moscow",
            },
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_load_config_basic(self) -> None:
        cfg = load_config()
        self.assertEqual(cfg.telegram_token, "123:test")
        self.assertIn("big", cfg.pills)
        self.assertIn("small", cfg.pills)
        self.assertEqual(cfg.eat_delay_minutes, 30)
        # config.yaml ships with two schedule entries.
        self.assertGreaterEqual(len(cfg.schedule), 1)
        for entry in cfg.schedule:
            self.assertIn(entry.pill_key, cfg.pills)
            self.assertTrue(0 <= entry.hour <= 23)
            self.assertTrue(0 <= entry.minute <= 59)

    def test_invalid_time_raises(self) -> None:
        from app.config import _parse_time

        with self.assertRaises(RuntimeError):
            _parse_time("25:00")
        with self.assertRaises(RuntimeError):
            _parse_time("noon")

    def test_alternating_dose_for(self) -> None:
        from datetime import date

        from app.config import Alternating, ScheduleEntry

        entry = ScheduleEntry(
            time="07:00",
            hour=7,
            minute=0,
            pill_key="big",
            dose="88 mg",
            alternating=Alternating(
                reference_date=date(2026, 9, 19),  # 88 mg on this date
                doses=["88 mg", "100 mg"],
            ),
        )
        # Reference day -> 88 mg; next day -> 100 mg; alternating thereafter.
        self.assertEqual(entry.dose_for(date(2026, 9, 19)), "88 mg")
        self.assertEqual(entry.dose_for(date(2026, 9, 20)), "100 mg")
        self.assertEqual(entry.dose_for(date(2026, 9, 21)), "88 mg")
        self.assertEqual(entry.dose_for(date(2026, 9, 22)), "100 mg")

        # Without alternating config, the static dose is returned.
        static = ScheduleEntry(
            time="07:00", hour=7, minute=0, pill_key="big", dose="1 pill"
        )
        self.assertEqual(static.dose_for(date(2026, 9, 22)), "1 pill")


class SheetsStatsTest(unittest.TestCase):
    def _make_logger(self, rows):
        # Build a real SheetsLogger without network by bypassing __init__.
        from app.sheets import SheetsLogger

        logger = object.__new__(SheetsLogger)
        logger.sheet_id = "test"
        logger.timezone_str = "UTC"
        logger.client = None
        ws = MagicMock()
        ws.get_all_values.return_value = rows
        logger._worksheet = ws
        return logger

    def test_stats_counts_only_recent(self) -> None:
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        rows = [
            ["Timestamp", "Date", "Time", "Pill", "Dose", "Status"],
            ["x", today, "09:00:00", "Big pill", "1 big pill", "taken"],
            ["x", today, "21:00:00", "Small pill", "1 small pill", "taken"],
            ["x", today, "21:00:00", "Small pill", "1 small pill", "skipped"],
            ["x", old, "09:00:00", "Big pill", "1 big pill", "taken"],  # too old
        ]
        logger = self._make_logger(rows)
        stats = logger.stats(days=7)
        self.assertEqual(stats["Big pill"], [1, 0])
        self.assertEqual(stats["Small pill"], [1, 1])

    def test_stats_handles_missing_sheet(self) -> None:
        logger = self._make_logger(None)
        logger._worksheet = None
        self.assertIsNone(logger.stats(days=7))


class SheetsCommentTest(unittest.TestCase):
    from app.sheets import HEADERS

    def _make_logger(self, ws):
        from app.sheets import SheetsLogger

        logger = object.__new__(SheetsLogger)
        logger.sheet_id = "test"
        logger.timezone_str = "UTC"
        logger.client = None
        logger._worksheet = ws
        return logger

    def test_set_comment_updates_existing_row(self) -> None:
        ws = MagicMock()
        ws.row_values.return_value = self.HEADERS
        ws.get_all_values.return_value = [
            self.HEADERS,
            ["t", "2026-09-19", "07:00", "Big pill", "88 mg", "taken", ""],
        ]
        logger = self._make_logger(ws)
        logger.set_comment("2026-09-19", "good day")
        # Comment column = 7th -> update_cell(row 2, col 7)
        ws.update_cell.assert_called_once_with(2, 7, "good day")
        ws.append_row.assert_not_called()

    def test_set_comment_appends_new_day(self) -> None:
        ws = MagicMock()
        ws.row_values.return_value = self.HEADERS
        ws.get_all_values.return_value = [self.HEADERS]
        logger = self._make_logger(ws)
        logger.set_comment("2026-09-20", "note")
        ws.update_cell.assert_not_called()
        ws.append_row.assert_called_once()


if __name__ == "__main__":
    unittest.main()