# 🚀 Setup Guide

This guide walks you through everything needed to run the medication reminder bot —
from creating the Telegram bot to deploying it to the free cloud so it works
**without your computer**.

There are **4 steps**:
1. [Create the Telegram bot (get a token)](#step-1-create-the-telegram-bot)
2. [Set up Google Sheets (service account + spreadsheet)](#step-2-set-up-google-sheets)
3. [Configure the schedule and secrets](#step-3-configure-schedule-and-secrets)
4. [Run it — locally or on the free cloud](#step-4-run-the-bot)

---

## Step 1: Create the Telegram bot

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)** (the official one, blue checkmark).
2. Send `/newbot`.
3. Follow the prompts: choose a **name** and a **username** (must end in `bot`).
4. BotFather will reply with a **token** that looks like:
   ```
   1234567890:AAH...very_long_string...
   ```
5. Copy this token — it's your `TELEGRAM_BOT_TOKEN`.

> ⚠️ Treat the token like a password. Anyone who has it can control your bot.

---

## Step 2: Set up Google Sheets

You need two things: a **spreadsheet** and a **service account** (a machine identity
that lets the bot write to it).

### 2a. Create the spreadsheet
1. Go to [sheets.new](https://sheets.new) → a new empty spreadsheet opens.
2. Note the **spreadsheet ID** from the URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_IS_THE_ID`**`/edit`
3. The bot creates the headers (`Timestamp, Date, Time, Pill, Dose, Status`)
   automatically on first use. You don't need to add columns yourself.
4. Copy the spreadsheet ID — it's your `GOOGLE_SHEET_ID`.

### 2b. Create a Google Cloud service account
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick one):
   - Top bar → project selector → **New Project** → name it → **Create**.
3. Enable the **Google Sheets API**:
   - Menu → **APIs & Services** → **Library**
   - Search **"Google Sheets API"** → open it → **Enable**.
4. Create a service account:
   - Menu → **APIs & Services** → **Credentials** → **Create Credentials** →
     **Service account**.
   - Give it a name (e.g. `medication-bot`) → **Create and continue** →
     **Done**.
5. Create a key (download the JSON):
   - In the service account list, click the account you just made.
   - **Keys** tab → **Add Key** → **Create new key** → **JSON** → **Create**.
   - A `*.json` file downloads to your computer. **Keep it safe.**

### 2c. Share the spreadsheet with the service account
1. Open your spreadsheet → click **Share** (top-right).
2. Paste the service account **email** — it looks like:
   `medication-bot@<project-id>.iam.gserviceaccount.com`
   (find it in the JSON under the `"client_email"` field, or on the Keys page).
3. Give it the role **Editor** → **Send / Share**.

The bot can now read and write your spreadsheet. ✅

---

## Step 3: Configure schedule and secrets

1. Copy the example env file:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and fill in:
   ```dotenv
   TELEGRAM_BOT_TOKEN=1234567890:AAH...your_token...
   GOOGLE_SHEET_ID=THIS_IS_THE_ID
   GOOGLE_CREDENTIALS_FILE=service_account.json
   TIMEZONE=Europe/Moscow
   ```
3. Put the service-account JSON you downloaded in step 2b into the project folder
   and name it **`service_account.json`** (or point `GOOGLE_CREDENTIALS_FILE` at it).
4. Edit **`config.yaml`** to set your **schedule**, **doses**, and **pill names**:
   ```yaml
   schedule:
     - time: "09:00"
       pill: big
       dose: "1 big pill"
     - time: "21:00"
       pill: small
       dose: "1 small pill"
   eat_delay_minutes: 30
   ```
   - `pill` must match a key in the `pills:` section (`big` / `small` by default).
   - Add/remove entries freely — each one becomes a daily reminder.
   - `eat_delay_minutes` controls the delay before the "you can eat now" message.

> 💡 Optional: to allow only yourself, find your chat id (the bot prints it to the
> logs when you message it) and add it to `allowed_chat_ids:` in `config.yaml`.
> Leave it empty to let anyone use the bot.

---

## Step 4: Run the bot

### Option A — Local test (recommended first)
```bash
cd medication-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```
Open Telegram, find your bot, and press **Start**. At each scheduled time it will
send a reminder; tap **✅ Took it** and you'll get the "you can eat now" message
after 30 minutes.

### Option B — Free cloud (no computer needed)

Two free-tier options are provided. Pick one.

#### Railway (recommended)
1. Push this folder to a GitHub repo.
2. Go to [railway.app](https://railway.app) → sign in with GitHub.
3. **New Project** → **Deploy from GitHub repo** → pick your repo.
4. Railway auto-detects the `Dockerfile` (config in `railway.json`).
5. Open **Variables** and add:
   - `TELEGRAM_BOT_TOKEN`
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_CREDENTIALS_JSON` ← paste the **full contents** of your
     `service_account.json` here (instead of a file path).
   - `TIMEZONE`
6. Deploy. The bot polls Telegram and runs 24/7. Free tier sleeps after
   inactivity, but a daily reminder is enough traffic to wake it.

#### Render
1. Push this folder to GitHub.
2. Go to [render.com](https://render.com) → **New** → **Blueprint** → pick the repo
   (uses `render.yaml`), or create a **Web Service** manually with **Docker** runtime.
3. Add the same env vars as above, including `GOOGLE_CREDENTIALS_JSON`.

> On the cloud there's no local `service_account.json` file, which is why you paste
> the credentials into `GOOGLE_CREDENTIALS_JSON` instead. The bot reads that var
> when the file path is absent.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Bot replies "not allowed" | Add your chat id to `allowed_chat_ids` in `config.yaml`, or leave it empty. |
| Nothing saved to the sheet | Check `GOOGLE_SHEET_ID` and that you shared the sheet with the service account email as **Editor**. |
| "Missing required env var" | Copy `.env.example` → `.env` and fill in `TELEGRAM_BOT_TOKEN`. |
| Reminders not firing | Confirm `TIMEZONE` is correct (e.g. `Europe/Moscow`). |
| `known_chats.json` appears | Normal — the bot stores chat ids so reminders survive restarts. |