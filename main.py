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
import threading

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import httpx
import logging

# ─── Telegram Bot ──────────────────────────────────────────────────────────
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ─── تنظیمات ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("Persepolis-Gateway")

IRAN_TZ = ZoneInfo("Asia/Tehran")

# ─── کانفیگ ──────────────────────────────────────────────────────────────────
CONFIG = {
    "port": int(os.environ.get("PORT", 8000)),
    "secret": os.environ.get("SECRET_KEY", secrets.token_urlsafe(32)),
    "host": os.environ.get("RAILWAY_PUBLIC_DOMAIN", os.environ.get("RENDER_EXTERNAL_URL", "localhost")),
    "admin_password": os.environ.get("ADMIN_PASSWORD", "123456"),
}

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="🏛️ Persepolis Gateway v10", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── State ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "persepolis_state.json"
SAVE_LOCK = asyncio.Lock()

# ─── Telegram Bot State ─────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_CONFIG = {
    "token": "",
    "admin_chat_id": "",
    "enabled": False,
}
BOT_APP: Application = None
BOT_RUNNING = False
BOT_LOCK = asyncio.Lock()

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
hourly_traffic_history: dict = defaultdict(lambda: defaultdict(int))
device_connections: dict = {}
DEVICE_CONNECTIONS_LOCK = asyncio.Lock()
http_client: httpx.AsyncClient | None = None

# ─── Node Management ──────────────────────────────────────────────────────────
NODES: dict = {}
NODES_LOCK = asyncio.Lock()

# ─── Auth ──────────────────────────────────────────────────────────────────────
SESSION_COOKIE = "persepolis_session"
SESSION_TTL = 60 * 60 * 24 * 7
AUTH = {"password_hash": hashlib.sha256(f"{CONFIG['admin_password']}{CONFIG['secret']}".encode()).hexdigest()}
SESSIONS: dict = {}
SESSIONS_LOCK = asyncio.Lock()

# ─── Settings ──────────────────────────────────────────────────────────────────
SETTINGS: dict = {
    "rgb_mode": False,
    "default_protocol": "vless-ws",
    "language": "fa",
    "theme": "dark",
    "bot_token": "",
    "bot_admin_chat_id": "",
    "bot_enabled": False,
}

PROTOCOLS = ("vless-ws", "xhttp-packet-up", "xhttp-stream-up", "xhttp-stream-one")
DEFAULT_PROTOCOL = "vless-ws"
DEFAULT_PORT = 443

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

def fmt_bytes_short(b: int) -> tuple:
    if not b or b == 0:
        return ("0", "B")
    if b < 1024:
        return (str(b), "B")
    if b < 1024**2:
        return (f"{b/1024:.1f}", "KB")
    if b < 1024**3:
        return (f"{b/1024**2:.2f}", "MB")
    if b < 1024**4:
        return (f"{b/1024**3:.2f}", "GB")
    return (f"{b/1024**4:.2f}", "TB")

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
                        fingerprint: str = "chrome", port: int = DEFAULT_PORT, 
                        sni: str = None, fake_port: bool = False) -> str:
    if not remark:
        remark = "تختجمشید"
    
    if not sni:
        sni = host
    
    if fake_port:
        port = 1
    
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

# ─── Telegram Bot Functions ────────────────────────────────────────────────

async def start_bot():
    global BOT_APP, BOT_RUNNING
    
    token = SETTINGS.get("bot_token", "")
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    
    if not token or not admin_chat_id:
        logger.warning("🤖 Telegram bot: Token or Admin Chat ID not set")
        return
    
    if BOT_RUNNING:
        logger.info("🤖 Telegram bot already running")
        return
    
    try:
        BOT_APP = Application.builder().token(token).build()
        
        BOT_APP.add_handler(CommandHandler("start", bot_start))
        BOT_APP.add_handler(CommandHandler("help", bot_help))
        BOT_APP.add_handler(CommandHandler("status", bot_status))
        BOT_APP.add_handler(CommandHandler("my", bot_my_status))
        BOT_APP.add_handler(CommandHandler("users", bot_users_list))
        BOT_APP.add_handler(CommandHandler("create", bot_create_user))
        BOT_APP.add_handler(CommandHandler("delete", bot_delete_user))
        BOT_APP.add_handler(CommandHandler("renew", bot_renew_user))
        BOT_APP.add_handler(CommandHandler("stats", bot_stats))
        BOT_APP.add_handler(CallbackQueryHandler(bot_callback))
        
        def run_bot():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                BOT_APP.run_polling(allowed_updates=Update.ALL_TYPES)
            except Exception as e:
                logger.error(f"🤖 Bot error: {e}")
        
        thread = threading.Thread(target=run_bot, daemon=True)
        thread.start()
        BOT_RUNNING = True
        
        await asyncio.sleep(2)
        await send_bot_message(admin_chat_id, 
            "🏛️ **ربات تخت جمشید فعال شد!**\n\n"
            "✅ ربات با موفقیت راه‌اندازی شد.\n"
            "📋 برای مشاهده دستورات از /help استفاده کنید."
        )
        
        logger.info("🤖 Telegram bot started successfully!")
        
    except Exception as e:
        logger.error(f"🤖 Failed to start bot: {e}")

async def stop_bot():
    global BOT_APP, BOT_RUNNING
    if BOT_APP:
        try:
            await BOT_APP.shutdown()
        except:
            pass
    BOT_RUNNING = False
    BOT_APP = None
    logger.info("🤖 Telegram bot stopped")

async def send_bot_message(chat_id: str, text: str, keyboard: list = None):
    if not BOT_APP or not BOT_RUNNING:
        logger.warning("🤖 Bot not running, message not sent")
        return False
    
    try:
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await BOT_APP.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await BOT_APP.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown"
            )
        return True
    except Exception as e:
        logger.error(f"🤖 Failed to send message: {e}")
        return False

