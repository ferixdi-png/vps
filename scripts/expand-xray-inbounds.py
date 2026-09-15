#!/usr/bin/env python3
"""Normalize and tune the live Xray node for the reachable Reality endpoints.

Goals:
- keep only provider-reachable ports so Happ never shows dead entries;
- keep two valid shortIds per endpoint;
- put the empirically fastest endpoint first;
- apply conservative Xray socket tuning supported by current Xray builds;
- improve outbound address selection without changing routing semantics.

The script is idempotent and rolls the Xray config back if the container fails
following a restart.
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
PRIORITY = {17443: 0, 443: 1, 12443: 2, 13443: 3, 8443: 4}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def tune_sockopt(stream: dict) -> None:
    """Apply low-risk TCP tuning documented by Xray Sockopt."""
    network = stream.get('network', 'raw')
    # REALITY transports used here are TCP-backed. Keep the values conservative
    # for a 1 GB VPS: TFO backlog is capped, keepalive detects stale sessions,
    # and user timeout avoids very long zombie connections.
    if network in ('raw', 'tcp', 'xhttp', 'grpc'):
        sock = stream.setdefault('sockopt', {})
        sock['tcpFastOpen'] = 256
        sock['tcpKeepAliveIdle'] = 60
        sock['tcpKeepAliveInterval'] = 15
        sock['tcpUserTimeout'] = 10000
        sock['tcpcongestion'] = 'bbr'


def tune_outbounds(cfg: dict) -> None:
    """Race IPv4/IPv6 destinations and use the fastest resolved address."""
    for outbound in cfg.get('outbounds', []):
        if outbound.get('protocol') not in ('freedom', 'direct'):
            continue
        stream = outbound.setdefault('streamSettings', {})
        sock = stream.setdefault('sockopt', {})
        sock['domainStrategy'] = 'UseIP'
        sock['happyEyeballs'] = {
            'tryDelayMs': 250,
            'prioritizeIPv6': False,
            'interleave': 1,
            'maxConcurrentTry': 4,
        }
        sock['tcpFastOpen'] = True
        sock['tcpKeepAliveIdle'] = 60
        sock['tcpKeepAliveInterval'] = 15
        sock['tcpUserTimeout'] = 10000
        sock['tcpcongestion'] = 'bbr'


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
        inbound['streamSettings'] = stream
        reality = stream.get('realitySettings') or {}
        if inbound.get('protocol', 'vless') == 'vless' and reality:
            short_ids = [str(x) for x in (reality.get('shortIds') or []) if x]
            while len(short_ids) < 2:
                candidate = secrets.token_hex(4)
                if candidate not in short_ids:
                    short_ids.append(candidate)
            reality['shortIds'] = short_ids[:2]
            tune_sockopt(stream)
        kept.append(inbound)

    ports = {x.get('port') for x in kept}
    missing = KEEP_PORTS - ports
    if missing:
        raise RuntimeError(f'required reachable inbounds missing: {sorted(missing)}')

    kept.sort(key=lambda x: PRIORITY.get(int(x.get('port', 99999)), 99))
    cfg['inbounds'] = kept
    tune_outbounds(cfg)

    backup = CONFIG.with_suffix('.json.pre-tune.bak')
    shutil.copy2(CONFIG, backup)
    tmp = CONFIG.with_suffix('.json.tune.tmp')
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
    print('Xray socket tuning: TFO + BBR + keepalive + TCP user timeout')
    print('Outbound selection: UseIP + Happy Eyeballs')
    print('Valid client profiles expected: 10 (2 shortIds x 5 reachable ports)')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'normalize-xray-inbounds failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise
