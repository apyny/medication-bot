"""Google Sheets logging + statistics."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import gspread
from google.auth import exceptions as google_auth_errors
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# Column layout of the medication log sheet.
HEADERS = ["Timestamp", "Date", "Time", "Pill", "Dose", "Status"]
STATUS_TAKEN = "taken"
STATUS_SKIPPED = "skipped"


class SheetsLogger:
    """Appends medication events to a Google Sheet and reads statistics."""

    def __init__(self, credentials_json: str, sheet_id: str, timezone_str: str):
        self.sheet_id = sheet_id
        self.timezone_str = timezone_str
        self.client: Optional[gspread.Client] = None
        self._worksheet = None

        if not credentials_json:
            logger.warning(
                "Google Sheets credentials not configured — history logging is DISABLED. "
                "The bot will still work, but nothing is saved. See SETUP.md."
            )
            return

        try:
            creds = service_account.Credentials.from_service_account_info(
                json.loads(credentials_json),
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            self.client = gspread.authorize(creds)
        except (ValueError, google_auth_errors.GoogleAuthError) as exc:
            logger.warning("Invalid Google credentials: %s. Logging disabled.", exc)
            self.client = None

    # ------------------------------------------------------------------ utils
    @property
    def worksheet(self):
        if self._worksheet is None and self.client:
            try:
                self._worksheet = self.client.open_by_key(self.sheet_id).sheet1
            except Exception as exc:  # gspread raises several error types
                logger.error("Could not open the spreadsheet: %s", exc)
                self._worksheet = None
        return self._worksheet

    @property
    def enabled(self) -> bool:
        return self.worksheet is not None

    def _ensure_headers(self) -> None:
        ws = self.worksheet
        if ws is None:
            return
        try:
            if ws.row_count == 0 or not ws.row_values(1) or ws.row_values(1)[0] != HEADERS[0]:
                ws.append_row(HEADERS)
        except Exception as exc:
            logger.error("Could not write headers: %s", exc)

    # ------------------------------------------------------------- logging
    def log_taken(self, pill_name: str, dose: str) -> bool:
        return self._append(pill_name, dose, STATUS_TAKEN)

    def log_skipped(self, pill_name: str, dose: str) -> bool:
        return self._append(pill_name, dose, STATUS_SKIPPED)

    def _append(self, pill_name: str, dose: str, status: str) -> bool:
        ws = self.worksheet
        if ws is None:
            return False
        now = datetime.now().astimezone()
        row = [
            now.isoformat(),
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            pill_name,
            dose,
            status,
        ]
        try:
            self._ensure_headers()
            ws.append_row(row, value_input_option="USER_ENTERED")
            return True
        except Exception as exc:
            logger.error("Failed to append row to spreadsheet: %s", exc)
            return False

    # ------------------------------------------------------------- stats
    def stats(self, days: int = 7):
        """Return a dict pill_name -> (taken_count, skipped_count) over last N days."""
        ws = self.worksheet
        if ws is None:
            return None
        try:
            values = ws.get_all_values()
        except Exception as exc:
            logger.error("Could not read spreadsheet: %s", exc)
            return None
        if not values or values[0][:1] != HEADERS[:1]:
            return {}

        from datetime import timedelta

        cutoff = (datetime.now().astimezone() - timedelta(days=days)).date()
        stats: dict[str, list[int]] = {}
        for row in values[1:]:
            if len(row) < 6:
                continue
            try:
                date = datetime.strptime(row[1], "%Y-%m-%d").date()
            except ValueError:
                continue
            if date < cutoff:
                continue
            pill = row[3]
            status = row[5]
            entry = stats.setdefault(pill, [0, 0])
            if status == STATUS_TAKEN:
                entry[0] += 1
            elif status == STATUS_SKIPPED:
                entry[1] += 1
        return stats