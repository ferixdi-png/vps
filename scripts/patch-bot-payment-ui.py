#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()

old = '''def payment_keyboard():
    full = f"{PAYMENT_PHONE} · {PAYMENT_BANK} · {PAYMENT_RECIPIENT}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать номер", copy_text=CopyTextButton(text=PAYMENT_PHONE))],
            [InlineKeyboardButton(text="📋 Скопировать реквизиты", copy_text=CopyTextButton(text=full))],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data="pay_sent")],
            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
        ]
    )
'''

new = '''def payment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать номер для оплаты", copy_text=CopyTextButton(text=PAYMENT_PHONE))],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data="pay_sent")],
            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
        ]
    )
'''

count = s.count(old)
if count != 1:
    raise SystemExit(f"payment-ui patch: expected 1 payment keyboard match, found {count}")
s = s.replace(old, new, 1)

old_confirm = '''    try:
        await bot.send_message(
            payment["telegram_id"],
            "✅ <b>Оплата подтверждена</b>\\n\\n"
            f"Доступ продлён на <b>{payment['days']} дней</b>.\\n"
            f"До: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>",
            parse_mode="HTML",
            reply_markup=menu(),
        )
    except Exception:
        pass
'''

new_confirm = '''    try:
        user_row = get_user(payment["telegram_id"])
        key_url = subscription_url(user_row)
        if not key_url:
            raise RuntimeError("subscription URL is not configured")

        await bot.send_message(
            payment["telegram_id"],
            "✅ <b>Оплата подтверждена</b>\\n\\n"
            f"Доступ продлён на <b>{payment['days']} дней</b>.\\n"
            f"До: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>",
            parse_mode="HTML",
        )
        await bot.send_message(
            payment["telegram_id"],
            "🔑 <b>Ваш ключ доступа:</b>\\n\\n"
            f"<code>{key_url}</code>\\n\\n"
            "Скопируйте ключ и добавьте его в Happ:\\n"
            "<b>+ → Вставить из буфера обмена</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        print(
            f"payment key delivery error payment={payment_id}: {type(e).__name__}: {e}",
            flush=True,
        )
'''

count = s.count(old_confirm)
if count != 1:
    raise SystemExit(f"payment-ui patch: expected 1 payment confirmation match, found {count}")
s = s.replace(old_confirm, new_confirm, 1)

path.write_text(s)
print(f"payment UI simplified and direct key delivery enabled {path}")
