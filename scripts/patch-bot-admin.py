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
'''def is_admin_row(row):
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
handler='''@dp.callback_query(F.data == "reissue")
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
        "✅ <b>Ключ полностью перевыпущен</b>\\n\\nСтарая ссылка подписки и старые VLESS-профили больше не действуют. Удали старую подписку из Happ и добавь новую через «🔑 Получить мой ключ».",
        parse_mode="HTML", reply_markup=happ_keyboard())


'''
s=s.replace(insert_at, handler+insert_at, 1)

old_status='''    if is_active(row):
        exp = parse_exp(row)
        left = exp - utcnow()
        hours = max(0, int(left.total_seconds() // 3600))
        days, rem_hours = divmod(hours, 24)
        await c.message.answer(
            f"🟢 <b>Доступ активен</b>\\n"
            f"Тариф: {plan_name(row)}\\n"
            f"До: {expiry_text(row)}\\n"
            f"Осталось: {days} дн. {rem_hours} ч.",
            parse_mode="HTML",
            reply_markup=menu(),
        )
'''
new_status='''    if is_active(row):
        if is_admin_row(row):
            await c.message.answer(
                "🟢 <b>Доступ активен</b>\\nТариф: Администратор · Безлимит\\nСрок: <b>Безлимит</b>",
                parse_mode="HTML", reply_markup=menu())
        else:
            exp = parse_exp(row)
            left = exp - utcnow()
            hours = max(0, int(left.total_seconds() // 3600))
            days, rem_hours = divmod(hours, 24)
            await c.message.answer(
                f"🟢 <b>Доступ активен</b>\\n"
                f"Тариф: {plan_name(row)}\\n"
                f"До: {expiry_text(row)}\\n"
                f"Осталось: {days} дн. {rem_hours} ч.",
                parse_mode="HTML",
                reply_markup=menu(),
            )
'''
replace_once(old_status, new_status, 'admin status')

replace_once(
'''    exp = parse_exp(row)
    expire_unix = int(exp.timestamp()) if exp else 0
    headers = {
''',
'''    exp = parse_exp(row)
    expire_unix = 0 if is_admin_row(row) else (int(exp.timestamp()) if exp else 0)
    headers = {
''',
'admin subscription expiry')

path.write_text(s)
print(f"admin patched {path}")
