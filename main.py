import asyncio
import json
import os
import hashlib
import secrets
import time
import aiofiles
import psutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote
from collections import deque, defaultdict
from pathlib import Path
import socket
import base64
from io import BytesIO
import httpx

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

# ─── تنظیمات ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Eagle-Gateway")

IRAN_TZ = ZoneInfo("Asia/Tehran")

CONFIG = {
    "port": int(os.environ.get("PORT", 8000)),
    "secret": os.environ.get("SECRET_KEY", secrets.token_urlsafe(32)),
    "host": os.environ.get("RAILWAY_PUBLIC_DOMAIN", os.environ.get("RENDER_EXTERNAL_URL", "localhost")),
    "admin_password": os.environ.get("ADMIN_PASSWORD", "123456"),
}

app = FastAPI(title="🪐 Eagle Gateway v10 Pro", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ─── State ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "eagle_state.json"
SAVE_LOCK = asyncio.Lock()

LINKS: dict = {}
LINKS_LOCK = asyncio.Lock()
SUBS: dict = {}
SUBS_LOCK = asyncio.Lock()
connections: dict = {}
stats = {"total_bytes": 0, "total_requests": 0, "total_errors": 0, "start_time": time.time()}
error_logs: deque = deque(maxlen=50)
activity_logs: deque = deque(maxlen=200)
hourly_traffic: dict = defaultdict(int)
daily_traffic: dict = defaultdict(int)
device_connections: dict = {}
DEVICE_CONNECTIONS_LOCK = asyncio.Lock()
http_client: httpx.AsyncClient | None = None

# ─── Auth ──────────────────────────────────────────────────────────────────────
SESSION_COOKIE = "eagle_session"
SESSION_TTL = 60 * 60 * 24 * 7
AUTH = {"password_hash": hashlib.sha256(f"{CONFIG['admin_password']}{CONFIG['secret']}".encode()).hexdigest()}
SESSIONS: dict = {}
SESSIONS_LOCK = asyncio.Lock()

SETTINGS: dict = {
    "rgb_mode": False, "default_protocol": "vless-ws", "default_port": 443,
    "inbound_port": 443, "language": "fa", "theme": "dark",
    "telegram_bot_token": "", "telegram_chat_id": "",
}

PROTOCOLS = ("vless-ws", "xhttp-packet-up", "xhttp-stream-up", "xhttp-stream-one")
DEFAULT_PROTOCOL = "vless-ws"
DEFAULT_PORTS = [443, 8443, 2053, 2096, 2087, 2083, 8080]

FINGERPRINTS = {
    "chrome": "🌐 Chrome", "firefox": "🦊 Firefox", "safari": "🧭 Safari",
    "edge": "🌊 Edge", "ios": "📱 iOS", "android": "🤖 Android",
    "safari_ios": "🍏 Safari iOS", "random": "🎲 Random", "none": "🚫 None"
}

# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_SESSIONS: dict = {}
TELEGRAM_SESSIONS_LOCK = asyncio.Lock()
CACHE_USERS = {"data": [], "timestamp": 0, "ttl": 3}

# ─────────────────────────────────────────────────────────────────────────────
# ===== Functions =====
# ─────────────────────────────────────────────────────────────────────────────

def now_ir() -> datetime:
    return datetime.now(IRAN_TZ)

def hash_password(pw: str) -> str:
    return hashlib.sha256(f"{pw}{CONFIG['secret']}".encode()).hexdigest()

def generate_uuid() -> str:
    h = secrets.token_hex(16)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

def get_host() -> str:
    return os.environ.get("RAILWAY_PUBLIC_DOMAIN", os.environ.get("RENDER_EXTERNAL_URL", CONFIG["host"]))

def fmt_bytes(b: int) -> str:
    if not b or b == 0:
        return "0 B"
    if b < 1024:
        return f"{b} B"
    if b < 1024**2:
        return f"{b/1024:.1f} KB"
    if b < 1024**3:
        return f"{b/1024**2:.2f} MB"
    if b < 1024**4:
        return f"{b/1024**3:.2f} GB"
    return f"{b/1024**4:.2f} TB"

def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else request.client.host if request.client else "نامشخص"

def uptime() -> str:
    secs = int(time.time() - stats["start_time"])
    return f"{secs//3600:02d}:{(secs%3600)//60:02d}:{secs%60:02d}"

def parse_size_to_bytes(value: float, unit: str) -> int:
    unit = unit.upper()
    if unit == "GB":
        return int(value * 1024 ** 3)
    if unit == "MB":
        return int(value * 1024 ** 2)
    if unit == "KB":
        return int(value * 1024)
    return int(value)

def is_link_expired(link: dict) -> bool:
    exp = link.get("expires_at")
    if not exp:
        return False
    try:
        return datetime.now() > datetime.fromisoformat(exp)
    except:
        return False

def is_link_allowed(link: dict | None) -> bool:
    if link is None:
        return False
    if not link.get("active", True):
        return False
    if is_link_expired(link):
        return False
    lb = link.get("limit_bytes", 0)
    if lb > 0 and link.get("used_bytes", 0) >= lb:
        return False
    return True

def generate_vless_link(uuid: str, host: str, remark: str = "", protocol: str = DEFAULT_PROTOCOL,
                        fingerprint: str = "chrome", port: int = 443, sni: str = None) -> str:
    if not remark:
        remark = "عقاب"
    sni = sni or host
    if protocol == "vless-ws":
        path = f"/ws/{uuid}"
        params = {"encryption": "none", "security": "tls", "type": "ws", "host": host,
                  "path": path, "sni": sni, "fp": fingerprint, "alpn": "h2,http/1.1"}
    else:
        mode = protocol.replace("xhttp-", "")
        path = f"/xhttp-siz10/{mode}/{uuid}"
        params = {"encryption": "none", "security": "tls", "type": "xhttp", "mode": mode,
                  "host": host, "path": path, "sni": sni, "fp": fingerprint, "alpn": "h2,http/1.1"}
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"vless://{uuid}@{host}:{port}?{query}#{quote(remark)}"

def log_activity(kind: str, message: str, level: str = "info"):
    activity_logs.append({"kind": kind, "level": level, "message": message, "time": datetime.now().isoformat()})

async def remove_device_connection(uuid: str, client_ip: str):
    async with DEVICE_CONNECTIONS_LOCK:
        if uuid in device_connections and client_ip in device_connections[uuid]:
            device_connections[uuid].remove(client_ip)
            if not device_connections[uuid]:
                del device_connections[uuid]

# ─── Telegram Functions ──────────────────────────────────────────────────────

async def tg_send(chat_id, text, kb=None):
    token = SETTINGS.get("telegram_bot_token", "")
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb:
        payload["reply_markup"] = json.dumps({"inline_keyboard": kb})
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(url, json=payload)
            return r.status_code == 200
    except:
        return False

async def tg_doc(chat_id, content, filename):
    token = SETTINGS.get("telegram_bot_token", "")
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, data={"chat_id": chat_id}, files={"document": (filename, BytesIO(content.encode()), "text/plain")})
            return r.status_code == 200
    except:
        return False

