#!/usr/bin/env bash
set -euo pipefail

log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Do not fight the deployment process while it intentionally restarts services.
if [ -e /run/ferixdi-deploying ]; then
  log 'deployment in progress; health check skipped'
  exit 0
fi

# Bot readiness: retry briefly before restarting to avoid flapping on a slow start.
bot_ok=0
for _ in 1 2 3; do
  if systemctl is-active --quiet ferixdi-bot && curl -fsS --max-time 4 http://127.0.0.1:8080/health >/dev/null; then
    bot_ok=1
    break
  fi
  sleep 2
done
if [ "$bot_ok" -ne 1 ]; then
  log 'bot readiness failed; restarting ferixdi-bot'
  systemctl restart ferixdi-bot
  sleep 4
  curl -fsS --max-time 5 http://127.0.0.1:8080/health >/dev/null || {
    log 'bot still unhealthy after restart'
    exit 1
  }
fi

# Xray must exist and remain running. Docker restart policy is not assumed.
if ! docker inspect -f '{{.State.Running}}' ferixdi-xray 2>/dev/null | grep -qx true; then
  log 'xray not running; attempting docker restart'
  docker restart ferixdi-xray >/dev/null
  sleep 2
fi

# Validate live JSON so corruption/truncation is caught before the next user change.
python3 -m json.tool /opt/ferixdi/node/xray-config.json >/dev/null

# Verify every configured TCP inbound is actually listening on the host. If one
# disappears while the container claims to be running, restart Xray once.
mapfile -t ports < <(python3 - <<'PY'
import json
cfg=json.load(open('/opt/ferixdi/node/xray-config.json'))
for inbound in cfg.get('inbounds', []):
    p=inbound.get('port')
    if isinstance(p, int):
        print(p)
PY
)
missing=0
for p in "${ports[@]}"; do
  if ! ss -lntH | awk '{print $4}' | grep -Eq "(^|:)${p}$"; then
    log "xray inbound port ${p} is not listening"
    missing=1
  fi
done
if [ "$missing" -eq 1 ]; then
  log 'restarting xray because at least one inbound is missing'
  docker restart ferixdi-xray >/dev/null
  sleep 3
fi

# Deep smoke test: for one active user, the local subscription endpoint must
# return valid base64 and at least one usable VLESS profile. This catches cases
# where the process is alive but key delivery has silently regressed.
if ! python3 - <<'PY'
import base64, sqlite3, urllib.request, sys
DB='/opt/ferixdi/data/bot.db'
con=sqlite3.connect(DB, timeout=5)
row=con.execute("SELECT sub_token FROM users WHERE enabled=1 AND expires_at IS NOT NULL ORDER BY created_at LIMIT 1").fetchone()
if not row:
    sys.exit(0)
raw=urllib.request.urlopen(f'http://127.0.0.1:8080/sub/{row[0]}', timeout=5).read()
text=base64.b64decode(raw, validate=True).decode()
profiles=[x for x in text.splitlines() if x.startswith('vless://')]
if not profiles:
    raise SystemExit('subscription returned zero VLESS profiles')
PY
then
  log 'subscription smoke test failed; restarting bot and marking Xray dirty'
  touch /opt/ferixdi/data/xray-dirty || true
  systemctl restart ferixdi-bot
fi

# Reconcile DB users against the managed Xray client set. A mismatch is not an
# emergency restart: mark it dirty and let the bot's serialized sync repair it.
python3 - <<'PY' || true
import json, sqlite3
from pathlib import Path
DB=Path('/opt/ferixdi/data/bot.db')
CFG=Path('/opt/ferixdi/node/xray-config.json')
DIRTY=Path('/opt/ferixdi/data/xray-dirty')
con=sqlite3.connect(DB, timeout=5)
expected={f"tg:{r[0]}" for r in con.execute("SELECT telegram_id FROM users WHERE enabled=1 AND expires_at IS NOT NULL")}
cfg=json.load(open(CFG))
actual_sets=[]
for inbound in cfg.get('inbounds', []):
    if inbound.get('protocol', 'vless') != 'vless':
        continue
    clients=inbound.get('settings', {}).get('clients', [])
    actual_sets.append({str(c.get('email','')) for c in clients if str(c.get('email','')).startswith('tg:')})
if actual_sets and any(s != expected for s in actual_sets):
    DIRTY.touch()
PY

# Keep disk exhaustion from silently breaking SQLite, logs, Docker or backups.
use_pct="$(df -P / | awk 'NR==2{gsub(/%/,"",$5); print $5}')"
if [ "${use_pct:-0}" -ge 85 ]; then
  log "warning: root filesystem usage ${use_pct}%"
  journalctl --vacuum-time=7d >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
  find /opt/ferixdi/backups -type f -name 'bot-*.db' -mtime +14 -delete 2>/dev/null || true
fi

log 'health check OK'
