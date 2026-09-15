#!/usr/bin/env python3
"""Apply production hardening to the deployed bot source.

Kept as an install-time patch so an existing production database and server can be
fixed without a destructive migration. Every replacement is asserted: deployment
fails rather than silently running an unpatched bot if main.py changes shape.
"""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"runtime patch {name}: expected 1 match, found {count}")
    s = s.replace(old, new, 1)


replace_once(
    "import base64\nimport json\n",
    "import base64\nimport html\nimport json\n",
    "html import",
)

replace_once(
    '''def db():\n    con = sqlite3.connect(DB_PATH)\n    con.row_factory = sqlite3.Row\n    return con\n''',
    '''def db():\n    con = sqlite3.connect(DB_PATH, timeout=10)\n    con.row_factory = sqlite3.Row\n    con.execute("PRAGMA busy_timeout=5000")\n    return con\n''',
    "sqlite timeout",
)

replace_once(
    '''def read_node_info():\n    data = {}\n    if NODE_INFO.exists():\n        for line in NODE_INFO.read_text().splitlines():\n            if "=" in line:\n                k, v = line.split("=", 1)\n                data[k.strip()] = v.strip()\n    return data\n''',
    '''def read_node_info():\n    # Production may retain an older NODE_INFO path in .env. Probe the canonical\n    # location as well so a stale environment value can never break key delivery.\n    data = {}\n    seen = set()\n    for candidate in (NODE_INFO, Path("/root/FERIXDI-NODE-INFO.txt"), Path("/opt/ferixdi/node/FERIXDI-NODE-INFO.txt")):\n        key = str(candidate)\n        if key in seen:\n            continue\n        seen.add(key)\n        try:\n            if not candidate.exists():\n                continue\n            for line in candidate.read_text().splitlines():\n                if "=" in line:\n                    k, v = line.split("=", 1)\n                    k, v = k.strip(), v.strip()\n                    if k and v and k not in data:\n                        data[k] = v\n        except Exception as e:\n            print(f"node info read warning {candidate}: {type(e).__name__}: {e}", flush=True)\n    return data\n''',
    "node info fallback",
)

old_profile = '''def profile_links(row):\n    cfg = load_xray()\n    info = read_node_info()\n    host = PUBLIC_HOST or info.get("IP")\n    pbk = info.get("PUBLIC_KEY")\n    sid = info.get("SHORT_ID")\n    if not host or not pbk or not sid:\n        raise RuntimeError("PUBLIC_HOST/PUBLIC_KEY/SHORT_ID not configured")\n\n    links = []\n    for inbound in cfg.get("inbounds", []):\n        port = inbound.get("port")\n        stream = inbound.get("streamSettings", {})\n        network = stream.get("network", "raw")\n        reality = stream.get("realitySettings", {})\n        sni = (reality.get("serverNames") or ["www.microsoft.com"])[0]\n        q = {\n            "encryption": "none",\n            "security": "reality",\n            "sni": sni,\n            "fp": "chrome",\n            "pbk": pbk,\n            "sid": sid,\n            "type": network,\n        }\n        label = f"Ferixdi Germany {network.upper()} {port}"\n        if network in ("raw", "tcp"):\n            q["flow"] = "xtls-rprx-vision"\n        elif network == "xhttp":\n            x = stream.get("xhttpSettings", {})\n            if x.get("path"):\n                q["path"] = x["path"]\n            q["mode"] = "auto"\n        elif network == "grpc":\n            g = stream.get("grpcSettings", {})\n            if g.get("serviceName"):\n                q["serviceName"] = g["serviceName"]\n        links.append(\n            f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q, safe='/')}#{quote(label)}"\n        )\n    return links\n'''

