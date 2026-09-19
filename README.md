# 💊 Telegram Medication Reminder Bot

A Telegram bot that reminds you to take your pills, tells you when you can eat
after taking them, and logs everything to a Google Sheet for statistics.

## Features

- ⏰ **Scheduled reminders** — configurable daily times for **big** and **small** pills.
- ✅ **"Took it" → eat notification** — tap a button, get told when you can eat 30 minutes later.
- 📊 **Google Sheets history** — every taken/skipped dose is logged with date, time, pill and dose.
- ☁️ **Runs without your computer** — deploys to Railway/Render free tier.

## Quick start

```bash
cp .env.example .env        # fill in your token + sheet id
pip install -r requirements.txt
python -m app.main
```

**Full instructions (Telegram, Google Sheets, deployment):** see [SETUP.md](SETUP.md).

## How it works

1. At each time in `config.yaml`'s `schedule`, the bot sends a reminder with buttons.
2. Tap **✅ Took it** → the dose is logged to Google Sheets, and a job is scheduled to
   send *"🍽️ You can eat now"* after `eat_delay_minutes` (default 30).
3. Tap **⏭️ Skip** → the skip is logged; no eat notification.
4. `/stats` shows recent totals read back from the sheet.

## Commands

| Command | Description |
| --- | --- |
| `/start` | Show the schedule and help. |
| `/stats [days]` | Show statistics from the sheet (default 7 days). |

## Configuration

- **`.env`** — secrets & settings (token, sheet id, credentials, timezone).
- **`config.yaml`** — pills, daily schedule, doses, eat delay, messages.

## Project layout

```
medication-bot/
├── app/
│   ├── main.py      # entrypoint
│   ├── config.py    # env + config.yaml loading
│   ├── bot.py       # handlers, reminders, eat-notification
│   └── sheets.py    # Google Sheets logging + stats
├── config.yaml      # schedule & messages
├── .env.example     # env template
├── Dockerfile       # containerized build
├── docker-compose.yml
├── railway.json     # Railway config
├── render.yaml      # Render config
└── SETUP.md         # full setup + deployment guide
```