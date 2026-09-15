#!/usr/bin/env python3
"""Second-stage production hardening for the Ferixdi VPN bot.

This patch is intentionally applied after patch-bot-runtime.py. All replacements
are asserted so a future source change fails the deploy rather than silently
running without the reliability fixes.
"""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ferixdi/bot/main.py")
s = path.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"hardening patch {name}: expected 1 match, found {count}")
    s = s.replace(old, new, 1)


replace_once(
    "import subprocess\nimport uuid\n",
    "import subprocess\nimport threading\nimport time\nimport uuid\n",
    "imports",
)

replace_once(
    "bot = Bot(BOT_TOKEN)\ndp = Dispatcher()\n",
    "bot = Bot(BOT_TOKEN)\ndp = Dispatcher()\nXRAY_LOCK = threading.Lock()\nXRAY_DIRTY = DB_PATH.parent / 'xray-dirty'\n",
    "state",
)

replace_once(
    '''def db():\n    con = sqlite3.connect(DB_PATH, timeout=10)\n    con.row_factory = sqlite3.Row\n    con.execute("PRAGMA busy_timeout=5000")\n    return con\n''',
    '''def db():\n    con = sqlite3.connect(DB_PATH, timeout=10)\n    con.row_factory = sqlite3.Row\n    con.execute("PRAGMA busy_timeout=5000")\n    con.execute("PRAGMA journal_mode=WAL")\n    con.execute("PRAGMA synchronous=NORMAL")\n    return con\n''',
    "sqlite WAL",
)

old_restart_sync = '''def restart_xray():\n    p = subprocess.run(\n        ["docker", "restart", XRAY_CONTAINER],\n        stdout=subprocess.PIPE,\n        stderr=subprocess.STDOUT,\n        text=True,\n        timeout=30,\n    )\n    if p.returncode != 0:\n        raise RuntimeError(p.stdout.strip() or "docker restart failed")\n\n\ndef sync_xray():\n    cfg = load_xray()\n    managed = active_users()\n    for inbound in cfg.get("inbounds", []):\n        settings = inbound.setdefault("settings", {})\n        current = settings.get("clients", [])\n        preserved = [c for c in current if not str(c.get("email", "")).startswith("tg:")]\n        network = inbound.get("streamSettings", {}).get("network", "raw")\n        generated = []\n        for u in managed:\n            c = {"id": u["vpn_uuid"], "email": f"tg:{u['telegram_id']}"}\n            if network in ("raw", "tcp"):\n                c["flow"] = "xtls-rprx-vision"\n            generated.append(c)\n        settings["clients"] = preserved + generated\n\n    backup = XRAY_CONFIG.with_suffix(".json.bak")\n    shutil.copy2(XRAY_CONFIG, backup)\n    tmp = XRAY_CONFIG.with_suffix(".json.tmp")\n    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\\n")\n    tmp.replace(XRAY_CONFIG)\n    try:\n        restart_xray()\n    except Exception:\n        shutil.copy2(backup, XRAY_CONFIG)\n        restart_xray()\n        raise\n'''

new_restart_sync = '''def restart_xray():\n    p = subprocess.run(\n        ["docker", "restart", XRAY_CONTAINER],\n        stdout=subprocess.PIPE,\n        stderr=subprocess.STDOUT,\n        text=True,\n        timeout=30,\n    )\n    if p.returncode != 0:\n        raise RuntimeError(p.stdout.strip() or "docker restart failed")\n\n\ndef mark_xray_dirty():\n    try:\n        XRAY_DIRTY.touch()\n    except Exception as e:\n        print(f"dirty marker warning: {e}", flush=True)\n\n\ndef sync_xray():\n    # Multiple Telegram callbacks can arrive concurrently. Serialize config writes\n    # and container restarts so one request can never overwrite another.\n    with XRAY_LOCK:\n        cfg = load_xray()\n        managed = active_users()\n        changed = False\n        for inbound in cfg.get("inbounds", []):\n            # This bot currently manages only VLESS inbounds. Other protocol\n            # families are left untouched until their credential model is added.\n            if inbound.get("protocol", "vless") != "vless":\n                continue\n            settings = inbound.setdefault("settings", {})\n            current = settings.get("clients", [])\n            preserved = [c for c in current if not str(c.get("email", "")).startswith("tg:")]\n            network = inbound.get("streamSettings", {}).get("network", "raw")\n            generated = []\n            for u in managed:\n                c = {"id": u["vpn_uuid"], "email": f"tg:{u['telegram_id']}"}\n                if network in ("raw", "tcp"):\n                    c["flow"] = "xtls-rprx-vision"\n                generated.append(c)\n            new_clients = preserved + generated\n            if current != new_clients:\n                settings["clients"] = new_clients\n                changed = True\n\n        if not changed:\n            try:\n                XRAY_DIRTY.unlink(missing_ok=True)\n            except Exception:\n                pass\n            return\n\n        backup = XRAY_CONFIG.with_suffix(".json.bak")\n        shutil.copy2(XRAY_CONFIG, backup)\n        tmp = XRAY_CONFIG.with_suffix(".json.tmp")\n        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\\n")\n        # Parse our own output before atomically replacing the live file.\n        json.loads(tmp.read_text())\n        tmp.replace(XRAY_CONFIG)\n        try:\n            restart_xray()\n            time.sleep(1)\n            p = subprocess.run(\n                ["docker", "inspect", "-f", "{{.State.Running}}", XRAY_CONTAINER],\n                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10,\n            )\n            if p.returncode != 0 or p.stdout.strip() != "true":\n                raise RuntimeError("Xray container is not running after restart")\n            XRAY_DIRTY.unlink(missing_ok=True)\n        except Exception:\n            shutil.copy2(backup, XRAY_CONFIG)\n            try:\n                restart_xray()\n            finally:\n                mark_xray_dirty()\n            raise\n'''
replace_once(old_restart_sync, new_restart_sync, "serialized xray sync")

# Generate two client handshake variants per usable Reality inbound. This gives
# users more fallback choices without opening unsafe transports or extra ports.
old_profile_tail = '''        links.append(\n            f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q, safe='/')}#{quote(label)}"\n        )\n    if not links:\n        raise RuntimeError("no usable Reality inbounds configured")\n    return links\n'''
new_profile_tail = '''        for fp_name, fp_label in (("chrome", "Chrome"), ("firefox", "Firefox")):\n            q_variant = dict(q)\n            q_variant["fp"] = fp_name\n            variant_label = f"{label} {fp_label}"\n            links.append(\n                f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q_variant, safe='/')}#{quote(variant_label)}"\n            )\n    if not links:\n        raise RuntimeError("no usable Reality inbounds configured")\n    return links\n'''
replace_once(old_profile_tail, new_profile_tail, "profile variants")

# Make trial activation atomic and restore the database if Xray provisioning fails.
old_trial = '''    row = ensure_user(c.from_user)\n    if row["trial_used"]:\n        await c.message.answer("Пробный период уже использован. Для продления нажми «💳 Продлить доступ».", reply_markup=menu())\n        return\n    expires = utcnow() + timedelta(days=TRIAL_DAYS)\n    with db() as con:\n        con.execute(\n            """UPDATE users SET enabled=1, trial_used=1, expires_at=?, plan_type='trial',\n            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0 WHERE telegram_id=?""",\n            (expires.isoformat(), c.from_user.id),\n        )\n    try:\n        await asyncio.to_thread(sync_xray)\n    except Exception as e:\n        with db() as con:\n            con.execute("UPDATE users SET enabled=0 WHERE telegram_id=?", (c.from_user.id,))\n        await c.message.answer(f"Не удалось активировать доступ. Код: {type(e).__name__}")\n        return\n'''
new_trial = '''    row = ensure_user(c.from_user)\n    if row["trial_used"]:\n        await c.message.answer("Пробный период уже использован. Для продления нажми «💳 Продлить доступ».", reply_markup=menu())\n        return\n    expires = utcnow() + timedelta(days=TRIAL_DAYS)\n    with db() as con:\n        cur = con.execute(\n            """UPDATE users SET enabled=1, trial_used=1, expires_at=?, plan_type='trial',\n            warn_24h_sent=0, warn_3h_sent=0, expired_notified=0\n            WHERE telegram_id=? AND trial_used=0""",\n            (expires.isoformat(), c.from_user.id),\n        )\n        if cur.rowcount != 1:\n            await c.message.answer("Пробный период уже использован.", reply_markup=menu())\n            return\n    mark_xray_dirty()\n    try:\n        await asyncio.to_thread(sync_xray)\n    except Exception as e:\n        # Do not burn the user's one-time trial because of an infrastructure error.\n        with db() as con:\n            con.execute(\n                """UPDATE users SET enabled=0, trial_used=0, expires_at=NULL, plan_type='none',\n                warn_24h_sent=0, warn_3h_sent=0, expired_notified=0 WHERE telegram_id=?""",\n                (c.from_user.id,),\n            )\n        mark_xray_dirty()\n        await c.message.answer(\n            f"⚠️ Сервер временно не подтвердил активацию. Пробный период не списан. Код: {type(e).__name__}"\n        )\n        return\n'''
replace_once(old_trial, new_trial, "trial rollback")

# Ensure expiry removals are retried after a temporary Xray/Docker failure.
replace_once(
    '''        if changed:\n            try:\n                await asyncio.to_thread(sync_xray)\n            except Exception as e:\n                print("expiry sync error:", e, flush=True)\n        await asyncio.sleep(60)\n''',
    '''        if changed:\n            mark_xray_dirty()\n        if XRAY_DIRTY.exists():\n            try:\n                await asyncio.to_thread(sync_xray)\n            except Exception as e:\n                print("expiry/xray retry error:", e, flush=True)\n        await asyncio.sleep(60)\n''',
    "expiry retry",
)

# Health must reflect more than just the Python process being alive.
replace_once(
    '''async def health_handler(request: web.Request):\n    return web.json_response({"ok": True, "service": "ferixdi-vpn-bot"})\n''',
    '''async def health_handler(request: web.Request):\n    problems = []\n    try:\n        with db() as con:\n            if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":\n                problems.append("db")\n    except Exception:\n        problems.append("db")\n    try:\n        info = read_node_info()\n        if not (PUBLIC_HOST or info.get("IP")) or not info.get("PUBLIC_KEY"):\n            problems.append("node-metadata")\n        cfg = load_xray()\n        if not cfg.get("inbounds"):\n            problems.append("xray-config")\n    except Exception:\n        problems.append("xray-config")\n    status = 200 if not problems else 503\n    return web.json_response(\n        {"ok": not problems, "service": "ferixdi-vpn-bot", "problems": problems},\n        status=status,\n    )\n''',
    "health readiness",
)

# A leaked subscription URL can be invalidated without changing the VPN UUID.
insert_before = '@dp.message(Command("stats"))\n'
if insert_before not in s:
    raise SystemExit("hardening patch rotate token: insertion point not found")
rotate_handler = '''@dp.message(Command("rotatekey"))\nasync def rotatekey(m: Message):\n    row = ensure_user(m.from_user)\n    if not is_active(row):\n        await m.answer("🔴 Доступ не активен.", reply_markup=menu())\n        return\n    new_token = secrets.token_urlsafe(24)\n    with db() as con:\n        con.execute("UPDATE users SET sub_token=? WHERE telegram_id=?", (new_token, m.from_user.id))\n    await m.answer(\n        "✅ Ссылка подписки обновлена. Старая ссылка больше не работает. Нажми «🔑 Мой ключ».",\n        reply_markup=menu(),\n    )\n\n\n'''
s = s.replace(insert_before, rotate_handler + insert_before, 1)

path.write_text(s)
print(f"hardening patched {path}")
