#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/ferixdi/repo"
BOT_DIR="/opt/ferixdi/bot"
ENV_FILE="/opt/ferixdi/.env"
SERVICE_FILE="/etc/systemd/system/ferixdi-bot.service"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git python3 python3-venv python3-pip ufw

mkdir -p /opt/ferixdi/data /opt/ferixdi/backups

if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch --all --prune
  git -C "$REPO_DIR" reset --hard origin/main
else
  rm -rf "$REPO_DIR"
  git clone https://github.com/ferixdi-png/vps.git "$REPO_DIR"
fi

rm -rf "$BOT_DIR"
cp -a "$REPO_DIR/bot" "$BOT_DIR"
python3 "$REPO_DIR/scripts/patch-bot-runtime.py" "$BOT_DIR/main.py"
python3 -m py_compile "$BOT_DIR/main.py"

python3 -m venv "$BOT_DIR/.venv"
"$BOT_DIR/.venv/bin/pip" install --upgrade pip
"$BOT_DIR/.venv/bin/pip" install 'aiogram==3.31.0' 'aiohttp>=3.12,<4'

if [ ! -f "$ENV_FILE" ]; then
  touch "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

ensure_env() {
  local key="$1" value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

PUBLIC_IP="$(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)"
ensure_env TRIAL_DAYS 3
ensure_env SUB_PORT 8080
ensure_env PUBLIC_HOST "$PUBLIC_IP"
ensure_env PUBLIC_SCHEME 'http'
ensure_env SUPPORT '@ferixdiii'
ensure_env SUPPORT_URL 'https://t.me/ferixdiii'
ensure_env HAPP_URL 'https://happ.info/'
ensure_env XRAY_CONFIG '/opt/ferixdi/node/xray-config.json'
ensure_env XRAY_CONTAINER 'ferixdi-xray'
ensure_env NODE_INFO '/root/FERIXDI-NODE-INFO.txt'
ensure_env DB_PATH '/opt/ferixdi/data/bot.db'
ensure_env BACKUP_DIR '/opt/ferixdi/backups'
ensure_env BACKUP_KEEP 14

cat > "$SERVICE_FILE" <<'UNIT'
[Unit]
Description=Ferixdi VPN Telegram Bot
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/ferixdi/bot
EnvironmentFile=/opt/ferixdi/.env
ExecStart=/opt/ferixdi/bot/.venv/bin/python /opt/ferixdi/bot/main.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
UNIT

ufw allow 8080/tcp || true
systemctl daemon-reload
systemctl enable ferixdi-bot.service

if ! grep -q '^BOT_TOKEN=.' "$ENV_FILE"; then
  echo 'BOT_TOKEN is not present in /opt/ferixdi/.env.'
  exit 2
fi

systemctl restart ferixdi-bot
sleep 3
systemctl --no-pager --full status ferixdi-bot || true

echo
echo 'FERIXDI BOT INSTALLED'
echo "Subscription endpoint: http://${PUBLIC_IP}:8080/sub/<personal-token>"
