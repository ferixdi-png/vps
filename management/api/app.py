import json, os, secrets, uuid, hmac, hashlib, base64
from pathlib import Path
from aiohttp import web
from db import init_db, get_user, create_user, activate_trial, extend_user, disable_user, stats, get_node_states

ENV=Path("/.env")

def env():
    out={}
    for line in ENV.read_text().splitlines():
        line=line.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

async def auth(request):
    e=env()
    if request.headers.get("Authorization") != f"Bearer {e['VPN_API_TOKEN']}":
        raise web.HTTPUnauthorized()

def sign_sub(user_id):
    e=env()
    raw=user_id.encode()
    sig=hmac.new(e["SUBSCRIPTION_SIGNING_SECRET"].encode(),raw,hashlib.sha256).digest()
    token=base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return token

async def health(request):
    return web.json_response({"ok":True})

async def ensure_user(request):
    await auth(request)
    body=await request.json()
    tg_id=int(body["telegram_id"])
    u=await get_user(tg_id)
    if u:
        return web.json_response(u)
    vpn_user_id=secrets.token_urlsafe(8)
    vpn_uuid=str(uuid.uuid4())
    await create_user(tg_id,body.get("username"),body.get("full_name",""),vpn_user_id,vpn_uuid)
    return web.json_response(await get_user(tg_id))

async def user_status(request):
    await auth(request)
    u=await get_user(int(request.match_info["telegram_id"]))
    if not u: raise web.HTTPNotFound()
    u["sub_token"]=sign_sub(u["vpn_user_id"])
    return web.json_response(u)

async def node_states(request):
    await auth(request)
    return web.json_response(await get_node_states())

async def get_stats(request):
    await auth(request)
    return web.json_response(await stats())

async def startup(app):
    await init_db()

app=web.Application()
app.on_startup.append(startup)
app.router.add_get("/health",health)
app.router.add_post("/users/ensure",ensure_user)
app.router.add_get("/users/{telegram_id}",user_status)
app.router.add_get("/nodes",node_states)
app.router.add_get("/stats",get_stats)
web.run_app(app,host="0.0.0.0",port=8081)