async def tg_answer(cb_id):
    token = SETTINGS.get("telegram_bot_token", "")
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            await client.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id})
    except:
        pass

async def setup_webhook():
    token = SETTINGS.get("telegram_bot_token", "")
    if not token:
        return
    host = get_host()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url": f"https://{host}/webhook/telegram"})
            logger.info("✅ Webhook set")
    except:
        pass

# ─── Session ──────────────────────────────────────────────────────────────────

async def create_session() -> str:
    token = secrets.token_urlsafe(32)
    async with SESSIONS_LOCK:
        SESSIONS[token] = time.time() + SESSION_TTL
    return token

async def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    async with SESSIONS_LOCK:
        exp = SESSIONS.get(token)
        if exp is None or exp < time.time():
            SESSIONS.pop(token, None)
            return False
        return True

async def destroy_session(token: str | None):
    if token:
        async with SESSIONS_LOCK:
            SESSIONS.pop(token, None)

async def require_auth(request: Request):
    if not await is_valid_session(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="unauthorized")
    return request.cookies.get(SESSION_COOKIE)

# ─── State ────────────────────────────────────────────────────────────────────

async def load_state():
    global LINKS, SUBS, AUTH, SETTINGS
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            async with aiofiles.open(DATA_FILE, "r") as f:
                data = json.loads(await f.read())
            LINKS.update(data.get("links", {}))
            SUBS.update(data.get("subs", {}))
            AUTH["password_hash"] = data.get("password_hash", AUTH["password_hash"])
            SETTINGS.update(data.get("settings", {}))
            daily_traffic.update(data.get("daily_traffic", {}))
            logger.info(f"📂 Loaded: {len(LINKS)} links")
    except Exception as e:
        logger.warning(f"Load state error: {e}")

async def save_state():
    async with SAVE_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {"links": dict(LINKS), "subs": dict(SUBS), "password_hash": AUTH["password_hash"],
                    "settings": SETTINGS, "daily_traffic": dict(daily_traffic), "saved_at": datetime.now().isoformat()}
            async with aiofiles.open(DATA_FILE, "w") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Save error: {e}")

# ─── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global http_client
    http_client = httpx.AsyncClient(timeout=10.0)
    await load_state()
    await setup_webhook()
    logger.info(f"🪐 Eagle Gateway started on port {CONFIG['port']}")

@app.on_event("shutdown")
async def shutdown():
    await save_state()
    if http_client:
        await http_client.aclose()

# ─── API ENDPOINTS (خلاصه) ──────────────────────────────────────────────────

@app.post("/api/settings/language")
async def set_language(req: Request, _=Depends(require_auth)):
    body = await req.json()
    lang = body.get("language", "fa")
    if lang in ["fa", "en"]:
        SETTINGS["language"] = lang
        await save_state()
        return {"ok": True}
    raise HTTPException(400, "زبان نامعتبر")

@app.get("/api/language")
async def get_language():
    return {"language": SETTINGS.get("language", "fa")}

@app.post("/api/settings/theme")
async def set_theme(req: Request, _=Depends(require_auth)):
    body = await req.json()
    theme = body.get("theme", "dark")
    if theme in ["dark", "light"]:
        SETTINGS["theme"] = theme
        await save_state()
        return {"ok": True}
    raise HTTPException(400, "تم نامعتبر")

@app.post("/api/change-password")
async def change_password(req: Request, _=Depends(require_auth)):
    body = await req.json()
    old, new = body.get("old_password", "").strip(), body.get("new_password", "").strip()
    if not old or not new or len(new) < 4:
        raise HTTPException(400, "رمز جدید حداقل 4 کاراکتر")
    if hash_password(old) != AUTH["password_hash"]:
        raise HTTPException(403, "رمز فعلی اشتباه")
    AUTH["password_hash"] = hash_password(new)
    CONFIG["admin_password"] = new
    os.environ["ADMIN_PASSWORD"] = new
    await save_state()
    return {"ok": True}

@app.get("/api/settings")
async def get_settings(_=Depends(require_auth)):
    return SETTINGS

@app.post("/api/settings/rgb")
async def toggle_rgb(req: Request, _=Depends(require_auth)):
    body = await req.json()
    SETTINGS["rgb_mode"] = bool(body.get("enabled", False))
    await save_state()
    return {"rgb_mode": SETTINGS["rgb_mode"]}

@app.post("/api/settings/telegram")
async def set_telegram(req: Request, _=Depends(require_auth)):
    body = await req.json()
    if body.get("token"):
        SETTINGS["telegram_bot_token"] = body["token"].strip()
    if body.get("chat_id"):
        SETTINGS["telegram_chat_id"] = body["chat_id"].strip()
    await save_state()
    await setup_webhook()
    return {"ok": True}

@app.post("/api/telegram/test")
async def test_telegram(_=Depends(require_auth)):
    chat_id = SETTINGS.get("telegram_chat_id")
    if not chat_id:
        return {"ok": False, "message": "Chat ID تنظیم نشده"}
    result = await tg_send(chat_id, "✅ تست اتصال موفق!")
    return {"ok": result, "message": "ارسال شد" if result else "خطا"}

@app.get("/api/telegram/status")
async def get_telegram_status(_=Depends(require_auth)):
    token, chat_id = SETTINGS.get("telegram_bot_token", ""), SETTINGS.get("telegram_chat_id", "")
    return {"active": bool(token and chat_id), "has_token": bool(token), "has_chat_id": bool(chat_id),
            "token_preview": token[:10] + "..." if len(token) > 10 else token, "chat_id": chat_id}

@app.get("/api/dashboard/stats")
async def dashboard_stats(_=Depends(require_auth)):
    disk = psutil.disk_usage('/')
    speed = 0
    if len(hourly_traffic) > 0:
        speed = sum(list(hourly_traffic.values())[-6:]) / 21600
    today = daily_traffic.get(now_ir().strftime("%Y-%m-%d"), 0)
    return {
        "traffic": {"total": stats["total_bytes"], "total_fmt": fmt_bytes(stats["total_bytes"]),
                    "today": today, "today_fmt": fmt_bytes(today)},
        "requests": stats["total_requests"], "uptime": uptime(),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free,
                 "total_fmt": fmt_bytes(disk.total), "used_fmt": fmt_bytes(disk.used), "free_fmt": fmt_bytes(disk.free),
                 "percent": disk.percent},
        "connections": len(connections),
        "speed": {"download": speed, "download_fmt": fmt_bytes(speed) + "/s" if speed > 0 else "0 B/s"},
        "links_count": len(LINKS), "active_links": sum(1 for l in LINKS.values() if is_link_allowed(l))
    }

