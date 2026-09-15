from pathlib import Path

p = Path('bot/main.py')
s = p.read_text()


def repl(old, new):
    global s
    if old not in s:
        raise SystemExit(f'pattern not found:\n{old[:180]}')
    s = s.replace(old, new, 1)

repl(
    'from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message',
    'from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message',
)

repl(
    'BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))\n',
    'BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))\n\n'
    'PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT", "299"))\n'
    'PAYMENT_DAYS = int(os.getenv("PAYMENT_DAYS", "30"))\n'
    'PAYMENT_PHONE = os.getenv("PAYMENT_PHONE", "89935801642").strip()\n'
    'PAYMENT_BANK = os.getenv("PAYMENT_BANK", "Яндекс Банк").strip()\n'
    'PAYMENT_RECIPIENT = os.getenv("PAYMENT_RECIPIENT", "Дмитрий").strip()\n',
)

repl(
    '        ensure_column(con, "users", "expired_notified", "INTEGER NOT NULL DEFAULT 0")\n',
    '        ensure_column(con, "users", "expired_notified", "INTEGER NOT NULL DEFAULT 0")\n'
    '        con.executescript(\n'
    '            """\n'
    '            CREATE TABLE IF NOT EXISTS payments (\n'
    '                id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
    '                telegram_id INTEGER NOT NULL,\n'
    '                amount INTEGER NOT NULL,\n'
    '                days INTEGER NOT NULL,\n'
    '                status TEXT NOT NULL DEFAULT \'pending\',\n'
    '                created_at TEXT NOT NULL,\n'
    '                confirmed_at TEXT,\n'
    '                admin_id INTEGER\n'
    '            );\n'
    '            CREATE INDEX IF NOT EXISTS idx_payments_user_status\n'
    '            ON payments(telegram_id, status);\n'
    '            CREATE INDEX IF NOT EXISTS idx_payments_status_created\n'
    '            ON payments(status, created_at);\n'
    '            """\n'
    '        )\n',
)

repl(
    '[InlineKeyboardButton(text="💳 Продлить доступ", url=SUPPORT_URL)],',
    '[InlineKeyboardButton(text="💳 Продлить доступ · 299 ₽ / 30 дней", callback_data="pay_open")],',
)

insert_before = '\n\n@dp.message(CommandStart())\n'
block = r'''


def payment_keyboard():
    full = f"{PAYMENT_PHONE} · {PAYMENT_BANK} · {PAYMENT_RECIPIENT}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать номер", copy_text=CopyTextButton(text=PAYMENT_PHONE))],
            [InlineKeyboardButton(text="📋 Скопировать реквизиты", copy_text=CopyTextButton(text=full))],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data="pay_sent")],
            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
        ]
    )


def payment_admin_keyboard(payment_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"pay_approve:{payment_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay_reject:{payment_id}"),
        ]]
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="💰 Заявки на оплату", callback_data="admin_payments")],
        ]
    )


def get_payment(payment_id):
    with db() as con:
        return con.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()


def add_paid_days(tg_id, days):
    row = get_user(tg_id)
    if not row:
        raise ValueError("user not found")
    base = parse_exp(row) if is_active(row) else utcnow()
    expires = base + timedelta(days=days)
    with db() as con:
        con.execute(
            """UPDATE users SET enabled=1, expires_at=?, plan_type='paid',
            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0 WHERE telegram_id=?""",
            (expires.isoformat(), tg_id),
        )
    return expires


async def notify_payment_admins(payment_id):
    payment = get_payment(payment_id)
    row = get_user(payment["telegram_id"]) if payment else None
    if not payment or not row:
        return
    username = f"@{row['username']}" if row['username'] else "без username"
    text = (
        "💰 <b>Новая заявка на оплату</b>\n\n"
        f"Пользователь: <b>{row['full_name'] or 'Без имени'}</b> ({username})\n"
        f"Telegram ID: <code>{row['telegram_id']}</code>\n"
        f"Сумма: <b>{payment['amount']} ₽</b>\n"
        f"Срок: <b>{payment['days']} дней</b>\n"
        f"Заявка: <code>#{payment['id']}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                reply_markup=payment_admin_keyboard(payment_id),
            )
        except Exception as e:
            print(f"payment notify admin {admin_id} error: {e}", flush=True)
'''
if insert_before not in s:
    raise SystemExit('start insertion point not found')
