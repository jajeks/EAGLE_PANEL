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

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import httpx
import logging

# ─── تنظیمات ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("Eagle-Gateway")

IRAN_TZ = ZoneInfo("Asia/Tehran")

# ─── کانفیگ ──────────────────────────────────────────────────────────────────
CONFIG = {
    "port": int(os.environ.get("PORT", 8000)),
    "secret": os.environ.get("SECRET_KEY", secrets.token_urlsafe(32)),
    "host": os.environ.get("RAILWAY_PUBLIC_DOMAIN", os.environ.get("RENDER_EXTERNAL_URL", "localhost")),
    "admin_password": os.environ.get("ADMIN_PASSWORD", "123456"),
}

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="🪐 Eagle Gateway v10 Pro", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── State ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "eagle_state.json"
SAVE_LOCK = asyncio.Lock()

# ─── In-Memory State ─────────────────────────────────────────────────────────
LINKS: dict = {}
LINKS_LOCK = asyncio.Lock()
SUBS: dict = {}
SUBS_LOCK = asyncio.Lock()
connections: dict = {}
stats = {
    "total_bytes": 0,
    "total_requests": 0,
    "total_errors": 0,
    "start_time": time.time(),
}
error_logs: deque = deque(maxlen=50)
activity_logs: deque = deque(maxlen=200)
hourly_traffic: dict = defaultdict(int)
device_connections: dict = {}
DEVICE_CONNECTIONS_LOCK = asyncio.Lock()
http_client: httpx.AsyncClient | None = None

# ─── Auth ──────────────────────────────────────────────────────────────────────
SESSION_COOKIE = "eagle_session"
SESSION_TTL = 60 * 60 * 24 * 7
AUTH = {"password_hash": hashlib.sha256(f"{CONFIG['admin_password']}{CONFIG['secret']}".encode()).hexdigest()}
SESSIONS: dict = {}
SESSIONS_LOCK = asyncio.Lock()

# ─── Settings ──────────────────────────────────────────────────────────────────
SETTINGS: dict = {
    "rgb_mode": False,
    "default_protocol": "vless-ws",
    "default_port": 443,
    "inbound_port": 443,
    "language": "fa",
    "theme": "dark",
}

PROTOCOLS = ("vless-ws", "xhttp-packet-up", "xhttp-stream-up", "xhttp-stream-one")
DEFAULT_PROTOCOL = "vless-ws"

# ─── ✅ لیست کامل فینگرپرینت‌ها ─────────────────────────────────────────────
FINGERPRINTS = {
    "chrome": "🌐 Chrome",
    "firefox": "🦊 Firefox",
    "safari": "🧭 Safari",
    "edge": "🌊 Edge",
    "ios": "📱 iOS",
    "android": "🤖 Android",
    "safari_ios": "🍏 Safari iOS",
    "random": "🎲 Random",
    "none": "🚫 None"
}

FINGERPRINT_EMOJI = {
    "chrome": "🌐",
    "firefox": "🦊",
    "safari": "🧭",
    "edge": "🌊",
    "ios": "📱",
    "android": "🤖",
    "safari_ios": "🍏",
    "random": "🎲",
    "none": "🚫"
}

# ─── Functions ─────────────────────────────────────────────────────────────────

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
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "نامشخص"

def uptime() -> str:
    secs = int(time.time() - stats["start_time"])
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

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
    except Exception:
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
                        fingerprint: str = "chrome", port: int = 443, 
                        sni: str = None) -> str:
    if not remark:
        remark = "عقاب"
    
    if not sni:
        sni = host
    
    if protocol == "vless-ws":
        path = f"/ws/{uuid}"
        params = {
            "encryption": "none",
            "security": "tls",
            "type": "ws",
            "host": host,
            "path": path,
            "sni": sni,
            "fp": fingerprint,
            "alpn": "h2,http/1.1",
        }
    else:
        mode = protocol.replace("xhttp-", "")
        path = f"/xhttp-siz10/{mode}/{uuid}"
        params = {
            "encryption": "none",
            "security": "tls",
            "type": "xhttp",
            "mode": mode,
            "host": host,
            "path": path,
            "sni": sni,
            "fp": fingerprint,
            "alpn": "h2,http/1.1",
        }
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"vless://{uuid}@{host}:{port}?{query}#{quote(remark)}"

def log_activity(kind: str, message: str, level: str = "info"):
    activity_logs.append({
        "kind": kind,
        "level": level,
        "message": message,
        "time": datetime.now().isoformat(),
    })

async def remove_device_connection(uuid: str, client_ip: str):
    async with DEVICE_CONNECTIONS_LOCK:
        if uuid in device_connections:
            if client_ip in device_connections[uuid]:
                device_connections[uuid].remove(client_ip)
                if not device_connections[uuid]:
                    del device_connections[uuid]

# ─── Session Functions ──────────────────────────────────────────────────────

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
        if exp is None:
            return False
        if exp < time.time():
            SESSIONS.pop(token, None)
            return False
        return True

async def destroy_session(token: str | None):
    if not token:
        return
    async with SESSIONS_LOCK:
        SESSIONS.pop(token, None)

async def require_auth(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not await is_valid_session(token):
        raise HTTPException(status_code=401, detail="unauthorized")
    return token

# ─── State Persistence ──────────────────────────────────────────────────────

async def load_state():
    global LINKS, SUBS, AUTH, SETTINGS
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            LINKS.update(data.get("links", {}))
            SUBS.update(data.get("subs", {}))
            if "password_hash" in data:
                AUTH["password_hash"] = data["password_hash"]
            if "settings" in data:
                SETTINGS.update(data["settings"])
            logger.info(f"📂 State loaded: {len(LINKS)} links, {len(SUBS)} subs")
    except Exception as e:
        logger.warning(f"Could not load state: {e}")

async def save_state():
    async with SAVE_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "links": dict(LINKS),
                "subs": dict(SUBS),
                "password_hash": AUTH["password_hash"],
                "settings": SETTINGS,
                "saved_at": datetime.now().isoformat(),
            }
            tmp = DATA_FILE.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            tmp.replace(DATA_FILE)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")

# ─── Startup / Shutdown ─────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global http_client
    limits = httpx.Limits(max_connections=500, max_keepalive_connections=100)
    timeout = httpx.Timeout(30.0, connect=10.0)
    http_client = httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True)
    await load_state()
    
    log_activity("system", "🪐 Eagle Gateway v10 Pro راه‌اندازی شد", "ok")
    logger.info(f"🪐 Eagle Gateway v10 Pro started on port {CONFIG['port']}")

@app.on_event("shutdown")
async def shutdown():
    await save_state()
    if http_client:
        await http_client.aclose()

# ─── ===== تغییر زبان ===== ──────────────────────────────────────────────────

@app.post("/api/settings/language")
async def set_language(request: Request, _=Depends(require_auth)):
    body = await request.json()
    lang = body.get("language", "fa")
    if lang in ["fa", "en"]:
        SETTINGS["language"] = lang
        await save_state()
        return {"ok": True, "language": lang}
    raise HTTPException(status_code=400, detail="زبان نامعتبر")

@app.get("/api/language")
async def get_language():
    return {"language": SETTINGS.get("language", "fa")}

# ─── ===== تغییر تم ===== ──────────────────────────────────────────────────

@app.post("/api/settings/theme")
async def set_theme(request: Request, _=Depends(require_auth)):
    body = await request.json()
    theme = body.get("theme", "dark")
    if theme in ["dark", "light"]:
        SETTINGS["theme"] = theme
        await save_state()
        return {"ok": True, "theme": theme}
    raise HTTPException(status_code=400, detail="تم نامعتبر")

# ─── ===== تغییر رمز پنل ===== ──────────────────────────────────────────────

@app.post("/api/change-password")
async def change_password(request: Request, _=Depends(require_auth)):
    body = await request.json()
    old = body.get("old_password", "").strip()
    new = body.get("new_password", "").strip()
    
    if not old or not new or len(new) < 4:
        raise HTTPException(400, "رمز جدید حداقل 4 کاراکتر")
    
    if hash_password(old) != AUTH["password_hash"]:
        raise HTTPException(403, "رمز فعلی اشتباه")
    
    AUTH["password_hash"] = hash_password(new)
    CONFIG["admin_password"] = new
    os.environ["ADMIN_PASSWORD"] = new
    
    await save_state()
    log_activity("settings", "رمز پنل تغییر کرد", "ok")
    
    return {"ok": True}

# ─── API: Settings ─────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings(_=Depends(require_auth)):
    return SETTINGS