@app.get("/api/inbound")
async def get_inbound(_=Depends(require_auth)):
    return {"port": SETTINGS.get("inbound_port", 443), "protocol": SETTINGS.get("default_protocol", "vless"),
            "host": get_host(), "is_active": True}

@app.post("/api/inbound")
async def update_inbound(req: Request, _=Depends(require_auth)):
    body = await req.json()
    port = body.get("port", 443)
    if port < 1 or port > 65535:
        raise HTTPException(400, "پورت نامعتبر")
    SETTINGS["inbound_port"] = port
    await save_state()
    return {"ok": True}

@app.post("/api/links")
async def create_link(req: Request, _=Depends(require_auth)):
    body = await req.json()
    label = (body.get("label") or "کاربر").strip()[:60]
    quota = float(body.get("limit_value") or 0)
    limit_bytes = 0 if quota <= 0 else parse_size_to_bytes(quota, "GB")
    exp_days = int(body.get("expires_days") or 30)
    expires_at = (datetime.now() + timedelta(days=exp_days)).isoformat() if exp_days > 0 else None
    protocol = body.get("protocol") or DEFAULT_PROTOCOL
    if protocol not in PROTOCOLS:
        protocol = DEFAULT_PROTOCOL
    max_devices = int(body.get("max_devices", 0))
    fingerprint = body.get("fingerprint", "chrome")
    if fingerprint not in FINGERPRINTS:
        fingerprint = "chrome"
    password_hash = hash_password(body.get("password", "").strip()) if body.get("password") else None
    ports = body.get("ports", [443])
    if not isinstance(ports, list) or not ports:
        ports = [443]
    ports = [p for p in ports if isinstance(p, int) and 1 <= p <= 65535] or [443]

    uid = generate_uuid()
    async with LINKS_LOCK:
        LINKS[uid] = {"label": label, "limit_bytes": limit_bytes, "used_bytes": 0,
                      "created_at": datetime.now().isoformat(), "active": True,
                      "expires_at": expires_at, "note": "", "is_default": False, "sub_id": None,
                      "protocol": protocol, "max_devices": max_devices, "fingerprint": fingerprint,
                      "password_hash": password_hash, "ports": ports}
    asyncio.create_task(save_state())
    log_activity("link", f"کانفیگ «{label}» ساخته شد", "ok")
    host = get_host()
    main_link = generate_vless_link(uid, host, remark=f"عقاب-{label}", protocol=protocol, fingerprint=fingerprint, port=ports[0])
    return {"uuid": uid, **LINKS[uid], "has_password": password_hash is not None,
            "vless_link": main_link, "sub_url": f"https://{host}/sub/{uid}"}

@app.get("/api/links")
async def list_links(_=Depends(require_auth)):
    host = get_host()
    async with LINKS_LOCK:
        result = []
        for uid, d in LINKS.items():
            ports = d.get("ports", [443])
            first_port = ports[0] if ports else 443
            active = d.get("active", True) and not is_link_expired(d)
            last_connected = None
            for c in connections.values():
                if c.get("uuid") == uid and (not last_connected or c.get("connected_at") > last_connected):
                    last_connected = c.get("connected_at")
            result.append({"uuid": uid, **d, "ports": ports, "expired": is_link_expired(d),
                           "has_password": d.get("password_hash") is not None,
                           "last_connected_at": last_connected, "vless_link": generate_vless_link(
                               uid, host, remark=f"عقاب-{d.get('label','کاربر')}",
                               protocol=d.get("protocol", DEFAULT_PROTOCOL),
                               fingerprint=d.get("fingerprint", "chrome"), port=first_port),
                           "sub_url": f"https://{host}/sub/{uid}"})
        result.sort(key=lambda x: x["created_at"], reverse=True)
        return {"links": result}

@app.patch("/api/links/{uid}")
async def update_link(uid: str, req: Request, _=Depends(require_auth)):
    body = await req.json()
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(404, "link not found")
        link = LINKS[uid]
        if link.get("password_hash"):
            pw = body.get("password", "").strip()
            if not pw or hash_password(pw) != link["password_hash"]:
                raise HTTPException(403, "رمز کانفیگ اشتباه است")
        if "label" in body:
            link["label"] = str(body["label"])[:60]
        if "limit_value" in body:
            lv = float(body["limit_value"] or 0)
            link["limit_bytes"] = 0 if lv <= 0 else parse_size_to_bytes(lv, "GB")
        if "expires_days" in body:
            ed = int(body["expires_days"] or 0)
            link["expires_at"] = (datetime.now() + timedelta(days=ed)).isoformat() if ed > 0 else None
        if "max_devices" in body:
            link["max_devices"] = int(body["max_devices"])
        if "fingerprint" in body and body["fingerprint"] in FINGERPRINTS:
            link["fingerprint"] = body["fingerprint"]
        if "active" in body:
            link["active"] = bool(body["active"])
        if "reset_usage" in body and body["reset_usage"]:
            link["used_bytes"] = 0
        if "ports" in body and isinstance(body["ports"], list):
            ports = [p for p in body["ports"] if isinstance(p, int) and 1 <= p <= 65535]
            if ports:
                link["ports"] = ports
    asyncio.create_task(save_state())
    return {"ok": True}

@app.delete("/api/links/{uid}")
async def delete_link(uid: str, req: Request, _=Depends(require_auth)):
    body = await req.json()
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(404, "link not found")
        link = LINKS[uid]
        if link.get("password_hash"):
            pw = body.get("password", "").strip()
            if not pw or hash_password(pw) != link["password_hash"]:
                raise HTTPException(403, "رمز کانفیگ اشتباه است")
        label = link.get("label", uid)
        del LINKS[uid]
    asyncio.create_task(save_state())
    log_activity("link", f"کانفیگ «{label}» حذف شد", "err")
    return {"ok": True}

@app.get("/stats")
async def get_stats(_=Depends(require_auth)):
    async with LINKS_LOCK:
        return {"active_connections": len(connections), "total_traffic_mb": round(stats["total_bytes"] / (1024**2), 2),
                "total_requests": stats["total_requests"], "total_errors": stats["total_errors"],
                "uptime": uptime(), "links_count": len(LINKS),
                "active_links": sum(1 for l in LINKS.values() if is_link_allowed(l))}

