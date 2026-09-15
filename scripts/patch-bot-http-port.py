#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()

old = 'SUB_PORT = int(os.getenv("SUB_PORT", "8080"))\n'
new = 'SUB_PORT = int(os.getenv("SUB_PORT", "8080"))\nHTTP_PORT = int(os.getenv("HTTP_PORT", str(SUB_PORT)))\n'
if old in s and 'HTTP_PORT = int(os.getenv("HTTP_PORT"' not in s:
    s = s.replace(old, new, 1)

old_site = 'site = web.TCPSite(runner, "0.0.0.0", SUB_PORT)'
new_site = 'site = web.TCPSite(runner, "127.0.0.1", HTTP_PORT)'
if old_site not in s:
    raise SystemExit('web.TCPSite SUB_PORT line not found')
s = s.replace(old_site, new_site, 1)
s = s.replace('print(f"Ferixdi bot started; subscription port={SUB_PORT}", flush=True)',
              'print(f"Ferixdi bot started; http_port={HTTP_PORT}; public_subscription_port={SUB_PORT}", flush=True)', 1)

path.write_text(s)
print(f'HTTP port split patched {path}')
