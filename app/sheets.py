"""Google Sheets logging + statistics."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.auth import exceptions as google_auth_errors
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# Column layout of the medication log sheet.
HEADERS = ["Timestamp", "Date", "Dose", "Status", "Comment"]
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
        """Ensure the header row matches HEADERS (adds new columns if needed)."""
        ws = self.worksheet
        if ws is None:
            return
        try:
            existing = ws.row_values(1) or []
            if existing != HEADERS:
                ws.update(range_name="A1", values=[HEADERS])
        except Exception as exc:
            logger.error("Could not write headers: %s", exc)

    # ------------------------------------------------------------- logging
    def log_taken(self, dose: str) -> bool:
        return self._append(dose, STATUS_TAKEN)

    def log_skipped(self, dose: str) -> bool:
        return self._append(dose, STATUS_SKIPPED)

    def _append(self, dose: str, status: str) -> bool:
        ws = self.worksheet
        if ws is None:
            return False
        now = datetime.now(ZoneInfo(self.timezone_str))
        row = [
            now.isoformat(),
            now.strftime("%Y-%m-%d"),
            dose,
            status,
            "",  # Comment (edited via /comment)
        ]
        try:
            self._ensure_headers()
            ws.append_row(row, value_input_option="USER_ENTERED")
            return True
        except Exception as exc:
            logger.error("Failed to append row to spreadsheet: %s", exc)
            return False

    def set_comment(self, date_str: str, text: str) -> bool:
        """Set/overwrite the comment for a given date (YYYY-MM-DD).

        Applies the comment to every existing row for that date; if there is no
        row yet, appends a comment-only placeholder row for the day.
        """
        ws = self.worksheet
        if ws is None:
            return False
        try:
            self._ensure_headers()
            values = ws.get_all_values()
        except Exception as exc:
            logger.error("Could not read spreadsheet for comment: %s", exc)
            return False

        date_col = HEADERS.index("Date") + 1  # 2
        comment_col = HEADERS.index("Comment") + 1  # 5
        updated = False
        for row_no, row in enumerate(values[1:], start=2):
            if len(row) >= date_col and row[date_col - 1] == date_str:
                ws.update_cell(row_no, comment_col, text)
                updated = True
        if not updated:
            # No entry for the day yet -> create a comment-only row.
            now = datetime.now(ZoneInfo(self.timezone_str))
            ws.append_row(
                [now.isoformat(), date_str, "", "", text],
                value_input_option="USER_ENTERED",
            )
        return True

    # ------------------------------------------------------------- stats
    def stats(self, days: int = 7):
        """Return a dict dose -> (taken_count, skipped_count) over last N days."""
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

        cutoff = (datetime.now(ZoneInfo(self.timezone_str)) - timedelta(days=days)).date()
        stats: dict[str, list[int]] = {}
        for row in values[1:]:
            if len(row) < 4:
                continue
            try:
                date = datetime.strptime(row[1], "%Y-%m-%d").date()
            except ValueError:
                continue
            if date < cutoff:
                continue
            dose = row[2]
            status = row[3]
            if not dose:
                continue  # comment-only rows have no dose
            entry = stats.setdefault(dose, [0, 0])
            if status == STATUS_TAKEN:
                entry[0] += 1
            elif status == STATUS_SKIPPED:
                entry[1] += 1
        return stats