async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    is_admin = (chat_id == admin_chat_id)
    
    text = f"""🏛️ **ربات تخت جمشید**

سلام {user.first_name} 👋

به ربات مدیریت پنل تخت جمشید خوش آمدید!

{'🔑 **شما ادمین هستید**' if is_admin else '👤 **شما کاربر هستید**'}

📋 **دستورات قابل استفاده:**

{'🔹 /status - وضعیت پنل\n🔹 /users - لیست کاربران\n🔹 /create - ساخت کاربر جدید\n🔹 /delete - حذف کاربر\n🔹 /renew - تمدید کاربر\n🔹 /stats - آمار پنل' if is_admin else '🔹 /my - وضعیت اشتراک من\n🔹 /help - راهنما'}

📱 **پنل مدیریت:** {get_host()}/dashboard
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def bot_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    is_admin = (chat_id == admin_chat_id)
    
    text = """🏛️ **راهنمای ربات تخت جمشید**

📋 **دستورات:**

""" + ("""
🔹 /status - وضعیت پنل
🔹 /users - لیست کاربران
🔹 /create - ساخت کاربر جدید
🔹 /delete - حذف کاربر
🔹 /renew - تمدید کاربر
🔹 /stats - آمار پنل
""" if is_admin else """
🔹 /my - وضعیت اشتراک من
🔹 /help - راهنما
""") + """
💡 **نحوه استفاده:**
برای ساخت کاربر: /create نام حجم GB مدت_روز
مثال: /create علی 2 30

📱 **پنل:** """ + get_host() + "/dashboard"
    await update.message.reply_text(text, parse_mode="Markdown")

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید!")
        return
    
    uptime_str = uptime()
    total_users = len(LINKS)
    active_users = sum(1 for l in LINKS.values() if is_link_allowed(l))
    total_traffic = fmt_bytes(stats["total_bytes"])
    active_conns = len(connections)
    total_nodes = len(NODES)
    
    text = f"""🏛️ **وضعیت پنل تخت جمشید**

📊 **آمار کلی:**
👥 کاربران: {total_users} (فعال: {active_users})
📥 ترافیک کل: {total_traffic}
🔌 اتصالات فعال: {active_conns}
🌐 Nodeها: {total_nodes}
⏱ آپتایم: {uptime_str}

📱 **پنل:** {get_host()}/dashboard
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def bot_my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔑 **لطفاً UUID خود را وارد کنید:**\n\n"
        "برای پیدا کردن UUID، به پنل بروید و از بخش کاربران آن را کپی کنید.\n\n"
        "📱 پنل: " + get_host() + "/dashboard",
        parse_mode="Markdown"
    )
    context.user_data['waiting_for_uuid'] = True

async def bot_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید!")
        return
    
    if not LINKS:
        await update.message.reply_text("📭 **هیچ کاربری در پنل وجود ندارد!**", parse_mode="Markdown")
        return
    
    text = "👥 **لیست کاربران پنل:**\n\n"
    for uid, link in list(LINKS.items())[:20]:
        label = link.get("label", "نامشخص")
        used = fmt_bytes(link.get("used_bytes", 0))
        limit = fmt_bytes(link.get("limit_bytes", 0)) if link.get("limit_bytes", 0) > 0 else "∞"
        status = "✅ فعال" if is_link_allowed(link) else "❌ غیرفعال"
        node_name = link.get("node_name", "پیش‌فرض")
        text += f"• **{label}**\n  UUID: `{uid[:8]}...`\n  مصرف: {used} / {limit}\n  وضعیت: {status}\n  🌐 {node_name}\n\n"
    
    if len(LINKS) > 20:
        text += f"\n... و {len(LINKS) - 20} کاربر دیگر"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def bot_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ **فرمت صحیح:**\n"
            "/create نام حجم_GB مدت_روز\n\n"
            "مثال: /create علی 2 30",
            parse_mode="Markdown"
        )
        return
    
    name = args[0]
    try:
        quota = float(args[1])
        days = int(args[2])
    except:
        await update.message.reply_text("❌ حجم و روز باید عدد باشند!", parse_mode="Markdown")
        return
    
    limit_bytes = int(quota * 1024 ** 3)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat() if days > 0 else None
    
    uid = generate_uuid()
    async with LINKS_LOCK:
        LINKS[uid] = {
            "label": name,
            "limit_bytes": limit_bytes,
            "used_bytes": 0,
            "created_at": datetime.now().isoformat(),
            "active": True,
            "expires_at": expires_at,
            "note": f"ساخته شده توسط ربات",
            "is_default": False,
            "sub_id": None,
            "protocol": DEFAULT_PROTOCOL,
            "max_devices": 1,
            "fingerprint": "chrome",
            "password_hash": None,
            "node_id": None,
            "node_host": None,
            "node_port": DEFAULT_PORT,
            "node_name": "پیش‌فرض",
        }
    
    await save_state()
    host = get_host()
    sub_url = f"https://{host}/sub/{uid}"
    
    log_activity("bot", f"کاربر {name} توسط ربات ساخته شد", "ok")
    
    await update.message.reply_text(
        f"✅ **کاربر ساخته شد!**\n\n"
        f"🏷️ نام: {name}\n"
        f"📊 حجم: {quota} GB\n"
        f"⏱ مدت: {days} روز\n"
        f"🔑 UUID: `{uid}`\n"
        f"🔗 ساب‌لینک: {sub_url}\n\n"
        f"📱 **پنل:** {host}/dashboard",
        parse_mode="Markdown"
    )

