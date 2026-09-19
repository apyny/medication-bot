"""Application entrypoint. Run with: python -m app.main"""
from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .bot import build_application
from .config import load_config
from .sheets import SheetsLogger


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP endpoint so hosts (e.g. Railway) can health-check the bot.

    The bot itself only polls Telegram and exposes no web server; without an
    HTTP listener some hosts mark the container unhealthy. This responds 200
    to any request on the configured PORT.
    """

    def do_GET(self) -> None:  # noqa: N802 (stdlib casing)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:  # keep health checks out of logs
        pass


def _start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.getLogger("medication-bot").info("Health server listening on :%s", port)


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

    _start_health_server()

    application = build_application(config, sheets)
    logger.info("Bot is polling Telegram. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()