@app.post("/api/settings/rgb")
async def toggle_rgb(request: Request, _=Depends(require_auth)):
    body = await request.json()
    SETTINGS["rgb_mode"] = bool(body.get("enabled", False))
    await save_state()
    return {"rgb_mode": SETTINGS["rgb_mode"]}

# ─── API: Dashboard Stats ──────────────────────────────────────────────────

@app.get("/api/dashboard/stats")
async def dashboard_stats(_=Depends(require_auth)):
    disk_usage = psutil.disk_usage('/')
    
    if len(hourly_traffic) > 0:
        last_hour = sum(list(hourly_traffic.values())[-6:])
        speed = last_hour / 21600
    else:
        speed = 0
    
    return {
        "traffic": {
            "total": stats["total_bytes"],
            "total_fmt": fmt_bytes(stats["total_bytes"]),
            "today": sum(hourly_traffic.values()),
            "today_fmt": fmt_bytes(sum(hourly_traffic.values()))
        },
        "requests": stats["total_requests"],
        "uptime": uptime(),
        "disk": {
            "total": disk_usage.total,
            "used": disk_usage.used,
            "free": disk_usage.free,
            "total_fmt": fmt_bytes(disk_usage.total),
            "used_fmt": fmt_bytes(disk_usage.used),
            "free_fmt": fmt_bytes(disk_usage.free),
            "percent": disk_usage.percent
        },
        "connections": len(connections),
        "speed": {
            "download": speed,
            "download_fmt": fmt_bytes(speed) + "/s" if speed > 0 else "0 B/s"
        },
        "links_count": len(LINKS),
        "active_links": sum(1 for l in LINKS.values() if is_link_allowed(l))
    }

# ─── API: Inbound ────────────────────────────────────────────────────────────

@app.get("/api/inbound")
async def get_inbound(_=Depends(require_auth)):
    return {
        "port": SETTINGS.get("inbound_port", 443),
        "protocol": SETTINGS.get("default_protocol", "vless"),
        "host": get_host(),
        "is_active": True
    }

@app.post("/api/inbound")
async def update_inbound(request: Request, _=Depends(require_auth)):
    body = await request.json()
    port = body.get("port", 443)
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="پورت نامعتبر")
    SETTINGS["inbound_port"] = port
    await save_state()
    return {"ok": True, "port": port}

# ─── API: Links ─────────────────────────────────────────────────────────────

@app.post("/api/links")
async def create_link(request: Request, _=Depends(require_auth)):
    body = await request.json()
    label = (body.get("label") or "لینک جدید").strip()[:60]
    lv = float(body.get("limit_value") or 0)
    lu = body.get("limit_unit") or "GB"
    limit_bytes = 0 if lv <= 0 else parse_size_to_bytes(lv, lu)
    exp_days = int(body.get("expires_days") or 0)
    expires_at = (datetime.now() + timedelta(days=exp_days)).isoformat() if exp_days > 0 else None
    note = (body.get("note") or "").strip()[:200]
    sub_id = body.get("sub_id") or None
    protocol = body.get("protocol") or DEFAULT_PROTOCOL
    if protocol not in PROTOCOLS:
        protocol = DEFAULT_PROTOCOL
    max_devices = int(body.get("max_devices", 0))
    fingerprint = body.get("fingerprint", "chrome")
    if fingerprint not in FINGERPRINTS:
        fingerprint = "chrome"
    config_password = body.get("password", "").strip()
    password_hash = hash_password(config_password) if config_password else None
    port = int(body.get("port", 443))
    if port < 1 or port > 65535:
        port = 443

    uid = generate_uuid()
    async with LINKS_LOCK:
        LINKS[uid] = {
            "label": label,
            "limit_bytes": limit_bytes,
            "used_bytes": 0,
            "created_at": datetime.now().isoformat(),
            "active": True,
            "expires_at": expires_at,
            "note": note,
            "is_default": False,
            "sub_id": sub_id,
            "protocol": protocol,
            "max_devices": max_devices,
            "fingerprint": fingerprint,
            "password_hash": password_hash,
            "port": port,
        }

    if sub_id:
        async with SUBS_LOCK:
            if sub_id in SUBS:
                ids = SUBS[sub_id].setdefault("link_ids", [])
                if uid not in ids:
                    ids.append(uid)

    asyncio.create_task(save_state())
    log_activity("link", f"کانفیگ «{label}» ساخته شد", "ok")
    host = get_host()
    
    remark = f"عقاب-{label}"
    main_link = generate_vless_link(uid, host, remark=remark, protocol=protocol, fingerprint=fingerprint, port=port)
    
    link_data = {
        "uuid": uid,
        **LINKS[uid],
        "has_password": password_hash is not None,
        "vless_link": main_link,
        "sub_url": f"https://{host}/sub/{uid}",
        "warning_config": "",
    }
    
    return link_data

@app.get("/api/links")
async def list_links(_=Depends(require_auth)):
    host = get_host()
    async with LINKS_LOCK:
        snap = dict(LINKS)
    
    result = []
    for uid, d in snap.items():
        proto = d.get("protocol", DEFAULT_PROTOCOL)
        fp = d.get("fingerprint", "chrome")
        port = d.get("port", 443)
        label = d.get("label", "کاربر")
        remark = f"عقاب-{label}"
        
        last_connected = None
        for c in connections.values():
            if c.get("uuid") == uid:
                if not last_connected or c.get("connected_at") > last_connected:
                    last_connected = c.get("connected_at")
        
        active = d.get("active", True) and not is_link_expired(d)
        
        result.append({
            "uuid": uid,
            **d,
            "protocol": proto,
            "fingerprint": fp,
            "max_devices": d.get("max_devices", 0),
            "expired": is_link_expired(d),
            "has_password": d.get("password_hash") is not None,
            "port": port,
            "last_connected_at": last_connected,
            "vless_link": generate_vless_link(uid, host, remark=remark, protocol=proto, fingerprint=fp, port=port),
            "sub_url": f"https://{host}/sub/{uid}",
            "warning_config": "",
        })
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return {"links": result}

@app.patch("/api/links/{uid}")
async def update_link(uid: str, request: Request, _=Depends(require_auth)):
    body = await request.json()
    
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(status_code=404, detail="link not found")
        link = LINKS[uid]
        
        if link.get("password_hash"):
            password = body.get("password", "").strip()
            if not password:
                raise HTTPException(status_code=403, detail="برای ویرایش این کانفیگ رمز آن را وارد کنید")
            if hash_password(password) != link["password_hash"]:
                raise HTTPException(status_code=403, detail="رمز کانفیگ اشتباه است")
        
        old_sub = link.get("sub_id")
        
        if "active" in body:
            link["active"] = bool(body["active"])
        if "label" in body:
            link["label"] = str(body["label"])[:60]
        if "note" in body:
            link["note"] = str(body["note"])[:200]
        if "reset_usage" in body and body["reset_usage"]:
            link["used_bytes"] = 0
        if "limit_value" in body:
            lv = float(body.get("limit_value") or 0)
            lu = body.get("limit_unit") or "GB"
            link["limit_bytes"] = 0 if lv <= 0 else parse_size_to_bytes(lv, lu)
        if "expires_days" in body:
            ed = int(body["expires_days"] or 0)
            link["expires_at"] = (datetime.now() + timedelta(days=ed)).isoformat() if ed > 0 else None
        if "max_devices" in body:
            link["max_devices"] = int(body["max_devices"])
        if "fingerprint" in body and body["fingerprint"] in FINGERPRINTS:
            link["fingerprint"] = body["fingerprint"]
        if "protocol" in body and body["protocol"] in PROTOCOLS:
            link["protocol"] = body["protocol"]
        if "port" in body:
            port = int(body["port"])
            if 1 <= port <= 65535:
                link["port"] = port
        new_sub = body.get("sub_id", "UNCHANGED")
        if new_sub != "UNCHANGED":
            link["sub_id"] = new_sub or None

    if new_sub != "UNCHANGED":
        async with SUBS_LOCK:
            if old_sub and old_sub in SUBS:
                ids = SUBS[old_sub].get("link_ids", [])
                if uid in ids:
                    ids.remove(uid)
            if new_sub and new_sub in SUBS:
                ids = SUBS[new_sub].setdefault("link_ids", [])
                if uid not in ids:
                    ids.append(uid)

    asyncio.create_task(save_state())
    log_activity("link", f"کانفیگ «{link['label']}» ویرایش شد", "info")
    return {"ok": True}