@app.get("/api/connections")
async def get_connections(_=Depends(require_auth)):
    async with LINKS_LOCK:
        snap = dict(LINKS)
    grouped = {}
    for c in connections.values():
        ip = c.get("ip", "نامشخص")
        link = snap.get(c.get("uuid"))
        label = link.get("label") if link else "نامشخص"
        if ip not in grouped:
            grouped[ip] = {"ip": ip, "sessions": 0, "bytes": 0, "labels": set(), "first_connected_at": c.get("connected_at"),
                           "last_connected_at": c.get("connected_at")}
        g = grouped[ip]
        g["sessions"] += 1
        g["bytes"] += c.get("bytes", 0)
        g["labels"].add(label)
        if c.get("connected_at"):
            if not g["first_connected_at"] or c["connected_at"] < g["first_connected_at"]:
                g["first_connected_at"] = c["connected_at"]
            if not g["last_connected_at"] or c["connected_at"] > g["last_connected_at"]:
                g["last_connected_at"] = c["connected_at"]
    result = [{"ip": ip, "sessions": g["sessions"], "labels": sorted(g["labels"]),
               "label": " · ".join(sorted(g["labels"])) if g["labels"] else "نامشخص",
               "bytes": g["bytes"], "bytes_fmt": fmt_bytes(g["bytes"]),
               "connected_at": g["first_connected_at"], "last_connected_at": g["last_connected_at"]}
              for ip, g in grouped.items()]
    result.sort(key=lambda x: x.get("last_connected_at") or "", reverse=True)
    return {"connections": result, "count": len(result)}

@app.post("/api/login")
async def api_login(req: Request):
    body = await req.json()
    if hash_password(str(body.get("password", ""))) != AUTH["password_hash"]:
        raise HTTPException(401, "رمز عبور اشتباه است")
    token = await create_session()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL if body.get("remember") else None, httponly=True, samesite="lax", path="/")
    return resp

