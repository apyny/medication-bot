"""Application entrypoint. Run with: python -m app.main"""
from __future__ import annotations

import logging

from .bot import build_application
from .config import load_config
from .sheets import SheetsLogger


def main() -> None:
    config = load_config()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        level=config.log_level.upper(),
    )
    logger = logging.getLogger("medication-bot")
    logger.info("Starting medication reminder bot...")

    sheets = SheetsLogger(
        config.google_credentials_json,
        config.google_sheet_id,
        config.timezone,
    )
    if sheets.enabled:
        logger.info("Google Sheets logging is ENABLED.")
    else:
        logger.warning(
            "Google Sheets logging is DISABLED. Configure GOOGLE_SHEET_ID and "
            "credentials per SETUP.md to enable history."
        )

    application = build_application(config, sheets)
    logger.info("Bot is polling Telegram. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()