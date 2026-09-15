#!/usr/bin/env python3
from pathlib import Path
import re, sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()

sub_decl = 'SUB_PORT = int(os.getenv("SUB_PORT", "8080"))\n'
if sub_decl in s and 'HTTP_PORT = 8080\n' not in s:
    s = s.replace(sub_decl, sub_decl + 'HTTP_PORT = 8080\nPUBLIC_SUB_PORT = 443\n', 1)

old_port = '    port = "" if (PUBLIC_SCHEME == "https" and SUB_PORT == 443) else f":{SUB_PORT}"\n'
if old_port in s:
    s = s.replace(old_port, '    port = "" if PUBLIC_SUB_PORT == 443 else f":{PUBLIC_SUB_PORT}"\n', 1)

old_site = 'site = web.TCPSite(runner, "0.0.0.0", SUB_PORT)'
if old_site in s:
    s = s.replace(old_site, 'site = web.TCPSite(runner, "127.0.0.1", HTTP_PORT)', 1)
old_print = 'print(f"Ferixdi bot started; subscription port={SUB_PORT}", flush=True)'
if old_print in s:
    s = s.replace(old_print, 'print(f"Ferixdi bot started; local_http={HTTP_PORT}; public_https={PUBLIC_SUB_PORT}", flush=True)', 1)

profile_start = s.find('def profile_links(row):\n')
profile_end = s.find('\n\ndef subscription_url(row):', profile_start)
if profile_start < 0 or profile_end < 0:
    raise SystemExit('profile_links section not found')
profile_block = s[profile_start:profile_end]
profile_block, host_count = re.subn(r'^    host = .*$', '    host = info.get("IP")', profile_block, count=1, flags=re.M)
if host_count != 1:
    raise SystemExit(f'profile host finalization expected 1 assignment, found {host_count}')
s = s[:profile_start] + profile_block + s[profile_end:]

old_body = '    body = base64.b64encode(("\\n".join(links) + "\\n").encode()).decode()\n'
new_body = '    body = "#profile-title: FERIXDI CONNECT\\n#profile-update-interval: 1\\n" + "\\n".join(links) + "\\n"\n'
if old_body in s:
    s = s.replace(old_body, new_body, 1)
s = s.replace('"Profile-Title": "Ferixdi VPN • 8 режимов"', '"Profile-Title": "FERIXDI CONNECT"')
s = s.replace('"Profile-Title": "Ferixdi VPN"', '"Profile-Title": "FERIXDI CONNECT"')

helper = '''\n\ndef subscription_open_keyboard(url: str):\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [InlineKeyboardButton(text="🌐 Открыть ключ", url=url)],\n            [InlineKeyboardButton(text="📱 Как добавить в Happ", callback_data="help")],\n            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],\n        ]\n    )\n'''

key_start = s.find('@dp.callback_query(F.data == "key")')
status_start = s.find('@dp.callback_query(F.data == "status")', key_start)
if key_start < 0 or status_start < 0:
    raise SystemExit('key handler section not found')

helper_start = s.rfind('\n\ndef ', 0, key_start)
if helper_start >= 0:
    block = s[helper_start:key_start]
    if 'compact_key_for_copy' in block or 'key_copy_keyboard' in block or 'subscription_copy_keyboard' in block or 'subscription_open_keyboard' in block:
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

new_key = '''@dp.callback_query(F.data == "key")\nasync def key(c: CallbackQuery):\n''' + rate_line + '''    await c.answer("Готовлю ключ…")\n    try:\n        ensure_user(c.from_user)\n        row = get_user(c.from_user.id)\n        if not is_active(row):\n            await c.message.answer("🔴 Доступ сейчас не активен. Активируй тест или продли подписку.", reply_markup=menu())\n            return\n        url = subscription_url(row)\n        if not url or not url.startswith("https://"):\n            raise RuntimeError("secure subscription URL is not configured")\n        if len(url) > 220:\n            raise RuntimeError(f"subscription URL unexpectedly long: {len(url)}")\n        text = (\n            "🔑 <b>FERIXDI CONNECT</b>\\n\\n"\n            "Скопируй ссылку ниже целиком:\\n"\n            f"<code>{url}</code>\\n\\n"\n            "Дальше: Happ → <b>+</b> → <b>Вставить из буфера обмена</b>.\\n"\n            "Happ загрузит сразу <b>8 профилей</b>."\n        )\n        await c.message.answer(text, parse_mode="HTML", reply_markup=subscription_open_keyboard(url), disable_web_page_preview=True)\n    except Exception as e:\n        print(f"key callback error tg={c.from_user.id}: {type(e).__name__}: {e}", flush=True)\n        try:\n            row = get_user(c.from_user.id)\n            url = subscription_url(row) if row else None\n            if url and url.startswith("https://"):\n                await c.message.answer(f"🔑 FERIXDI CONNECT\\n\\n{url}\\n\\nЗажми ссылку → Копировать. Потом Happ → + → Вставить из буфера обмена.")\n                return\n        except Exception as inner:\n            print(f"key fallback error: {type(inner).__name__}: {inner}", flush=True)\n        await c.message.answer("⚠️ Не удалось сформировать ключ. Попробуй ещё раз через несколько секунд.", reply_markup=menu())\n\n\n'''
s = s[:key_start] + new_key + s[status_start:]

help_start = s.find('@dp.callback_query(F.data == "help")')
next_start = s.find('@dp.callback_query(F.data == "pay_open")', help_start)
if help_start >= 0 and next_start >= 0:
    old_help = s[help_start:next_start]
    rate_line = ''
    m = re.search(r'async def help_cb\(c: CallbackQuery\):\n(    if await reject_callback_flood\([^\n]+\):\n        return\n)?', old_help)
    if m and m.group(1):
        rate_line = m.group(1)
    new_help = '''@dp.callback_query(F.data == "help")\nasync def help_cb(c: CallbackQuery):\n''' + rate_line + '''    await c.answer()\n    await c.message.answer(\n        "📱 <b>Установка FERIXDI CONNECT в Happ</b>\\n\\n"\n        "① Нажми <b>«🔑 Мой ключ»</b>.\\n"\n        "② Зажми ссылку и выбери <b>«Копировать»</b>.\\n"\n        "③ В Happ нажми <b>+</b>.\\n"\n        "④ Выбери <b>«Вставить из буфера обмена»</b>.\\n\\n"\n        "Готово. Happ загрузит все 8 профилей.",\n        parse_mode="HTML",\n        reply_markup=happ_keyboard(),\n    )\n\n\n'''
    s = s[:help_start] + new_help + s[next_start:]

path.write_text(s)
print(f'Happ robust standard HTTPS flow patched {path}')
