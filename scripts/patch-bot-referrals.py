#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"referral patch {name}: expected 1 match, found {count}")
    s = s.replace(old, new, 1)


# Referral ledger: one reward per invited Telegram account, forever.
replace_once(
    '''            CREATE INDEX IF NOT EXISTS idx_payments_status_created
            ON payments(status, created_at);
            """
        )
''',
    '''            CREATE INDEX IF NOT EXISTS idx_payments_status_created
            ON payments(status, created_at);

            CREATE TABLE IF NOT EXISTS referrals (
                invitee_id INTEGER PRIMARY KEY,
                referrer_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                rewarded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_referrals_referrer
            ON referrals(referrer_id, created_at);
            """
        )
''',
    "referral table",
)

# Add referral CTA to the main menu.
replace_once(
    '''            [InlineKeyboardButton(text="📱 Установка через Happ", callback_data="help")],
            [InlineKeyboardButton(text="💳 Продлить доступ · 299 ₽ / 30 дней", callback_data="pay_open")],
''',
    '''            [InlineKeyboardButton(text="📱 Установка через Happ", callback_data="help")],
            [InlineKeyboardButton(text="🎁 Пригласить друга · +1 день", callback_data="referral")],
            [InlineKeyboardButton(text="💳 Продлить доступ · 299 ₽ / 30 дней", callback_data="pay_open")],
''',
    "menu button",
)

helpers = r'''

def referral_count(tg_id: int) -> int:
    with db() as con:
        return int(con.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (tg_id,)).fetchone()[0])


def register_referral(invitee_id: int, referrer_id: int):
    """Reward referrer with +1 day exactly once for a brand-new invitee."""
    if invitee_id == referrer_id:
        return None
    now = utcnow()
    with db() as con:
        invitee = con.execute("SELECT * FROM users WHERE telegram_id=?", (invitee_id,)).fetchone()
        referrer = con.execute("SELECT * FROM users WHERE telegram_id=?", (referrer_id,)).fetchone()
        if not invitee or not referrer:
            return None
        if con.execute("SELECT 1 FROM referrals WHERE invitee_id=?", (invitee_id,)).fetchone():
            return None

        # Admin already has unlimited access; still record a valid referral but do not
        # create a fake expiry for the admin account.
        if referrer_id in ADMIN_IDS:
            con.execute(
                "INSERT INTO referrals(invitee_id, referrer_id, created_at, rewarded_at) VALUES (?, ?, ?, ?)",
                (invitee_id, referrer_id, now.isoformat(), now.isoformat()),
            )
            return "admin"

        exp = parse_exp(referrer)
        base = exp if (referrer["enabled"] and exp and exp > now) else now
        new_exp = base + timedelta(days=1)
        con.execute(
            "INSERT INTO referrals(invitee_id, referrer_id, created_at, rewarded_at) VALUES (?, ?, ?, ?)",
            (invitee_id, referrer_id, now.isoformat(), now.isoformat()),
        )
        con.execute(
            """UPDATE users SET enabled=1, expires_at=?,
            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0
            WHERE telegram_id=?""",
            (new_exp.isoformat(), referrer_id),
        )
        return new_exp


async def process_start_referral(m: Message, was_new: bool):
    if not was_new:
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].startswith("ref_"):
        return
    raw = parts[1][4:]
    if not raw.isdigit():
        return
    referrer_id = int(raw)
    result = register_referral(m.from_user.id, referrer_id)
    if result is None:
        return
    if result != "admin":
        # Rebuild Xray immediately so an expired referrer who earned a day can
        # connect right away. One retry covers transient Docker restart failures.
        last_error = None
        for _ in range(2):
            try:
                await asyncio.to_thread(sync_xray)
                last_error = None
                break
            except Exception as e:
                last_error = e
                await asyncio.sleep(1)
        if last_error:
            print(f"referral xray sync error referrer={referrer_id}: {type(last_error).__name__}: {last_error}", flush=True)
    try:
        if result == "admin":
            await bot.send_message(referrer_id, "🎁 По твоей ссылке пришёл новый пользователь. Реферал засчитан.")
        else:
            await bot.send_message(
                referrer_id,
                "🎁 <b>Друг присоединился по твоей ссылке</b>\n\n"
                "+1 день доступа уже добавлен автоматически.\n"
                f"Новый срок: <b>{result.strftime('%d.%m.%Y %H:%M UTC')}</b>",
                parse_mode="HTML",
                reply_markup=menu(),
            )
    except Exception as e:
        print(f"referral notify error referrer={referrer_id}: {type(e).__name__}: {e}", flush=True)


@dp.callback_query(F.data == "referral")
async def referral(c: CallbackQuery):
    if await reject_callback_flood(c, "ui", 6, 10.0, 60.0):
        return
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{c.from_user.id}"
    count = referral_count(c.from_user.id)
    text = (
        "🎁 <b>Пригласи друга и получи +1 день</b>\n\n"
        "1. Скопируй свою персональную ссылку.\n"
        "2. Отправь её другу.\n"
        "3. Когда новый пользователь впервые запустит бота по этой ссылке, тебе автоматически добавится <b>1 день</b>.\n\n"
        f"Приглашено друзей: <b>{count}</b>\n\n"
        f"<code>{link}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать реферальную ссылку", copy_text=CopyTextButton(text=link))],
        [InlineKeyboardButton(text="📨 Поделиться", url="https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote("Ferixdi VPN: 24 часа бесплатно", safe=""))],
    ])
    await c.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await c.answer()


'''
anchor = '@dp.message(CommandStart())\n'
if anchor not in s:
    raise SystemExit('referral patch: start anchor missing')
s = s.replace(anchor, helpers + anchor, 1)

# The antispam patch already wrapped /start. Preserve it and add deep-link processing.
replace_once(
    '''@dp.message(CommandStart())
async def start(m: Message):
    if not tg_rate_allowed(m.from_user.id, "start", 3, 10.0, 20.0):
        return
    ensure_user(m.from_user)
''',
    '''@dp.message(CommandStart())
async def start(m: Message):
    if not tg_rate_allowed(m.from_user.id, "start", 3, 10.0, 20.0):
        return
    was_new = get_user(m.from_user.id) is None
    ensure_user(m.from_user)
    await process_start_referral(m, was_new)
''',
    "start referral",
)

# Tighten enforcement: expired VLESS clients are removed from Xray within about
# 10 seconds, while the subscription endpoint already rejects them immediately.
start = s.find('async def expiry_loop():')
end = s.find('\n\ndef backup_db():', start)
if start < 0 or end < 0:
    raise SystemExit('referral patch: expiry loop section missing')
section = s[start:end]
if section.count('        await asyncio.sleep(60)') != 1:
    raise SystemExit(f"referral patch expiry sleep: expected 1 match, found {section.count('        await asyncio.sleep(60)')}")
section = section.replace('        await asyncio.sleep(60)', '        await asyncio.sleep(10)', 1)
s = s[:start] + section + s[end:]

path.write_text(s)
print(f"referrals + strict expiry patched {path}")
