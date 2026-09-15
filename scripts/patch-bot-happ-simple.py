#!/usr/bin/env python3
from pathlib import Path
import re, sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()

# Public Happ subscription is HTTPS on 9443. The bot itself stays on
# loopback:8080 so health checks and the reverse proxy remain separate.
sub_decl = 'SUB_PORT = int(os.getenv("SUB_PORT", "8080"))\n'
if sub_decl in s and 'HTTP_PORT = 8080\n' not in s:
    s = s.replace(sub_decl, sub_decl + 'HTTP_PORT = 8080\nPUBLIC_SUB_PORT = 9443\n', 1)

old_port = '    port = "" if (PUBLIC_SCHEME == "https" and SUB_PORT == 443) else f":{SUB_PORT}"\n'
if old_port in s:
    s = s.replace(old_port, '    port = f":{PUBLIC_SUB_PORT}"\n', 1)

old_site = 'site = web.TCPSite(runner, "0.0.0.0", SUB_PORT)'
if old_site in s:
    s = s.replace(old_site, 'site = web.TCPSite(runner, "127.0.0.1", HTTP_PORT)', 1)
old_print = 'print(f"Ferixdi bot started; subscription port={SUB_PORT}", flush=True)'
if old_print in s:
    s = s.replace(old_print, 'print(f"Ferixdi bot started; local_http={HTTP_PORT}; public_https={PUBLIC_SUB_PORT}", flush=True)', 1)

# Happ understands a plain-text standard subscription. Avoid wrapping the
# body in base64 so clipboard URL import has the simplest possible path.
old_body = '    body = base64.b64encode(("\\n".join(links) + "\\n").encode()).decode()\n'
new_body = '    body = "#profile-title: FERIXDI CONNECT\\n#profile-update-interval: 1\\n" + "\\n".join(links) + "\\n"\n'
if old_body not in s:
    raise SystemExit('subscription response body not found')
s = s.replace(old_body, new_body, 1)
s = s.replace('"Profile-Title": "Ferixdi VPN"', '"Profile-Title": "FERIXDI CONNECT"')

helper = '''\n\ndef subscription_copy_keyboard(url: str):\n    # Happ's clipboard importer accepts the standard HTTPS subscription URL\n    # directly. Do not wrap it in an app-specific deep link.\n    if len(url) > 256:\n        raise RuntimeError(f"subscription URL too long: {len(url)}")\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [InlineKeyboardButton(text="📋 Скопировать ключ", copy_text=CopyTextButton(text=url))],\n            [InlineKeyboardButton(text="📱 Как добавить в Happ", callback_data="help")],\n            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],\n        ]\n    )\n'''

key_start = s.find('@dp.callback_query(F.data == "key")')
status_start = s.find('@dp.callback_query(F.data == "status")', key_start)
if key_start < 0 or status_start < 0:
    raise SystemExit('key handler section not found')

helper_start = s.rfind('\n\ndef ', 0, key_start)
if helper_start >= 0:
    block = s[helper_start:key_start]
    if 'compact_key_for_copy' in block or 'key_copy_keyboard' in block or 'subscription_copy_keyboard' in block:
        s = s[:helper_start] + s[key_start:]
        key_start = s.find('@dp.callback_query(F.data == "key")')
        status_start = s.find('@dp.callback_query(F.data == "status")', key_start)

s = s[:key_start] + helper + '\n' + s[key_start:]
key_start = s.find('@dp.callback_query(F.data == "key")')
status_start = s.find('@dp.callback_query(F.data == "status")', key_start)

old_key = s[key_start:status_start]
rate_line = ''
m = re.search(r'async def key\(c: CallbackQuery\):\n(    if await reject_callback_flood\([^\n]+\):\n        return\n)?', old_key)
if m and m.group(1):
    rate_line = m.group(1)

new_key = '''@dp.callback_query(F.data == "key")\nasync def key(c: CallbackQuery):\n''' + rate_line + '''    await c.answer("Готовлю ключ…")\n    try:\n        ensure_user(c.from_user)\n        row = get_user(c.from_user.id)\n        if not is_active(row):\n            await c.message.answer(\n                "🔴 Доступ сейчас не активен. Активируй тест или продли подписку.",\n                reply_markup=menu(),\n            )\n            return\n        url = subscription_url(row)\n        if not url or not url.startswith("https://"):\n            raise RuntimeError("secure subscription URL is not configured")\n        await c.message.answer(\n            "🔑 <b>FERIXDI CONNECT</b>\\n\\n"\n            "Один ключ добавляет сразу <b>8 профилей Ferixdi</b>.\\n\\n"\n            "1. Нажми <b>«📋 Скопировать ключ»</b>.\\n"\n            "2. Открой Happ и нажми <b>+</b>.\\n"\n            "3. Нажми <b>«Вставить из буфера обмена»</b>.\\n\\n"\n            "Happ сам загрузит все 8 профилей. Ничего вручную вводить не нужно.",\n            parse_mode="HTML",\n            reply_markup=subscription_copy_keyboard(url),\n        )\n    except Exception as e:\n        print(f"key callback error tg={c.from_user.id}: {type(e).__name__}: {e}", flush=True)\n        await c.message.answer(\n            "⚠️ Не удалось сформировать ключ. Попробуй ещё раз через несколько секунд.",\n            reply_markup=menu(),\n        )\n\n\n'''
s = s[:key_start] + new_key + s[status_start:]

help_start = s.find('@dp.callback_query(F.data == "help")')
next_start = s.find('@dp.callback_query(F.data == "pay_open")', help_start)
if help_start < 0 or next_start < 0:
    raise SystemExit('help handler section not found')
old_help = s[help_start:next_start]
rate_line = ''
m = re.search(r'async def help_cb\(c: CallbackQuery\):\n(    if await reject_callback_flood\([^\n]+\):\n        return\n)?', old_help)
if m and m.group(1):
    rate_line = m.group(1)
new_help = '''@dp.callback_query(F.data == "help")\nasync def help_cb(c: CallbackQuery):\n''' + rate_line + '''    await c.answer()\n    await c.message.answer(\n        "📱 <b>Установка FERIXDI CONNECT в Happ</b>\\n\\n"\n        "① Нажми <b>«🔑 Мой ключ»</b>.\\n"\n        "② Нажми <b>«📋 Скопировать ключ»</b>.\\n"\n        "③ В Happ нажми <b>+</b>.\\n"\n        "④ Выбери <b>«Вставить из буфера обмена»</b>.\\n\\n"\n        "Готово. Happ загрузит подписку FERIXDI CONNECT со всеми 8 профилями.",\n        parse_mode="HTML",\n        reply_markup=happ_keyboard(),\n    )\n\n\n'''
s = s[:help_start] + new_help + s[next_start:]

path.write_text(s)
print(f'Happ standard HTTPS clipboard flow patched {path}')
