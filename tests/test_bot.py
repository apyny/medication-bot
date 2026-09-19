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


if __name__ == "__main__":
    unittest.main()