new_profile = '''def profile_links(row):\n    cfg = load_xray()\n    info = read_node_info()\n    host = (PUBLIC_HOST or info.get("IP") or "").strip()\n    pbk = (info.get("PUBLIC_KEY") or "").strip()\n    default_sid = (info.get("SHORT_ID") or "").strip()\n    if not host:\n        raise RuntimeError("PUBLIC_HOST/IP not configured")\n    if not pbk:\n        raise RuntimeError("PUBLIC_KEY not configured")\n\n    links = []\n    for inbound in cfg.get("inbounds", []):\n        port = inbound.get("port")\n        stream = inbound.get("streamSettings", {})\n        network = stream.get("network", "raw")\n        reality = stream.get("realitySettings", {})\n        # Prefer the short id actually configured for this inbound. This makes\n        # subscriptions resilient when ports are regenerated independently.\n        sid = ((reality.get("shortIds") or [default_sid])[0] or default_sid).strip()\n        if not port or not sid or not reality:\n            continue\n        sni = (reality.get("serverNames") or ["www.microsoft.com"])[0]\n        q = {\n            "encryption": "none",\n            "security": "reality",\n            "sni": sni,\n            "fp": "chrome",\n            "pbk": pbk,\n            "sid": sid,\n            "type": network,\n        }\n        label = f"Ferixdi Germany {network.upper()} {port}"\n        if network in ("raw", "tcp"):\n            q["flow"] = "xtls-rprx-vision"\n        elif network == "xhttp":\n            x = stream.get("xhttpSettings", {})\n            if x.get("path"):\n                q["path"] = x["path"]\n            q["mode"] = "auto"\n        elif network == "grpc":\n            g = stream.get("grpcSettings", {})\n            if g.get("serviceName"):\n                q["serviceName"] = g["serviceName"]\n        links.append(\n            f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q, safe='/')}#{quote(label)}"\n        )\n    if not links:\n        raise RuntimeError("no usable Reality inbounds configured")\n    return links\n'''
replace_once(old_profile, new_profile, "profile metadata fallback")

old_key = '''@dp.callback_query(F.data == "key")\nasync def key(c: CallbackQuery):\n    ensure_user(c.from_user)\n    row = get_user(c.from_user.id)\n    if not is_active(row):\n        await c.message.answer("🔴 Доступ сейчас не активен. Используй пробный период или продли подписку.", reply_markup=menu())\n        await c.answer()\n        return\n    url = subscription_url(row)\n    links = profile_links(row)\n    text = (\n        "🔑 <b>Твой персональный ключ</b>\\n\\n"\n        f"Тариф: <b>{plan_name(row)}</b>\\n"\n        f"Действует до: <b>{expiry_text(row)}</b>\\n\\n"\n    )\n    if url:\n        text += "<b>Ссылка подписки:</b>\\n<code>" + url + "</code>\\n\\n"\n    if links:\n        text += "Если приложение не принимает подписку, используй резервный VLESS-профиль:\\n<code>" + links[0] + "</code>"\n    await c.message.answer(text, parse_mode="HTML", reply_markup=happ_keyboard())\n    await c.answer()\n'''

new_key = '''@dp.callback_query(F.data == "key")\nasync def key(c: CallbackQuery):\n    await c.answer("Готовлю ключ…")\n    try:\n        ensure_user(c.from_user)\n        row = get_user(c.from_user.id)\n        if not is_active(row):\n            await c.message.answer(\n                "🔴 Доступ сейчас не активен. Используй пробный период или продли подписку.",\n                reply_markup=menu(),\n            )\n            return\n\n        url = subscription_url(row)\n        links = profile_links(row)\n        text = (\n            "🔑 <b>Твой персональный ключ</b>\\n\\n"\n            f"Тариф: <b>{html.escape(plan_name(row))}</b>\\n"\n            f"Действует до: <b>{html.escape(expiry_text(row))}</b>\\n\\n"\n        )\n        if url:\n            text += "<b>Ссылка подписки:</b>\\n<code>" + html.escape(url, quote=False) + "</code>\\n\\n"\n        if links:\n            text += (\n                "Резервный профиль, если подписка не импортируется:\\n"\n                "<code>" + html.escape(links[0], quote=False) + "</code>"\n            )\n        await c.message.answer(text, parse_mode="HTML", reply_markup=happ_keyboard())\n    except Exception as e:\n        print(f"key callback error tg={c.from_user.id}: {type(e).__name__}: {e}", flush=True)\n        # Last-resort response intentionally uses plain text and no markup so even\n        # a Telegram HTML/entity problem cannot leave the user with a spinner only.\n        try:\n            await bot.send_message(\n                c.from_user.id,\n                "⚠️ Ключ временно не сформировался. Я сохранил твой доступ. "\n                "Попробуй ещё раз через несколько секунд. Если повторится — напиши в поддержку: " + SUPPORT,\n            )\n        except Exception as send_error:\n            print(f"key fallback send error tg={c.from_user.id}: {type(send_error).__name__}: {send_error}", flush=True)\n'''
replace_once(old_key, new_key, "key callback")

