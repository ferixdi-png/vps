from pathlib import Path

bot_path = Path('bot/main.py')
s = bot_path.read_text()

start = s.find('@dp.message(Command("admin"))\nasync def admin_panel(m: Message):')
if start != -1:
    end = s.find('\n\n@dp.callback_query(F.data == "admin_stats")', start)
    if end == -1:
        raise SystemExit('could not find end of temporary admin handler')
    s = s[:start] + s[end + 2:]
    bot_path.write_text(s)
    print('removed temporary /admin handler; runtime admin panel remains canonical')
else:
    print('temporary /admin handler already absent')

panel_path = Path('scripts/patch-bot-admin-panel.py')
p = panel_path.read_text()
needle = '        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_panel")],\n'
row = '        [InlineKeyboardButton(text="💰 Заявки на оплату", callback_data="admin_payments")],\n'
if row not in p:
    if needle not in p:
        raise SystemExit('admin panel keyboard anchor not found')
    p = p.replace(needle, row + needle, 1)
    panel_path.write_text(p)
    print('added payments button to canonical admin panel')
else:
    print('payments button already present')