@app.post("/api/logout")
async def api_logout(req: Request):
    await destroy_session(req.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp

@app.get("/api/me")
async def api_me(req: Request):
    return {"authenticated": await is_valid_session(req.cookies.get(SESSION_COOKIE))}

@app.get("/api/activity")
async def get_activity(_=Depends(require_auth)):
    return {"logs": list(activity_logs)[-100:]}

@app.get("/api/backup")
async def get_backup(_=Depends(require_auth)):
    async with LINKS_LOCK:
        return {"links": dict(LINKS), "subs": dict(SUBS), "password_hash": AUTH["password_hash"],
                "settings": SETTINGS, "daily_traffic": dict(daily_traffic), "version": "10.0"}

@app.post("/api/backup/restore")
async def restore_backup(req: Request, _=Depends(require_auth)):
    body = await req.json()
    if "links" in body:
        async with LINKS_LOCK:
            LINKS.clear()
            for uid, data in body["links"].items():
                if isinstance(data, dict):
                    LINKS[uid] = data
    if "settings" in body:
        SETTINGS.update(body["settings"])
    await save_state()
    return {"ok": True}

# ─── WebSocket Tunnel ──────────────────────────────────────────────────────

RELAY_BUF = 512 * 1024

def _ws_ip(ws):
    fwd = ws.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else ws.client.host if ws.client else "نامشخص"

async def check_device_limit(uuid: str, client_ip: str) -> bool:
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
        if not link or link.get("max_devices", 0) == 0:
            return True
        max_devices = link["max_devices"]
    async with DEVICE_CONNECTIONS_LOCK:
        current = device_connections.get(uuid, [])
        if client_ip in current:
            return True
        if len(current) >= max_devices:
            return False
        device_connections.setdefault(uuid, []).append(client_ip)
        return True

async def parse_vless_header(chunk: bytes):
    if len(chunk) < 24:
        raise ValueError("chunk too small")
    pos = 1 + 16
    addon_len = chunk[pos]
    pos += 1 + addon_len
    command = chunk[pos]
    pos += 1
    port = int.from_bytes(chunk[pos:pos+2], "big")
    pos += 2
    addr_type = chunk[pos]
    pos += 1
    if addr_type == 1:
        address = ".".join(str(b) for b in chunk[pos:pos+4])
        pos += 4
    elif addr_type == 2:
        dlen = chunk[pos]
        pos += 1
        address = chunk[pos:pos+dlen].decode("utf-8", errors="ignore")
        pos += dlen
    elif addr_type == 3:
        ab = chunk[pos:pos+16]
        pos += 16
        address = ":".join(f"{ab[i]:02x}{ab[i+1]:02x}" for i in range(0, 16, 2))
    else:
        raise ValueError(f"unknown addr type: {addr_type}")
    return command, address, port, chunk[pos:]

async def check_and_use(uid: str, n: int) -> bool:
    async with LINKS_LOCK:
        link = LINKS.get(uid)
        if not link or not is_link_allowed(link):
            return False
        link["used_bytes"] = link.get("used_bytes", 0) + n
        stats["total_bytes"] = stats.get("total_bytes", 0) + n
        hourly_traffic[now_ir().strftime("%H:00")] = hourly_traffic.get(now_ir().strftime("%H:00"), 0) + n
        daily_traffic[now_ir().strftime("%Y-%m-%d")] = daily_traffic.get(now_ir().strftime("%Y-%m-%d"), 0) + n
        limit = link.get("limit_bytes", 0)
        used = link.get("used_bytes", 0)
        if limit > 0 and used / limit > 0.8 and not link.get("alert_80"):
            link["alert_80"] = True
            log_activity("warning", f"⚠️ مصرف {link.get('label')} به 80% رسید", "warn")
            chat_id = SETTINGS.get("telegram_chat_id")
            if chat_id:
                await tg_send(chat_id, f"⚠️ هشدار مصرف!\nکاربر: {link.get('label')}\nمصرف: {fmt_bytes(used)} / {fmt_bytes(limit)}")
        return True

async def relay_ws_to_tcp(ws, writer, conn_id, uid):
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            if not data:
                continue
            if not await check_and_use(uid, len(data)):
                await ws.close(code=1008, reason="quota/disabled")
                break
            stats["total_requests"] = stats.get("total_requests", 0) + 1
            if conn_id in connections:
                connections[conn_id]["bytes"] = connections[conn_id].get("bytes", 0) + len(data)
            writer.write(data)
            if writer.transport.get_write_buffer_size() > RELAY_BUF:
                await writer.drain()
    except:
        pass
    finally:
        try:
            writer.write_eof()
        except:
            pass

async def relay_tcp_to_ws(ws, reader, conn_id, uid):
    first = True
    try:
        while True:
            data = await reader.read(RELAY_BUF)
            if not data:
                break
            if not await check_and_use(uid, len(data)):
                await ws.close(code=1008, reason="quota/disabled")
                break
            if conn_id in connections:
                connections[conn_id]["bytes"] = connections[conn_id].get("bytes", 0) + len(data)
            payload = (b"\x00\x00" + data) if first else data
            first = False
            await ws.send_bytes(payload)
    except:
        pass

@app.websocket("/ws/{uuid}")
async def websocket_tunnel(ws: WebSocket, uuid: str):
    await ws.accept()
    client_ip = _ws_ip(ws)
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        await ws.close(code=1008, reason="user not found")
        return
    if not is_link_allowed(link):
        await ws.close(code=1008, reason="not authorized")
        return
    if link.get("max_devices", 0) > 0 and not await check_device_limit(uuid, client_ip):
        await ws.close(code=1008, reason="device limit exceeded")
        return

    conn_id = secrets.token_urlsafe(6)
    connections[conn_id] = {"uuid": uuid, "ip": client_ip, "transport": "vless-ws",
                            "connected_at": datetime.now().isoformat(), "bytes": 0}
    writer = None

    try:
        first_msg = await asyncio.wait_for(ws.receive(), timeout=15.0)
        if first_msg["type"] == "websocket.disconnect":
            return
        first_chunk = first_msg.get("bytes") or (first_msg.get("text") or "").encode()
        if not first_chunk:
            return
        command, address, port, payload = await parse_vless_header(first_chunk)
        if not await check_and_use(uuid, len(first_chunk)):
            await ws.close(code=1008, reason="quota/disabled")
            return
        stats["total_requests"] = stats.get("total_requests", 0) + 1
        if conn_id in connections:
            connections[conn_id]["bytes"] = connections[conn_id].get("bytes", 0) + len(first_chunk)

        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), timeout=10.0)
        if writer:
            sock = writer.transport.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if payload:
            writer.write(payload)
            await writer.drain()

        done, pending = await asyncio.wait(
            {asyncio.create_task(relay_ws_to_tcp(ws, writer, conn_id, uuid)),
             asyncio.create_task(relay_tcp_to_ws(ws, reader, conn_id, uuid))},
            return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except:
                pass
        asyncio.create_task(save_state())
    except:
        pass
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
        connections.pop(conn_id, None)
        await remove_device_connection(uuid, client_ip)

# ─── Subscriptions ─────────────────────────────────────────────────────────

@app.get("/sub/{uuid}")
async def subscription_single(req: Request, uuid: str):
    import base64
    ua = req.headers.get("user-agent", "").lower()
    is_browser = any(b in ua for b in ["chrome", "firefox", "safari", "edge", "opera", "brave", "msie", "trident"])
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        if is_browser:
            return HTMLResponse("""<html><body><h1>کاربر یافت نشد</h1></body></html>""", status_code=404)
        raise HTTPException(404, "user not found")
    if not is_link_allowed(link):
        if is_browser:
            return HTMLResponse("""<html><body><h1>کاربر غیرفعال</h1></body></html>""", status_code=403)
        raise HTTPException(403, "user disabled or expired")
    host = get_host()
    ports = link.get("ports", [443])
    vless_links = []
    for port in ports:
        remark = f"{link.get('label','کاربر')}-p{port}" if len(ports) > 1 else link.get('label', 'کاربر')
        vless_links.append(generate_vless_link(uuid, host, remark=remark,
                                               protocol=link.get("protocol", DEFAULT_PROTOCOL),
                                               fingerprint=link.get("fingerprint", "chrome"), port=port))
    if not is_browser:
        userinfo = f"upload=0&download={link.get('used_bytes',0)}&total={link.get('limit_bytes',0)}"
        try:
            if link.get("expires_at"):
                exp_ts = int(datetime.fromisoformat(link["expires_at"].replace('Z', '+00:00')).timestamp())
                userinfo += f"&expire={exp_ts}"
        except:
            pass
        content = base64.b64encode("\n".join(vless_links).encode()).decode()
        return Response(content=content, media_type="text/plain",
                        headers={"Subscription-Userinfo": userinfo,
                                 "profile-title": quote(link.get("label", "کاربر")),
                                 "profile-update-interval": "12"})
    from pages import get_sub_page_html
    active_conns = [c for c in connections.values() if c.get("uuid") == uuid]
    link_data = {**link, "expired": is_link_expired(link), "active_connections": len(active_conns),
                 "active_connections_list": active_conns, "vless_links": vless_links,
                 "vless_link": vless_links[0] if vless_links else "", "sub_url": f"https://{host}/sub/{uuid}"}
    return HTMLResponse(content=get_sub_page_html(uuid, link_data))

@app.get("/sub-all")
async def subscription_all(_=Depends(require_auth)):
    import base64
    host = get_host()
    async with LINKS_LOCK:
        lines = []
        for uid, d in LINKS.items():
            if is_link_allowed(d):
                for port in d.get("ports", [443]):
                    lines.append(generate_vless_link(uid, host,
                                 remark=f"عقاب-{d.get('label','کاربر')}",
                                 protocol=d.get("protocol", DEFAULT_PROTOCOL),
                                 fingerprint=d.get("fingerprint", "chrome"), port=port))
    return Response(content=base64.b64encode("\n".join(lines).encode()).decode(), media_type="text/plain")

@app.get("/info/{uuid}")
async def info_page(uuid: str, req: Request):
    from pages import get_sub_page_html
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        return HTMLResponse("""<html><body><h1>کاربر یافت نشد</h1></body></html>""", status_code=404)
    if not is_link_allowed(link):
        return HTMLResponse("""<html><body><h1>کاربر غیرفعال</h1></body></html>""", status_code=403)
    host = get_host()
    ports = link.get("ports", [443])
    vless_links = [generate_vless_link(uuid, host, remark=f"{link.get('label','کاربر')}-p{port}" if len(ports) > 1 else link.get('label','کاربر'),
                                       protocol=link.get("protocol", DEFAULT_PROTOCOL),
                                       fingerprint=link.get("fingerprint", "chrome"), port=port) for port in ports]
    active_conns = [c for c in connections.values() if c.get("uuid") == uuid]
    link_data = {**link, "expired": is_link_expired(link), "active_connections": len(active_conns),
                 "active_connections_list": active_conns, "vless_links": vless_links,
                 "vless_link": vless_links[0] if vless_links else "", "sub_url": f"https://{host}/sub/{uuid}"}
    return HTMLResponse(content=get_sub_page_html(uuid, link_data))

# ─── ===== BAT TELEGRAM (نسخه نهایی تست شده) ===== ─────────────────────────

@app.post("/webhook/telegram")
async def telegram_webhook(req: Request):
    token = SETTINGS.get("telegram_bot_token", "")
    if not token:
        return {"ok": False}
    try:
        body = await req.json()
        logger.info(f"📩 Webhook received")
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        return {"ok": False}
    
    asyncio.create_task(process_tg_update(body))
    return {"ok": True}

async def process_tg_update(body: dict):
    try:
        msg = body.get("message")
        cb = body.get("callback_query")
        
        if msg:
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "").strip()
            username = msg.get("from", {}).get("username", "کاربر")
            
            logger.info(f"📨 Message from {chat_id}: {text}")
            
            if text.startswith("/"):
                if text == "/start":
                    await send_main_menu(chat_id, username)
                elif text == "/new":
                    await start_new_user(chat_id)
                elif text == "/list":
                    await send_user_list(chat_id)
                elif text == "/edit":
                    await show_user_list_for_edit(chat_id)
                elif text.startswith("/config"):
                    parts = text.split()
                    if len(parts) > 1:
                        await send_user_config(chat_id, parts[1])
                    else:
                        await tg_send(chat_id, "❌ UUID را وارد کنید: /config UUID")
                elif text.startswith("/renew"):
                    parts = text.split()
                    if len(parts) > 1:
                        await renew_user(chat_id, parts[1])
                    else:
                        await tg_send(chat_id, "❌ UUID را وارد کنید: /renew UUID")
                elif text.startswith("/delete"):
                    parts = text.split()
                    if len(parts) > 1:
                        await delete_user(chat_id, parts[1])
                    else:
                        await tg_send(chat_id, "❌ UUID را وارد کنید: /delete UUID")
                else:
                    await tg_send(chat_id, "❌ دستور نامعتبر!", [[{"text": "🏠 منو", "callback_data": "main_menu"}]])
            else:
                # پیام متنی - بررسی سشن
                await handle_text_msg(chat_id, text, username)
                
        elif cb:
            chat_id = cb.get("message", {}).get("chat", {}).get("id")
            data = cb.get("data", "")
            username = cb.get("from", {}).get("username", "کاربر")
            cb_id = cb.get("id")
            
            logger.info(f"🔘 Callback from {chat_id}: {data}")
            
            await tg_answer(cb_id)
            await handle_callback(chat_id, data, username)
            
    except Exception as e:
        logger.error(f"TG process error: {e}")