@app.delete("/api/links/{uid}")
async def delete_link(uid: str, request: Request, _=Depends(require_auth)):
    body = await request.json()
    password = body.get("password", "").strip()
    
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(status_code=404, detail="link not found")
        link = LINKS[uid]
        
        if link.get("password_hash"):
            if not password:
                raise HTTPException(status_code=403, detail="برای حذف این کانفیگ رمز آن را وارد کنید")
            if hash_password(password) != link["password_hash"]:
                raise HTTPException(status_code=403, detail="رمز کانفیگ اشتباه است")
        
        label = link.get("label", uid)
        sub_id = link.get("sub_id")
        del LINKS[uid]
    
    if sub_id:
        async with SUBS_LOCK:
            if sub_id in SUBS:
                ids = SUBS[sub_id].get("link_ids", [])
                if uid in ids:
                    ids.remove(uid)
    
    asyncio.create_task(save_state())
    log_activity("link", f"کانفیگ «{label}» حذف شد", "err")
    
    return {"ok": True, "deleted": uid}

# ─── API: Stats & Connections ──────────────────────────────────────────────

@app.get("/stats")
async def get_stats(_=Depends(require_auth)):
    async with LINKS_LOCK:
        snap = dict(LINKS)
    
    top_user = None
    top_usage = 0
    for uid, link in snap.items():
        used = link.get("used_bytes", 0)
        if used > top_usage:
            top_usage = used
            top_user = {
                "uuid": uid,
                "label": link.get("label", "نامشخص"),
                "used_bytes": used,
                "used_fmt": fmt_bytes(used)
            }
    
    return {
        "active_connections": len(connections),
        "total_traffic_mb": round(stats["total_bytes"] / (1024 ** 2), 2),
        "total_requests": stats["total_requests"],
        "total_errors": stats["total_errors"],
        "uptime": uptime(),
        "timestamp": datetime.now().isoformat(),
        "hourly": dict(hourly_traffic),
        "recent_errors": list(error_logs)[-10:],
        "links_count": len(snap),
        "active_links": sum(1 for l in snap.values() if is_link_allowed(l)),
        "expired_links": sum(1 for l in snap.values() if is_link_expired(l)),
        "subs_count": len(SUBS),
        "top_user": top_user,
    }

@app.get("/api/connections")
async def get_connections(_=Depends(require_auth)):
    async with LINKS_LOCK:
        snap = dict(LINKS)

    grouped: dict[str, dict] = {}
    for conn_id, c in connections.items():
        ip = c.get("ip", "نامشخص")
        link = snap.get(c.get("uuid"))
        label = link.get("label") if link else "نامشخص"
        g = grouped.get(ip)
        if g is None:
            g = {
                "ip": ip,
                "sessions": 0,
                "bytes": 0,
                "labels": set(),
                "transports": set(),
                "first_connected_at": c.get("connected_at"),
                "last_connected_at": c.get("connected_at"),
            }
            grouped[ip] = g
        g["sessions"] += 1
        g["bytes"] += c.get("bytes", 0)
        g["labels"].add(label)
        g["transports"].add(c.get("transport", "vless-ws"))
        ca = c.get("connected_at")
        if ca:
            if not g["first_connected_at"] or ca < g["first_connected_at"]:
                g["first_connected_at"] = ca
            if not g["last_connected_at"] or ca > g["last_connected_at"]:
                g["last_connected_at"] = ca

    result = []
    for ip, g in grouped.items():
        result.append({
            "ip": ip,
            "sessions": g["sessions"],
            "labels": sorted(g["labels"]),
            "label": " · ".join(sorted(g["labels"])) if g["labels"] else "نامشخص",
            "transports": sorted(g["transports"]),
            "bytes": g["bytes"],
            "bytes_fmt": fmt_bytes(g["bytes"]),
            "connected_at": g["first_connected_at"],
            "last_connected_at": g["last_connected_at"],
        })
    result.sort(key=lambda x: x.get("last_connected_at") or "", reverse=True)

    return {
        "connections": result,
        "count": len(result),
        "raw_count": len(connections),
    }

# ─── Auth Endpoints ────────────────────────────────────────────────────────

@app.post("/api/login")
async def api_login(request: Request):
    body = await request.json()
    ip = client_ip(request)
    password = body.get("password", "")
    remember = body.get("remember", False)
    
    if hash_password(str(password)) != AUTH["password_hash"]:
        log_activity("auth", f"تلاش ورود ناموفق از {ip}", "err")
        raise HTTPException(status_code=401, detail="رمز عبور اشتباه است")
    
    token = await create_session()
    log_activity("auth", f"ورود موفق به پنل از {ip}", "ok")
    
    max_age = SESSION_TTL if remember else None
    resp = JSONResponse({"ok": True})
    resp.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", path="/")
    return resp

