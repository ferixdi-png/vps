#!/usr/bin/env python3
"""Normalize the live Xray node to reachable, low-latency Reality inbounds.

Only provider-exposed ports are published. The script also applies conservative
2026 transport tuning: TCP_NODELAY/TFO/BBR socket hints, moderate XHTTP XMUX
reuse settings, and fast direct outbound socket options. Changes are idempotent.
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


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def tune_stream(inbound: dict) -> None:
    stream = inbound.setdefault('streamSettings', {})
    # Safe per-socket latency/throughput hints supported by current Xray.
    sock = stream.setdefault('sockopt', {})
    sock['tcpFastOpen'] = True
    sock['tcpNoDelay'] = True
    sock['tcpcongestion'] = 'bbr'

    network = stream.get('network', 'raw')
    if network == 'xhttp':
        x = stream.setdefault('xhttpSettings', {})
        x.setdefault('mode', 'auto')
        extra = x.setdefault('extra', {})
        # Moderate reuse: fewer handshakes during bursty browsing while rotating
        # old HTTP transports sooner than the long defaults.
        xmux = extra.setdefault('xmux', {})
        xmux['maxConcurrency'] = '5'
        xmux['hMaxRequestTimes'] = '300-600'
        xmux['hMaxReusableSecs'] = '900-1800'
        # Do not set maxConnections together with maxConcurrency.
        xmux.pop('maxConnections', None)


def tune_outbounds(cfg: dict) -> None:
    for outbound in cfg.get('outbounds', []):
        if outbound.get('protocol') != 'freedom':
            continue
        stream = outbound.setdefault('streamSettings', {})
        sock = stream.setdefault('sockopt', {})
        sock['tcpFastOpen'] = True
        sock['tcpNoDelay'] = True
        sock.setdefault('domainStrategy', 'UseIP')
        sock.setdefault('happyEyeballs', {
            'tryDelayMs': 150,
            'prioritizeIPv6': False,
            'interleave': 1,
            'maxConcurrentTry': 4,
        })


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
        tune_stream(inbound)
        kept.append(inbound)

    ports = {x.get('port') for x in kept}
    missing = KEEP_PORTS - ports
    if missing:
        raise RuntimeError(f'required reachable inbounds missing: {sorted(missing)}')

    cfg['inbounds'] = kept
    tune_outbounds(cfg)

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
    print('Removed blocked ports:', ','.join(map(str, [p for p in removed if p is not None])) or 'none')
    print('Transport tuning: TFO=on TCP_NODELAY=on BBR=on XHTTP-XMUX=moderate')
    print('Valid client profiles expected: 10 (2 shortIds x 5 reachable ports)')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'normalize-xray-inbounds failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise
