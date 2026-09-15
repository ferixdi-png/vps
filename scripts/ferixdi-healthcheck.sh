#!/usr/bin/env bash
set -euo pipefail

log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

if [ -e /run/ferixdi-deploying ]; then
  log 'deployment in progress; health check skipped'
  exit 0
fi

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

if ! docker inspect -f '{{.State.Running}}' ferixdi-xray 2>/dev/null | grep -qx true; then
  log 'xray not running; attempting docker restart'
  docker restart ferixdi-xray >/dev/null
  sleep 2
fi

python3 -m json.tool /opt/ferixdi/node/xray-config.json >/dev/null

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

# Deep smoke test for the current Happ format: plaintext standard subscription
# with FERIXDI CONNECT directives and exactly eight VLESS profiles.
if ! python3 - <<'PY'
import sqlite3, urllib.request, sys
from datetime import datetime, timezone
DB='/opt/ferixdi/data/bot.db'
con=sqlite3.connect(DB, timeout=5)
rows=con.execute("SELECT sub_token, expires_at FROM users WHERE enabled=1 AND expires_at IS NOT NULL ORDER BY created_at").fetchall()
now=datetime.now(timezone.utc)
token=None
for t, exp in rows:
    try:
        if datetime.fromisoformat(exp) > now:
            token=t
            break
    except Exception:
        pass
if not token:
    sys.exit(0)
text=urllib.request.urlopen(f'http://127.0.0.1:8080/sub/{token}', timeout=5).read().decode()
lines=[x.strip() for x in text.splitlines() if x.strip()]
if not lines or lines[0] != '#profile-title: FERIXDI CONNECT':
    raise SystemExit('subscription profile title missing')
profiles=[x for x in lines if x.startswith('vless://')]
if len(profiles) != 8:
    raise SystemExit(f'subscription returned {len(profiles)} VLESS profiles instead of 8')
PY
then
  log 'subscription smoke test failed; restarting bot and marking Xray dirty'
  touch /opt/ferixdi/data/xray-dirty || true
  systemctl restart ferixdi-bot
fi

python3 - <<'PY' || true
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
DB=Path('/opt/ferixdi/data/bot.db')
CFG=Path('/opt/ferixdi/node/xray-config.json')
DIRTY=Path('/opt/ferixdi/data/xray-dirty')
con=sqlite3.connect(DB, timeout=5)
now=datetime.now(timezone.utc)
expected=set()
for tg_id, exp in con.execute("SELECT telegram_id, expires_at FROM users WHERE enabled=1 AND expires_at IS NOT NULL"):
    try:
        if datetime.fromisoformat(exp) > now:
            expected.add(f"tg:{tg_id}")
    except Exception:
        pass
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

use_pct="$(df -P / | awk 'NR==2{gsub(/%/,"",$5); print $5}')"
if [ "${use_pct:-0}" -ge 85 ]; then
  log "warning: root filesystem usage ${use_pct}%"
  journalctl --vacuum-time=7d >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
  find /opt/ferixdi/backups -type f -name 'bot-*.db' -mtime +14 -delete 2>/dev/null || true
fi

log 'health check OK'