async def bot_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید!")
        return
    
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "❌ **فرمت صحیح:**\n"
            "/delete UUID\n\n"
            "برای پیدا کردن UUID از /users استفاده کنید.",
            parse_mode="Markdown"
        )
        return
    
    uid = args[0]
    async with LINKS_LOCK:
        if uid not in LINKS:
            await update.message.reply_text("❌ کاربری با این UUID یافت نشد!", parse_mode="Markdown")
            return
        label = LINKS[uid].get("label", "نامشخص")
        del LINKS[uid]
    
    await save_state()
    log_activity("bot", f"کاربر {label} توسط ربات حذف شد", "err")
    await update.message.reply_text(f"✅ **کاربر {label} با موفقیت حذف شد!**", parse_mode="Markdown")

async def bot_renew_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید!")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ **فرمت صحیح:**\n"
            "/renew UUID روز\n\n"
            "مثال: /renew xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx 30",
            parse_mode="Markdown"
        )
        return
    
    uid = args[0]
    try:
        days = int(args[1])
    except:
        await update.message.reply_text("❌ روز باید عدد باشد!", parse_mode="Markdown")
        return
    
    async with LINKS_LOCK:
        if uid not in LINKS:
            await update.message.reply_text("❌ کاربری با این UUID یافت نشد!", parse_mode="Markdown")
            return
        link = LINKS[uid]
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        link["expires_at"] = expires_at
        link["active"] = True
        label = link.get("label", "نامشخص")
    
    await save_state()
    log_activity("bot", f"کاربر {label} توسط ربات تمدید شد ({days} روز)", "ok")
    await update.message.reply_text(f"✅ **کاربر {label} تمدید شد!**\n📅 {days} روز به اشتراک اضافه شد.", parse_mode="Markdown")

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    admin_chat_id = SETTINGS.get("bot_admin_chat_id", "")
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید!")
        return
    
    total_users = len(LINKS)
    active_users = sum(1 for l in LINKS.values() if is_link_allowed(l))
    total_traffic = fmt_bytes(stats["total_bytes"])
    today_traffic = fmt_bytes(sum(hourly_traffic.values()))
    active_conns = len(connections)
    total_nodes = len(NODES)
    
    top_user = None
    top_usage = 0
    for uid, link in LINKS.items():
        used = link.get("used_bytes", 0)
        if used > top_usage:
            top_usage = used
            top_user = link.get("label", "نامشخص")
    
    text = f"""📊 **آمار کامل پنل**

👥 **کاربران:** {total_users} (فعال: {active_users})
📥 **ترافیک کل:** {total_traffic}
📤 **ترافیک امروز:** {today_traffic}
🔌 **اتصالات فعال:** {active_conns}
🌐 **Nodeها:** {total_nodes}
🏆 **بیشترین مصرف:** {top_user} ({fmt_bytes(top_usage)})

⏱ **آپتایم:** {uptime()}

📱 **پنل:** {get_host()}/dashboard
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("user_"):
        uid = data.split("_")[1]
        async with LINKS_LOCK:
            link = LINKS.get(uid)
        if not link:
            await query.edit_message_text("❌ کاربر یافت نشد!", parse_mode="Markdown")
            return
        
        label = link.get("label", "نامشخص")
        used = fmt_bytes(link.get("used_bytes", 0))
        limit = fmt_bytes(link.get("limit_bytes", 0)) if link.get("limit_bytes", 0) > 0 else "∞"
        status = "✅ فعال" if is_link_allowed(link) else "❌ غیرفعال"
        expires_at = link.get("expires_at", "نامحدود")
        node_name = link.get("node_name", "پیش‌فرض")
        
        text = f"""👤 **اطلاعات کاربر {label}**

