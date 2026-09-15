#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/ferixdi/repo"
BOT_DIR="/opt/ferixdi/bot"
ENV_FILE="/opt/ferixdi/.env"
SERVICE_FILE="/etc/systemd/system/ferixdi-bot.service"
DEPLOY_SHA="${DEPLOY_SHA:-}"

export DEBIAN_FRONTEND=noninteractive
if ! command -v git >/dev/null || ! command -v python3 >/dev/null; then
  apt-get update -y
  apt-get install -y git python3 python3-venv python3-pip ufw
fi

mkdir -p /opt/ferixdi/data /opt/ferixdi/backups "$BOT_DIR"

if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch --all --prune
else
  rm -rf "$REPO_DIR"
  git clone https://github.com/ferixdi-png/vps.git "$REPO_DIR"
fi

if [ -n "$DEPLOY_SHA" ]; then
  git -C "$REPO_DIR" fetch origin "$DEPLOY_SHA" --depth=1 || true
  git -C "$REPO_DIR" reset --hard "$DEPLOY_SHA"
else
  git -C "$REPO_DIR" reset --hard origin/main
fi

echo "Deploying commit: $(git -C "$REPO_DIR" rev-parse --short HEAD)"

# Repair client-facing Reality metadata from the live Xray private key before
# the bot starts. No private key is written outside the Xray config.
python3 "$REPO_DIR/scripts/repair-node-metadata.py"

# Preserve the virtualenv between deploys; refresh only application source.
find "$BOT_DIR" -maxdepth 1 -type f -name '*.py' -delete
cp -a "$REPO_DIR/bot/." "$BOT_DIR/"
python3 "$REPO_DIR/scripts/patch-bot-runtime.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-hardening.py" "$BOT_DIR/main.py"
python3 -m py_compile "$BOT_DIR/main.py"

if [ ! -x "$BOT_DIR/.venv/bin/python" ]; then
  python3 -m venv "$BOT_DIR/.venv"
fi
"$BOT_DIR/.venv/bin/pip" install -q --disable-pip-version-check 'aiogram==3.31.0' 'aiohttp>=3.12,<4'

if [ ! -f "$ENV_FILE" ]; then
  touch "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

PUBLIC_IP="$(awk -F= '$1=="IP" && length($2)>0 {print $2; exit}' /root/FERIXDI-NODE-INFO.txt 2>/dev/null || true)"
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP="$(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)"
fi

set_env TRIAL_DAYS 3
set_env SUB_PORT 8080
set_env PUBLIC_HOST "$PUBLIC_IP"
set_env PUBLIC_SCHEME 'http'
set_env SUPPORT '@ferixdiii'
set_env SUPPORT_URL 'https://t.me/ferixdiii'
set_env HAPP_URL 'https://happ.info/'
set_env XRAY_CONFIG '/opt/ferixdi/node/xray-config.json'
set_env XRAY_CONTAINER 'ferixdi-xray'
set_env NODE_INFO '/root/FERIXDI-NODE-INFO.txt'
set_env DB_PATH '/opt/ferixdi/data/bot.db'
set_env BACKUP_DIR '/opt/ferixdi/backups'
set_env BACKUP_KEEP 14
chmod 600 "$ENV_FILE"

cat > "$SERVICE_FILE" <<'UNIT'
[Unit]
Description=Ferixdi VPN Telegram Bot
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory=/opt/ferixdi/bot
EnvironmentFile=/opt/ferixdi/.env
ExecStart=/opt/ferixdi/bot/.venv/bin/python /opt/ferixdi/bot/main.py
Restart=always
RestartSec=2
User=root
UMask=0077
MemoryMax=300M
TasksMax=128
LimitNOFILE=4096
TimeoutStopSec=20
KillSignal=SIGTERM

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
if ! grep -q '^PUBLIC_KEY=.' /root/FERIXDI-NODE-INFO.txt; then
  echo 'PUBLIC_KEY repair failed.'
  exit 3
fi
if ! test -s /opt/ferixdi/node/xray-config.json; then
  echo 'Xray config is missing.'
  exit 4
fi

# A clean DB backup before every deployment makes rollback independent of the
# six-hour in-process backup loop.
if [ -s /opt/ferixdi/data/bot.db ]; then
  cp -a /opt/ferixdi/data/bot.db "/opt/ferixdi/backups/predeploy-$(date -u +%Y%m%d-%H%M%S).db" || true
  find /opt/ferixdi/backups -type f -name 'predeploy-*.db' -printf '%T@ %p\n' 2>/dev/null | sort -nr | tail -n +8 | cut -d' ' -f2- | xargs -r rm -f
fi

systemctl restart ferixdi-bot
sleep 2
systemctl --no-pager --full status ferixdi-bot || true

echo
echo 'FERIXDI BOT INSTALLED'
echo "Subscription endpoint: http://${PUBLIC_IP}:8080/sub/<personal-token>"