async def send_main_menu(chat_id, username):
    clear_session(chat_id)
    kb = [
        [{"text": "📝 ساخت کاربر جدید", "callback_data": "new_user"}],
        [{"text": "📊 لیست کاربران", "callback_data": "list_users"}],
        [{"text": "✏️ ویرایش کاربر", "callback_data": "edit_user"}],
        [{"text": "📥 دریافت کانفیگ", "callback_data": "get_config"}],
        [{"text": "🔄 تمدید کاربر", "callback_data": "renew_user"}],
        [{"text": "❌ حذف کاربر", "callback_data": "delete_user"}]
    ]
    await tg_send(chat_id, f"🪐 <b>پنل عقاب</b>\n👤 {username}\n📅 {now_ir().strftime('%Y-%m-%d %H:%M')}", kb)

def clear_session(chat_id):
    async def _clear():
        async with TELEGRAM_SESSIONS_LOCK:
            if str(chat_id) in TELEGRAM_SESSIONS:
                del TELEGRAM_SESSIONS[str(chat_id)]
                logger.info(f"🧹 Session cleared for {chat_id}")
    asyncio.create_task(_clear())

async def handle_text_msg(chat_id, text, username):
    """پردازش پیام متنی کاربر"""
    async with TELEGRAM_SESSIONS_LOCK:
        session = TELEGRAM_SESSIONS.get(str(chat_id))
        logger.info(f"📋 Session for {chat_id}: {session}")
    
    if session and session.get("action") in ["creating_user", "editing_user"]:
        await handle_user_step(chat_id, text, session)
    else:
        await tg_send(chat_id, "❌ لطفاً از /new برای ساخت کاربر استفاده کنید.", 
                      [[{"text": "📝 ساخت کاربر", "callback_data": "new_user"}]])

async def handle_user_step(chat_id, text, session):
    action = session.get("action")
    step = session.get("step", "label")
    data = session.get("data", {})
    
    logger.info(f"🔄 Step: {step}, Action: {action}, Data: {data}")

    if step == "label":
        if len(text) < 2:
            await tg_send(chat_id, "❌ نام باید حداقل ۲ کاراکتر باشد.")
            return
        
        data["label"] = text.strip()
        async with TELEGRAM_SESSIONS_LOCK:
            TELEGRAM_SESSIONS[str(chat_id)]["step"] = "quota"
            TELEGRAM_SESSIONS[str(chat_id)]["data"] = data
        
        kb = [
            [{"text": "1GB", "callback_data": "quota_1"}, {"text": "2GB", "callback_data": "quota_2"}, {"text": "5GB", "callback_data": "quota_5"}],
            [{"text": "10GB", "callback_data": "quota_10"}, {"text": "20GB", "callback_data": "quota_20"}, {"text": "50GB", "callback_data": "quota_50"}],
            [{"text": "♾️ نامحدود", "callback_data": "quota_0"}, {"text": "✏️ عدد دلخواه", "callback_data": "quota_custom"}],
            [{"text": "❌ انصراف", "callback_data": "main_menu"}]
        ]
        await tg_send(chat_id, f"✅ نام <b>{data['label']}</b> ذخیره شد!\n📊 حجم را انتخاب کنید:", kb)

    elif step == "quota":
        try:
            quota = float(text.replace(",", "."))
            if quota < 0:
                await tg_send(chat_id, "❌ عدد منفی مجاز نیست.")
                return
            data["quota"] = quota
            async with TELEGRAM_SESSIONS_LOCK:
                TELEGRAM_SESSIONS[str(chat_id)]["step"] = "days"
            await tg_send(chat_id, f"✅ {quota}GB\n📅 تعداد روز انقضا را وارد کنید:")
        except ValueError:
            await tg_send(chat_id, "❌ عدد معتبر وارد کنید (مثلاً 15)")

    elif step == "days":
        try:
            days = int(text)
            if days <= 0:
                await tg_send(chat_id, "❌ روز باید بیشتر از 0 باشد.")
                return
            data["days"] = days
            async with TELEGRAM_SESSIONS_LOCK:
                TELEGRAM_SESSIONS[str(chat_id)]["step"] = "fingerprint"
            
            kb = [
                [{"text": "🌐 Chrome", "callback_data": "fp_chrome"}, {"text": "🦊 Firefox", "callback_data": "fp_firefox"}],
                [{"text": "🧭 Safari", "callback_data": "fp_safari"}, {"text": "📱 iOS", "callback_data": "fp_ios"}],
                [{"text": "🤖 Android", "callback_data": "fp_android"}, {"text": "🎲 Random", "callback_data": "fp_random"}],
                [{"text": "🚫 None", "callback_data": "fp_none"}]
            ]
            await tg_send(chat_id, f"✅ {days} روز\n🖐️ فینگرپرینت را انتخاب کنید:", kb)
        except ValueError:
            await tg_send(chat_id, "❌ عدد روز معتبر وارد کنید (مثلاً 30)")