🔑 UUID: `{uid}`
📊 مصرف: {used} / {limit}
📅 انقضا: {expires_at}
🌐 Node: {node_name}
📱 وضعیت: {status}
"""
        await query.edit_message_text(text, parse_mode="Markdown")

# ─── State Persistence ──────────────────────────────────────────────────────

async def load_state():
    global LINKS, SUBS, AUTH, SETTINGS, hourly_traffic_history, hourly_traffic, NODES
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            LINKS.update(data.get("links", {}))
            SUBS.update(data.get("subs", {}))
            NODES.update(data.get("nodes", {}))
            if "password_hash" in data:
                AUTH["password_hash"] = data["password_hash"]
            if "settings" in data:
                SETTINGS.update(data["settings"])
            if "hourly_traffic" in data:
                hourly_traffic = defaultdict(int, data["hourly_traffic"])
            if "hourly_traffic_history" in data:
                hist = data["hourly_traffic_history"]
                hourly_traffic_history = defaultdict(lambda: defaultdict(int))
                for day, hours in hist.items():
                    hourly_traffic_history[day] = defaultdict(int, hours)
            logger.info(f"📂 State loaded: {len(LINKS)} links, {len(SUBS)} subs, {len(NODES)} nodes")
            
            if SETTINGS.get("bot_token") and SETTINGS.get("bot_admin_chat_id"):
                asyncio.create_task(start_bot())
                
    except Exception as e:
        logger.warning(f"Could not load state: {e}")

async def save_state():
    async with SAVE_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            
            hist_dict = {}
            for day, hours in hourly_traffic_history.items():
                hist_dict[day] = dict(hours)
            
            data = {
                "links": dict(LINKS),
                "subs": dict(SUBS),
                "nodes": dict(NODES),
                "password_hash": AUTH["password_hash"],
                "settings": SETTINGS,
                "hourly_traffic": dict(hourly_traffic),
                "hourly_traffic_history": hist_dict,
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
    
    log_activity("system", "🏛️ Persepolis Gateway v10 راه‌اندازی شد", "ok")
    logger.info(f"🏛️ Persepolis Gateway v10 started on port {CONFIG['port']}")

@app.on_event("shutdown")
async def shutdown():
    await stop_bot()
    await save_state()
    if http_client:
        await http_client.aclose()

# ─── API: Bot Settings ─────────────────────────────────────────────────────

@app.post("/api/bot/settings")
async def update_bot_settings(request: Request, _=Depends(require_auth)):
    global BOT_RUNNING, BOT_APP
    body = await request.json()
    token = body.get("token", "").strip()
    admin_chat_id = body.get("admin_chat_id", "").strip()
    enabled = body.get("enabled", False)
    
    SETTINGS["bot_token"] = token
    SETTINGS["bot_admin_chat_id"] = admin_chat_id
    SETTINGS["bot_enabled"] = enabled
    await save_state()
    
    if enabled and token and admin_chat_id:
        if BOT_RUNNING:
            await stop_bot()
        await start_bot()
        log_activity("bot", "ربات تلگرام فعال شد", "ok")
    else:
        if BOT_RUNNING:
            await stop_bot()
        log_activity("bot", "ربات تلگرام غیرفعال شد", "info")
    
    return {"ok": True, "enabled": enabled, "token_set": bool(token), "admin_chat_id_set": bool(admin_chat_id)}

@app.get("/api/bot/settings")
async def get_bot_settings(_=Depends(require_auth)):
    return {
        "token": SETTINGS.get("bot_token", ""),
        "admin_chat_id": SETTINGS.get("bot_admin_chat_id", ""),
        "enabled": SETTINGS.get("bot_enabled", False),
        "running": BOT_RUNNING
    }

@app.post("/api/bot/test")
async def test_bot(request: Request, _=Depends(require_auth)):
    body = await request.json()
    chat_id = body.get("chat_id", "")
    token = body.get("token", "")
    if not chat_id:
        raise HTTPException(400, "chat_id required")
    try:
        from telegram import Bot
        bot = Bot(token=token or SETTINGS.get("bot_token", ""))
        await bot.send_message(
            chat_id=chat_id,
            text="🏛️ **پیام تست از ربات تخت جمشید**\n\n✅ ربات با موفقیت کار میکند!",
            parse_mode="Markdown"
        )
        return {"ok": True, "message": "پیام تست ارسال شد!"}
    except Exception as e:
        raise HTTPException(400, f"خطا در ارسال پیام: {str(e)}")

# ─── API: Node Management ────────────────────────────────────────────────────

@app.get("/api/nodes")
async def get_nodes(_=Depends(require_auth)):
    async with NODES_LOCK:
        return {"nodes": list(NODES.values())}

@app.post("/api/nodes")
async def create_node(request: Request, _=Depends(require_auth)):
    body = await request.json()
    
    node_id = secrets.token_urlsafe(8)
    name = body.get("name", "Node جدید").strip()[:50]
    location = body.get("location", "🌍 جهانی")
    host = body.get("host", "").strip()
    port = int(body.get("port", 443))
    protocol = body.get("protocol", "vless-ws")
    fingerprint = body.get("fingerprint", "chrome")
    api_url = body.get("api_url", "").strip()
    enabled = body.get("enabled", True)
    
    if not host:
        raise HTTPException(400, "هاست اجباری است")
    
    async with NODES_LOCK:
        NODES[node_id] = {
            "id": node_id,
            "name": name,
            "location": location,
            "host": host,
            "port": port,
            "protocol": protocol,
            "fingerprint": fingerprint,
            "api_url": api_url,
            "enabled": enabled,
            "created_at": datetime.now().isoformat(),
        }
    
    await save_state()
    log_activity("node", f"Node «{name}» ساخته شد", "ok")
    return {"ok": True, "node": NODES[node_id]}

@app.patch("/api/nodes/{node_id}")
async def update_node(node_id: str, request: Request, _=Depends(require_auth)):
    body = await request.json()
    async with NODES_LOCK:
        if node_id not in NODES:
            raise HTTPException(404, "Node یافت نشد")
        node = NODES[node_id]
        if "name" in body:
            node["name"] = body["name"].strip()[:50]
        if "location" in body:
            node["location"] = body["location"]
        if "host" in body:
            node["host"] = body["host"].strip()
        if "port" in body:
            node["port"] = int(body["port"])
        if "protocol" in body:
            node["protocol"] = body["protocol"]
        if "fingerprint" in body:
            node["fingerprint"] = body["fingerprint"]
        if "api_url" in body:
            node["api_url"] = body["api_url"].strip()
        if "enabled" in body:
            node["enabled"] = bool(body["enabled"])
    await save_state()
    log_activity("node", f"Node «{node['name']}» ویرایش شد", "info")
    return {"ok": True}

@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: str, _=Depends(require_auth)):
    async with NODES_LOCK:
        if node_id not in NODES:
            raise HTTPException(404, "Node یافت نشد")
        name = NODES[node_id].get("name", "نامشخص")
        del NODES[node_id]
    await save_state()
    log_activity("node", f"Node «{name}» حذف شد", "err")
    return {"ok": True}

# ─── API: Settings ─────────────────────────────────────────────────────────

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

@app.post("/api/settings/theme")
async def set_theme(request: Request, _=Depends(require_auth)):
    body = await request.json()
    theme = body.get("theme", "dark")
    if theme in ["dark", "light"]:
        SETTINGS["theme"] = theme
        await save_state()
        return {"ok": True, "theme": theme}
    raise HTTPException(status_code=400, detail="تم نامعتبر")

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
        "active_links": sum(1 for l in LINKS.values() if is_link_allowed(l)),
        "nodes_count": len(NODES)
    }

# ─── API: Inbound ────────────────────────────────────────────────────────────

@app.get("/api/inbound")
async def get_inbound(_=Depends(require_auth)):
    return {
        "port": DEFAULT_PORT,
        "protocol": SETTINGS.get("default_protocol", "vless"),
        "host": get_host(),
        "is_active": True
    }

# ─── API: Links ─────────────────────────────────────────────────────────────

@app.post("/api/links")
async def create_link(request: Request, _=Depends(require_auth)):
    body = await request.json()
    label = (body.get("label") or "لینک جدید").strip()[:60]
    lv = float(body.get("limit_value") or 0)
    lu = body.get("limit_unit") or "GB"
    limit_bytes = 0 if lv <= 0 else parse_size_to_bytes(lv, lu)
    exp_days = int(body.get("expires_days") or 0)
    
    expires_at = None
    if exp_days > 0:
        exp_date = datetime.now() + timedelta(days=exp_days)
        expires_at = exp_date.isoformat()
    
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
    
    # انتخاب Node
    node_id = body.get("node_id") or None
    node_host = None
    node_port = DEFAULT_PORT
    node_name = "پیش‌فرض"
    
    if node_id:
        async with NODES_LOCK:
            node = NODES.get(node_id)
            if node and node.get("enabled", True):
                node_host = node.get("host")
                node_port = node.get("port", DEFAULT_PORT)
                node_name = node.get("name", "Unknown")
    
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
            "node_id": node_id,
            "node_host": node_host,
            "node_port": node_port,
            "node_name": node_name,
        }

    if sub_id:
        async with SUBS_LOCK:
            if sub_id in SUBS:
                ids = SUBS[sub_id].setdefault("link_ids", [])
                if uid not in ids:
                    ids.append(uid)

    asyncio.create_task(save_state())
    
    host = get_host()
    final_host = node_host if node_host else host
    final_port = node_port if node_host else DEFAULT_PORT
    
    remark = f"🏛️ {label}"
    main_link = generate_vless_link(uid, final_host, remark=remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=False)
    
    log_activity("link", f"کانفیگ «{label}» ساخته شد روی Node: {node_name}", "ok")
    
    link_data = {
        "uuid": uid,
        **LINKS[uid],
        "has_password": password_hash is not None,
        "vless_link": main_link,
        "sub_url": f"https://{host}/sub/{uid}",
        "warning_config": "",
        "node_name": node_name,
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
        label = d.get("label", "کاربر")
        remark = f"🏛️ {label}"
        
        last_connected = None
        for c in connections.values():
            if c.get("uuid") == uid:
                if not last_connected or c.get("connected_at") > last_connected:
                    last_connected = c.get("connected_at")
        
        active = d.get("active", True) and not is_link_expired(d)
        node_name = d.get("node_name", "پیش‌فرض")
        node_host = d.get("node_host")
        final_host = node_host if node_host else host
        final_port = d.get("node_port", DEFAULT_PORT) if node_host else DEFAULT_PORT
        
        result.append({
            "uuid": uid,
            **d,
            "protocol": proto,
            "fingerprint": fp,
            "max_devices": d.get("max_devices", 0),
            "expired": is_link_expired(d),
            "has_password": d.get("password_hash") is not None,
            "last_connected_at": last_connected,
            "vless_link": generate_vless_link(uid, final_host, remark=remark, protocol=proto, fingerprint=fp, port=final_port, fake_port=False),
            "sub_url": f"https://{host}/sub/{uid}",
            "warning_config": "",
            "node_name": node_name,
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
            if ed > 0:
                exp_date = datetime.now() + timedelta(days=ed)
                link["expires_at"] = exp_date.isoformat()
            else:
                link["expires_at"] = None
        if "max_devices" in body:
            link["max_devices"] = int(body["max_devices"])
        if "fingerprint" in body and body["fingerprint"] in FINGERPRINTS:
            link["fingerprint"] = body["fingerprint"]
        if "protocol" in body and body["protocol"] in PROTOCOLS:
            link["protocol"] = body["protocol"]
        
        # تغییر Node
        if "node_id" in body:
            new_node_id = body["node_id"]
            if new_node_id:
                async with NODES_LOCK:
                    node = NODES.get(new_node_id)
                    if node and node.get("enabled", True):
                        link["node_id"] = new_node_id
                        link["node_host"] = node.get("host")
                        link["node_port"] = node.get("port", DEFAULT_PORT)
                        link["node_name"] = node.get("name", "Unknown")
                    else:
                        link["node_id"] = None
                        link["node_host"] = None
                        link["node_port"] = DEFAULT_PORT
                        link["node_name"] = "پیش‌فرض"
            else:
                link["node_id"] = None
                link["node_host"] = None
                link["node_port"] = DEFAULT_PORT
                link["node_name"] = "پیش‌فرض"
        
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
    hourly_data = {}
    now = datetime.now()
    for i in range(30):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        if day in hourly_traffic_history:
            for hour, bytes_count in hourly_traffic_history[day].items():
                hourly_data[hour] = hourly_data.get(hour, 0) + bytes_count
    return {
        "active_connections": len(connections),
        "total_traffic_mb": round(stats["total_bytes"] / (1024 ** 2), 2),
        "total_requests": stats["total_requests"],
        "total_errors": stats["total_errors"],
        "uptime": uptime(),
        "timestamp": datetime.now().isoformat(),
        "hourly": dict(hourly_traffic),
        "hourly_history": hourly_data,
        "recent_errors": list(error_logs)[-10:],
        "links_count": len(snap),
        "active_links": sum(1 for l in snap.values() if is_link_allowed(l)),
        "expired_links": sum(1 for l in snap.values() if is_link_expired(l)),
        "subs_count": len(SUBS),
        "nodes_count": len(NODES),
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
    async with NODES_LOCK:
        nodes = dict(NODES)
    hist_dict = {}
    for day, hours in hourly_traffic_history.items():
        hist_dict[day] = dict(hours)
    return {
        "links": links,
        "subs": subs,
        "nodes": nodes,
        "password_hash": AUTH["password_hash"],
        "settings": SETTINGS,
        "hourly_traffic": dict(hourly_traffic),
        "hourly_traffic_history": hist_dict,
        "exported_at": datetime.now().isoformat(),
        "version": "10.0"
    }

@app.post("/api/backup/restore")
async def restore_backup(request: Request, _=Depends(require_auth)):
    global hourly_traffic_history, NODES
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
        if "nodes" in body and isinstance(body["nodes"], dict):
            async with NODES_LOCK:
                NODES.clear()
                NODES.update(body["nodes"])
        if "password_hash" in body:
            AUTH["password_hash"] = body["password_hash"]
        if "settings" in body and isinstance(body["settings"], dict):
            SETTINGS.update(body["settings"])
        if "hourly_traffic" in body:
            hourly_traffic.clear()
            hourly_traffic.update(body["hourly_traffic"])
        if "hourly_traffic_history" in body:
            hourly_traffic_history = defaultdict(lambda: defaultdict(int))
            for day, hours in body["hourly_traffic_history"].items():
                hourly_traffic_history[day] = defaultdict(int, hours)
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
        now = datetime.now()
        day_key = now.strftime("%Y-%m-%d")
        hour_key = now.strftime("%H:00")
        hourly_traffic[hour_key] = hourly_traffic.get(hour_key, 0) + n
        hourly_traffic_history[day_key][hour_key] = hourly_traffic_history[day_key].get(hour_key, 0) + n
        limit = link.get("limit_bytes", 0)
        used = link.get("used_bytes", 0)
        if limit > 0 and used / limit > 0.8 and not link.get("alert_80"):
            link["alert_80"] = True
            log_activity("warning", f"⚠️ مصرف کانفیگ {link.get('label')} به 80% رسید", "warn")
            if SETTINGS.get("bot_enabled") and SETTINGS.get("bot_admin_chat_id"):
                await send_bot_message(
                    SETTINGS["bot_admin_chat_id"],
                    f"⚠️ **هشدار مصرف!**\n\n"
                    f"👤 کاربر: {link.get('label')}\n"
                    f"📊 مصرف: {fmt_bytes(used)} / {fmt_bytes(limit)}\n"
                    f"📈 درصد: {int((used/limit)*100)}%\n"
                    f"🌐 Node: {link.get('node_name', 'پیش‌فرض')}\n\n"
                    f"🔗 پنل: {get_host()}/dashboard"
                )
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

# ─── ===== ساب‌لینک با ۳ کانفیگ ===== ──────────────────────────────────

@app.get("/sub/{uuid}")
async def subscription_single(request: Request, uuid: str):
    import base64
    user_agent = request.headers.get("user-agent", "").lower()
    is_browser = any(b in user_agent for b in [
        "chrome", "firefox", "safari", "edge", "opera", "brave",
        "msie", "trident"
    ])
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        if is_browser:
            return HTMLResponse("""<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>🏛️ کاربر یافت نشد</title><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;800&display=swap" rel="stylesheet"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Vazirmatn',sans-serif;background:#0a0a1a;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#F5ECD7}.card{background:rgba(10,10,30,0.85);backdrop-filter:blur(30px);border:1px solid rgba(212,175,55,0.12);border-radius:28px;padding:40px;max-width:420px;text-align:center}.icon{font-size:64px;margin-bottom:16px}h2{font-size:22px;font-weight:800;margin-bottom:8px}p{color:#8A7A4A;font-size:13px;line-height:1.8}</style></head><body><div class="card"><div class="icon">🏛️</div><h2>کاربر یافت نشد</h2><p>لینک ساب‌لینک معتبر نیست یا کاربر حذف شده است.</p></div></body></html>""", status_code=404)
        else:
            raise HTTPException(status_code=404, detail="user not found")
    if not is_link_allowed(link):
        if is_browser:
            return HTMLResponse("""<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>⛔ کاربر غیرفعال</title><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;800&display=swap" rel="stylesheet"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Vazirmatn',sans-serif;background:#0a0a1a;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#F5ECD7}.card{background:rgba(10,10,30,0.85);backdrop-filter:blur(30px);border:1px solid rgba(239,68,68,0.12);border-radius:28px;padding:40px;max-width:420px;text-align:center}.icon{font-size:64px;margin-bottom:16px}h2{font-size:22px;font-weight:800;margin-bottom:8px}p{color:#8A7A4A;font-size:13px;line-height:1.8}.status{color:#F87171}</style></head><body><div class="card"><div class="icon">⛔</div><h2>کاربر غیرفعال یا منقضی</h2><p class="status">این کانفیگ فعال نیست یا تاریخ انقضای آن گذشته است.</p></div></body></html>""", status_code=403)
        else:
            raise HTTPException(status_code=403, detail="user disabled or expired")
    
    host = get_host()
    label = link.get("label", "کاربر")
    protocol = link.get("protocol", DEFAULT_PROTOCOL)
    fingerprint = link.get("fingerprint", "chrome")
    limit_bytes = link.get("limit_bytes", 0)
    used_bytes = link.get("used_bytes", 0)
    expires_at = link.get("expires_at")
    max_devices = link.get("max_devices", 0)
    node_name = link.get("node_name", "پیش‌فرض")
    node_host = link.get("node_host")
    node_port = link.get("node_port", DEFAULT_PORT)
    
    percent = 0
    if limit_bytes > 0:
        percent = min(100, (used_bytes / limit_bytes) * 100)
    
    days_left = "نامحدود"
    if expires_at:
        try:
            clean_exp = expires_at.replace('Z', '').replace('+00:00', '')
            if 'T' in clean_exp:
                exp_date = datetime.fromisoformat(clean_exp)
            else:
                exp_date = datetime.fromisoformat(clean_exp)
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=IRAN_TZ)
            now = datetime.now(IRAN_TZ)
            days = (exp_date - now).days
            if days > 0:
                days_left = f"{days} روز"
            elif days == 0:
                days_left = "امروز"
            else:
                days_left = "منقضی"
        except:
            days_left = "نامشخص"
    
    remaining_bytes = limit_bytes - used_bytes if limit_bytes > 0 else 0
    remaining_val, remaining_unit = fmt_bytes_short(remaining_bytes) if remaining_bytes > 0 else ("∞", "")
    used_val, used_unit = fmt_bytes_short(used_bytes)
    limit_val, limit_unit = fmt_bytes_short(limit_bytes) if limit_bytes > 0 else ("∞", "")
    
    user_ip = "نامشخص"
    for c in connections.values():
        if c.get("uuid") == uuid:
            user_ip = c.get("ip", "نامشخص")
            break
    
    # استفاده از هاست Node اگر وجود داشته باشد
    final_host = node_host if node_host else host
    final_port = node_port if node_host else DEFAULT_PORT
    
    # ساخت ۳ کانفیگ
    main_remark = f"🏛️ {label}"
    main_link = generate_vless_link(uuid, final_host, remark=main_remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=False)
    
    time_remark = f"⏳ {days_left}"
    time_link = generate_vless_link(uuid, final_host, remark=time_remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=True)
    
    if limit_bytes > 0:
        volume_remark = f"📊 {remaining_val} {remaining_unit}" if remaining_bytes > 0 else "📊 0 B"
    else:
        volume_remark = "📊 ∞"
    volume_link = generate_vless_link(uuid, final_host, remark=volume_remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=True)
    
    if not is_browser:
        config_lines = [main_link, time_link, volume_link]
        content = "\n".join(config_lines)
        content_b64 = base64.b64encode(content.encode()).decode()
        return Response(
            content=content_b64,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=config_{uuid[:8]}.txt",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "profile-title": quote(f"🏛️ {label} ({node_name})"),
                "profile-update-interval": "1",
                "profile-web-page-url": f"https://{host}/info/{uuid}",
            }
        )
    
    from pages import get_sub_page_html
    active_connections_list = []
    for c in connections.values():
        if c.get("uuid") == uuid:
            active_connections_list.append(c)
    active_connections_count = len(active_connections_list)
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
        "vless_links": [main_link, time_link, volume_link],
        "vless_link": main_link,
        "sub_url": f"https://{host}/sub/{uuid}",
        "user_ip": user_ip,
        "percent": percent,
        "days_left": days_left,
        "used_fmt": fmt_bytes(used_bytes),
        "used_val": used_val,
        "used_unit": used_unit,
        "limit_fmt": fmt_bytes(limit_bytes) if limit_bytes > 0 else "نامحدود",
        "limit_val": limit_val,
        "limit_unit": limit_unit,
        "max_devices": max_devices,
        "time_link": time_link,
        "volume_link": volume_link,
        "main_link": main_link,
        "remaining_val": remaining_val,
        "remaining_unit": remaining_unit,
        "node_name": node_name,
        "node_host": node_host,
        "node_port": node_port,
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
                label = d.get("label", "کاربر")
                remark = f"🏛️ {label}"
                node_host = d.get("node_host")
                node_port = d.get("node_port", DEFAULT_PORT) if node_host else DEFAULT_PORT
                final_host = node_host if node_host else host
                lines.append(generate_vless_link(uid, final_host, remark=remark, protocol=d.get("protocol", DEFAULT_PROTOCOL), fingerprint=fp, port=final_port, fake_port=False))
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
                label = link.get("label", "کاربر")
                remark = f"🏛️ {label}"
                node_host = link.get("node_host")
                node_port = link.get("node_port", DEFAULT_PORT) if node_host else DEFAULT_PORT
                final_host = node_host if node_host else host
                lines.append(generate_vless_link(lid, final_host, remark=remark, protocol=link.get("protocol", DEFAULT_PROTOCOL), fingerprint=fp, port=final_port, fake_port=False))
    content = base64.b64encode("\n".join(lines).encode()).decode()
    return Response(
        content=content,
        media_type="text/plain",
        headers={
            "profile-title": quote(sub["name"]),
            "profile-update-interval": "12",
        }
    )

