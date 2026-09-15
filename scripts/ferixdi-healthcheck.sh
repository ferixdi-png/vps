#!/usr/bin/env bash
set -euo pipefail

log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Bot readiness: retry briefly before restarting to avoid flapping during deploy.
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
fi

# Xray must exist and remain running. Docker restart policy is not assumed.
if ! docker inspect -f '{{.State.Running}}' ferixdi-xray 2>/dev/null | grep -qx true; then
  log 'xray not running; attempting docker restart'
  docker restart ferixdi-xray >/dev/null
fi

# Validate live JSON so disk corruption/truncation is caught before the next user change.
python3 -m json.tool /opt/ferixdi/node/xray-config.json >/dev/null

# Keep disk exhaustion from silently breaking SQLite, logs, Docker or backups.
use_pct="$(df -P / | awk 'NR==2{gsub(/%/,"",$5); print $5}')"
if [ "${use_pct:-0}" -ge 90 ]; then
  log "warning: root filesystem usage ${use_pct}%"
  journalctl --vacuum-time=7d >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
fi