async def finish_create_user(chat_id, data):
    try:
        label = data.get("label", "کاربر")
        quota = data.get("quota", 2)
        days = data.get("days", 30)
        fp = data.get("fingerprint", "chrome")

        uid = generate_uuid()
        async with LINKS_LOCK:
            LINKS[uid] = {
                "label": label,
                "limit_bytes": int(quota * 1024**3) if quota > 0 else 0,
                "used_bytes": 0,
                "created_at": datetime.now().isoformat(),
                "active": True,
                "expires_at": (datetime.now() + timedelta(days=days)).isoformat(),
                "note": "ساخته شده از بات",
                "is_default": False,
                "sub_id": None,
                "protocol": DEFAULT_PROTOCOL,
                "max_devices": 1,
                "fingerprint": fp,
                "password_hash": None,
                "ports": [443]
            }

        await save_state()
        log_activity("link", f"کاربر {label} از بات ساخته شد", "ok")

        host = get_host()
        sub_url = f"https://{host}/sub/{uid}"
        vless_link = generate_vless_link(uid, host, remark=f"عقاب-{label}", fingerprint=fp, port=443)

        clear_session(chat_id)

        kb = [[{"text": "📝 کاربر دیگر", "callback_data": "new_user"}, {"text": "🏠 منو", "callback_data": "main_menu"}]]
        await tg_send(chat_id,
            f"✅ <b>کاربر {label} ساخته شد!</b>\n\n"
            f"📊 حجم: {fmt_bytes(int(quota * 1024**3)) if quota > 0 else 'نامحدود'}\n"
            f"📅 انقضا: {days} روز\n"
            f"🖐️ FP: {fp}\n"
            f"🔗 ساب: <code>{sub_url}</code>\n"
            f"🔗 کانفیگ: <code>{vless_link}</code>", kb)
            
    except Exception as e:
        logger.error(f"Finish create error: {e}")
        await tg_send(chat_id, "❌ خطا در ساخت کاربر! لطفاً دوباره /new را بزنید.")
        clear_session(chat_id)

async def finish_edit_user(chat_id, data):
    try:
        uid = data.get("uid")
        label = data.get("label")
        quota = data.get("quota")
        days = data.get("days")
        fp = data.get("fingerprint")

        async with LINKS_LOCK:
            if uid not in LINKS:
                await tg_send(chat_id, "❌ کاربر یافت نشد!")
                return
            link = LINKS[uid]
            link["label"] = label
            link["limit_bytes"] = int(quota * 1024**3) if quota > 0 else 0
            link["expires_at"] = (datetime.now() + timedelta(days=days)).isoformat()
            link["fingerprint"] = fp
            link["active"] = True

        await save_state()
        log_activity("link", f"کاربر {label} ویرایش شد", "ok")

        clear_session(chat_id)

        await tg_send(chat_id, f"✅ <b>کاربر {label} ویرایش شد!</b>",
                      [[{"text": "🏠 منو", "callback_data": "main_menu"}]])
    except Exception as e:
        logger.error(f"Finish edit error: {e}")
        await tg_send(chat_id, "❌ خطا در ویرایش کاربر!")
        clear_session(chat_id)

async def handle_callback(chat_id, data, username):
    if data == "main_menu":
        await send_main_menu(chat_id, username)

    elif data == "new_user":
        await start_new_user(chat_id)

    elif data == "list_users":
        await send_user_list(chat_id)

    elif data == "edit_user":
        await show_user_list_for_edit(chat_id)

    elif data == "get_config":
        await show_user_list_for_config(chat_id)

    elif data == "renew_user":
        await show_user_list_for_renew(chat_id)

    elif data == "delete_user":
        await show_user_list_for_delete(chat_id)

    elif data == "quota_custom":
        async with TELEGRAM_SESSIONS_LOCK:
            session = TELEGRAM_SESSIONS.get(str(chat_id))
            if session:
                session["step"] = "quota"
        await tg_send(chat_id, "✏️ عدد حجم را به <b>GB</b> وارد کنید:", [])

    elif data.startswith("quota_"):
        val = data.replace("quota_", "")
        quota = float(val)
        async with TELEGRAM_SESSIONS_LOCK:
            session = TELEGRAM_SESSIONS.get(str(chat_id))
            if session:
                session["data"]["quota"] = quota
                session["step"] = "days"
        await tg_send(chat_id, f"✅ {quota}GB\n📅 تعداد روز انقضا را وارد کنید:")

    elif data.startswith("fp_"):
        fp = data.replace("fp_", "")
        async with TELEGRAM_SESSIONS_LOCK:
            session = TELEGRAM_SESSIONS.get(str(chat_id))
            if session:
                session["data"]["fingerprint"] = fp
                if session.get("action") == "editing_user":
                    await finish_edit_user(chat_id, session["data"])
                else:
                    await finish_create_user(chat_id, session["data"])

    elif data.startswith("select_edit_"):
        uid = data.replace("select_edit_", "")
        clear_session(chat_id)
        async with TELEGRAM_SESSIONS_LOCK:
            TELEGRAM_SESSIONS[str(chat_id)] = {"action": "editing_user", "step": "label", "data": {"uid": uid}}
        await tg_send(chat_id, "✏️ نام جدید را وارد کنید:", [[{"text": "❌ انصراف", "callback_data": "main_menu"}]])

    elif data.startswith("select_config_"):
        await send_user_config(chat_id, data.replace("select_config_", ""))

    elif data.startswith("select_renew_"):
        await renew_user(chat_id, data.replace("select_renew_", ""))

    elif data.startswith("select_delete_"):
        await delete_user(chat_id, data.replace("select_delete_", ""))

    elif data.startswith("list_page_"):
        await send_user_list(chat_id, int(data.replace("list_page_", "")))

    else:
        await tg_send(chat_id, "❌ گزینه نامعتبر!")