s = s.replace(insert_before, block + insert_before, 1)

insert_before = '\n\n@dp.message(Command("stats"))\n'
block = r'''


@dp.callback_query(F.data == "pay_open")
async def pay_open(c: CallbackQuery):
    ensure_user(c.from_user)
    await c.message.answer(
        "💳 <b>Продление доступа</b>\n\n"
        f"30 дней — <b>{PAYMENT_AMOUNT} ₽</b>\n\n"
        "Переведи точную сумму по номеру телефона через приложение своего банка:\n"
        f"📱 <code>{PAYMENT_PHONE}</code>\n"
        f"🏦 <b>{PAYMENT_BANK}</b>\n"
        f"👤 Получатель: <b>{PAYMENT_RECIPIENT}</b>\n\n"
        "После перевода нажми <b>«✅ Я оплатил»</b>. Администратор проверит платёж и активирует 30 дней.",
        parse_mode="HTML",
        reply_markup=payment_keyboard(),
    )
    await c.answer()


@dp.callback_query(F.data == "pay_sent")
async def pay_sent(c: CallbackQuery):
    ensure_user(c.from_user)
    with db() as con:
        existing = con.execute(
            "SELECT * FROM payments WHERE telegram_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (c.from_user.id,),
        ).fetchone()
        if existing:
            await c.message.answer(
                f"⏳ Заявка <b>#{existing['id']}</b> уже отправлена. Повторно нажимать не нужно — дождись проверки.",
                parse_mode="HTML",
                reply_markup=menu(),
            )
            await c.answer("Заявка уже ждёт проверки")
            return
        cur = con.execute(
            "INSERT INTO payments (telegram_id, amount, days, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (c.from_user.id, PAYMENT_AMOUNT, PAYMENT_DAYS, utcnow().isoformat()),
        )
        payment_id = cur.lastrowid
    await notify_payment_admins(payment_id)
    await c.message.answer(
        f"✅ <b>Заявка #{payment_id} отправлена</b>\n\n"
        "После проверки перевода бот сам продлит доступ на 30 дней.",
        parse_mode="HTML",
        reply_markup=menu(),
    )
    await c.answer("Заявка отправлена")


@dp.message(Command("admin"))
async def admin_panel(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    await m.answer("🛠 <b>Админ-панель Ferixdi</b>", parse_mode="HTML", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        await c.answer("Нет доступа", show_alert=True)
        return
    with db() as con:
        rows = con.execute("SELECT * FROM users").fetchall()
        total = len(rows)
        active = sum(1 for r in rows if is_active(r))
        paid = sum(1 for r in rows if r["plan_type"] == "paid" and is_active(r))
        pending = con.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
    await c.message.answer(
        f"👥 Всего: {total}\n🟢 Активных: {active}\n💳 Платных: {paid}\n💰 Ждут проверки: {pending}",
        reply_markup=admin_keyboard(),
    )
    await c.answer()


@dp.callback_query(F.data == "admin_payments")
async def admin_payments(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        await c.answer("Нет доступа", show_alert=True)
        return
    with db() as con:
        items = con.execute("SELECT * FROM payments WHERE status='pending' ORDER BY id ASC LIMIT 20").fetchall()
    if not items:
        await c.message.answer("✅ Нет заявок, ожидающих проверки.", reply_markup=admin_keyboard())
        await c.answer()
        return
    for payment in items:
        row = get_user(payment["telegram_id"])
        username = f"@{row['username']}" if row and row['username'] else "без username"
        await c.message.answer(
            "💰 <b>Оплата ждёт проверки</b>\n\n"
            f"Пользователь: <b>{row['full_name'] if row else 'Не найден'}</b> ({username})\n"
            f"Telegram ID: <code>{payment['telegram_id']}</code>\n"
            f"Сумма: <b>{payment['amount']} ₽</b>\n"
            f"Заявка: <code>#{payment['id']}</code>",
            parse_mode="HTML",
            reply_markup=payment_admin_keyboard(payment["id"]),
        )
    await c.answer()


@dp.callback_query(F.data.startswith("pay_approve:"))
async def pay_approve(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        await c.answer("Нет доступа", show_alert=True)
        return
    try:
        payment_id = int(c.data.split(":", 1)[1])
    except Exception:
        await c.answer("Некорректная заявка", show_alert=True)
        return
    payment = get_payment(payment_id)
    if not payment or payment["status"] != "pending":
        await c.answer("Заявка уже обработана или не найдена", show_alert=True)
        return

    with db() as con:
        claimed = con.execute(
            "UPDATE payments SET status='processing', admin_id=? WHERE id=? AND status='pending'",
            (c.from_user.id, payment_id),
        ).rowcount
    if not claimed:
        await c.answer("Заявку уже обработал другой администратор", show_alert=True)
        return

    try:
        expires = add_paid_days(payment["telegram_id"], payment["days"])
        await asyncio.to_thread(sync_xray)
    except Exception as e:
        with db() as con:
            con.execute("UPDATE payments SET status='pending', admin_id=NULL WHERE id=?", (payment_id,))
        await c.answer(f"Ошибка активации: {type(e).__name__}", show_alert=True)
        return

    with db() as con:
        con.execute(
            "UPDATE payments SET status='paid', confirmed_at=?, admin_id=? WHERE id=?",
            (utcnow().isoformat(), c.from_user.id, payment_id),
        )
    try:
        await bot.send_message(
            payment["telegram_id"],
            "✅ <b>Оплата подтверждена</b>\n\n"
            f"Доступ продлён на <b>{payment['days']} дней</b>.\n"
            f"До: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>",
            parse_mode="HTML",
            reply_markup=menu(),
        )
    except Exception:
        pass
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(f"✅ Заявка #{payment_id} подтверждена. Пользователю добавлено 30 дней.")
    await c.answer("Оплата подтверждена")


@dp.callback_query(F.data.startswith("pay_reject:"))
async def pay_reject(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        await c.answer("Нет доступа", show_alert=True)
        return
    try:
        payment_id = int(c.data.split(":", 1)[1])
    except Exception:
        await c.answer("Некорректная заявка", show_alert=True)
        return
    payment = get_payment(payment_id)
    if not payment or payment["status"] != "pending":
        await c.answer("Заявка уже обработана или не найдена", show_alert=True)
        return
    with db() as con:
        changed = con.execute(
            "UPDATE payments SET status='rejected', confirmed_at=?, admin_id=? WHERE id=? AND status='pending'",
            (utcnow().isoformat(), c.from_user.id, payment_id),
        ).rowcount
    if not changed:
        await c.answer("Заявку уже обработал другой администратор", show_alert=True)
        return
    try:
        await bot.send_message(
            payment["telegram_id"],
            "❌ <b>Платёж пока не найден</b>\n\n"
            "Проверь сумму и реквизиты. Если перевод точно прошёл — напиши в поддержку.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💬 Написать в поддержку", url=SUPPORT_URL)
            ]]),
        )
    except Exception:
        pass
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(f"❌ Заявка #{payment_id} отклонена.")
    await c.answer("Заявка отклонена")
'''
if insert_before not in s:
    raise SystemExit('stats insertion point not found')
s = s.replace(insert_before, block + insert_before, 1)

p.write_text(s)
print('manual payment flow patched')
