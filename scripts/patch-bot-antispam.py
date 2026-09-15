#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'antispam patch {name}: expected 1 match, found {count}')
    s = s.replace(old, new, 1)


# Reuse defaultdict/deque/time already imported by previous hardening patches.
replace_once(
    "SUB_RATE_MAX = 90\n",
    "SUB_RATE_MAX = 30\nTG_EVENTS = defaultdict(deque)\nTG_BLOCK_UNTIL = {}\nTRIAL_GLOBAL_EVENTS = deque()\n",
    'state',
)

insert = '''\n\ndef tg_rate_allowed(tg_id: int, bucket: str = "ui", limit: int = 8, window: float = 10.0, block_for: float = 30.0) -> bool:\n    if tg_id in ADMIN_IDS:\n        return True\n    now = time.monotonic()\n    blocked = TG_BLOCK_UNTIL.get(tg_id, 0.0)\n    if blocked > now:\n        return False\n    key = (tg_id, bucket)\n    q = TG_EVENTS[key]\n    while q and now - q[0] > window:\n        q.popleft()\n    if len(q) >= limit:\n        TG_BLOCK_UNTIL[tg_id] = now + block_for\n        q.clear()\n        print(f"telegram flood blocked tg={tg_id} bucket={bucket} for={int(block_for)}s", flush=True)\n        return False\n    q.append(now)\n    if len(TG_EVENTS) > 4096:\n        for stale_key in list(TG_EVENTS)[:2048]:\n            dq = TG_EVENTS.get(stale_key)\n            if not dq or now - dq[-1] > 300:\n                TG_EVENTS.pop(stale_key, None)\n    return True\n\n\ndef trial_capacity_available() -> bool:\n    now = time.monotonic()\n    while TRIAL_GLOBAL_EVENTS and now - TRIAL_GLOBAL_EVENTS[0] > 60.0:\n        TRIAL_GLOBAL_EVENTS.popleft()\n    # Protect the 1 GB VPS from a coordinated trial-activation/restart storm.\n    if len(TRIAL_GLOBAL_EVENTS) >= 8:\n        return False\n    TRIAL_GLOBAL_EVENTS.append(now)\n    return True\n\n\nasync def reject_callback_flood(c: CallbackQuery, bucket: str = "ui", limit: int = 8, window: float = 10.0, block_for: float = 30.0) -> bool:\n    if tg_rate_allowed(c.from_user.id, bucket, limit, window, block_for):\n        return False\n    try:\n        await c.answer("Слишком много запросов. Подожди немного 🙂", show_alert=False)\n    except Exception:\n        pass\n    return True\n\n'''
needle = 'def utcnow():\n'
if needle not in s:
    raise SystemExit('antispam patch helper insertion point missing')
s = s.replace(needle, insert + '\n' + needle, 1)

replace_once(
    '@dp.message(CommandStart())\nasync def start(m: Message):\n    ensure_user(m.from_user)\n',
    '@dp.message(CommandStart())\nasync def start(m: Message):\n    if not tg_rate_allowed(m.from_user.id, "start", 3, 10.0, 20.0):\n        return\n    ensure_user(m.from_user)\n',
    'start limit',
)

replace_once(
    '@dp.callback_query(F.data == "trial")\nasync def trial(c: CallbackQuery):\n    await c.answer("Активирую доступ…")\n',
    '@dp.callback_query(F.data == "trial")\nasync def trial(c: CallbackQuery):\n    if await reject_callback_flood(c, "trial", 2, 30.0, 60.0):\n        return\n    if c.from_user.id not in ADMIN_IDS and not trial_capacity_available():\n        await c.answer("Сейчас много активаций. Повтори через минуту 🙂", show_alert=False)\n        return\n    await c.answer("Активирую доступ…")\n',
    'trial limit',
)

for name, bucket, limit, window in (
    ('key', 'ui', 6, 10.0),
    ('status', 'ui', 6, 10.0),
    ('help_cb', 'ui', 6, 10.0),
    ('reissue', 'reissue', 1, 60.0),
):
    marker = f'async def {name}(c: CallbackQuery):\n'
    if s.count(marker) != 1:
        raise SystemExit(f'antispam patch {name}: expected 1 handler, found {s.count(marker)}')
    s = s.replace(marker, marker + f'    if await reject_callback_flood(c, "{bucket}", {limit}, {window}, 60.0):\n        return\n', 1)

# /rotatekey changes a live subscription token, so rate-limit it separately.
replace_once(
    '@dp.message(Command("rotatekey"))\nasync def rotatekey(m: Message):\n    row = ensure_user(m.from_user)\n',
    '@dp.message(Command("rotatekey"))\nasync def rotatekey(m: Message):\n    if not tg_rate_allowed(m.from_user.id, "rotatekey", 1, 60.0, 60.0):\n        await m.answer("⏳ Перевыпускать ссылку можно не чаще раза в минуту.")\n        return\n    row = ensure_user(m.from_user)\n',
    'rotatekey limit',
)

path.write_text(s)
print(f'antispam patched {path}')
