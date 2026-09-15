#!/usr/bin/env python3
"""Expand the live Xray Reality node to a wider set of real inbounds.

The script is idempotent. It clones already-working Reality transports, changes
only their listening port/tag and transport path/service name where applicable,
and keeps the existing private key, short IDs and client list. It only mutates a
host-networked container; bridged containers need explicit Docker port mapping.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path('/opt/ferixdi/node/xray-config.json')
CONTAINER = 'ferixdi-xray'
TARGETS = [
    (9443, 'raw'),
    (10443, 'raw'),
    (11443, 'xhttp'),
    (14443, 'xhttp'),
    (15443, 'xhttp'),
    (16443, 'grpc'),
    (18443, 'grpc'),
]


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def network_mode() -> str:
    return run('docker', 'inspect', '-f', '{{.HostConfig.NetworkMode}}', CONTAINER)


def choose_template(inbounds: list[dict], network: str) -> dict:
    for inbound in inbounds:
        stream = inbound.get('streamSettings') or {}
        if inbound.get('protocol', 'vless') != 'vless':
            continue
        if not stream.get('realitySettings'):
            continue
        n = stream.get('network', 'raw')
        if network == 'raw' and n in ('raw', 'tcp'):
            return inbound
        if n == network:
            return inbound
    raise RuntimeError(f'no working {network} Reality inbound to clone')


def make_clone(template: dict, port: int, network: str) -> dict:
    item = copy.deepcopy(template)
    item['port'] = port
    item['listen'] = '0.0.0.0'
    item['tag'] = f'ferixdi-{network}-{port}'
    stream = item.setdefault('streamSettings', {})
    stream['network'] = network
    if network == 'xhttp':
        x = stream.setdefault('xhttpSettings', {})
        x['path'] = f'/fx/{port}'
        x.setdefault('mode', 'auto')
        stream.pop('grpcSettings', None)
    elif network == 'grpc':
        g = stream.setdefault('grpcSettings', {})
        g['serviceName'] = f'ferixdi-{port}'
        stream.pop('xhttpSettings', None)
    elif network == 'raw':
        stream.pop('xhttpSettings', None)
        stream.pop('grpcSettings', None)
    return item


def main() -> None:
    if network_mode() != 'host':
        print('Xray container is not host-networked; expansion skipped safely')
        return
    cfg = json.loads(CONFIG.read_text())
    inbounds = cfg.setdefault('inbounds', [])
    existing_ports = {int(x.get('port')) for x in inbounds if x.get('port') is not None}
    added = []
    for port, network in TARGETS:
        if port in existing_ports:
            continue
        template = choose_template(inbounds, network)
        inbounds.append(make_clone(template, port, network))
        existing_ports.add(port)
        added.append(port)

    if not added:
        print(f'Xray already has {len(inbounds)} inbounds; nothing to add')
        return

    backup = CONFIG.with_suffix('.json.pre-expand.bak')
    shutil.copy2(CONFIG, backup)
    tmp = CONFIG.with_suffix('.json.expand.tmp')
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    json.loads(tmp.read_text())
    tmp.replace(CONFIG)

    try:
        subprocess.run(['docker', 'restart', CONTAINER], check=True, timeout=30,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        running = run('docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER)
        if running != 'true':
            raise RuntimeError('Xray did not return to running state')
    except Exception:
        shutil.copy2(backup, CONFIG)
        subprocess.run(['docker', 'restart', CONTAINER], check=False, timeout=30)
        raise

    print('Added real Reality inbounds:', ','.join(map(str, added)))
    print('Total live inbounds:', len(cfg.get('inbounds', [])))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'expand-xray-inbounds failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise
