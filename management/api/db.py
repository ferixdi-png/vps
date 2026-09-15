import aiosqlite
from datetime import datetime, timezone

DB="/data/ferixdi.db"

SCHEMA="""
CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  username TEXT,
  full_name TEXT,
  vpn_user_id TEXT UNIQUE NOT NULL,
  vpn_uuid TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  trial_used INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS node_state (
  node_id TEXT PRIMARY KEY,
  is_up INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0,
  recover_count INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER,
  last_checked_at TEXT,
  last_error TEXT
);
"""

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def get_user(tg_id):
    async with aiosqlite.connect(DB) as db:
        db.row_factory=aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)) as c:
            r=await c.fetchone()
            return dict(r) if r else None

async def create_user(tg_id, username, full_name, vpn_user_id, vpn_uuid):
    now=datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
          INSERT OR IGNORE INTO users
          (telegram_id,username,full_name,vpn_user_id,vpn_uuid,created_at,enabled)
          VALUES (?,?,?,?,?,?,0)
        """,(tg_id,username,full_name,vpn_user_id,vpn_uuid,now))
        await db.commit()

async def activate_trial(tg_id, expires_at):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
          UPDATE users SET trial_used=1,enabled=1,expires_at=?
          WHERE telegram_id=? AND trial_used=0
        """,(expires_at,tg_id))
        await db.commit()

async def extend_user(tg_id, expires_at):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET enabled=1,expires_at=? WHERE telegram_id=?",(expires_at,tg_id))
        await db.commit()

async def disable_user(tg_id):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET enabled=0 WHERE telegram_id=?",(tg_id,))
        await db.commit()

async def list_expired(now_iso):
    async with aiosqlite.connect(DB) as db:
        db.row_factory=aiosqlite.Row
        async with db.execute("""
          SELECT * FROM users WHERE enabled=1 AND expires_at IS NOT NULL AND expires_at<=?
        """,(now_iso,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def stats():
    async with aiosqlite.connect(DB) as db:
        db.row_factory=aiosqlite.Row
        async with db.execute("""
          SELECT COUNT(*) total,
          SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) active,
          SUM(CASE WHEN trial_used=1 THEN 1 ELSE 0 END) trials
          FROM users
        """) as c:
            r=await c.fetchone()
            return dict(r)

async def set_node_state(node_id,is_up,fail_count,recover_count,latency_ms,last_error):
    now=datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO node_state(node_id,is_up,fail_count,recover_count,latency_ms,last_checked_at,last_error)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(node_id) DO UPDATE SET
          is_up=excluded.is_up,
          fail_count=excluded.fail_count,
          recover_count=excluded.recover_count,
          latency_ms=excluded.latency_ms,
          last_checked_at=excluded.last_checked_at,
          last_error=excluded.last_error
        """,(node_id,1 if is_up else 0,fail_count,recover_count,latency_ms,now,last_error))
        await db.commit()

async def get_node_states():
    async with aiosqlite.connect(DB) as db:
        db.row_factory=aiosqlite.Row
        async with db.execute("SELECT * FROM node_state") as c:
            return {r["node_id"]:dict(r) for r in await c.fetchall()}
