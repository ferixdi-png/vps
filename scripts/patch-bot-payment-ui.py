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
    raise SystemExit(f"payment-ui patch: expected 1 match, found {count}")

s = s.replace(old, new, 1)
path.write_text(s)
print(f"payment UI simplified {path}")
