#!/usr/bin/env python3
from pathlib import Path
import re, sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()

helper = '''\n\ndef key_copy_keyboard(link: str):\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [InlineKeyboardButton(text="📋 Скопировать ключ", copy_text=CopyTextButton(text=link))],\n            [InlineKeyboardButton(text="📱 Как вставить в Happ", callback_data="help")],\n            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],\n        ]\n    )\n'''

key_start = s.find('@dp.callback_query(F.data == "key")')
status_start = s.find('@dp.callback_query(F.data == "status")', key_start)
if key_start < 0 or status_start < 0:
    raise SystemExit('key handler section not found')

if 'def key_copy_keyboard(' not in s:
    s = s[:key_start] + helper + '\n' + s[key_start:]
    key_start = s.find('@dp.callback_query(F.data == "key")')
    status_start = s.find('@dp.callback_query(F.data == "status")', key_start)

old_key = s[key_start:status_start]
rate_line = ''
m = re.search(r'async def key\(c: CallbackQuery\):\n(    if await reject_callback_flood\([^\n]+\):\n        return\n)?', old_key)
if m and m.group(1):
    rate_line = m.group(1)

new_key = '''@dp.callback_query(F.data == "key")\nasync def key(c: CallbackQuery):\n''' + rate_line + '''    await c.answer("Готовлю ключ…")\n    try:\n        ensure_user(c.from_user)\n        row = get_user(c.from_user.id)\n        if not is_active(row):\n            await c.message.answer(\n                "🔴 Доступ сейчас не активен. Активируй тест или продли подписку.",\n                reply_markup=menu(),\n            )\n            return\n        links = profile_links(row)\n        if not links:\n            raise RuntimeError("no vpn profiles")\n        primary = links[0]\n        await c.message.answer(\n            "🔑 <b>Твой ключ готов</b>\\n\\n"\n            "1. Нажми <b>«📋 Скопировать ключ»</b> ниже.\\n"\n            "2. Открой Happ и нажми <b>+</b>.\\n"\n            "3. Выбери <b>«Вставить из буфера обмена»</b>.\\n"\n            "4. Подключайся.\\n\\n"\n            "Важно: выбирай именно <b>«Вставить из буфера обмена»</b>, а не «URL подписки». ",\n            parse_mode="HTML",\n            reply_markup=key_copy_keyboard(primary),\n        )\n    except Exception as e:\n        print(f"key callback error tg={c.from_user.id}: {type(e).__name__}: {e}", flush=True)\n        await c.message.answer(\n            "⚠️ Не удалось сформировать ключ. Попробуй ещё раз через несколько секунд.",\n            reply_markup=menu(),\n        )\n\n\n'''
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
new_help = '''@dp.callback_query(F.data == "help")\nasync def help_cb(c: CallbackQuery):\n''' + rate_line + '''    await c.answer()\n    await c.message.answer(\n        "📱 <b>Как добавить ключ в Happ</b>\\n\\n"\n        "① В боте нажми <b>«🔑 Мой ключ»</b>.\\n"\n        "② Нажми <b>«📋 Скопировать ключ»</b>.\\n"\n        "③ Открой Happ и нажми <b>+</b> справа сверху.\\n"\n        "④ Нажми <b>«Вставить из буфера обмена»</b>.\\n"\n        "⑤ Готово — выбери добавленный профиль и подключись.\\n\\n"\n        "❗ Не нажимай «URL подписки»: для обычного ключа это не нужно.",\n        parse_mode="HTML",\n        reply_markup=happ_keyboard(),\n    )\n\n\n'''
s = s[:help_start] + new_help + s[next_start:]

path.write_text(s)
print(f'Happ simple key flow patched {path}')
