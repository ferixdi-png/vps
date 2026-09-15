#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()

def replace_once(old, new, name):
    global s
    if s.count(old) != 1:
        raise SystemExit(f"admin patch {name}: expected 1 match, found {s.count(old)}")
    s = s.replace(old, new, 1)

replace_once(
'''def is_active(row):
    exp = parse_exp(row)
    return bool(row and row["enabled"] and exp and exp > utcnow())


def active_users():
    with db() as con:
        return [r for r in con.execute("SELECT * FROM users WHERE enabled=1").fetchall() if is_active(r)]
''',
'''def recover_admin_ids():
    # If ADMIN_IDS was accidentally omitted from deployment secrets, recover the
    # original owner from the existing production database. An explicit value wins.
    if ADMIN_IDS:
        return
    try:
        with db() as con:
            row = con.execute("SELECT telegram_id FROM users ORDER BY created_at LIMIT 1").fetchone()
        if row:
            ADMIN_IDS.add(int(row["telegram_id"]))
            print(f"admin id recovered from production database: {row['telegram_id']}", flush=True)
    except Exception as e:
        print(f"admin id recovery warning: {type(e).__name__}: {e}", flush=True)


recover_admin_ids()


def is_admin_row(row):
    return bool(row and row["telegram_id"] in ADMIN_IDS)


def is_active(row):
    if is_admin_row(row):
        return True
    exp = parse_exp(row)
    return bool(row and row["enabled"] and exp and exp > utcnow())


def active_users():
    with db() as con:
        return [r for r in con.execute("SELECT * FROM users").fetchall() if is_active(r)]
''',
'admin activity')

replace_once(
'''def expiry_text(row):
    exp = parse_exp(row)
    if not exp:
        return "не задан"
    return exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def plan_name(row):
    return "Платная" if row and row["plan_type"] == "paid" else "Пробная"
''',
'''def expiry_text(row):
    if is_admin_row(row):
        return "Безлимит"
    exp = parse_exp(row)
    if not exp:
        return "не задан"
    return exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def plan_name(row):
    if is_admin_row(row):
        return "Администратор · Безлимит"
    return "Платная" if row and row["plan_type"] == "paid" else "Пробная"
''',
'admin labels')

replace_once(
'''def happ_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📲 Скачать Happ", url=HAPP_URL)],
            [InlineKeyboardButton(text="🔑 Получить мой ключ", callback_data="key")],
            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
        ]
    )
''',
'''def happ_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📲 Скачать Happ", url=HAPP_URL)],
            [InlineKeyboardButton(text="🔑 Получить мой ключ", callback_data="key")],
            [InlineKeyboardButton(text="♻️ Перевыпустить ключ", callback_data="reissue")],
            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
        ]
    )
''',
'reissue button')

insert_at='@dp.callback_query(F.data == "status")\n'
if insert_at not in s:
    raise SystemExit('admin patch: status insertion point missing')
handler=r'''@dp.callback_query(F.data == "reissue")
async def reissue(c: CallbackQuery):
    await c.answer("Перевыпускаю ключ…")
    row = ensure_user(c.from_user)
    if not is_active(row):
        await c.message.answer("🔴 Доступ не активен.", reply_markup=menu())
        return
    old_uuid, old_token = row["vpn_uuid"], row["sub_token"]
    new_uuid, new_token = str(uuid.uuid4()), secrets.token_urlsafe(24)
    try:
        with db() as con:
            con.execute("UPDATE users SET vpn_uuid=?, sub_token=? WHERE telegram_id=?", (new_uuid, new_token, c.from_user.id))
        mark_xray_dirty()
        await asyncio.to_thread(sync_xray)
    except Exception as e:
        with db() as con:
            con.execute("UPDATE users SET vpn_uuid=?, sub_token=? WHERE telegram_id=?", (old_uuid, old_token, c.from_user.id))
        mark_xray_dirty()
        try:
            await asyncio.to_thread(sync_xray)
        except Exception:
            pass
        await c.message.answer(f"⚠️ Перевыпуск не завершён. Старый ключ сохранён. Код: {type(e).__name__}", reply_markup=happ_keyboard())
        return
    await c.message.answer(
        "✅ <b>Ключ полностью перевыпущен</b>\n\nСтарая ссылка подписки и старые VLESS-профили больше не действуют. Удали старую подписку из Happ и добавь новую через «🔑 Получить мой ключ».",
        parse_mode="HTML", reply_markup=happ_keyboard())


'''
s=s.replace(insert_at, handler+insert_at, 1)

status_anchor='''    row = get_user(c.from_user.id)
    if is_active(row):
'''
status_pos = s.find('@dp.callback_query(F.data == "status")')
help_pos = s.find('@dp.callback_query(F.data == "help")', status_pos)
if status_pos < 0 or help_pos < 0:
    raise SystemExit('admin patch: status section missing')
status_section = s[status_pos:help_pos]
if status_section.count(status_anchor) != 1:
    raise SystemExit(f'admin patch status anchor: expected 1 match, found {status_section.count(status_anchor)}')
status_repl=r'''    row = get_user(c.from_user.id)
    if is_admin_row(row):
        await c.message.answer(
            "🟢 <b>Доступ активен</b>\nТариф: Администратор · Безлимит\nСрок: <b>Безлимит</b>",
            parse_mode="HTML", reply_markup=menu())
        return
    if is_active(row):
'''
status_section = status_section.replace(status_anchor, status_repl, 1)
s = s[:status_pos] + status_section + s[help_pos:]

sub_old='''    exp = parse_exp(row)
    expire_unix = int(exp.timestamp()) if exp else 0
    headers = {
'''
sub_new='''    exp = parse_exp(row)
    expire_unix = 0 if is_admin_row(row) else (int(exp.timestamp()) if exp else 0)
    headers = {
'''
replace_once(sub_old, sub_new, 'admin subscription expiry')

path.write_text(s)
print(f"admin patched {path}")
