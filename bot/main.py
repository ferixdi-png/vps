import asyncio
import base64
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))
SUB_PORT = int(os.getenv("SUB_PORT", "8080"))
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip()
PUBLIC_SCHEME = os.getenv("PUBLIC_SCHEME", "http").strip() or "http"
SUPPORT = os.getenv("SUPPORT", "@ferixdiii")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/ferixdiii")
HAPP_URL = os.getenv("HAPP_URL", "https://happ.info/")
XRAY_CONFIG = Path(os.getenv("XRAY_CONFIG", "/opt/ferixdi/node/xray-config.json"))
XRAY_CONTAINER = os.getenv("XRAY_CONTAINER", "ferixdi-xray")
NODE_INFO = Path(os.getenv("NODE_INFO", "/root/FERIXDI-NODE-INFO.txt"))
DB_PATH = Path(os.getenv("DB_PATH", "/opt/ferixdi/data/bot.db"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/opt/ferixdi/backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def utcnow():
    return datetime.now(timezone.utc)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def ensure_column(con, table, name, ddl):
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                vpn_uuid TEXT NOT NULL UNIQUE,
                sub_token TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 0,
                trial_used INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        ensure_column(con, "users", "plan_type", "TEXT NOT NULL DEFAULT 'none'")
        ensure_column(con, "users", "warn_24h_sent", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "users", "warn_3h_sent", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "users", "expired_notified", "INTEGER NOT NULL DEFAULT 0")


def ensure_user(tg):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE telegram_id=?", (tg.id,)).fetchone()
        if row:
            con.execute(
                "UPDATE users SET username=?, full_name=? WHERE telegram_id=?",
                (tg.username or "", tg.full_name or "", tg.id),
            )
            return con.execute("SELECT * FROM users WHERE telegram_id=?", (tg.id,)).fetchone()
        con.execute(
            """INSERT INTO users
            (telegram_id, username, full_name, vpn_uuid, sub_token, enabled, trial_used, created_at, plan_type)
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, 'none')""",
            (
                tg.id,
                tg.username or "",
                tg.full_name or "",
                str(uuid.uuid4()),
                secrets.token_urlsafe(24),
                utcnow().isoformat(),
            ),
        )
        return con.execute("SELECT * FROM users WHERE telegram_id=?", (tg.id,)).fetchone()


def get_user(tg_id):
    with db() as con:
        return con.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()


def get_user_by_token(token):
    with db() as con:
        return con.execute("SELECT * FROM users WHERE sub_token=?", (token,)).fetchone()


def parse_exp(row):
    if not row or not row["expires_at"]:
        return None
    try:
        return datetime.fromisoformat(row["expires_at"])
    except Exception:
        return None


def is_active(row):
    exp = parse_exp(row)
    return bool(row and row["enabled"] and exp and exp > utcnow())


def active_users():
    with db() as con:
        return [r for r in con.execute("SELECT * FROM users WHERE enabled=1").fetchall() if is_active(r)]


def read_node_info():
    data = {}
    if NODE_INFO.exists():
        for line in NODE_INFO.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def load_xray():
    if not XRAY_CONFIG.exists():
        raise RuntimeError(f"Xray config not found: {XRAY_CONFIG}")
    return json.loads(XRAY_CONFIG.read_text())


def restart_xray():
    p = subprocess.run(
        ["docker", "restart", XRAY_CONTAINER],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stdout.strip() or "docker restart failed")


def sync_xray():
    cfg = load_xray()
    managed = active_users()
    for inbound in cfg.get("inbounds", []):
        settings = inbound.setdefault("settings", {})
        current = settings.get("clients", [])
        preserved = [c for c in current if not str(c.get("email", "")).startswith("tg:")]
        network = inbound.get("streamSettings", {}).get("network", "raw")
        generated = []
        for u in managed:
            c = {"id": u["vpn_uuid"], "email": f"tg:{u['telegram_id']}"}
            if network in ("raw", "tcp"):
                c["flow"] = "xtls-rprx-vision"
            generated.append(c)
        settings["clients"] = preserved + generated

    backup = XRAY_CONFIG.with_suffix(".json.bak")
    shutil.copy2(XRAY_CONFIG, backup)
    tmp = XRAY_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(XRAY_CONFIG)
    try:
        restart_xray()
    except Exception:
        shutil.copy2(backup, XRAY_CONFIG)
        restart_xray()
        raise


def profile_links(row):
    cfg = load_xray()
    info = read_node_info()
    host = PUBLIC_HOST or info.get("IP")
    pbk = info.get("PUBLIC_KEY")
    sid = info.get("SHORT_ID")
    if not host or not pbk or not sid:
        raise RuntimeError("PUBLIC_HOST/PUBLIC_KEY/SHORT_ID not configured")

    links = []
    for inbound in cfg.get("inbounds", []):
        port = inbound.get("port")
        stream = inbound.get("streamSettings", {})
        network = stream.get("network", "raw")
        reality = stream.get("realitySettings", {})
        sni = (reality.get("serverNames") or ["www.microsoft.com"])[0]
        q = {
            "encryption": "none",
            "security": "reality",
            "sni": sni,
            "fp": "chrome",
            "pbk": pbk,
            "sid": sid,
            "type": network,
        }
        label = f"Ferixdi Germany {network.upper()} {port}"
        if network in ("raw", "tcp"):
            q["flow"] = "xtls-rprx-vision"
        elif network == "xhttp":
            x = stream.get("xhttpSettings", {})
            if x.get("path"):
                q["path"] = x["path"]
            q["mode"] = "auto"
        elif network == "grpc":
            g = stream.get("grpcSettings", {})
            if g.get("serviceName"):
                q["serviceName"] = g["serviceName"]
        links.append(
            f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q, safe='/')}#{quote(label)}"
        )
    return links


def subscription_url(row):
    info = read_node_info()
    host = PUBLIC_HOST or info.get("IP")
    if not host:
        return None
    port = "" if (PUBLIC_SCHEME == "https" and SUB_PORT == 443) else f":{SUB_PORT}"
    return f"{PUBLIC_SCHEME}://{host}{port}/sub/{row['sub_token']}"


def expiry_text(row):
    exp = parse_exp(row)
    if not exp:
        return "не задан"
    return exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def plan_name(row):
    return "Платная" if row and row["plan_type"] == "paid" else "Пробная"


def menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 3 дня бесплатно", callback_data="trial")],
            [InlineKeyboardButton(text="🔑 Мой ключ", callback_data="key"), InlineKeyboardButton(text="📊 Статус", callback_data="status")],
            [InlineKeyboardButton(text="📱 Установка через Happ", callback_data="help")],
            [InlineKeyboardButton(text="💳 Продлить доступ", url=SUPPORT_URL)],
        ]
    )


def happ_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📲 Скачать Happ", url=HAPP_URL)],
            [InlineKeyboardButton(text="🔑 Получить мой ключ", callback_data="key")],
            [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
        ]
    )


@dp.message(CommandStart())
async def start(m: Message):
    ensure_user(m.from_user)
    await m.answer(
        "<b>Ferixdi VPN</b>\n\n"
        "Персональный доступ для защищённого подключения и работы с онлайн-сервисами.\n"
        "🎁 Новому пользователю доступно 3 дня бесплатно.\n"
        "🔑 Один персональный ключ.\n"
        "📱 Быстрая установка через Happ.",
        reply_markup=menu(),
        parse_mode="HTML",
    )


@dp.message(Command("myid"))
async def myid(m: Message):
    await m.answer(f"Твой Telegram ID: <code>{m.from_user.id}</code>", parse_mode="HTML")


@dp.callback_query(F.data == "trial")
async def trial(c: CallbackQuery):
    row = ensure_user(c.from_user)
    if row["trial_used"]:
        await c.message.answer("Пробный период уже использован. Для продления нажми «💳 Продлить доступ».", reply_markup=menu())
        await c.answer()
        return
    expires = utcnow() + timedelta(days=TRIAL_DAYS)
    with db() as con:
        con.execute(
            """UPDATE users SET enabled=1, trial_used=1, expires_at=?, plan_type='trial',
            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0 WHERE telegram_id=?""",
            (expires.isoformat(), c.from_user.id),
        )
    try:
        await asyncio.to_thread(sync_xray)
    except Exception as e:
        with db() as con:
            con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (c.from_user.id,))
        await c.message.answer(f"Не удалось активировать доступ. Код: {type(e).__name__}")
        await c.answer()
        return
    await c.message.answer(
        f"✅ <b>Доступ активирован на {TRIAL_DAYS} дня</b>\n\n"
        f"Работает до: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>\n\n"
        "Теперь нажми «📱 Установка через Happ» — там инструкция по шагам.",
        reply_markup=menu(),
        parse_mode="HTML",
    )
    await c.answer()


@dp.callback_query(F.data == "key")
async def key(c: CallbackQuery):
    ensure_user(c.from_user)
    row = get_user(c.from_user.id)
    if not is_active(row):
        await c.message.answer("🔴 Доступ сейчас не активен. Используй пробный период или продли подписку.", reply_markup=menu())
        await c.answer()
        return
    url = subscription_url(row)
    links = profile_links(row)
    text = (
        "🔑 <b>Твой персональный ключ</b>\n\n"
        f"Тариф: <b>{plan_name(row)}</b>\n"
        f"Действует до: <b>{expiry_text(row)}</b>\n\n"
    )
    if url:
        text += "<b>Ссылка подписки:</b>\n<code>" + url + "</code>\n\n"
    if links:
        text += "Если приложение не принимает подписку, используй резервный VLESS-профиль:\n<code>" + links[0] + "</code>"
    await c.message.answer(text, parse_mode="HTML", reply_markup=happ_keyboard())
    await c.answer()


@dp.callback_query(F.data == "status")
async def status(c: CallbackQuery):
    ensure_user(c.from_user)
    row = get_user(c.from_user.id)
    if is_active(row):
        exp = parse_exp(row)
        left = exp - utcnow()
        hours = max(0, int(left.total_seconds() // 3600))
        days, rem_hours = divmod(hours, 24)
        await c.message.answer(
            f"🟢 <b>Доступ активен</b>\n"
            f"Тариф: {plan_name(row)}\n"
            f"До: {expiry_text(row)}\n"
            f"Осталось: {days} дн. {rem_hours} ч.",
            parse_mode="HTML",
            reply_markup=menu(),
        )
    else:
        await c.message.answer("🔴 Доступ не активен", reply_markup=menu())
    await c.answer()


@dp.callback_query(F.data == "help")
async def help_cb(c: CallbackQuery):
    await c.message.answer(
        "<b>Установка через Happ</b>\n\n"
        "1. Нажми «📲 Скачать Happ» и установи приложение для своей платформы.\n"
        "2. Вернись в бот и нажми «🔑 Получить мой ключ».\n"
        "3. Скопируй ссылку подписки целиком.\n"
        "4. В Happ нажми <b>+</b> → добавление подписки / URL.\n"
        "5. Вставь ссылку, сохрани и выбери профиль Ferixdi.\n"
        "6. Нажми кнопку подключения.\n\n"
        "Если не получается, нажми «💬 Поддержка».",
        parse_mode="HTML",
        reply_markup=happ_keyboard(),
    )
    await c.answer()


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    with db() as con:
        rows = con.execute("SELECT * FROM users").fetchall()
        total = len(rows)
        active = sum(1 for r in rows if is_active(r))
        trials = sum(1 for r in rows if r["trial_used"])
        paid = sum(1 for r in rows if r["plan_type"] == "paid" and is_active(r))
    await m.answer(f"👥 Всего: {total}\n🟢 Активных: {active}\n💳 Платных: {paid}\n🎁 Использовали trial: {trials}")


@dp.message(Command("extend"))
async def extend(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    parts = (m.text or "").split()
    if len(parts) != 3:
        await m.answer("Использование: /extend TELEGRAM_ID DAYS")
        return
    try:
        tg_id, days = int(parts[1]), int(parts[2])
    except ValueError:
        await m.answer("ID и DAYS должны быть числами")
        return
    row = get_user(tg_id)
    if not row:
        await m.answer("Пользователь ещё не запускал бота")
        return
    base = parse_exp(row) if is_active(row) else utcnow()
    expires = base + timedelta(days=days)
    with db() as con:
        con.execute(
            """UPDATE users SET enabled=1, expires_at=?, plan_type='paid',
            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0 WHERE telegram_id=?""",
            (expires.isoformat(), tg_id),
        )
    await asyncio.to_thread(sync_xray)
    try:
        await bot.send_message(
            tg_id,
            f"✅ <b>Оплата подтверждена</b>\n\nДоступ продлён на {days} дн.\nДо: <b>{expires.strftime('%d.%m.%Y %H:%M UTC')}</b>",
            parse_mode="HTML",
            reply_markup=menu(),
        )
    except Exception:
        pass
    await m.answer(f"✅ Продлено на {days} дн. До {expires.strftime('%d.%m.%Y %H:%M UTC')}")


@dp.message(Command("disable"))
async def disable(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    parts = (m.text or "").split()
    if len(parts) != 2:
        await m.answer("Использование: /disable TELEGRAM_ID")
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        return
    with db() as con:
        con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (tg_id,))
    await asyncio.to_thread(sync_xray)
    await m.answer("✅ Доступ отключён")


async def sub_handler(request: web.Request):
    row = get_user_by_token(request.match_info["token"])
    if not is_active(row):
        raise web.HTTPNotFound()
    links = profile_links(row)
    body = base64.b64encode(("\n".join(links) + "\n").encode()).decode()
    exp = parse_exp(row)
    expire_unix = int(exp.timestamp()) if exp else 0
    headers = {
        "Profile-Title": "Ferixdi VPN",
        "Subscription-Userinfo": f"upload=0; download=0; total=0; expire={expire_unix}",
    }
    return web.Response(text=body, content_type="text/plain", headers=headers)


async def health_handler(request: web.Request):
    return web.json_response({"ok": True, "service": "ferixdi-vpn-bot"})


async def safe_send(tg_id, text):
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML", reply_markup=menu())
    except Exception as e:
        print(f"notify {tg_id} error: {e}", flush=True)


async def expiry_loop():
    while True:
        changed = False
        now = utcnow()
        with db() as con:
            rows = con.execute("SELECT * FROM users WHERE enabled=1 AND expires_at IS NOT NULL").fetchall()
            for row in rows:
                exp = parse_exp(row)
                if not exp:
                    continue
                left = exp - now
                seconds = left.total_seconds()

                if 0 < seconds <= 24 * 3600 and not row["warn_24h_sent"]:
                    con.execute("UPDATE users SET warn_24h_sent=1 WHERE telegram_id=?", (row["telegram_id"],))
                    asyncio.create_task(safe_send(
                        row["telegram_id"],
                        "⏰ <b>Подписка заканчивается меньше чем через сутки</b>\n\n"
                        f"Доступ до: <b>{expiry_text(row)}</b>\n"
                        "Чтобы подключение не остановилось, продли доступ заранее.",
                    ))

                if 0 < seconds <= 3 * 3600 and not row["warn_3h_sent"]:
                    con.execute("UPDATE users SET warn_3h_sent=1 WHERE telegram_id=?", (row["telegram_id"],))
                    asyncio.create_task(safe_send(
                        row["telegram_id"],
                        "⚠️ <b>До окончания подписки осталось меньше 3 часов</b>\n\n"
                        "После окончания персональный ключ автоматически отключится.",
                    ))

                if seconds <= 0:
                    con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (row["telegram_id"],))
                    changed = True
                    if not row["expired_notified"]:
                        con.execute("UPDATE users SET expired_notified=1 WHERE telegram_id=?", (row["telegram_id"],))
                        asyncio.create_task(safe_send(
                            row["telegram_id"],
                            "🔴 <b>Подписка закончилась</b>\n\n"
                            "Доступ отключён автоматически. Нажми «💳 Продлить доступ», чтобы продолжить пользоваться тем же ботом.",
                        ))
        if changed:
            try:
                await asyncio.to_thread(sync_xray)
            except Exception as e:
                print("expiry sync error:", e, flush=True)
        await asyncio.sleep(60)


def backup_db():
    if not DB_PATH.exists():
        return
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"bot-{stamp}.db"
    with db() as src:
        with sqlite3.connect(dest) as dst:
            src.backup(dst)
    backups = sorted(BACKUP_DIR.glob("bot-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[BACKUP_KEEP:]:
        try:
            old.unlink()
        except Exception:
            pass


async def backup_loop():
    while True:
        try:
            await asyncio.to_thread(backup_db)
        except Exception as e:
            print("backup error:", e, flush=True)
        await asyncio.sleep(6 * 3600)


async def main():
    init_db()
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/sub/{token}", sub_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", SUB_PORT)
    await site.start()
    asyncio.create_task(expiry_loop())
    asyncio.create_task(backup_loop())
    print(f"Ferixdi bot started; subscription port={SUB_PORT}", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
