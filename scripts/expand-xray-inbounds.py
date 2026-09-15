#!/usr/bin/env python3
"""Normalize the live Xray node to externally reachable Reality inbounds.

Only provider-reachable ports are kept. The subscription order is optimized for
what the user actually sees in Happ: the empirically lowest-latency endpoint is
first, followed by throughput/stability fallbacks. Each inbound keeps two valid
shortIds, giving ten working client profiles across five reachable ports.
"""
from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path('/opt/ferixdi/node/xray-config.json')
CONTAINER = 'ferixdi-xray'
KEEP_PORTS = {443, 8443, 12443, 13443, 17443}
# Based on current Happ measurements: gRPC 17443 is far lower latency than the
# other exposed ports, so present it first to users. The rest are ordered by use.
PRIORITY = {17443: 0, 443: 1, 12443: 2, 13443: 3, 8443: 4}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    cfg = json.loads(CONFIG.read_text())
    original = cfg.get('inbounds', [])
    kept = []
    removed = []

    for inbound in original:
        port = inbound.get('port')
        if port not in KEEP_PORTS:
            removed.append(port)
            continue
        stream = inbound.get('streamSettings') or {}
        reality = stream.get('realitySettings') or {}
        if inbound.get('protocol', 'vless') == 'vless' and reality:
            short_ids = [str(x) for x in (reality.get('shortIds') or []) if x]
            while len(short_ids) < 2:
                candidate = secrets.token_hex(4)
                if candidate not in short_ids:
                    short_ids.append(candidate)
            reality['shortIds'] = short_ids[:2]
        kept.append(inbound)

    ports = {x.get('port') for x in kept}
    missing = KEEP_PORTS - ports
    if missing:
        raise RuntimeError(f'required reachable inbounds missing: {sorted(missing)}')

    kept.sort(key=lambda x: PRIORITY.get(int(x.get('port', 99999)), 99))
    cfg['inbounds'] = kept

    backup = CONFIG.with_suffix('.json.pre-normalize.bak')
    shutil.copy2(CONFIG, backup)
    tmp = CONFIG.with_suffix('.json.normalize.tmp')
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    json.loads(tmp.read_text())
    tmp.replace(CONFIG)

    try:
        subprocess.run(['docker', 'restart', CONTAINER], check=True, timeout=30,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if run('docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER) != 'true':
            raise RuntimeError('Xray did not return to running state')
    except Exception:
        shutil.copy2(backup, CONFIG)
        subprocess.run(['docker', 'restart', CONTAINER], check=False, timeout=30)
        raise

    print('Reachable Reality ports:', ','.join(map(str, sorted(KEEP_PORTS))))
    print('Subscription priority:', ' > '.join(map(str, [17443, 443, 12443, 13443, 8443])))
    print('Removed blocked ports:', ','.join(map(str, [p for p in removed if p is not None])) or 'none')
    print('Valid client profiles expected: 10 (2 shortIds x 5 reachable ports)')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'normalize-xray-inbounds failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise
