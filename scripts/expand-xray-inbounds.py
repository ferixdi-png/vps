#!/usr/bin/env python3
"""Normalize and tune the live Xray node for the reachable Reality endpoints.

The current client measurements show gRPC and XHTTP are healthy while the RAW
profiles on 443/8443 fail Happ's real proxy check. Reuse the already-proven gRPC
transport on those two externally reachable ports instead of publishing dead RAW
profiles. Keep XHTTP as the modern stable alternative.

The script is idempotent and rolls back the live Xray config if restart fails.
"""
from __future__ import annotations

import copy
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path('/opt/ferixdi/node/xray-config.json')
CONTAINER = 'ferixdi-xray'
KEEP_PORTS = {443, 8443, 12443, 13443, 17443}
PRIORITY = {17443: 0, 443: 1, 8443: 2, 12443: 3, 13443: 4}
GRPC_PORTS = {443, 8443, 17443}
XHTTP_PORTS = {12443, 13443}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def tune_sockopt(stream: dict) -> None:
    network = stream.get('network', 'raw')
    if network in ('raw', 'tcp', 'xhttp', 'grpc'):
        sock = stream.setdefault('sockopt', {})
        sock['tcpFastOpen'] = 256
        sock['tcpKeepAliveIdle'] = 60
        sock['tcpKeepAliveInterval'] = 15
        sock['tcpUserTimeout'] = 10000
        sock['tcpcongestion'] = 'bbr'


def tune_outbounds(cfg: dict) -> None:
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
    by_port = {int(x.get('port')): x for x in original if str(x.get('port', '')).isdigit()}

    if 17443 not in by_port:
        raise RuntimeError('gRPC template inbound 17443 is missing')
    grpc_template_stream = copy.deepcopy(by_port[17443].get('streamSettings') or {})
    if grpc_template_stream.get('network') != 'grpc':
        raise RuntimeError('port 17443 is not gRPC; refusing automatic conversion')

    kept = []
    removed = []
    for inbound in original:
        port = inbound.get('port')
        if port not in KEEP_PORTS:
            removed.append(port)
            continue

        current_stream = inbound.get('streamSettings') or {}
        current_reality = copy.deepcopy(current_stream.get('realitySettings') or {})

        # RAW 443/8443 were n/a in Happ while gRPC 17443 was consistently the
        # lowest-latency transport. Reuse the proven gRPC transport on those
        # already-open TCP ports, preserving each port's Reality identity.
        if port in {443, 8443}:
            stream = copy.deepcopy(grpc_template_stream)
            stream['network'] = 'grpc'
            if current_reality:
                stream['realitySettings'] = current_reality
            grpc = stream.setdefault('grpcSettings', {})
            grpc['serviceName'] = f'ferixdi-{port}'
            inbound['streamSettings'] = stream
            for client in inbound.setdefault('settings', {}).get('clients', []):
                client.pop('flow', None)
        else:
            stream = current_stream
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

    for inbound in kept:
        port = int(inbound['port'])
        network = (inbound.get('streamSettings') or {}).get('network')
        if port in GRPC_PORTS and network != 'grpc':
            raise RuntimeError(f'port {port} expected grpc, got {network}')
        if port in XHTTP_PORTS and network != 'xhttp':
            raise RuntimeError(f'port {port} expected xhttp, got {network}')

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
    print('Transport layout: gRPC=17443,443,8443; XHTTP=12443,13443')
    print('Subscription priority: 17443 > 443 > 8443 > 12443 > 13443')
    print('Removed blocked ports:', ','.join(map(str, [p for p in removed if p is not None])) or 'none')
    print('Xray socket tuning: TFO + BBR + keepalive + TCP user timeout')
    print('Outbound selection: UseIP + Happy Eyeballs')
    print('Valid client profiles expected: 10 (2 shortIds x 5 reachable endpoints)')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'normalize-xray-inbounds failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise
