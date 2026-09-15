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

python3 "$REPO_DIR/scripts/repair-node-metadata.py"
python3 "$REPO_DIR/scripts/expand-xray-inbounds.py"

find "$BOT_DIR" -maxdepth 1 -type f -name '*.py' -delete
cp -a "$REPO_DIR/bot/." "$BOT_DIR/"
python3 "$REPO_DIR/scripts/patch-bot-runtime.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-hardening.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-profile-clean.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-edge.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-admin.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-trial-day.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-antispam.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-admin-panel.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-payment-ui.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-referrals.py" "$BOT_DIR/main.py"
python3 "$REPO_DIR/scripts/patch-bot-happ-simple.py" "$BOT_DIR/main.py"
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
if [ -z "$PUBLIC_IP" ]; then
  echo 'Could not determine public IPv4.'
  exit 5
fi
SUB_HOST="${PUBLIC_IP//./-}.sslip.io"

bash "$REPO_DIR/scripts/setup-subscription-https.sh" "$SUB_HOST"

CURRENT_ADMIN_IDS="$(awk -F= '$1=="ADMIN_IDS" {print $2; exit}' "$ENV_FILE" 2>/dev/null || true)"
if [ -z "$CURRENT_ADMIN_IDS" ] && [ -s /opt/ferixdi/data/bot.db ]; then
  CURRENT_ADMIN_IDS="$(python3 - <<'PY'
import sqlite3
p='/opt/ferixdi/data/bot.db'
try:
    con=sqlite3.connect(p)
    rows=con.execute('SELECT telegram_id FROM users ORDER BY created_at').fetchall()
    if len(rows)==1:
        print(rows[0][0])
except Exception:
    pass
PY
)"
fi
if [ -n "$CURRENT_ADMIN_IDS" ]; then
  set_env ADMIN_IDS "$CURRENT_ADMIN_IDS"
fi

set_env TRIAL_DAYS 1
set_env SUB_PORT 9443
set_env PUBLIC_HOST "$SUB_HOST"
set_env PUBLIC_SCHEME 'https'
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
Environment=PYTHONUNBUFFERED=1
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

install -m 0755 "$REPO_DIR/scripts/ferixdi-healthcheck.sh" /usr/local/sbin/ferixdi-healthcheck
cat > /etc/systemd/system/ferixdi-healthcheck.service <<'UNIT'
[Unit]
Description=Ferixdi VPN health check
After=network-online.target docker.service ferixdi-bot.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ferixdi-healthcheck
UNIT
cat > /etc/systemd/system/ferixdi-healthcheck.timer <<'UNIT'
[Unit]
Description=Run Ferixdi VPN health check every minute

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
UNIT

cat > /etc/sysctl.d/99-ferixdi-network.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.somaxconn=8192
net.core.netdev_max_backlog=16384
net.core.rmem_max=33554432
net.core.wmem_max=33554432
net.ipv4.tcp_rmem=4096 131072 33554432
net.ipv4.tcp_wmem=4096 131072 33554432
net.ipv4.tcp_moderate_rcvbuf=1
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.tcp_syncookies=1
net.ipv4.tcp_keepalive_time=120
net.ipv4.tcp_keepalive_intvl=30
net.ipv4.tcp_keepalive_probes=4
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.tcp_fin_timeout=15
net.ipv4.ip_local_port_range=10240 65535
EOF
sysctl --system >/dev/null 2>&1 || true

for port in 80 443 8443 9443 12443 13443 17443; do
  ufw allow "${port}/tcp" || true
done
ufw delete allow 8080/tcp >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl enable ferixdi-bot.service
systemctl enable --now ferixdi-healthcheck.timer

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

if [ -s /opt/ferixdi/data/bot.db ]; then
  cp -a /opt/ferixdi/data/bot.db "/opt/ferixdi/backups/predeploy-$(date -u +%Y%m%d-%H%M%S).db" || true
  find /opt/ferixdi/backups -type f -name 'predeploy-*.db' -printf '%T@ %p\n' 2>/dev/null | sort -nr | tail -n +8 | cut -d' ' -f2- | xargs -r rm -f
fi

systemctl restart ferixdi-bot
sleep 2
systemctl --no-pager --full status ferixdi-bot || true
systemctl --no-pager --full status ferixdi-healthcheck.timer || true

echo
echo 'FERIXDI BOT INSTALLED'
echo "Subscription endpoint: https://${SUB_HOST}:9443/sub/<personal-token>"
