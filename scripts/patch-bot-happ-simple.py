#!/usr/bin/env python3
from pathlib import Path
import re, sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()

helper = '''\n\ndef subscription_copy_keyboard(url: str):\n    if len(url) > 256:\n        raise RuntimeError(f"subscription URL too long: {len(url)}")\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [InlineKeyboardButton(text="📋 Скопировать подписку", copy_text=CopyTextButton(text=url))],\n            [InlineKeyboardButton(text="📱 Как добавить в Happ", callback_data="help")],\n            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],\n        ]\n    )\n'''

key_start = s.find('@dp.callback_query(F.data == "key")')
status_start = s.find('@dp.callback_query(F.data == "status")', key_start)
if key_start < 0 or status_start < 0:
    raise SystemExit('key handler section not found')

# Remove the previous single-profile helper block if it exists.
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

new_key = '''@dp.callback_query(F.data == "key")\nasync def key(c: CallbackQuery):\n''' + rate_line + '''    await c.answer("Готовлю подписку…")\n    try:\n        ensure_user(c.from_user)\n        row = get_user(c.from_user.id)\n        if not is_active(row):\n            await c.message.answer(\n                "🔴 Доступ сейчас не активен. Активируй тест или продли подписку.",\n                reply_markup=menu(),\n            )\n            return\n        url = subscription_url(row)\n        if not url or not url.startswith("https://"):\n            raise RuntimeError("secure subscription URL is not configured")\n        await c.message.answer(\n            "🔑 <b>Подписка готова</b>\\n\\n"\n            "В ней сразу <b>8 профилей Ferixdi</b>, как на компьютере.\\n\\n"\n            "1. Нажми <b>«📋 Скопировать подписку»</b>.\\n"\n            "2. Открой Happ и нажми <b>+</b>.\\n"\n            "3. Выбери <b>«URL подписки»</b>.\\n"\n            "4. Вставь ссылку и сохрани.\\n\\n"\n            "Готово — в Happ появятся все 8 профилей.",\n            parse_mode="HTML",\n            reply_markup=subscription_copy_keyboard(url),\n        )\n    except Exception as e:\n        print(f"key callback error tg={c.from_user.id}: {type(e).__name__}: {e}", flush=True)\n        await c.message.answer(\n            "⚠️ Не удалось сформировать подписку. Попробуй ещё раз через несколько секунд.",\n            reply_markup=menu(),\n        )\n\n\n'''
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
new_help = '''@dp.callback_query(F.data == "help")\nasync def help_cb(c: CallbackQuery):\n''' + rate_line + '''    await c.answer()\n    await c.message.answer(\n        "📱 <b>Как добавить Ferixdi в Happ</b>\\n\\n"\n        "① Нажми <b>«🔑 Мой ключ»</b>.\\n"\n        "② Нажми <b>«📋 Скопировать подписку»</b>.\\n"\n        "③ В Happ нажми <b>+</b> справа сверху.\\n"\n        "④ Выбери <b>«URL подписки»</b>.\\n"\n        "⑤ Вставь ссылку и сохрани.\\n\\n"\n        "После этого появятся сразу <b>8 профилей Ferixdi</b>.",\n        parse_mode="HTML",\n        reply_markup=happ_keyboard(),\n    )\n\n\n'''
s = s[:help_start] + new_help + s[next_start:]

path.write_text(s)
print(f'Happ HTTPS subscription flow patched {path}')