async def start_new_user(chat_id):
    clear_session(chat_id)
    async with TELEGRAM_SESSIONS_LOCK:
        TELEGRAM_SESSIONS[str(chat_id)] = {"action": "creating_user", "step": "label", "data": {}}
        logger.info(f"✅ Session created for {chat_id}")
    await tg_send(chat_id, "📝 نام کاربری را وارد کنید:", [[{"text": "❌ انصراف", "callback_data": "main_menu"}]])

async def get_cached_users():
    if time.time() - CACHE_USERS["timestamp"] < CACHE_USERS["ttl"]:
        return CACHE_USERS["data"]
    async with LINKS_LOCK:
        users = list(LINKS.items())
    CACHE_USERS["data"] = users
    CACHE_USERS["timestamp"] = time.time()
    return users

async def send_user_list(chat_id, page=0):
    users = await get_cached_users()
    if not users:
        await tg_send(chat_id, "📭 کاربری وجود ندارد!")
        return
    per_page, total = 5, (len(users) + 4) // 5
    start, end = page * per_page, min(start + per_page, len(users))
    msg = f"📊 کاربران ({page+1}/{total})\n\n"
    for uid, link in users[start:end]:
        label = link.get("label", "بدون نام")
        used, limit = link.get("used_bytes", 0), link.get("limit_bytes", 0)
        active = link.get("active", True) and not is_link_expired(link)
        msg += f"• <b>{label}</b>\n  مصرف: {fmt_bytes(used)} / {fmt_bytes(limit) if limit > 0 else '∞'}\n  وضعیت: {'🟢' if active else '🔴'}\n  UUID: <code>{uid[:8]}...</code>\n\n"
    kb = []
    nav = []
    if page > 0:
        nav.append({"text": "⬅️", "callback_data": f"list_page_{page-1}"})
    if page < total - 1:
        nav.append({"text": "➡️", "callback_data": f"list_page_{page+1}"})
    if nav:
        kb.append(nav)
    kb.append([{"text": "🏠 منو", "callback_data": "main_menu"}])
    await tg_send(chat_id, msg, kb)

async def show_user_list_for_config(chat_id):
    users = await get_cached_users()
    if not users:
        await tg_send(chat_id, "📭 کاربری وجود ندارد!")
        return
    kb = [[{"text": f"📥 {link.get('label','بدون نام')}", "callback_data": f"select_config_{uid}"}] for uid, link in users[:10]]
    kb.append([{"text": "🏠 منو", "callback_data": "main_menu"}])
    await tg_send(chat_id, "📥 کاربر را انتخاب کنید:", kb)

async def show_user_list_for_edit(chat_id):
    users = await get_cached_users()
    if not users:
        await tg_send(chat_id, "📭 کاربری وجود ندارد!")
        return
    kb = [[{"text": f"✏️ {link.get('label','بدون نام')}", "callback_data": f"select_edit_{uid}"}] for uid, link in users[:10]]
    kb.append([{"text": "🏠 منو", "callback_data": "main_menu"}])
    await tg_send(chat_id, "✏️ کاربر را برای ویرایش انتخاب کنید:", kb)

async def show_user_list_for_renew(chat_id):
    users = await get_cached_users()
    if not users:
        await tg_send(chat_id, "📭 کاربری وجود ندارد!")
        return
    kb = [[{"text": f"🔄 {link.get('label','بدون نام')}", "callback_data": f"select_renew_{uid}"}] for uid, link in users[:10]]
    kb.append([{"text": "🏠 منو", "callback_data": "main_menu"}])
    await tg_send(chat_id, "🔄 کاربر را برای تمدید انتخاب کنید:", kb)

async def show_user_list_for_delete(chat_id):
    users = await get_cached_users()
    if not users:
        await tg_send(chat_id, "📭 کاربری وجود ندارد!")
        return
    kb = [[{"text": f"❌ {link.get('label','بدون نام')}", "callback_data": f"select_delete_{uid}"}] for uid, link in users[:10]]
    kb.append([{"text": "🏠 منو", "callback_data": "main_menu"}])
    await tg_send(chat_id, "❌ کاربر را برای حذف انتخاب کنید:", kb)

async def send_user_config(chat_id, uuid):
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        await tg_send(chat_id, "❌ کاربر یافت نشد!")
        return
    host, label = get_host(), link.get("label", "کاربر")
    vless_links = [generate_vless_link(uuid, host, remark=label, fingerprint=link.get("fingerprint", "chrome"), port=port) for port in link.get("ports", [443])]
    await tg_doc(chat_id, "\n\n".join(vless_links), f"config_{uuid[:8]}.txt")
    await tg_send(chat_id, f"🔗 ساب: <code>https://{host}/sub/{uuid}</code>", [[{"text": "🏠 منو", "callback_data": "main_menu"}]])

async def renew_user(chat_id, uuid):
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        await tg_send(chat_id, "❌ کاربر یافت نشد!")
        return
    link["expires_at"] = (datetime.now() + timedelta(days=30)).isoformat()
    if link.get("limit_bytes", 0) > 0:
        link["limit_bytes"] += 5 * 1024**3
    link["active"] = True
    await save_state()
    await tg_send(chat_id, f"✅ {link.get('label')} تمدید شد!", [[{"text": "🏠 منو", "callback_data": "main_menu"}]])

async def delete_user(chat_id, uuid):
    async with LINKS_LOCK:
        if uuid not in LINKS:
            await tg_send(chat_id, "❌ کاربر یافت نشد!")
            return
        label = LINKS[uuid].get("label", "بدون نام")
        del LINKS[uuid]
    await save_state()
    await tg_send(chat_id, f"✅ {label} حذف شد!", [[{"text": "🏠 منو", "callback_data": "main_menu"}]])

# ─── HTML Pages ─────────────────────────────────────────────────────────────

from pages import LOGIN_HTML, DASHBOARD_HTML

@app.get("/login")
async def login_page(req: Request):
    if await is_valid_session(req.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url="/dashboard")
    return HTMLResponse(content=LOGIN_HTML)

@app.get("/dashboard")
async def dashboard(req: Request):
    if not await is_valid_session(req.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url="/login")
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/")
async def root():
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>🪐 Eagle Gateway</title>
    <style>body{font-family:sans-serif;background:#0a0a0f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
    .card{text-align:center;padding:40px;background:rgba(20,20,40,0.7);border-radius:20px;border:1px solid rgba(100,80,255,0.2)}
    h1{font-size:48px;margin:0}.sub{color:#888}a{color:#7C6BFF;text-decoration:none}</style></head>
    <body><div class="card"><h1>🪐</h1><h2>Eagle Gateway v10 Pro</h2><p class="sub">پنل مدیریت فیلترشکن</p><a href="/login">ورود →</a></div></body></html>""")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["port"], log_level="info", workers=1)
