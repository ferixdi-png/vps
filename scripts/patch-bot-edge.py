#!/usr/bin/env python3
"""Edge/API hardening applied after the production bot patches."""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"edge patch {name}: expected 1 match, found {count}")
    s = s.replace(old, new, 1)


replace_once(
    "import asyncio\nimport base64\nimport html\n",
    "import asyncio\nimport base64\nimport html\nfrom collections import defaultdict, deque\n",
    "rate-limit imports",
)

replace_once(
    "XRAY_LOCK = threading.Lock()\nXRAY_DIRTY = DB_PATH.parent / 'xray-dirty'\n",
    "XRAY_LOCK = threading.Lock()\nXRAY_DIRTY = DB_PATH.parent / 'xray-dirty'\nSUB_REQUESTS = defaultdict(deque)\nSUB_RATE_WINDOW = 60.0\nSUB_RATE_MAX = 90\n",
    "rate-limit state",
)

old_sub = '''async def sub_handler(request: web.Request):\n    row = get_user_by_token(request.match_info["token"])\n    if not is_active(row):\n        raise web.HTTPNotFound()\n    try:\n        links = profile_links(row)\n    except Exception as e:\n        print(f"subscription render error: {type(e).__name__}: {e}", flush=True)\n        raise web.HTTPServiceUnavailable(text="subscription temporarily unavailable")\n    if not links:\n        raise web.HTTPServiceUnavailable(text="no VPN profiles configured")\n    body = base64.b64encode(("\\n".join(links) + "\\n").encode()).decode()\n    exp = parse_exp(row)\n    expire_unix = int(exp.timestamp()) if exp else 0\n    headers = {\n        "Profile-Title": "Ferixdi VPN",\n        "Subscription-Userinfo": f"upload=0; download=0; total=0; expire={expire_unix}",\n    }\n    return web.Response(text=body, content_type="text/plain", headers=headers)\n'''

new_sub = '''async def sub_handler(request: web.Request):\n    token = request.match_info["token"]\n    if not (20 <= len(token) <= 128) or not all(ch.isalnum() or ch in "-_" for ch in token):\n        raise web.HTTPNotFound()\n\n    peer = request.remote or "unknown"\n    now = time.monotonic()\n    q = SUB_REQUESTS[peer]\n    while q and now - q[0] > SUB_RATE_WINDOW:\n        q.popleft()\n    if len(q) >= SUB_RATE_MAX:\n        raise web.HTTPTooManyRequests(text="too many requests", headers={"Retry-After": "60"})\n    q.append(now)\n    if len(SUB_REQUESTS) > 2048:\n        for key in list(SUB_REQUESTS)[:1024]:\n            if not SUB_REQUESTS[key] or now - SUB_REQUESTS[key][-1] > SUB_RATE_WINDOW:\n                SUB_REQUESTS.pop(key, None)\n\n    row = get_user_by_token(token)\n    if not is_active(row):\n        raise web.HTTPNotFound()\n    try:\n        links = profile_links(row)\n    except Exception as e:\n        print(f"subscription render error: {type(e).__name__}: {e}", flush=True)\n        raise web.HTTPServiceUnavailable(text="subscription temporarily unavailable")\n    if not links:\n        raise web.HTTPServiceUnavailable(text="no VPN profiles configured")\n    body = base64.b64encode(("\\n".join(links) + "\\n").encode()).decode()\n    exp = parse_exp(row)\n    expire_unix = int(exp.timestamp()) if exp else 0\n    headers = {\n        "Profile-Title": "Ferixdi VPN 12",\n        "Subscription-Userinfo": f"upload=0; download=0; total=0; expire={expire_unix}",\n        "Profile-Update-Interval": "1",\n        "ping-type": "tcp",\n        "proxy-ping-mode": "keepalive",\n        "proxy-ping-timeout": "5",\n        "subscription-request-timeout": "5",\n        "Cache-Control": "no-store, private, max-age=0",\n        "Pragma": "no-cache",\n        "X-Content-Type-Options": "nosniff",\n    }\n    return web.Response(text=body, content_type="text/plain", headers=headers)\n'''
replace_once(old_sub, new_sub, "subscription endpoint")

old_health = '''async def health_handler(request: web.Request):\n    problems = []\n'''
new_health = '''async def health_handler(request: web.Request):\n    if request.remote not in ("127.0.0.1", "::1", None):\n        raise web.HTTPNotFound()\n    problems = []\n'''
replace_once(old_health, new_health, "local-only health")

path.write_text(s)
print(f"edge hardened {path}")
