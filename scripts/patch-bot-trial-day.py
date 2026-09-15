#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'trial-day patch {name}: expected 1 match, found {count}')
    s = s.replace(old, new, 1)


replace_once(
    'TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))',
    'TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "1"))',
    'trial default',
)
replace_once(
    'InlineKeyboardButton(text="🎁 3 дня бесплатно", callback_data="trial")',
    'InlineKeyboardButton(text="🎁 24 часа бесплатно", callback_data="trial")',
    'trial button',
)
replace_once(
    '"🎁 Новому пользователю доступно 3 дня бесплатно.\\n"',
    '"🎁 Новому пользователю доступен тест на 24 часа.\\n"',
    'start text',
)
replace_once(
    'f"✅ <b>Доступ активирован на {TRIAL_DAYS} дня</b>\\n\\n"',
    '"✅ <b>Тестовый доступ активирован на 24 часа</b>\\n\\n"',
    'activation text',
)

old = '''                if 0 < seconds <= 24 * 3600 and not row["warn_24h_sent"]:\n                    con.execute("UPDATE users SET warn_24h_sent=1 WHERE telegram_id=?", (row["telegram_id"],))\n                    asyncio.create_task(safe_send(\n                        row["telegram_id"],\n                        "⏰ <b>Подписка заканчивается меньше чем через сутки</b>\\n\\n"\n                        f"Доступ до: <b>{expiry_text(row)}</b>\\n"\n                        "Чтобы подключение не остановилось, продли доступ заранее.",\n                    ))\n\n                if 0 < seconds <= 3 * 3600 and not row["warn_3h_sent"]:\n                    con.execute("UPDATE users SET warn_3h_sent=1 WHERE telegram_id=?", (row["telegram_id"],))\n                    asyncio.create_task(safe_send(\n                        row["telegram_id"],\n                        "⚠️ <b>До окончания подписки осталось меньше 3 часов</b>\\n\\n"\n                        "После окончания персональный ключ автоматически отключится.",\n                    ))\n\n                if seconds <= 0:\n                    con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (row["telegram_id"],))\n                    changed = True\n                    if not row["expired_notified"]:\n                        con.execute("UPDATE users SET expired_notified=1 WHERE telegram_id=?", (row["telegram_id"],))\n                        asyncio.create_task(safe_send(\n                            row["telegram_id"],\n                            "🔴 <b>Подписка закончилась</b>\\n\\n"\n                            "Доступ отключён автоматически. Нажми «💳 Продлить доступ», чтобы продолжить пользоваться тем же ботом.",\n                        ))\n'''
new = '''                is_trial = row["plan_type"] == "trial"\n\n                # A 24-hour trial must not fire the old "24 hours left" warning\n                # immediately after activation. Trial users instead receive two\n                # useful conversion reminders: halfway through and one hour before\n                # expiry. Paid plans keep the existing 24h / 3h cadence.\n                first_threshold = 12 * 3600 if is_trial else 24 * 3600\n                second_threshold = 1 * 3600 if is_trial else 3 * 3600\n\n                if 0 < seconds <= first_threshold and not row["warn_24h_sent"]:\n                    con.execute("UPDATE users SET warn_24h_sent=1 WHERE telegram_id=?", (row["telegram_id"],))\n                    if is_trial:\n                        text = (\n                            "⏳ <b>Половина тестового дня уже прошла</b>\\n\\n"\n                            "Если Ferixdi VPN у тебя работает как надо, можно заранее оформить доступ, "\n                            "чтобы завтра ключ не отключился.\\n\\n"\n                            "Нажми «💳 Продлить доступ» ниже."\n                        )\n                    else:\n                        text = (\n                            "⏰ <b>Подписка заканчивается меньше чем через сутки</b>\\n\\n"\n                            f"Доступ до: <b>{expiry_text(row)}</b>\\n"\n                            "Чтобы подключение не остановилось, продли доступ заранее."\n                        )\n                    asyncio.create_task(safe_send(row["telegram_id"], text))\n\n                if 0 < seconds <= second_threshold and not row["warn_3h_sent"]:\n                    con.execute("UPDATE users SET warn_3h_sent=1 WHERE telegram_id=?", (row["telegram_id"],))\n                    if is_trial:\n                        text = (\n                            "⚠️ <b>Тест закончится примерно через час</b>\\n\\n"\n                            "После этого персональный ключ отключится автоматически. "\n                            "Если всё устраивает, самое время продлить доступ 💳"\n                        )\n                    else:\n                        text = (\n                            "⚠️ <b>До окончания подписки осталось меньше 3 часов</b>\\n\\n"\n                            "После окончания персональный ключ автоматически отключится."\n                        )\n                    asyncio.create_task(safe_send(row["telegram_id"], text))\n\n                if seconds <= 0:\n                    con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (row["telegram_id"],))\n                    changed = True\n                    if not row["expired_notified"]:\n                        con.execute("UPDATE users SET expired_notified=1 WHERE telegram_id=?", (row["telegram_id"],))\n                        if is_trial:\n                            text = (\n                                "🔴 <b>24 часа теста закончились</b>\\n\\n"\n                                "Ferixdi VPN автоматически отключил тестовый ключ. "\n                                "Если всё понравилось — давай оставим доступ активным 🙂\\n\\n"\n                                "Нажми «💳 Продлить доступ» и оплати подписку."\n                            )\n                        else:\n                            text = (\n                                "🔴 <b>Подписка закончилась</b>\\n\\n"\n                                "Доступ отключён автоматически. Нажми «💳 Продлить доступ», "\n                                "чтобы снова включить персональный ключ."\n                            )\n                        asyncio.create_task(safe_send(row["telegram_id"], text))\n'''
replace_once(old, new, 'expiry notifications')

path.write_text(s)
print(f'24-hour trial patched {path}')