@app.get("/info/{uuid}")
async def info_page(uuid: str, request: Request):
    from pages import get_sub_page_html
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        return HTMLResponse("""<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>🏛️ کاربر یافت نشد</title><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;800&display=swap" rel="stylesheet"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Vazirmatn',sans-serif;background:#0a0a1a;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#F5ECD7}.card{background:rgba(10,10,30,0.85);backdrop-filter:blur(30px);border:1px solid rgba(212,175,55,0.12);border-radius:28px;padding:40px;max-width:420px;text-align:center}.icon{font-size:64px;margin-bottom:16px}h2{font-size:22px;font-weight:800;margin-bottom:8px}p{color:#8A7A4A;font-size:13px;line-height:1.8}</style></head><body><div class="card"><div class="icon">🏛️</div><h2>کاربر یافت نشد</h2><p>لینک اطلاعات معتبر نیست یا کاربر حذف شده است.</p></div></body></html>""", status_code=404)
    if not is_link_allowed(link):
        return HTMLResponse("""<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>⛔ کاربر غیرفعال</title><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;800&display=swap" rel="stylesheet"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Vazirmatn',sans-serif;background:#0a0a1a;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#F5ECD7}.card{background:rgba(10,10,30,0.85);backdrop-filter:blur(30px);border:1px solid rgba(239,68,68,0.12);border-radius:28px;padding:40px;max-width:420px;text-align:center}.icon{font-size:64px;margin-bottom:16px}h2{font-size:22px;font-weight:800;margin-bottom:8px}p{color:#8A7A4A;font-size:13px;line-height:1.8}.status{color:#F87171}</style></head><body><div class="card"><div class="icon">⛔</div><h2>کاربر غیرفعال یا منقضی</h2><p class="status">این کانفیگ فعال نیست یا تاریخ انقضای آن گذشته است.</p></div></body></html>""", status_code=403)
    
    host = get_host()
    label = link.get("label", "کاربر")
    protocol = link.get("protocol", DEFAULT_PROTOCOL)
    fingerprint = link.get("fingerprint", "chrome")
    limit_bytes = link.get("limit_bytes", 0)
    used_bytes = link.get("used_bytes", 0)
    expires_at = link.get("expires_at")
    max_devices = link.get("max_devices", 0)
    node_name = link.get("node_name", "پیش‌فرض")
    node_host = link.get("node_host")
    node_port = link.get("node_port", DEFAULT_PORT)
    
    percent = 0
    if limit_bytes > 0:
        percent = min(100, (used_bytes / limit_bytes) * 100)
    days_left = "نامحدود"
    if expires_at:
        try:
            clean_exp = expires_at.replace('Z', '').replace('+00:00', '')
            if 'T' in clean_exp:
                exp_date = datetime.fromisoformat(clean_exp)
            else:
                exp_date = datetime.fromisoformat(clean_exp)
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=IRAN_TZ)
            now = datetime.now(IRAN_TZ)
            days = (exp_date - now).days
            if days > 0:
                days_left = f"{days} روز"
            elif days == 0:
                days_left = "امروز"
            else:
                days_left = "منقضی"
        except:
            days_left = "نامشخص"
    
    user_ip = "نامشخص"
    for c in connections.values():
        if c.get("uuid") == uuid:
            user_ip = c.get("ip", "نامشخص")
            break
    
    remaining_bytes = limit_bytes - used_bytes if limit_bytes > 0 else 0
    remaining_val, remaining_unit = fmt_bytes_short(remaining_bytes) if remaining_bytes > 0 else ("∞", "")
    
    final_host = node_host if node_host else host
    final_port = node_port if node_host else DEFAULT_PORT
    
    main_remark = f"🏛️ {label}"
    main_link = generate_vless_link(uuid, final_host, remark=main_remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=False)
    time_remark = f"⏳ {days_left}"
    time_link = generate_vless_link(uuid, final_host, remark=time_remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=True)
    if limit_bytes > 0:
        volume_remark = f"📊 {remaining_val} {remaining_unit}" if remaining_bytes > 0 else "📊 0 B"
    else:
        volume_remark = "📊 ∞"
    volume_link = generate_vless_link(uuid, final_host, remark=volume_remark, protocol=protocol, fingerprint=fingerprint, port=final_port, fake_port=True)
    
    active_connections_list = []
    for c in connections.values():
        if c.get("uuid") == uuid:
            active_connections_list.append(c)
    active_connections_count = len(active_connections_list)
    last_connected = None
    for c in connections.values():
        if c.get("uuid") == uuid:
            if not last_connected or c.get("connected_at") > last_connected:
                last_connected = c.get("connected_at")
    used_val, used_unit = fmt_bytes_short(used_bytes)
    limit_val, limit_unit = fmt_bytes_short(limit_bytes) if limit_bytes > 0 else ("∞", "")
    link_data = {
        **link,
        "expired": is_link_expired(link),
        "active_connections": active_connections_count,
        "active_connections_list": active_connections_list,
        "last_connected_at": last_connected,
        "vless_links": [main_link, time_link, volume_link],
        "vless_link": main_link,
        "sub_url": f"https://{host}/sub/{uuid}",
        "user_ip": user_ip,
        "percent": percent,
        "days_left": days_left,
        "used_fmt": fmt_bytes(used_bytes),
        "used_val": used_val,
        "used_unit": used_unit,
        "limit_fmt": fmt_bytes(limit_bytes) if limit_bytes > 0 else "نامحدود",
        "limit_val": limit_val,
        "limit_unit": limit_unit,
        "max_devices": max_devices,
        "time_link": time_link,
        "volume_link": volume_link,
        "main_link": main_link,
        "remaining_val": remaining_val,
        "remaining_unit": remaining_unit,
        "node_name": node_name,
        "node_host": node_host,
        "node_port": node_port,
    }
    return HTMLResponse(content=get_sub_page_html(uuid, link_data))

# ─── HTML Pages ─────────────────────────────────────────────────────────────

from pages import LOGIN_HTML, DASHBOARD_HTML

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
    <head><meta charset="UTF-8"><title>🏛️ Persepolis Gateway</title>
    <style>
    body{font-family:sans-serif;background:#0a0a1a;color:#F5ECD7;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
    .card{text-align:center;padding:40px;background:rgba(20,15,10,0.7);border-radius:20px;border:1px solid rgba(212,175,55,0.2)}
    h1{font-size:48px;margin:0}
    .sub{color:#8A7A4A}
    a{color:#D4A843;text-decoration:none;font-weight:bold}
    </style>
    </head>
    <body>
    <div class="card">
        <h1>🏛️</h1>
        <h2>Persepolis Gateway v10 Pro</h2>
        <p class="sub">پنل مدیریت فیلترشکن</p>
        <a href="/login">ورود به پنل →</a>
    </div>
    </body>
    </html>
    """)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["port"], log_level="info", workers=1)