old_trial_start = '''@dp.callback_query(F.data == "trial")\nasync def trial(c: CallbackQuery):\n    row = ensure_user(c.from_user)\n'''
new_trial_start = '''@dp.callback_query(F.data == "trial")\nasync def trial(c: CallbackQuery):\n    await c.answer("Активирую доступ…")\n    row = ensure_user(c.from_user)\n'''
replace_once(old_trial_start, new_trial_start, "trial early ack")
trial_section_start = s.index('@dp.callback_query(F.data == "trial")')
trial_section_end = s.index('@dp.callback_query(F.data == "key")')
trial_section = s[trial_section_start:trial_section_end]
trial_section = trial_section.replace("        await c.answer()\n", "").replace("    await c.answer()\n", "")
s = s[:trial_section_start] + trial_section + s[trial_section_end:]

replace_once(
    '''@dp.callback_query(F.data == "status")\nasync def status(c: CallbackQuery):\n    ensure_user(c.from_user)\n''',
    '''@dp.callback_query(F.data == "status")\nasync def status(c: CallbackQuery):\n    await c.answer()\n    ensure_user(c.from_user)\n''',
    "status early ack",
)
status_start = s.index('@dp.callback_query(F.data == "status")')
status_end = s.index('@dp.callback_query(F.data == "help")')
status_section = s[status_start:status_end]
first = status_section.find("    await c.answer()\n")
if first >= 0:
    tail = status_section[first + len("    await c.answer()\n"):].replace("    await c.answer()\n", "")
    status_section = status_section[:first + len("    await c.answer()\n")] + tail
s = s[:status_start] + status_section + s[status_end:]

replace_once(
    '''@dp.callback_query(F.data == "help")\nasync def help_cb(c: CallbackQuery):\n    await c.message.answer(\n''',
    '''@dp.callback_query(F.data == "help")\nasync def help_cb(c: CallbackQuery):\n    await c.answer()\n    await c.message.answer(\n''',
    "help early ack",
)
help_start = s.index('@dp.callback_query(F.data == "help")')
help_end = s.index('@dp.message(Command("stats"))')
help_section = s[help_start:help_end]
first = help_section.find("    await c.answer()\n")
if first >= 0:
    tail = help_section[first + len("    await c.answer()\n"):].replace("    await c.answer()\n", "")
    help_section = help_section[:first + len("    await c.answer()\n")] + tail
s = s[:help_start] + help_section + s[help_end:]

replace_once(
    '''async def sub_handler(request: web.Request):\n    row = get_user_by_token(request.match_info["token"])\n    if not is_active(row):\n        raise web.HTTPNotFound()\n    links = profile_links(row)\n    body = base64.b64encode(("\\n".join(links) + "\\n").encode()).decode()\n''',
    '''async def sub_handler(request: web.Request):\n    row = get_user_by_token(request.match_info["token"])\n    if not is_active(row):\n        raise web.HTTPNotFound()\n    try:\n        links = profile_links(row)\n    except Exception as e:\n        print(f"subscription render error: {type(e).__name__}: {e}", flush=True)\n        raise web.HTTPServiceUnavailable(text="subscription temporarily unavailable")\n    if not links:\n        raise web.HTTPServiceUnavailable(text="no VPN profiles configured")\n    body = base64.b64encode(("\\n".join(links) + "\\n").encode()).decode()\n''',
    "subscription resilience",
)

path.write_text(s)
print(f"patched {path}")
