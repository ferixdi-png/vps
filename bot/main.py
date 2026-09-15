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
from urllib.parse import urlencode, quote

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))
SUB_PORT = int(os.getenv("SUB_PORT", "8080"))
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip()
SUPPORT = os.getenv("SUPPORT", "@ferixdiii")
XRAY_CONFIG = Path(os.getenv("XRAY_CONFIG", "/opt/ferixdi/node/xray-config.json"))
XRAY_CONTAINER = os.getenv("XRAY_CONTAINER", "ferixdi-xray")
NODE_INFO = Path(os.getenv("NODE_INFO", "/root/FERIXDI-NODE-INFO.txt"))
DB_PATH = Path(os.getenv("DB_PATH", "/opt/ferixdi/data/bot.db"))

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def utcnow():
    return datetime.now(timezone.utc)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


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
            (telegram_id, username, full_name, vpn_uuid, sub_token, enabled, trial_used, created_at)
            VALUES (?, ?, ?, ?, ?, 0, 0, ?)""",
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


def is_active(row):
    if not row or not row["enabled"] or not row["expires_at"]:
        return False
    try:
        return datetime.fromisoformat(row["expires_at"]) > utcnow()
    except Exception:
        return False


def active_users():
    now = utcnow()
    out = []
    with db() as con:
        for row in con.execute("SELECT * FROM users WHERE enabled=1").fetchall():
            try:
                if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) > now:
                    out.append(row)
            except Exception:
                pass
    return out


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
        # Keep manually-created/bootstrap users; only replace bot-managed tg:* clients.
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
    return f"http://{host}:{SUB_PORT}/sub/{row['sub_token']}"


def menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 3 дня бесплатно", callback_data="trial")],
            [InlineKeyboardButton(text="🔑 Мой ключ", callback_data="key"), InlineKeyboardButton(text="📊 Статус", callback_data="status")],
            [InlineKeyboardButton(text="📱 Как подключить", callback_data="help")],
        ]
    )


@dp.message(CommandStart())
async def start(m: Message):
    ensure_user(m.from_user)
    await m.answer(
        "<b>Ferixdi VPN</b>\n\n"
        "Персональное защищённое подключение. Один профиль подписки и автоматическое управление доступом.",
        reply_markup=menu(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "trial")
async def trial(c: CallbackQuery):
    row = ensure_user(c.from_user)
    if row["trial_used"]:
        await c.message.answer("Пробный период уже был использован. Для продления: " + SUPPORT)
        await c.answer()
        return
    expires = utcnow() + timedelta(days=TRIAL_DAYS)
    with db() as con:
        con.execute(
            "UPDATE users SET enabled=1, trial_used=1, expires_at=? WHERE telegram_id=?",
            (expires.isoformat(), c.from_user.id),
        )
    try:
        await asyncio.to_thread(sync_xray)
    except Exception as e:
        with db() as con:
            con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (c.from_user.id,))
        await c.message.answer(f"Не удалось активировать узел. Администратору: {e}")
        await c.answer()
        return
    row = get_user(c.from_user.id)
    await c.message.answer(
        f"✅ Доступ активирован на {TRIAL_DAYS} дня.\n\n"
        "Нажми «🔑 Мой ключ» и добавь ссылку в VPN-клиент.",
        reply_markup=menu(),
    )
    await c.answer()


@dp.callback_query(F.data == "key")
async def key(c: CallbackQuery):
    row = ensure_user(c.from_user)
    row = get_user(c.from_user.id)
    if not is_active(row):
        await c.message.answer("Доступ сейчас не активен. Используй пробный период или обратись: " + SUPPORT)
        await c.answer()
        return
    url = subscription_url(row)
    links = profile_links(row)
    text = "🔑 <b>Твой персональный доступ</b>\n\n"
    if url:
        text += "Добавь эту ссылку как подписку:\n<code>" + url + "</code>\n\n"
    if links:
        text += "Если клиент не поддерживает подписки, используй первый профиль:\n<code>" + links[0] + "</code>"
    await c.message.answer(text, parse_mode="HTML")
    await c.answer()


@dp.callback_query(F.data == "status")
async def status(c: CallbackQuery):
    row = ensure_user(c.from_user)
    row = get_user(c.from_user.id)
    if is_active(row):
        exp = datetime.fromisoformat(row["expires_at"]).astimezone(timezone.utc)
        await c.message.answer("🟢 Доступ активен\nДо: " + exp.strftime("%d.%m.%Y %H:%M UTC"))
    else:
        await c.message.answer("🔴 Доступ не активен")
    await c.answer()


@dp.callback_query(F.data == "help")
async def help_cb(c: CallbackQuery):
    await c.message.answer(
        "<b>Как подключить</b>\n\n"
        "1. Установи совместимый VLESS/Xray-клиент.\n"
        "2. Открой «Мой ключ».\n"
        "3. Добавь ссылку как подписку.\n"
        "4. Выбери профиль и подключись.\n\n"
        "Поддержка: " + SUPPORT,
        parse_mode="HTML",
    )
    await c.answer()


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = sum(1 for r in con.execute("SELECT * FROM users WHERE enabled=1").fetchall() if is_active(r))
        trials = con.execute("SELECT COUNT(*) FROM users WHERE trial_used=1").fetchone()[0]
    await m.answer(f"👥 Всего: {total}\n🟢 Активных: {active}\n🎁 Trial: {trials}")


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
    base = utcnow()
    if is_active(row):
        base = datetime.fromisoformat(row["expires_at"])
    expires = base + timedelta(days=days)
    with db() as con:
        con.execute("UPDATE users SET enabled=1, expires_at=? WHERE telegram_id=?", (expires.isoformat(), tg_id))
    await asyncio.to_thread(sync_xray)
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
    # Standard V2Ray subscription body (base64 of newline-separated URIs).
    body = base64.b64encode(("\n".join(links) + "\n").encode()).decode()
    return web.Response(text=body, content_type="text/plain", headers={"Profile-Title": "Ferixdi VPN"})


async def health_handler(request: web.Request):
    return web.json_response({"ok": True, "service": "ferixdi-vpn-bot"})


async def expiry_loop():
    while True:
        changed = False
        now = utcnow()
        with db() as con:
            rows = con.execute("SELECT * FROM users WHERE enabled=1 AND expires_at IS NOT NULL").fetchall()
            for row in rows:
                try:
                    if datetime.fromisoformat(row["expires_at"]) <= now:
                        con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (row["telegram_id"],))
                        changed = True
                except Exception:
                    pass
        if changed:
            try:
                await asyncio.to_thread(sync_xray)
            except Exception as e:
                print("expiry sync error:", e, flush=True)
        await asyncio.sleep(60)


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
    print(f"Ferixdi bot started; subscription port={SUB_PORT}", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
