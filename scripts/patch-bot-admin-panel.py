#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()

anchor = '@dp.message(Command("stats"))\n'
if anchor not in s:
    raise SystemExit('admin-panel patch: stats anchor missing')
if 'async def admin_panel(' in s:
    raise SystemExit('admin-panel patch: already applied')

panel = r'''def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
        ],
        [
            InlineKeyboardButton(text="🟢 Активные", callback_data="adm_active"),
            InlineKeyboardButton(text="💳 Платные", callback_data="adm_paid"),
        ],
        [
            InlineKeyboardButton(text="⏳ Истекают 24ч", callback_data="adm_expiring"),
            InlineKeyboardButton(text="🎁 Trial", callback_data="adm_trials"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_panel")],
    ])


def admin_counts():
    with db() as con:
        rows = con.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    total = len(rows)
    active = sum(1 for r in rows if is_active(r) and not is_admin_row(r))
    paid = sum(1 for r in rows if r["plan_type"] == "paid" and is_active(r) and not is_admin_row(r))
    trials = sum(1 for r in rows if r["trial_used"])
    trial_active = sum(1 for r in rows if r["plan_type"] == "trial" and is_active(r))
    now = utcnow()
    expiring = 0
    for r in rows:
        if is_admin_row(r) or not is_active(r):
            continue
        exp = parse_exp(r)
        if exp and 0 < (exp - now).total_seconds() <= 24 * 3600:
            expiring += 1
    return total, active, paid, trials, trial_active, expiring


def admin_panel_text():
    total, active, paid, trials, trial_active, expiring = admin_counts()
    return (
        "🛠 <b>Ferixdi VPN · Админ-панель</b>\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"🟢 Активных: <b>{active}</b>\n"
        f"💳 Платных активных: <b>{paid}</b>\n"
        f"🎁 Использовали trial: <b>{trials}</b>\n"
        f"🧪 Trial сейчас активен: <b>{trial_active}</b>\n"
        f"⏳ Истекают за 24ч: <b>{expiring}</b>\n\n"
        "Нажми на раздел ниже. В карточке пользователя можно продлить или отключить доступ кнопками."
    )


def admin_user_title(row):
    name = (row["full_name"] or row["username"] or str(row["telegram_id"])).strip()
    if len(name) > 24:
        name = name[:23] + "…"
    if is_admin_row(row):
        icon = "👑"
    elif is_active(row):
        icon = "🟢"
    else:
        icon = "⚪"
    return f"{icon} {name} · {row['telegram_id']}"


def admin_user_card(row):
    username = f"@{html.escape(row['username'])}" if row["username"] else "—"
    if is_admin_row(row):
        state = "👑 Администратор · Безлимит"
    elif is_active(row):
        state = "🟢 Активен"
    else:
        state = "🔴 Неактивен"
    return (
        "👤 <b>Пользователь</b>\n\n"
        f"Имя: <b>{html.escape(row['full_name'] or '—')}</b>\n"
        f"Username: {username}\n"
        f"Telegram ID: <code>{row['telegram_id']}</code>\n"
        f"Статус: {state}\n"
        f"Тариф: <b>{html.escape(plan_name(row))}</b>\n"
        f"До: <b>{html.escape(expiry_text(row))}</b>\n"
        f"Trial использован: <b>{'да' if row['trial_used'] else 'нет'}</b>"
    )


def admin_user_actions(row):
    tg_id = int(row["telegram_id"])
    rows = [
        [
            InlineKeyboardButton(text="+1 день", callback_data=f"adm_ext:{tg_id}:1"),
            InlineKeyboardButton(text="+7 дней", callback_data=f"adm_ext:{tg_id}:7"),
            InlineKeyboardButton(text="+30 дней", callback_data=f"adm_ext:{tg_id}:30"),
        ],
    ]
    if tg_id not in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text="⛔ Отключить", callback_data=f"adm_off:{tg_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Пользователи", callback_data="adm_users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_rows(kind="all", limit=20):
    with db() as con:
        rows = con.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    now = utcnow()
    out = []
    for r in rows:
        if kind == "active" and (not is_active(r) or is_admin_row(r)):
            continue
        if kind == "paid" and not (r["plan_type"] == "paid" and is_active(r) and not is_admin_row(r)):
            continue
        if kind == "trial" and not r["trial_used"]:
            continue
        if kind == "expiring":
            if is_admin_row(r) or not is_active(r):
                continue
            exp = parse_exp(r)
            if not exp or not (0 < (exp - now).total_seconds() <= 24 * 3600):
                continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def admin_list_keyboard(rows):
    buttons = [[InlineKeyboardButton(text=admin_user_title(r), callback_data=f"adm_user:{r['telegram_id']}")] for r in rows]
    buttons.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="adm_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def admin_edit(c: CallbackQuery, text: str, markup=None):
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await c.message.answer(text, parse_mode="HTML", reply_markup=markup)


async def admin_guard(c: CallbackQuery):
    if c.from_user.id in ADMIN_IDS:
        return True
    try:
        await c.answer("Нет доступа", show_alert=True)
    except Exception:
        pass
    return False


@dp.message(Command("admin"))
async def admin_panel(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    await m.answer(admin_panel_text(), parse_mode="HTML", reply_markup=admin_panel_keyboard())


@dp.callback_query(F.data == "adm_panel")
async def admin_panel_cb(c: CallbackQuery):
    if not await admin_guard(c):
        return
    await c.answer()
    await admin_edit(c, admin_panel_text(), admin_panel_keyboard())


@dp.callback_query(F.data == "adm_stats")
async def admin_stats_cb(c: CallbackQuery):
    if not await admin_guard(c):
        return
    await c.answer()
    await admin_edit(c, admin_panel_text(), admin_panel_keyboard())


async def admin_show_list(c: CallbackQuery, kind: str, title: str):
    rows = admin_rows(kind)
    text = f"{title}\n\n"
    if rows:
        text += f"Показано: <b>{len(rows)}</b>. Нажми на пользователя для управления."
    else:
        text += "Пока пусто."
    await admin_edit(c, text, admin_list_keyboard(rows))


@dp.callback_query(F.data == "adm_users")
async def admin_users_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    await c.answer()
    await admin_show_list(c, "all", "👥 <b>Последние пользователи</b>")


@dp.callback_query(F.data == "adm_active")
async def admin_active_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    await c.answer()
    await admin_show_list(c, "active", "🟢 <b>Активные пользователи</b>")


@dp.callback_query(F.data == "adm_paid")
async def admin_paid_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    await c.answer()
    await admin_show_list(c, "paid", "💳 <b>Платные пользователи</b>")


@dp.callback_query(F.data == "adm_trials")
async def admin_trials_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    await c.answer()
    await admin_show_list(c, "trial", "🎁 <b>Использовали trial</b>")


@dp.callback_query(F.data == "adm_expiring")
async def admin_expiring_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    await c.answer()
    await admin_show_list(c, "expiring", "⏳ <b>Истекают в ближайшие 24 часа</b>")


@dp.callback_query(F.data.startswith("adm_user:"))
async def admin_user_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    await c.answer()
    try:
        tg_id = int(c.data.split(":", 1)[1])
    except Exception:
        return
    row = get_user(tg_id)
    if not row:
        await admin_edit(c, "Пользователь не найден.", admin_panel_keyboard())
        return
    await admin_edit(c, admin_user_card(row), admin_user_actions(row))


@dp.callback_query(F.data.startswith("adm_ext:"))
async def admin_extend_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    try:
        _, tg_raw, days_raw = c.data.split(":", 2)
        tg_id, days = int(tg_raw), int(days_raw)
    except Exception:
        await c.answer("Некорректная команда", show_alert=True)
        return
    row = get_user(tg_id)
    if not row:
        await c.answer("Пользователь не найден", show_alert=True)
        return
    if tg_id in ADMIN_IDS:
        await c.answer("У администратора уже безлимит", show_alert=True)
        return
    base = parse_exp(row) if is_active(row) else utcnow()
    expires = base + timedelta(days=days)
    with db() as con:
        con.execute(
            """UPDATE users SET enabled=1, expires_at=?, plan_type='paid',
            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0 WHERE telegram_id=?""",
            (expires.isoformat(), tg_id),
        )
    mark_xray_dirty()
    try:
        await asyncio.to_thread(sync_xray)
    except Exception as e:
        await c.answer(f"Xray: {type(e).__name__}", show_alert=True)
        return
    try:
        await bot.send_message(
            tg_id,
            f"✅ <b>Доступ продлён</b>\n\nНа {days} дн.\nДо: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>",
            parse_mode="HTML", reply_markup=menu())
    except Exception:
        pass
    await c.answer(f"Продлено на {days} дн.")
    row = get_user(tg_id)
    await admin_edit(c, admin_user_card(row), admin_user_actions(row))


@dp.callback_query(F.data.startswith("adm_off:"))
async def admin_disable_cb(c: CallbackQuery):
    if not await admin_guard(c): return
    try:
        tg_id = int(c.data.split(":", 1)[1])
    except Exception:
        return
    if tg_id in ADMIN_IDS:
        await c.answer("Администратора отключить нельзя", show_alert=True)
        return
    row = get_user(tg_id)
    if not row:
        await c.answer("Пользователь не найден", show_alert=True)
        return
    with db() as con:
        con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (tg_id,))
    mark_xray_dirty()
    try:
        await asyncio.to_thread(sync_xray)
    except Exception as e:
        await c.answer(f"Xray: {type(e).__name__}", show_alert=True)
        return
    try:
        await bot.send_message(tg_id, "🔴 Доступ отключён администратором.", reply_markup=menu())
    except Exception:
        pass
    await c.answer("Доступ отключён")
    row = get_user(tg_id)
    await admin_edit(c, admin_user_card(row), admin_user_actions(row))


'''

s = s.replace(anchor, panel + anchor, 1)
path.write_text(s)
print(f"admin panel patched {path}")