@app.post("/api/logout")
async def api_logout(request: Request):
    await destroy_session(request.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp

@app.get("/api/me")
async def api_me(request: Request):
    return {"authenticated": await is_valid_session(request.cookies.get(SESSION_COOKIE))}

# ─── API: Activity Logs ───────────────────────────────────────────────────────

@app.get("/api/activity")
async def get_activity_logs(_=Depends(require_auth)):
    limit = 100
    logs = list(activity_logs)[-limit:]
    return {"logs": logs}

# ─── Backup ────────────────────────────────────────────────────────────────────

@app.get("/api/backup")
async def get_backup(_=Depends(require_auth)):
    async with LINKS_LOCK:
        links = dict(LINKS)
    async with SUBS_LOCK:
        subs = dict(SUBS)
    return {
        "links": links,
        "subs": subs,
        "password_hash": AUTH["password_hash"],
        "settings": SETTINGS,
        "exported_at": datetime.now().isoformat(),
        "version": "10.0"
    }

@app.post("/api/backup/restore")
async def restore_backup(request: Request, _=Depends(require_auth)):
    try:
        body = await request.json()
        
        if "links" in body and isinstance(body["links"], dict):
            async with LINKS_LOCK:
                LINKS.clear()
                for uid, link_data in body["links"].items():
                    if not isinstance(link_data, dict):
                        continue
                    LINKS[uid] = link_data
        
        if "subs" in body and isinstance(body["subs"], dict):
            async with SUBS_LOCK:
                SUBS.clear()
                for sid, sub_data in body["subs"].items():
                    if not isinstance(sub_data, dict):
                        continue
                    SUBS[sid] = sub_data
        
        if "password_hash" in body:
            AUTH["password_hash"] = body["password_hash"]
        
        if "settings" in body and isinstance(body["settings"], dict):
            SETTINGS.update(body["settings"])
        
        await save_state()
        log_activity("backup", "بکاپ بازیابی شد", "ok")
        return {"ok": True, "message": "بکاپ با موفقیت بازیابی شد"}
    except Exception as e:
        logger.error(f"Backup restore error: {e}")
        raise HTTPException(status_code=400, detail=f"خطا در بازیابی بکاپ: {str(e)}")

# ─── VLESS WebSocket Tunnel ────────────────────────────────────────────────

RELAY_BUF = 512 * 1024

def _ws_client_ip(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = ws.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return ws.client.host if ws.client else "نامشخص"

async def check_device_limit(uuid: str, client_ip: str) -> bool:
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
        if not link:
            return False
        max_devices = link.get("max_devices", 0)
        if max_devices == 0:
            return True
    
    async with DEVICE_CONNECTIONS_LOCK:
        current_ips = device_connections.get(uuid, [])
        if client_ip in current_ips:
            return True
        if len(current_ips) >= max_devices:
            return False
        if uuid not in device_connections:
            device_connections[uuid] = []
        device_connections[uuid].append(client_ip)
        return True

async def parse_vless_header(chunk: bytes):
    if len(chunk) < 24:
        raise ValueError("chunk too small")
    pos = 1
    pos += 16
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
        if link is None:
            return False
        if not is_link_allowed(link):
            return False
        link["used_bytes"] = link.get("used_bytes", 0) + n
        stats["total_bytes"] = stats.get("total_bytes", 0) + n
        hourly_traffic[now_ir().strftime("%H:00")] = hourly_traffic.get(now_ir().strftime("%H:00"), 0) + n
        
        limit = link.get("limit_bytes", 0)
        used = link.get("used_bytes", 0)
        if limit > 0 and used / limit > 0.8 and not link.get("alert_80"):
            link["alert_80"] = True
            log_activity("warning", f"⚠️ مصرف کانفیگ {link.get('label')} به 80% رسید", "warn")
        
        return True

async def relay_ws_to_tcp(ws: WebSocket, writer: asyncio.StreamWriter, conn_id: str, uid: str):
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            if not data:
                continue
            if not await check_and_use(uid, len(data)):
                await ws.close(code=1008, reason="quota/disabled/unknown")
                break
            stats["total_requests"] = stats.get("total_requests", 0) + 1
            if conn_id in connections:
                connections[conn_id]["bytes"] = connections[conn_id].get("bytes", 0) + len(data)
            writer.write(data)
            if writer.transport.get_write_buffer_size() > RELAY_BUF:
                await writer.drain()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            writer.write_eof()
        except Exception:
            pass

async def relay_tcp_to_ws(ws: WebSocket, reader: asyncio.StreamReader, conn_id: str, uid: str):
    first = True
    try:
        while True:
            data = await reader.read(RELAY_BUF)
            if not data:
                break
            if not await check_and_use(uid, len(data)):
                await ws.close(code=1008, reason="quota/disabled/unknown")
                break
            if conn_id in connections:
                connections[conn_id]["bytes"] = connections[conn_id].get("bytes", 0) + len(data)
            payload = (b"\x00\x00" + data) if first else data
            first = False
            await ws.send_bytes(payload)
    except Exception:
        pass

@app.websocket("/ws/{uuid}")
async def websocket_tunnel(ws: WebSocket, uuid: str):
    await ws.accept()

    client_ip = _ws_client_ip(ws)
    
    async with LINKS_LOCK:
        link = LINKS.get(uuid)

    if not link:
        logger.warning(f"🚫 WS rejected uuid={uuid[:8]}… (user not found)")
        await ws.close(code=1008, reason="user not found")
        return

    if not is_link_allowed(link):
        logger.warning(f"🚫 WS rejected uuid={uuid[:8]}… (not allowed)")
        await ws.close(code=1008, reason="not authorized")
        return

    max_devices = link.get("max_devices", 0)
    if max_devices > 0:
        if not await check_device_limit(uuid, client_ip):
            logger.warning(f"🚫 Device limit exceeded for {uuid[:8]}… (max: {max_devices})")
            await ws.close(code=1008, reason="device limit exceeded")
            return

    conn_id = secrets.token_urlsafe(6)
    connections[conn_id] = {
        "uuid": uuid,
        "ip": client_ip,
        "transport": "vless-ws",
        "connected_at": datetime.now().isoformat(),
        "bytes": 0,
    }
    
    logger.info(f"✅ WS [{conn_id}] uuid={uuid[:8]}… ip={client_ip} total={len(connections)}")
    log_activity("connection", f"اتصال جدید از {client_ip} (کانفیگ {link.get('label','?')})", "info")
    
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
        logger.info(f"➡️  [{conn_id}] → {address}:{port}")

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port),
            timeout=10.0
        )
        sock = writer.transport.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024*1024)

        if payload:
            writer.write(payload)
            await writer.drain()

        done, pending = await asyncio.wait(
            {
                asyncio.create_task(relay_ws_to_tcp(ws, writer, conn_id, uuid)),
                asyncio.create_task(relay_tcp_to_ws(ws, reader, conn_id, uuid)),
            },
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        asyncio.create_task(save_state())

    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        stats["total_errors"] = stats.get("total_errors", 0) + 1
        error_logs.append({"error": "connection timeout", "time": datetime.now().isoformat()})
    except Exception as exc:
        stats["total_errors"] = stats.get("total_errors", 0) + 1
        error_logs.append({"error": str(exc), "time": datetime.now().isoformat()})
        logger.error(f"WS error [{conn_id}]: {exc}")
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        connections.pop(conn_id, None)
        await remove_device_connection(uuid, client_ip)
        logger.info(f"🔌 WS closed [{conn_id}] total={len(connections)}")

# ─── ===== تابع صفحه ساب (داخل خود main.py) ===== ──────────────────────

def get_sub_page_html(uuid: str, link: dict) -> str:
    """صفحه HTML زیبا برای نمایش اطلاعات کانفیگ"""
    used = link.get('used_bytes', 0)
    limit = link.get('limit_bytes', 0)
    active = link.get('active', True)
    expired = link.get('expired', False)
    label = link.get('label', 'کاربر')
    fingerprint = link.get('fingerprint', 'chrome')
    max_devices = link.get('max_devices', 0)
    protocol = link.get('protocol', 'vless-ws')
    port = link.get('port', 443)
    active_connections = link.get('active_connections', 0)
    active_connections_list = link.get('active_connections_list', [])
    last_connected = link.get('last_connected_at')
    last_connected_text = "—"
    if last_connected:
        try:
            dt = datetime.fromisoformat(last_connected)
            last_connected_text = dt.strftime("%Y-%m-%d %H:%M")
        except:
            last_connected_text = last_connected[:16]
    
    percent = 0
    if limit > 0:
        percent = min(100, (used / limit) * 100)
    
    expires_at = link.get('expires_at')
    if expires_at:
        try:
            exp_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            days_left = (exp_date - datetime.now().astimezone()).days
            if days_left < 0:
                days_left = 0
        except:
            days_left = 'نامشخص'
    else:
        days_left = 'نامحدود'
    
    is_allowed = active and not expired
    sub_url = link.get('sub_url', '')
    
    def fmt_bytes_local(b):
        if not b or b == 0:
            return '0 B'
        if b < 1024:
            return f'{b} B'
        if b < 1024**2:
            return f'{b/1024:.1f} KB'
        if b < 1024**3:
            return f'{b/1024**2:.2f} MB'
        if b < 1024**4:
            return f'{b/1024**3:.2f} GB'
        return f'{b/1024**4:.2f} TB'
    
    used_fmt = fmt_bytes_local(used)
    limit_fmt = 'نامحدود' if limit == 0 else fmt_bytes_local(limit)
    
    host = get_host()
    remark = f"عقاب-{label}"
    new_vless_link = generate_vless_link(uuid, host, remark=remark, protocol=protocol, fingerprint=fingerprint, port=port)
    
    conns_html = ""
    if active_connections > 0:
        conns_html = f"""
        <div style="background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.04);border-radius:10px;padding:8px 10px;margin:8px 0">
            <div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;font-size:9px;color:#8888BB">
                <span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#34D399;animation:pulse 1.5s infinite"></span>
                <span style="font-weight:700;color:#34D399;font-size:9px">{active_connections} دستگاه متصل</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:3px">"""
        for conn in active_connections_list[:10]:
            ip = conn.get('ip', 'نامشخص')
            conns_html += f"""<span style="font-family:monospace;font-size:8px;background:rgba(100,80,255,0.04);border:1px solid rgba(100,80,255,0.04);padding:1px 6px;border-radius:3px;color:#8888BB">🔵 {ip}</span>"""
        if len(active_connections_list) > 10:
            conns_html += f"""<span style="font-family:monospace;font-size:8px;background:rgba(100,80,255,0.02);padding:1px 6px;border-radius:3px;color:#555577">+{len(active_connections_list)-10}</span>"""
        conns_html += "</div></div>"
    else:
        conns_html = f"""<div style="background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.04);border-radius:10px;padding:6px 10px;margin:8px 0;text-align:center"><span style="font-size:9px;color:#555577">🔴 بدون اتصال فعال</span></div>"""
    
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>🪐 {label}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.25}}}}
body{{font-family:'Vazirmatn',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;color:#F0EEFF;background:linear-gradient(135deg,#0a0a1a,#1a0a2a,#0a0a2a);}}
.stars-sub{{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}}
.star-sub{{position:absolute;border-radius:50%;background:#fff;animation:twinkleSub 4s ease-in-out infinite}}
@keyframes twinkleSub{{0%,100%{{opacity:0.1}}50%{{opacity:0.4}}}}
.glow-sub{{position:fixed;border-radius:50%;filter:blur(150px);z-index:0;pointer-events:none}}
.glow-sub1{{width:350px;height:350px;background:rgba(100,80,255,0.04);top:-120px;right:-60px;animation:glowFloat2 7s ease-in-out infinite}}
.glow-sub2{{width:250px;height:250px;background:rgba(167,139,250,0.03);bottom:-60px;left:-40px;animation-delay:2s;animation:glowFloat2 9s ease-in-out infinite reverse}}
@keyframes glowFloat2{{0%,100%{{transform:translate(0,0) scale(1)}}50%{{transform:translate(20px,-20px) scale(1.05)}}}}
.card{{position:relative;z-index:10;background:rgba(10,10,30,0.8);backdrop-filter:blur(30px);border:1px solid rgba(100,80,255,0.06);border-radius:20px;padding:24px 22px 20px;max-width:420px;width:100%;box-shadow:0 0 60px rgba(0,0,0,0.4),0 0 80px rgba(100,80,255,0.02);animation:cardIn 0.6s ease;}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(20px) scale(0.97)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
.brand{{display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid rgba(100,80,255,0.04);}}
.brand-icon{{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;box-shadow:0 0 30px rgba(100,80,255,0.1);}}
.brand-text .name{{font-size:13px;font-weight:800;background:linear-gradient(135deg,#A78BFA,#7C6BFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.brand-text .sub{{font-size:7px;color:#555577;margin-top:0px}}
.user-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}}
.user-name{{font-size:17px;font-weight:800;color:#F0EEFF;display:flex;align-items:center;gap:4px}}
.user-name .fire{{font-size:15px}}
.status{{display:inline-flex;align-items:center;gap:3px;padding:2px 10px;border-radius:12px;font-size:9px;font-weight:700;}}
.status.active{{background:rgba(100,80,255,0.12);color:#A78BFA;border:1px solid rgba(100,80,255,0.08);}}
.status.inactive{{background:rgba(239,68,68,0.12);color:#F87171;border:1px solid rgba(239,68,68,0.08);}}
.uuid-box{{background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.04);border-radius:6px;padding:4px 8px;font-size:8px;font-family:monospace;color:#555577;word-break:break-all;margin:3px 0 8px;cursor:pointer;transition:.3s}}
.uuid-box:hover{{background:rgba(100,80,255,0.04);transform:scale(1.01)}}
.info-grid{{display:grid;gap:5px;margin:8px 0}}
.info-item{{background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.02);border-radius:6px;padding:6px 10px;display:flex;justify-content:space-between;align-items:center;transition:.3s}}
.info-item:hover{{background:rgba(100,80,255,0.04)}}
.info-label{{font-size:9px;color:#8888BB;display:flex;align-items:center;gap:3px}}
.info-label i{{font-size:10px;color:#7C6BFF}}
.info-value{{font-size:11px;font-weight:700;color:#F0EEFF}}
.info-value.used{{color:#A78BFA}}
.info-value.proto{{font-size:8px;background:rgba(100,80,255,0.05);padding:1px 6px;border-radius:4px;border:1px solid rgba(100,80,255,0.04);}}
.progress{{margin:8px 0 10px}}
.progress-bar{{height:3px;border-radius:3px;background:rgba(100,80,255,0.04);overflow:hidden}}
.progress-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,#7C6BFF,#5B4BD9,#A78BFA);width:{percent:.1f}%;transition:width 1s ease}}
.progress-text{{display:flex;justify-content:space-between;font-size:8px;color:#8888BB;margin-top:2px}}
.progress-text .pct{{font-weight:700;color:#F0EEFF}}
.vless-section{{background:rgba(100,80,255,0.02);border:1px solid rgba(100,80,255,0.03);border-radius:8px;padding:8px 10px;margin:8px 0}}
.vless-label{{font-size:7px;color:#8888BB;font-weight:700;text-transform:uppercase;letter-spacing:.04em;display:flex;align-items:center;gap:4px;margin-bottom:4px}}
.vless-label i{{color:#7C6BFF;font-size:10px}}
.vless-link{{font-family:monospace;font-size:8px;color:#A78BFA;word-break:break-all;line-height:1.5;background:rgba(0,0,0,0.2);padding:4px 6px;border-radius:4px;border:1px solid rgba(100,80,255,0.02);}}
.actions{{display:flex;gap:4px;margin-top:8px;flex-wrap:wrap}}
.btn{{font-family:inherit;font-size:9px;font-weight:600;border-radius:6px;padding:5px 10px;cursor:pointer;display:inline-flex;align-items:center;gap:3px;border:none;transition:all .3s;white-space:nowrap;flex:1;justify-content:center}}
.btn i{{font-size:11px}}
.btn-primary{{background:linear-gradient(135deg,#7C6BFF,#5B4BD9);color:#fff;box-shadow:0 3px 15px rgba(100,80,255,0.15)}}
.btn-primary:hover{{transform:translateY(-2px);box-shadow:0 6px 25px rgba(100,80,255,0.25)}}
.btn-secondary{{background:rgba(100,80,255,0.03);border:1px solid rgba(100,80,255,0.04);color:#8888BB}}
.btn-secondary:hover{{background:rgba(100,80,255,0.06);color:#F0EEFF;transform:translateY(-2px)}}
.btn-success{{background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.08);color:#34D399}}
.btn-success:hover{{background:rgba(16,185,129,0.1);transform:translateY(-2px)}}
.footer{{margin-top:12px;padding-top:10px;border-top:1px solid rgba(100,80,255,0.02);text-align:center;font-size:7px;color:#555577}}
.footer .eagle{{color:#7C6BFF;font-weight:700}}
.toast{{position:fixed;bottom:16px;left:50%;transform:translateX(-50%) translateY(40px);background:rgba(10,10,30,0.9);backdrop-filter:blur(20px);border:1px solid rgba(100,80,255,0.08);color:#F0EEFF;border-radius:8px;padding:6px 14px;font-size:10px;opacity:0;transition:all .4s;z-index:999;pointer-events:none;display:flex;align-items:center;gap:4px;box-shadow:0 8px 30px rgba(0,0,0,0.3)}}
.toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}
.toast.ok{{border-color:rgba(16,185,129,0.15);color:#34D399}}
@media(max-width:400px){{.card{{padding:16px 14px 14px}}.user-name{{font-size:15px}}.brand-icon{{width:30px;height:30px;font-size:14px}}.info-item{{padding:4px 8px}}.btn{{font-size:8px;padding:4px 8px}}}}
</style>
</head>
<body>
<div class="stars-sub">
    <div class="star-sub" style="width:2px;height:2px;top:10%;left:10%;animation-delay:0s"></div>
    <div class="star-sub" style="width:3px;height:3px;top:30%;left:40%;animation-delay:1.5s"></div>
    <div class="star-sub" style="width:1px;height:1px;top:50%;left:70%;animation-delay:0.8s"></div>
    <div class="star-sub" style="width:2px;height:2px;top:70%;left:20%;animation-delay:2.2s"></div>
    <div class="star-sub" style="width:3px;height:3px;top:85%;left:80%;animation-delay:0.5s"></div>
</div>
<div class="glow-sub glow-sub1"></div><div class="glow-sub glow-sub2"></div>
<div class="toast" id="toast"></div>
<div class="card">
    <div class="brand"><div class="brand-icon">🪐</div><div class="brand-text"><div class="name">پنل عقاب</div><div class="sub">اطلاعات اشتراک</div></div></div>
    <div class="user-header"><div class="user-name"><span class="fire">🪐</span> {label}</div><span class="status {'active' if is_allowed else 'inactive'}"><i class="ti {'ti-circle-check' if is_allowed else 'ti-circle-x'}"></i>{'فعال' if is_allowed else 'غیرفعال'}</span></div>
    <div class="uuid-box" onclick="copyUUID()">🔑 {uuid}</div>
    {conns_html}
    <div class="info-grid">
        <div class="info-item"><span class="info-label"><i class="ti ti-database"></i> مصرف</span><span class="info-value used">{used_fmt}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-package"></i> سهمیه</span><span class="info-value">{limit_fmt}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-calendar"></i> باقیمانده</span><span class="info-value">{days_left if days_left == 'نامحدود' else f'{days_left} روز'}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-devices"></i> دستگاه</span><span class="info-value">{max_devices if max_devices > 0 else '∞'}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-clock"></i> آخرین اتصال</span><span class="info-value" style="font-size:9px;">{last_connected_text}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-fingerprint"></i> FP</span><span class="info-value proto">{fingerprint}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-settings"></i> پروتکل</span><span class="info-value proto">{protocol}</span></div>
        <div class="info-item"><span class="info-label"><i class="ti ti-plug"></i> پورت</span><span class="info-value proto">{port}</span></div>
    </div>
    <div class="progress"><div class="progress-bar"><div class="progress-fill" style="width:{percent:.1f}%"></div></div><div class="progress-text"><span>میزان مصرف</span><span class="pct">{percent:.1f}%</span></div></div>
    <div class="vless-section"><div class="vless-label"><i class="ti ti-link"></i> لینک کانفیگ</div><div class="vless-link" id="vless-link">{new_vless_link}</div></div>
    <div class="actions"><button class="btn btn-primary" onclick="copyVless()"><i class="ti ti-copy"></i> کپی</button><button class="btn btn-success" onclick="copySub()"><i class="ti ti-link"></i> ساب</button><button class="btn btn-secondary" onclick="showQR()"><i class="ti ti-qrcode"></i> QR</button></div>
    <div class="footer"><span class="eagle">🪐</span> پنل عقاب</div>
</div>
<script>
const vless=`{new_vless_link}`;
const subUrl=`{sub_url}`;
const uuid=`{uuid}`;
function toast(msg,type=''){{const t=document.getElementById('toast');t.textContent=msg;t.className='toast show'+(type?' '+type:'');setTimeout(()=>t.classList.remove('show'),2000);}}
function copyVless(){{navigator.clipboard.writeText(vless).then(()=>toast('✅ کپی شد','ok'));}}
function copySub(){{navigator.clipboard.writeText(subUrl).then(()=>toast('✅ کپی شد','ok'));}}
function copyUUID(){{navigator.clipboard.writeText(uuid).then(()=>toast('✅ کپی شد','ok'));}}
function showQR(){{window.open('https://api.qrserver.com/v1/create-qr-code/?size=250x250&data='+encodeURIComponent(vless),'_blank');}}
</script>
</body></html>"""

# ─── Subscriptions ─────────────────────────────────────────────────────────

@app.get("/sub/{uuid}")
async def subscription_single(request: Request, uuid: str):
    import base64
    
    # تشخیص User-Agent
    user_agent = request.headers.get("user-agent", "").lower()
    is_browser = any(b in user_agent for b in [
        "chrome", "firefox", "safari", "edge", "opera", "brave",
        "msie", "trident"
    ])
    
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    
    if not link:
        if is_browser:
            return HTMLResponse("""
            <!DOCTYPE html>
            <html lang="fa" dir="rtl">
            <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>🦅 کاربر یافت نشد</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;800&display=swap" rel="stylesheet">
            <style>
            *{margin:0;padding:0;box-sizing:border-box}
            body{font-family:'Vazirmatn',sans-serif;background:#0a0a0f;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#F0F0FF}
            .card{background:rgba(15,15,30,0.85);backdrop-filter:blur(30px);border:1px solid rgba(59,130,246,0.12);border-radius:28px;padding:40px;max-width:420px;text-align:center}
            .icon{font-size:64px;margin-bottom:16px}
            h2{font-size:22px;font-weight:800;margin-bottom:8px}
            p{color:#6A6A8A;font-size:13px;line-height:1.8}
            </style>
            </head>
            <body>
            <div class="card">
                <div class="icon">🦅</div>
                <h2>کاربر یافت نشد</h2>
                <p>لینک ساب‌لینک معتبر نیست یا کاربر حذف شده است.</p>
            </div>
            </body>
            </html>
            """, status_code=404)
        else:
            raise HTTPException(status_code=404, detail="user not found")
    
    if not is_link_allowed(link):
        if is_browser:
            return HTMLResponse("""
            <!DOCTYPE html>
            <html lang="fa" dir="rtl">
            <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>⛔ کاربر غیرفعال</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;800&display=swap" rel="stylesheet">
            <style>
            *{margin:0;padding:0;box-sizing:border-box}
            body{font-family:'Vazirmatn',sans-serif;background:#0a0a0f;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#F0F0FF}
            .card{background:rgba(15,15,30,0.85);backdrop-filter:blur(30px);border:1px solid rgba(239,68,68,0.12);border-radius:28px;padding:40px;max-width:420px;text-align:center}
            .icon{font-size:64px;margin-bottom:16px}
            h2{font-size:22px;font-weight:800;margin-bottom:8px}
            p{color:#6A6A8A;font-size:13px;line-height:1.8}
            .status{color:#F87171}
            </style>
            </head>
            <body>
            <div class="card">
                <div class="icon">⛔</div>
                <h2>کاربر غیرفعال یا منقضی</h2>
                <p class="status">این کانفیگ فعال نیست یا تاریخ انقضای آن گذشته است.</p>
            </div>
            </body>
            </html>
            """, status_code=403)
        else:
            raise HTTPException(status_code=403, detail="user disabled or expired")
    
    # ===== اگر کلاینت باشد → دانلود کانفیگ =====
    if not is_browser:
        host = get_host()
        label = link.get("label", "کاربر")
        remark = f"عقاب-{label}"
        protocol = link.get("protocol", DEFAULT_PROTOCOL)
        fingerprint = link.get("fingerprint", "chrome")
        port = link.get("port", 443)
        
        vless_link = generate_vless_link(
            uuid, 
            host, 
            remark=remark,
            protocol=protocol,
            fingerprint=fingerprint,
            port=port
        )
        
        content = base64.b64encode(vless_link.encode()).decode()
        
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=config_{uuid[:8]}.txt",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )
    
    # ===== اگر مرورگر باشد → صفحه اطلاعات زیبا =====
    active_connections_list = []
    for c in connections.values():
        if c.get("uuid") == uuid:
            active_connections_list.append(c)
    
    active_connections_count = len(active_connections_list)
    
    label = link.get("label", "کاربر")
    remark = f"عقاب-{label}"
    
    last_connected = None
    for c in connections.values():
        if c.get("uuid") == uuid:
            if not last_connected or c.get("connected_at") > last_connected:
                last_connected = c.get("connected_at")
    
    link_data = {
        **link,
        "expired": is_link_expired(link),
        "active_connections": active_connections_count,
        "active_connections_list": active_connections_list,
        "last_connected_at": last_connected,
        "vless_link": generate_vless_link(
            uuid, 
            get_host(), 
            remark=remark,
            protocol=link.get("protocol", DEFAULT_PROTOCOL),
            fingerprint=link.get("fingerprint", "chrome"),
            port=link.get("port", 443)
        ),
        "sub_url": f"https://{get_host()}/sub/{uuid}",
    }
    
    return HTMLResponse(content=get_sub_page_html(uuid, link_data))

@app.get("/sub-all")
async def subscription_all(_=Depends(require_auth)):
    import base64
    host = get_host()
    async with LINKS_LOCK:
        lines = []
        for uid, d in LINKS.items():
            if is_link_allowed(d):
                fp = d.get("fingerprint", "chrome")
                port = d.get("port", 443)
                label = d.get("label", "کاربر")
                remark = f"عقاب-{label}"
                lines.append(generate_vless_link(uid, host, remark=remark, protocol=d.get("protocol", DEFAULT_PROTOCOL), fingerprint=fp, port=port))
    content = base64.b64encode("\n".join(lines).encode()).decode()
    return Response(content=content, media_type="text/plain")

@app.get("/sub-group/{uuid_key}")
async def sub_group_subscription(uuid_key: str, request: Request):
    import base64
    async with SUBS_LOCK:
        sub = next((s for s in SUBS.values() if s.get("uuid_key") == uuid_key), None)
    if not sub:
        raise HTTPException(status_code=404, detail="not found")

    if sub.get("password_hash"):
        pw = request.query_params.get("pw", "")
        if hash_password(pw) != sub["password_hash"]:
            raise HTTPException(status_code=403, detail="wrong password")

    host = get_host()
    link_ids = sub.get("link_ids", [])
    async with LINKS_LOCK:
        lines = []
        for lid in link_ids:
            link = LINKS.get(lid)
            if link and is_link_allowed(link):
                fp = link.get("fingerprint", "chrome")
                port = link.get("port", 443)
                label = link.get("label", "کاربر")
                remark = f"عقاب-{label}"
                lines.append(generate_vless_link(lid, host, remark=remark, protocol=link.get("protocol", DEFAULT_PROTOCOL), fingerprint=fp, port=port))

    content = base64.b64encode("\n".join(lines).encode()).decode()
    return Response(
        content=content,
        media_type="text/plain",
        headers={
            "profile-title": quote(sub["name"]),
            "profile-update-interval": "12",
        }
    )

@app.get("/p/{uuid_key}", response_class=HTMLResponse)
async def public_sub_page(uuid_key: str):
    return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:var(--t1)'>🦅 گروه اشتراک</h2>")

@app.get("/api/public/sub/{uuid_key}")
async def public_sub_data(uuid_key: str, request: Request):
    async with SUBS_LOCK:
        sub_entry = next(((sid, s) for sid, s in SUBS.items() if s.get("uuid_key") == uuid_key), None)
    if not sub_entry:
        raise HTTPException(status_code=404, detail="not found")
    sub_id, sub = sub_entry

    has_pw = sub.get("password_hash") is not None
    if has_pw:
        pw = request.query_params.get("pw", "")
        if hash_password(pw) != sub["password_hash"]:
            return JSONResponse({"locked": True, "name": sub["name"]})

    host = get_host()
    link_ids = sub.get("link_ids", [])
    async with LINKS_LOCK:
        snap = dict(LINKS)

    links_out = []
    active_conns = 0
    for lid in link_ids:
        link = snap.get(lid)
        if not link:
            continue
        allowed = is_link_allowed(link)
        conn_count = sum(1 for c in connections.values() if c.get("uuid") == lid)
        active_conns += conn_count
        proto = link.get("protocol", DEFAULT_PROTOCOL)
        fp = link.get("fingerprint", "chrome")
        port = link.get("port", 443)
        label = link.get("label", "کاربر")
        remark = f"عقاب-{label}"
        links_out.append({
            "uuid": lid,
            "label": link["label"],
            "active": allowed,
            "protocol": proto,
            "fingerprint": fp,
            "max_devices": link.get("max_devices", 0),
            "used_bytes": link.get("used_bytes", 0),
            "used_fmt": fmt_bytes(link.get("used_bytes", 0)),
            "limit_bytes": link.get("limit_bytes", 0),
            "limit_fmt": "∞" if link.get("limit_bytes", 0) == 0 else fmt_bytes(link["limit_bytes"]),
            "expires_at": link.get("expires_at"),
            "has_password": link.get("password_hash") is not None,
            "port": port,
            "vless_link": generate_vless_link(lid, host, remark=remark, protocol=proto, fingerprint=fp, port=port),
            "sub_url": f"https://{host}/sub/{lid}",
            "connections": conn_count,
        })

    total_used = sum(l["used_bytes"] for l in links_out)
    return {
        "locked": False,
        "name": sub["name"],
        "desc": sub.get("desc", ""),
        "sub_url": f"https://{host}/sub-group/{uuid_key}",
        "active_connections": active_conns,
        "total_used_fmt": fmt_bytes(total_used),
        "links": links_out,
    }

# ─── HTML Pages ─────────────────────────────────────────────────────────────

# صفحه لاگین (ساده شده)
LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🪐 ورود · پنل عقاب</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0a1a;--card:rgba(10,10,30,0.75);--card-b:rgba(100,80,255,0.12);--accent:#7C6BFF;--t1:#F0EEFF;--t2:#8888BB;--t3:#555577;--border:rgba(100,80,255,0.08)}
body{font-family:'Vazirmatn',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0a0a1a,#1a0a2a,#0a0a2a);padding:20px;color:var(--t1)}
.container{max-width:400px;width:100%;background:var(--card);backdrop-filter:blur(30px);border-radius:24px;border:1px solid var(--border);padding:40px;box-shadow:0 25px 80px rgba(0,0,0,0.6)}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:32px}
.brand-icon{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);display:flex;align-items:center;justify-content:center;font-size:22px}
.brand-text{font-size:16px;font-weight:800;background:linear-gradient(135deg,#A78BFA,#7C6BFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.brand-sub{font-size:9px;color:var(--t3)}
.welcome{font-size:22px;font-weight:800;color:var(--t1);margin-bottom:4px}
.sub-text{font-size:13px;color:var(--t3);margin-bottom:28px}
.field{margin-bottom:18px}
.field label{display:block;font-size:10px;font-weight:600;color:var(--t2);margin-bottom:4px}
.field input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--border);background:rgba(0,0,20,.3);color:var(--t1);font-family:inherit;font-size:14px;outline:none;transition:.3s}
.field input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(100,80,255,.08)}
.field input::placeholder{color:var(--t3)}
.options{display:flex;justify-content:space-between;align-items:center;margin:14px 0 20px;font-size:12px}
.options label{display:flex;align-items:center;gap:6px;color:var(--t2);cursor:pointer}
.options label input[type="checkbox"]{accent-color:var(--accent);width:16px;height:16px;cursor:pointer}
.btn-login{width:100%;padding:12px;border-radius:10px;border:none;cursor:pointer;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);color:#fff;font-family:inherit;font-size:15px;font-weight:700;transition:all .3s}
.btn-login:hover{transform:translateY(-2px);box-shadow:0 8px 40px rgba(100,80,255,.35)}
.btn-login:disabled{opacity:.5;cursor:not-allowed;transform:none}
.error-box{display:none;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.15);border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:12px;color:#F87171;align-items:center;gap:8px}
.error-box.show{display:flex}
</style>
</head>
<body>
<div class="container">
    <div class="brand"><div class="brand-icon">🪐</div><div><div class="brand-text">پنل عقاب</div><div class="brand-sub">مدیریت کاربران</div></div></div>
    <div class="welcome" id="welcome-text">خوش آمدید</div>
    <div class="sub-text" id="sub-text">وارد حساب کاربری خود شوید</div>
    <div class="error-box" id="error-box"><i class="ti ti-alert-circle"></i><span id="error-text"></span></div>
    <form id="login-form" onsubmit="handleLogin(event)">
        <div class="field"><label id="label-username">نام کاربری یا ایمیل</label><input type="text" id="username" placeholder="نام کاربری" value="admin" dir="ltr"></div>
        <div class="field"><label id="label-password">رمز عبور</label><input type="password" id="password" placeholder="رمز عبور را وارد کنید" dir="ltr"></div>
        <div class="options"><label><input type="checkbox" id="remember"> <span id="remember-text">مرا به خاطر بسپار</span></label></div>
        <button class="btn-login" type="submit" id="login-btn"><i class="ti ti-login-2"></i> <span id="login-text">ورود</span></button>
    </form>
</div>
<script>
const translations={fa:{welcome:"خوش آمدید",sub:"وارد حساب کاربری خود شوید",username:"نام کاربری یا ایمیل",password:"رمز عبور",remember:"مرا به خاطر بسپار",login:"ورود"},en:{welcome:"Welcome Back",sub:"Login to your account",username:"Username or Email",password:"Password",remember:"Remember me",login:"Login"}};
let currentLang=localStorage.getItem('eagle-lang')||'fa';
function setLang(lang){currentLang=lang;localStorage.setItem('eagle-lang',lang);updateTexts()}
function updateTexts(){const t=translations[currentLang];document.getElementById('welcome-text').textContent=t.welcome;document.getElementById('sub-text').textContent=t.sub;document.getElementById('label-username').textContent=t.username;document.getElementById('label-password').textContent=t.password;document.getElementById('remember-text').textContent=t.remember;document.getElementById('login-text').textContent=t.login}
async function handleLogin(e){e.preventDefault();const btn=document.getElementById('login-btn');const err=document.getElementById('error-box');const errText=document.getElementById('error-text');err.classList.remove('show');btn.disabled=true;btn.innerHTML='<i class="ti ti-loader-2" style="animation:spin 1s linear infinite"></i> در حال ورود...';try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('password').value,remember:document.getElementById('remember').checked})});if(!r.ok){const d=await r.json().catch(()=>({}));errText.textContent=d.detail||'رمز عبور اشتباه است';err.classList.add('show');btn.disabled=false;btn.innerHTML='<i class="ti ti-login-2"></i> '+translations[currentLang].login;return}window.location.href='/dashboard'}catch(e){errText.textContent='خطا در ارتباط با سرور';err.classList.add('show');btn.disabled=false;btn.innerHTML='<i class="ti ti-login-2"></i> '+translations[currentLang].login}}
setLang(currentLang);
</script>
</body></html>"""

# صفحه داشبورد (ساده شده)
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🪐 پنل عقاب · خانه</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0a1a;--bg2:#12122a;--card:rgba(10,10,30,0.7);--card-b:rgba(100,80,255,0.08);--card-bh:rgba(100,80,255,0.15);--accent:#7C6BFF;--accent2:#A78BFA;--accent3:#5B4BD9;--green:#10B981;--green-bg:rgba(16,185,129,0.08);--green-t:#34D399;--red:#EF4444;--red-bg:rgba(239,68,68,0.08);--red-t:#F87171;--amber:#F59E0B;--amber-bg:rgba(245,158,11,0.08);--amber-t:#FCD34D;--t1:#F0EEFF;--t2:#8888BB;--t3:#555577;--sidebar-w:180px;--radius:12px;--shadow:0 8px 32px rgba(0,0,0,0.5)}
body{font-family:'Vazirmatn',sans-serif;background:var(--bg);color:var(--t1);min-height:100vh;display:flex;font-size:13px}
.sidebar{width:var(--sidebar-w);min-height:100vh;background:var(--card);backdrop-filter:blur(30px);border-left:1px solid var(--card-b);display:flex;flex-direction:column;flex-shrink:0;position:fixed;right:0;top:0;bottom:0;z-index:200}
.logo{display:flex;align-items:center;gap:10px;padding:16px 12px;border-bottom:1px solid var(--card-b)}
.logo-icon{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);display:flex;align-items:center;justify-content:center;font-size:18px}
.logo-name{font-size:13px;font-weight:800;background:linear-gradient(135deg,#A78BFA,#7C6BFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.logo-sub{font-size:7px;color:var(--t3)}
.nav-wrap{flex:1;overflow-y:auto;padding:6px 0}
.nav-it{display:flex;align-items:center;gap:8px;padding:8px 10px;color:var(--t3);font-size:11px;cursor:pointer;border-right:2px solid transparent;transition:all .2s;margin:1px 4px;border-radius:6px}
.nav-it i{font-size:14px;width:18px;text-align:center}
.nav-it:hover{background:rgba(100,80,255,0.05);color:var(--t2)}
.nav-it.on{background:rgba(100,80,255,0.08);color:var(--t1);border-right-color:var(--accent);font-weight:600}
.sb-foot{padding:10px 12px;border-top:1px solid var(--card-b)}
.logout-btn{display:flex;align-items:center;justify-content:center;gap:6px;background:var(--red-bg);color:var(--red-t);border-radius:6px;padding:6px;font-size:10px;font-weight:500;font-family:inherit;border:1px solid rgba(239,68,68,0.1);cursor:pointer;width:100%;transition:.2s}
.logout-btn:hover{background:rgba(239,68,68,0.15)}
.main{margin-right:var(--sidebar-w);flex:1;padding:16px 20px 80px;min-width:0}
.pg{display:none}.pg.on{display:block}
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px}
.tb-title{font-size:17px;font-weight:800;color:var(--t1);display:flex;align-items:center;gap:6px}
.tb-title i{color:var(--accent);font-size:19px}
.tb-sub{font-size:10px;color:var(--t3)}
.btn{font-family:inherit;font-size:10px;font-weight:600;border-radius:6px;padding:5px 10px;cursor:pointer;display:inline-flex;align-items:center;gap:4px;border:none;transition:all .2s;white-space:nowrap}
.btn-p{background:linear-gradient(135deg,#7C6BFF,#5B4BD9,#A78BFA);color:#fff;box-shadow:0 3px 15px rgba(100,80,255,.2)}
.btn-p:hover{transform:translateY(-1px);box-shadow:0 6px 25px rgba(100,80,255,.3)}
.btn-o{background:rgba(255,255,255,0.02);border:1px solid var(--card-b);color:var(--t2)}
.btn-o:hover{background:rgba(100,80,255,0.05)}
.btn-sm{padding:2px 6px;font-size:8px;border-radius:4px}
.btn-d{background:var(--red-bg);color:var(--red-t);border:1px solid rgba(239,68,68,.1)}
.btn-d:hover{background:rgba(239,68,68,.15)}
.badge{font-size:8px;padding:2px 8px;border-radius:12px;font-weight:700;display:inline-flex;align-items:center;gap:3px}
.bg-green{background:var(--green-bg);color:var(--green-t)}
.bg-fire{background:rgba(100,80,255,0.08);color:#A78BFA}
.dot{width:5px;height:5px;border-radius:50%;display:inline-block}
.dg{background:var(--green)}
.stats-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}
.stat-card{background:var(--card);backdrop-filter:blur(20px);border:1px solid var(--card-b);border-radius:var(--radius);padding:12px 8px;text-align:center}
.stat-card .icon{font-size:18px;display:block;margin-bottom:3px}
.stat-card .number{font-size:18px;font-weight:800;color:var(--t1)}
.stat-card .label{font-size:9px;color:var(--t3);margin-top:2px}
.stat-card .sub{font-size:7px;color:var(--t3);opacity:.6}
</style>
</head>
<body>
<aside class="sidebar" id="sb">
  <div class="logo"><div class="logo-icon">🪐</div><div><div class="logo-name">پنل عقاب</div><div class="logo-sub">مدیریت کاربران</div></div></div>
  <div class="nav-wrap">
    <div class="nav-it on" data-pg="dashboard"><i class="ti ti-layout-dashboard"></i> خانه</div>
    <div class="nav-it" data-pg="users"><i class="ti ti-users"></i> کاربران</div>
    <div class="nav-it" data-pg="inbound"><i class="ti ti-plug"></i> اینباند</div>
    <div class="nav-it" data-pg="connections"><i class="ti ti-plug-connected"></i> اتصالات</div>
    <div class="nav-it" data-pg="settings"><i class="ti ti-settings"></i> تنظیمات</div>
  </div>
  <div class="sb-foot"><button class="logout-btn" onclick="logout()"><i class="ti ti-logout"></i> خروج</button></div>
</aside>
<main class="main">
<section class="pg on" id="pg-dashboard">
  <div class="topbar"><div><div class="tb-title"><i class="ti ti-layout-dashboard"></i> خانه</div><div class="tb-sub" id="last-update">بروزرسانی: لحظه‌ای</div></div>
    <div class="tb-right"><span class="badge bg-fire" id="online-badge"><span class="dot dg"></span> ۰ آنلاین</span></div>
  </div>
  <div class="stats-grid">
    <div class="stat-card"><span class="icon">📊</span><div class="number" id="stat-traffic">۰</div><div class="label">ترافیک</div><div class="sub">MB</div></div>
    <div class="stat-card"><span class="icon">📨</span><div class="number" id="stat-requests">۰</div><div class="label">درخواست‌ها</div><div class="sub">تعداد</div></div>
    <div class="stat-card"><span class="icon">⏱️</span><div class="number" id="stat-uptime">۰۰:۰۰:۰۰</div><div class="label">آپتایم</div><div class="sub">زمان</div></div>
    <div class="stat-card"><span class="icon">💾</span><div class="number" id="stat-disk">۰ GB</div><div class="label">فضای دیسک</div><div class="sub" id="stat-disk-used">استفاده</div></div>
    <div class="stat-card"><span class="icon">📶</span><div class="number" id="stat-speed">۰ B/s</div><div class="label">سرعت</div><div class="sub">لحظه‌ای</div></div>
    <div class="stat-card"><span class="icon">👥</span><div class="number" id="stat-users">۰</div><div class="label">کاربران</div><div class="sub" id="stat-users-active">۰ فعال</div></div>
  </div>
</section>
</main>
<script>
async function logout(){try{await fetch('/api/logout',{method:'POST'})}catch(e){}location.href='/login'}
async function loadDashboard(){try{const r=await fetch('/api/dashboard/stats');const data=await r.json();document.getElementById('stat-traffic').textContent=(data.traffic.total/(1024*1024)).toFixed(1);document.getElementById('stat-requests').textContent=data.requests||0;document.getElementById('stat-uptime').textContent=data.uptime||'00:00:00';document.getElementById('stat-disk').textContent=data.disk.total_fmt||'0 GB';document.getElementById('stat-disk-used').textContent='استفاده: '+(data.disk.used_fmt||'0');document.getElementById('stat-speed').textContent=data.speed.download_fmt||'0 B/s';document.getElementById('stat-users').textContent=data.links_count||0;document.getElementById('stat-users-active').textContent=(data.active_links||0)+' فعال';document.getElementById('online-badge').innerHTML='<span class="dot dg"></span> '+(data.connections||0)+' آنلاین';document.getElementById('last-update').textContent='بروزرسانی: '+new Date().toLocaleTimeString('fa-IR')}catch(e){}}
document.addEventListener('DOMContentLoaded',async()=>{try{const r=await fetch('/api/me');const d=await r.json();if(!d.authenticated)location.href='/login'}catch(e){location.href='/login'}loadDashboard();setInterval(loadDashboard,5000)});
</script>
</body></html>"""

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if await is_valid_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url="/dashboard")
    return HTMLResponse(content=LOGIN_HTML)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not await is_valid_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url="/login")
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>🪐 Eagle Gateway</title>
    <style>
    body{font-family:sans-serif;background:#0a0a0f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
    .card{text-align:center;padding:40px;background:rgba(20,20,40,0.7);border-radius:20px;border:1px solid rgba(100,80,255,0.2)}
    h1{font-size:48px;margin:0}
    .sub{color:#888}
    a{color:#7C6BFF;text-decoration:none;font-weight:bold}
    </style>
    </head>
    <body>
    <div class="card">
        <h1>🪐</h1>
        <h2>Eagle Gateway v10 Pro</h2>
        <p class="sub">پنل مدیریت فیلترشکن</p>
        <a href="/login">ورود به پنل →</a>
    </div>
    </body>
    </html>
    """)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["port"], log_level="info", workers=1)
