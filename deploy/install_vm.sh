#!/usr/bin/env bash
# One-time setup for the medication bot on an Ubuntu VM (Google Cloud e2-micro).
# Run as:  bash install_vm.sh
# (It uses sudo when needed. After it finishes, edit /opt/medication-bot/.env
#  with your secrets, then the service auto-starts on boot.)
set -euo pipefail

APP_DIR="/opt/medication-bot"
SERVICE="medication-bot"
REPO="https://github.com/apyny/medication-bot.git"

echo "==> Installing system packages (git, python3, venv)..."
sudo apt-get update
sudo apt-get install -y git python3 python3-venv

echo "==> Cloning repository to $APP_DIR..."
sudo mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  sudo git clone "$REPO" "$APP_DIR"
fi

echo "==> Creating Python virtualenv and installing dependencies..."
cd "$APP_DIR"
sudo python3 -m venv .venv
sudo ./.venv/bin/pip install --upgrade pip
sudo ./.venv/bin/pip install -r requirements.txt

echo "==> Creating .env from example (edit it with your secrets)..."
if [ ! -f "$APP_DIR/.env" ]; then
  sudo cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
echo "    -> Next step: edit $APP_DIR/.env (TELEGRAM_BOT_TOKEN, GOOGLE_SHEET_ID,"
echo "       GOOGLE_CREDENTIALS_B64, TIMEZONE)."

echo "==> Installing systemd service (auto-starts on boot)..."
sudo tee /etc/systemd/system/$SERVICE.service > /dev/null <<EOF
[Unit]
Description=Medication reminder Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m app.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable $SERVICE
sudo systemctl restart $SERVICE

echo
echo "==> Done. Next steps:"
echo "  1) Edit secrets:  sudo nano $APP_DIR/.env"
echo "  2) Restart:       sudo systemctl restart $SERVICE"
echo "  3) Check status:  sudo systemctl status $SERVICE"
echo "  4) Watch logs:    sudo journalctl -u $SERVICE -f"
echo "     (look for 'Google Sheets logging is ENABLED.')"