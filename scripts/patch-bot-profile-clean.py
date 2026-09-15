#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()
old = '''        for fp_name, fp_label in (("chrome", "Chrome"), ("firefox", "Firefox")):\n            q_variant = dict(q)\n            q_variant["fp"] = fp_name\n            variant_label = f"{label} {fp_label}"\n            links.append(\n                f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q_variant, safe='/')}#{quote(variant_label)}"\n            )\n'''
new = '''        short_ids = [str(x) for x in (reality.get("shortIds") or []) if x] or [sid]\n        for idx, sid_variant in enumerate(short_ids[:2], 1):\n            q_variant = dict(q)\n            q_variant["sid"] = sid_variant\n            variant_label = f"{label} #{idx}"\n            links.append(\n                f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q_variant, safe='/')}#{quote(variant_label)}"\n            )\n'''
count = s.count(old)
if count != 1:
    raise SystemExit(f'profile-clean patch expected 1 match, found {count}')
s = s.replace(old, new, 1)

old_url = '''    return f"{PUBLIC_SCHEME}://{host}{port}/sub/{row['sub_token']}"\n'''
new_url = '''    return f"{PUBLIC_SCHEME}://{host}{port}/sub/{row['sub_token']}?rev=10reachable-20260915"\n'''
if s.count(old_url) != 1:
    raise SystemExit(f'profile-clean subscription revision expected 1 match, found {s.count(old_url)}')
s = s.replace(old_url, new_url, 1)

path.write_text(s)
print(f'profile-clean patched {path}')
