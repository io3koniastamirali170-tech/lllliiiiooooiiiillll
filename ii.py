#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════╗
║        💎 VIP SERVICES PRO — بات خدمات مجازی        ║
║     فروشگاه + بازی‌ها + کد هدیه + پنل ادمین کامل     ║
╚════════════════════════════════════════════════════╝

✅ سازگار با دیتابیس نسخه قبلی (هیچ داده‌ای پاک نمی‌شود)

اجرا:
    pip install "python-telegram-bot>=20.7"
    BOT_TOKEN="123456:ABC..." python3 vip_bot_pro.py

متغیرهای محیطی:
    BOT_TOKEN  (اجباری)  توکن بات از BotFather
    ADMIN_ID   (اختیاری) آیدی عددی ادمین
    DB_PATH    (اختیاری) مسیر فایل دیتابیس
"""

import os
import re
import json
import time
import random
import string
import shutil
import asyncio
import sqlite3
import logging
import tempfile
from datetime import datetime
from collections import deque, defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import (
    Application, ApplicationHandlerStop, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, ConversationHandler, TypeHandler, filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ════════════════════ ⚙️ تنظیمات اصلی ════════════════════
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7438138322"))
DEFAULT_BOT_NAME = "💎 VIP Services"
WEBSITE_URL = "https://liiiiiooiiiillll.sryze.cc"
OWNER_USERNAME = "@liiiiiooiiiillll"

NEW_USER_BONUS = 10          # سکه هدیه عضویت
REFERRAL_BONUS = 15          # سکه هر دعوت موفق

# ── سیستم تجربه (XP) ──
XP_DAILY = 8
XP_GAME = 3
XP_WIN = 6
XP_REFERRAL = 15
XP_GIFT = 5

# ── محدودیت روزانه بازی‌های تک‌نفره ──
LIMIT_SLOTS = 15
LIMIT_GUESS = 10
LIMIT_FLIP = 15
GUESS_COST = 5
GUESS_PRIZE = 20
SLOT_BETS = [5, 10, 25, 50]
FLIP_BETS = [5, 10, 25, 50]

DEFAULT_CATEGORIES = {"general": "🌐 عمومی", "premium": "💎 پریمیوم", "hot": "🔥 ویژه"}

# ════════════════════ 🗄 دیتابیس ════════════════════
DB_PATH = os.environ.get("DB_PATH", "vip_bot.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    coins INTEGER DEFAULT 0,
    used_configs INTEGER DEFAULT 0,
    last_daily REAL,
    country TEXT,
    join_date TEXT,
    is_banned INTEGER DEFAULT 0,
    total_spent INTEGER DEFAULT 0,
    referal_code TEXT UNIQUE,
    refered_by INTEGER DEFAULT 0,
    game_wins INTEGER DEFAULT 0,
    game_losses INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    config TEXT,
    price INTEGER DEFAULT 10,
    category TEXT DEFAULT 'general',
    stock INTEGER DEFAULT 999,
    sales_count INTEGER DEFAULT 0,
    created_at REAL,
    is_active INTEGER DEFAULT 1
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    description TEXT,
    date REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS support_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT,
    is_from_admin INTEGER DEFAULT 0,
    date REAL,
    is_read INTEGER DEFAULT 0,
    reply_to_id INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS gift_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    amount INTEGER,
    max_uses INTEGER DEFAULT 1,
    used_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS gift_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT,
    user_id INTEGER,
    date REAL,
    UNIQUE(code, user_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS game_plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    game TEXT,
    day TEXT,
    count INTEGER DEFAULT 0,
    UNIQUE(user_id, game, day)
)
""")

conn.commit()

# ── مهاجرت امن: ستون‌های جدید بدون پاک شدن داده‌ها ──
for alter_sql in [
    "ALTER TABLE configs ADD COLUMN sales_count INTEGER DEFAULT 0",
    "ALTER TABLE configs ADD COLUMN is_active INTEGER DEFAULT 1",
    "ALTER TABLE users ADD COLUMN total_spent INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN game_wins INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN game_losses INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1",
    "ALTER TABLE users ADD COLUMN streak INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN last_seen REAL DEFAULT 0",
]:
    try:
        cur.execute(alter_sql)
        conn.commit()
    except sqlite3.OperationalError:
        pass

cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_cfg_cat ON configs(category)")
conn.commit()

# ════════════════════ 🔧 تنظیمات پایدار ════════════════════
def get_setting(key: str, default=""):
    cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    cur.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

_DEFAULT_SETTINGS = {
    "maintenance_mode": "0",
    "purchase_notify": "1",
    "join_notify": "1",
    "force_join": "0",
    "force_channels": "[]",
    "daily_min": "15",
    "daily_max": "50",
    "game_reward": "5",
    "bot_name": DEFAULT_BOT_NAME,
}
for _k, _v in _DEFAULT_SETTINGS.items():
    if get_setting(_k, None) is None:
        set_setting(_k, _v)
if get_setting("welcome_msg", None) is None:
    set_setting("welcome_msg", "🌟 به " + get_setting("bot_name", DEFAULT_BOT_NAME) + " خوش اومدی!")

def bot_name() -> str:
    return get_setting("bot_name", DEFAULT_BOT_NAME)

def is_maintenance() -> bool:
    return get_setting("maintenance_mode") == "1"

def get_categories() -> dict:
    try:
        cats = json.loads(get_setting("categories", "{}"))
    except Exception:
        cats = {}
    if not cats:
        cats = dict(DEFAULT_CATEGORIES)
        set_setting("categories", json.dumps(cats, ensure_ascii=False))
    return cats

def save_categories(cats: dict):
    set_setting("categories", json.dumps(cats, ensure_ascii=False))

def get_channels() -> list:
    try:
        chans = json.loads(get_setting("force_channels", "[]"))
        return [c for c in chans if isinstance(c, str)]
    except Exception:
        return []

def save_channels(chans: list):
    set_setting("force_channels", json.dumps(chans, ensure_ascii=False))

# ════════════════════ 💬 حالت‌های گفتگو ════════════════════
(ASK_AMOUNT, ADDCFG_NAME, ADDCFG_CONTENT, ADDCFG_CATEGORY, ADDCFG_PRICE_STOCK,
 EDIT_PRICE_STOCK, BC_TEXT, BC_CONFIRM, SEND_MSG_UID, SEND_MSG_TEXT,
 SUPPORT_MSG, ADMIN_REPLY_MSG, REDEEM_CODE, GIFT_CREATE, SET_WELCOME,
 SET_DAILY, SET_BOTNAME, ADD_CHANNEL, ADDCAT_NAME, USER_SEARCH) = range(20)

# ════════════════════ 🎨 قالب و ابزار رابط کاربری ════════════════════
DIV = "─────────────────"

def md_escape(text) -> str:
    return re.sub(r'([_*`\[])', r'\\\1', str(text))

def fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def panel(title: str, rows, tip: str = None) -> str:
    """قالب یکدست همه صفحه‌ها: تیتر + جداکننده + بدنه + نکته"""
    if isinstance(rows, str):
        rows = [rows]
    parts = [f"◈ *{title}*", DIV]
    parts.extend(rows)
    if tip:
        parts.append(DIV)
        parts.append(f"💡 {tip}")
    return "\n".join(parts)

def tree(pairs) -> list:
    """لیست (برچسب، مقدار) → خطوط درختی شیک"""
    lines = []
    n = len(pairs)
    for i, (k, v) in enumerate(pairs):
        if n == 1:
            c = "▪️"
        elif i == 0:
            c = "┌"
        elif i == n - 1:
            c = "└"
        else:
            c = "├"
        lines.append(f"{c} {k}: {v}")
    return lines

def bar(cur_val, total, cells: int = 10) -> str:
    """نوار پیشرفت متنی ▰▰▰▱▱"""
    if total <= 0:
        total = 1
    filled = int(round(cells * max(0, min(cur_val, total)) / total))
    filled = max(0, min(cells, filled))
    return "▰" * filled + "▱" * (cells - filled)

def kb(rows) -> InlineKeyboardMarkup:
    """[[(متن، دیتا/url), ...], ...] → کیبورد"""
    out = []
    for row in rows:
        btns = []
        for label, data in row:
            if isinstance(data, str) and data.startswith("http"):
                btns.append(InlineKeyboardButton(label, url=data))
            else:
                btns.append(InlineKeyboardButton(label, callback_data=data))
        out.append(btns)
    return InlineKeyboardMarkup(out)

def cancel_kb():
    return kb([[("🚫 لغو عملیات", "cancel_conv")]])

def pager_row(prefix: str, page: int, total_pages: int) -> list:
    row = []
    if page > 0:
        row.append(("◀️ قبلی", f"{prefix}_{page - 1}"))
    row.append((f"📄 {page + 1}/{max(1, total_pages)}", "noop"))
    if page < total_pages - 1:
        row.append(("بعدی ▶️", f"{prefix}_{page + 1}"))
    return row

def time_ago(timestamp) -> str:
    if not timestamp:
        return "خیلی وقت پیش"
    diff = time.time() - timestamp
    if diff < 60:
        return f"{int(diff)} ثانیه پیش"
    elif diff < 3600:
        return f"{int(diff // 60)} دقیقه پیش"
    elif diff < 86400:
        return f"{int(diff // 3600)} ساعت پیش"
    return f"{int(diff // 86400)} روز پیش"

# ════════════════════ 🧰 توابع کمکی دیتا ════════════════════
def get_user(uid: int):
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    return cur.fetchone()

def get_config(cfg_id: int):
    cur.execute("SELECT * FROM configs WHERE id=?", (cfg_id,))
    return cur.fetchone()

def log_tx(uid: int, ttype: str, amount: int, desc: str):
    cur.execute(
        "INSERT INTO transactions (user_id, type, amount, description, date) VALUES (?,?,?,?,?)",
        (uid, ttype, amount, desc, time.time()),
    )
    conn.commit()

async def safe_edit(query, text, reply_markup=None, parse_mode=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("edit failed: %s", e)
            try:
                await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception:
                pass

# ════════════════════ ⭐ سیستم سطح و تجربه ════════════════════
def level_from_xp(xp: int) -> int:
    return int((max(0, xp) / 40) ** 0.5) + 1

def xp_bounds(level: int):
    lo = 40 * (level - 1) ** 2
    hi = 40 * level ** 2
    return lo, hi

async def add_xp(uid: int, amount: int, context=None):
    user = get_user(uid)
    if not user:
        return
    new_xp = (user["xp"] or 0) + amount
    new_level = level_from_xp(new_xp)
    old_level = user["level"] or 1
    if new_level > old_level:
        bonus = new_level * 10
        cur.execute("UPDATE users SET xp=?, level=?, coins=coins+? WHERE id=?",
                    (new_xp, new_level, bonus, uid))
        conn.commit()
        log_tx(uid, "level_up", bonus, f"پاداش رسیدن به سطح {new_level}")
        if context:
            try:
                await context.bot.send_message(
                    uid,
                    panel("🎊 ارتقای سطح", [
                        f"تبریک! به *سطح {new_level}* رسیدی 🚀",
                        f"🎁 پاداش: {bonus} سکه",
                    ]),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
    else:
        cur.execute("UPDATE users SET xp=? WHERE id=?", (new_xp, uid))
        conn.commit()

# ── محدودیت روزانه بازی‌ها ──
def plays_today(uid: int, game: str) -> int:
    day = time.strftime("%Y-%m-%d")
    cur.execute("SELECT count FROM game_plays WHERE user_id=? AND game=? AND day=?", (uid, game, day))
    row = cur.fetchone()
    return row["count"] if row else 0

def inc_play(uid: int, game: str):
    day = time.strftime("%Y-%m-%d")
    cur.execute(
        "INSERT INTO game_plays (user_id, game, day, count) VALUES (?,?,?,1) "
        "ON CONFLICT(user_id, game, day) DO UPDATE SET count=count+1",
        (uid, game, day),
    )
    conn.commit()

# ════════════════════ 🛡 ضد اسپم و وضعیت آنلاین ════════════════════
_hits = defaultdict(lambda: deque(maxlen=40))
_seen_cache = {}

def rate_limited(uid: int) -> bool:
    now = time.time()
    dq = _hits[uid]
    dq.append(now)
    recent = sum(1 for t in dq if now - t < 8)
    return recent > 12

def touch_user(uid: int):
    now = time.time()
    if now - _seen_cache.get(uid, 0) > 60:
        _seen_cache[uid] = now
        try:
            cur.execute("UPDATE users SET last_seen=? WHERE id=?", (now, uid))
            conn.commit()
        except Exception:
            pass

# ════════════════════ 📣 عضویت اجباری کانال ════════════════════
_join_cache = {}

async def channels_missing(uid: int, context, force: bool = False) -> list:
    if get_setting("force_join", "0") != "1" or uid == ADMIN_ID:
        return []
    chans = get_channels()
    if not chans:
        return []
    now = time.time()
    cached = _join_cache.get(uid)
    if not force and cached and now - cached[0] < 300:
        return cached[1]
    missing = []
    for ch in chans:
        try:
            m = await context.bot.get_chat_member(ch, uid)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                missing.append(ch)
        except Exception as e:
            logger.warning("join-check failed for %s: %s", ch, e)
    _join_cache[uid] = (now, missing)
    return missing

def join_text(missing: list) -> str:
    rows = ["برای استفاده از بات باید عضو کانال‌های زیر بشی:", ""]
    for ch in missing:
        rows.append(f"📣 {md_escape(ch)}")
    rows.append("")
    rows.append("بعد از عضویت روی «بررسی عضویت» بزن ✅")
    return panel("📣 عضویت در کانال", rows)

def join_kb(missing: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in missing:
        rows.append([(f"➕ عضویت در {ch}", f"https://t.me/{ch.lstrip('@')}")])
    rows.append([("✅ بررسی عضویت", "chk_join")])
    return kb(rows)

# ════════════════════ 🚦 دروازه سراسری (بن/اسپم/تعمیر/جوین) ════════════════════
async def global_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id == ADMIN_ID:
        return
    uid = user.id
    q = update.callback_query

    # 🛡 ضد اسپم روی کلیک‌ها
    if q and rate_limited(uid):
        try:
            await q.answer("🐢 آروم‌تر! چند ثانیه صبر کن...")
        except Exception:
            pass
        raise ApplicationHandlerStop

    row = get_user(uid)
    if row:
        touch_user(uid)
        # ⛔ کاربر مسدود
        if row["is_banned"]:
            try:
                if q:
                    await q.answer("⛔ دسترسی شما مسدود شده است!", show_alert=True)
                elif update.effective_message:
                    await update.effective_message.reply_text(
                        f"⛔ دسترسی شما مسدود شده.\nبرای اعتراض به {OWNER_USERNAME} پیام بده."
                    )
            except Exception:
                pass
            raise ApplicationHandlerStop

    # 🔧 حالت تعمیر (پیام /start صفحه تعمیر را نشان می‌دهد)
    if is_maintenance() and q:
        try:
            await q.answer("🔧 بات در حال بروزرسانیه، کمی بعد دوباره بیا!", show_alert=True)
        except Exception:
            pass
        raise ApplicationHandlerStop

    # 📣 جوین اجباری روی کلیک‌ها
    if q and q.data != "chk_join" and row:
        missing = await channels_missing(uid, context)
        if missing:
            try:
                await q.answer("📣 اول عضو کانال‌ها شو!", show_alert=True)
            except Exception:
                pass
            try:
                await q.message.edit_text(join_text(missing), reply_markup=join_kb(missing),
                                          parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
            raise ApplicationHandlerStop

# ════════════════════ 📱 منوهای اصلی ════════════════════
def main_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🛍 فروشگاه خدمات", "shop")],
        [("👛 کیف پول", "wallet"), ("🎁 جایزه روزانه", "daily")],
        [("🎮 سالن بازی", "games"), ("🏆 رتبه‌بندی", "lb_coins")],
        [("👤 پروفایل من", "profile"), ("🎟 کد هدیه", "redeem_entry")],
        [("👥 دعوت دوستان", "invite")],
        [("💬 پشتیبانی", "support_entry"), ("❓ راهنما", "help")],
        [("🌐 وبسایت ما", WEBSITE_URL)],
    ])

def home_text(u) -> str:
    lvl = u["level"] or 1
    rows = tree([
        ("💰 موجودی", f"{fmt(u['coins'])} سکه"),
        ("⭐ سطح", f"{lvl}"),
        ("🔥 استریک روزانه", f"{u['streak'] or 0} روز"),
    ])
    rows += ["", "یکی از گزینه‌های زیر رو انتخاب کن 👇"]
    return panel(bot_name(), rows)

async def noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ════════════════════ 🚀 شروع ════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if is_maintenance() and uid != ADMIN_ID:
        await update.message.reply_text(
            panel("🔧 حالت تعمیر", [
                "بات در حال تعمیر و بروزرسانیه.",
                "لطفاً کمی بعد دوباره مراجعه کن 🙏",
            ]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb([[("🌐 وبسایت ما", WEBSITE_URL)]]),
        )
        return

    existing = get_user(uid)

    if not existing:
        ref_code = f"VIP{uid % 1000000:06d}"
        join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        country = (user.language_code or "-").upper()

        referrer_id = 0
        if context.args:
            arg = context.args[0].strip()
            cur.execute("SELECT id FROM users WHERE referal_code=?", (arg,))
            row = cur.fetchone()
            if row and row["id"] != uid:
                referrer_id = row["id"]

        cur.execute(
            """INSERT INTO users (id, username, first_name, coins, country, join_date, referal_code, refered_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, user.username or "no_username", user.first_name, NEW_USER_BONUS,
             country, join_date, ref_code, referrer_id),
        )
        conn.commit()
        log_tx(uid, "signup_bonus", NEW_USER_BONUS, "هدیه عضویت")

        if referrer_id:
            cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (REFERRAL_BONUS, referrer_id))
            conn.commit()
            log_tx(referrer_id, "referral_bonus", REFERRAL_BONUS, f"معرفی کاربر {uid}")
            await add_xp(referrer_id, XP_REFERRAL, context)
            try:
                await context.bot.send_message(
                    referrer_id,
                    panel("🎉 دعوت موفق", [
                        "یک نفر با لینک تو عضو شد!",
                        f"🎁 پاداش: +{REFERRAL_BONUS} سکه",
                    ]),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        if get_setting("join_notify", "1") == "1":
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"🆕 *کاربر جدید*\n{DIV}\n"
                    f"👤 {md_escape(user.first_name)}\n"
                    f"🆔 `{uid}`\n"
                    f"🔗 @{md_escape(user.username or '-')}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        missing = await channels_missing(uid, context)
        if missing:
            await update.message.reply_text(join_text(missing), reply_markup=join_kb(missing),
                                            parse_mode=ParseMode.MARKDOWN)
            return

        welcome = get_setting("welcome_msg", "خوش اومدی!")
        await update.message.reply_text(
            panel("🌟 خوش آمدی!", [
                md_escape(welcome),
                "",
                f"🎁 {NEW_USER_BONUS} سکه هدیه گرفتی!",
                f"🔰 کد معرف تو: `{ref_code}`",
            ]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(),
        )
    else:
        cur.execute("UPDATE users SET first_name=?, username=? WHERE id=?",
                    (user.first_name, user.username, uid))
        conn.commit()

        missing = await channels_missing(uid, context)
        if missing:
            await update.message.reply_text(join_text(missing), reply_markup=join_kb(missing),
                                            parse_mode=ParseMode.MARKDOWN)
            return

        fresh = get_user(uid)
        await update.message.reply_text(home_text(fresh), parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=main_menu())

async def chk_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    missing = await channels_missing(uid, context, force=True)
    if missing:
        await q.answer("❌ هنوز عضو همه کانال‌ها نشدی!", show_alert=True)
        return
    await q.answer("✅ عضویتت تایید شد!")
    user = get_user(uid)
    if user:
        await safe_edit(q, home_text(user), reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = get_user(q.from_user.id)
    if not user:
        await safe_edit(q, "برای شروع /start رو بزن.")
        return
    await safe_edit(q, home_text(user), reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)

# ════════════════════ ❓ راهنما و وبسایت ════════════════════
async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = [
        "🛍 از «فروشگاه» سرویس بخر و همون لحظه تحویل بگیر",
        "🎁 هر ۲۴ ساعت «جایزه روزانه» بگیر — استریک = سکه بیشتر!",
        "🎮 تو «سالن بازی» ۵ بازی مختلف در انتظارته",
        "🎟 «کد هدیه» داری؟ واردش کن و سکه بگیر",
        "👥 با «دعوت دوستان» به ازای هر نفر سکه بگیر",
        "⭐ با هر فعالیت XP بگیر و سطحت رو بالا ببر",
        "🏆 خودت رو تو «رتبه‌بندی» محک بزن",
        "💬 سوال داری؟ «پشتیبانی» همیشه بازه",
        "",
        f"👑 مالک: {md_escape(OWNER_USERNAME)}",
    ]
    await safe_edit(q, panel("❓ راهنمای بات", rows),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([
                        [("🌐 وبسایت", WEBSITE_URL)],
                        [("🔙 بازگشت", "back_main")],
                    ]))

async def website_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await safe_edit(q, panel("🌐 وبسایت ما", [f"🔗 آدرس: `{WEBSITE_URL}`"]),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([
                        [("🚀 باز کردن وبسایت", WEBSITE_URL)],
                        [("🔙 بازگشت", "back_main")],
                    ]))

# ════════════════════ 👤 پروفایل و دستاوردها ════════════════════
def achievements_of(u, referred: int) -> list:
    total_games = (u["game_wins"] or 0) + (u["game_losses"] or 0)
    days = 0
    try:
        days = (datetime.now() - datetime.strptime(u["join_date"], "%Y-%m-%d %H:%M:%S")).days
    except Exception:
        pass
    return [
        ("🛍", "اولین خرید", (u["used_configs"] or 0) >= 1),
        ("📦", "مشتری ثابت", (u["used_configs"] or 0) >= 10),
        ("🎲", "اهل بازی", total_games >= 20),
        ("🏆", "قهرمان", (u["game_wins"] or 0) >= 10),
        ("👥", "سفیر", referred >= 5),
        ("💰", "ثروتمند", (u["coins"] or 0) >= 500),
        ("⭐", "کهنه‌کار", days >= 30),
        ("🚀", "سطح ۵", (u["level"] or 1) >= 5),
    ]

async def profile_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    u = get_user(uid)
    cur.execute("SELECT COUNT(*) c FROM users WHERE refered_by=?", (uid,))
    referred = cur.fetchone()["c"]

    lvl = u["level"] or 1
    xp = u["xp"] or 0
    lo, hi = xp_bounds(lvl)
    total_games = (u["game_wins"] or 0) + (u["game_losses"] or 0)
    wr = (u["game_wins"] or 0) * 100 // total_games if total_games else 0

    ach = achievements_of(u, referred)
    earned = [f"{e} {name}" for e, name, ok in ach if ok]
    ach_line = " | ".join(earned) if earned else "هنوز دستاوردی نگرفتی — شروع کن! 💪"

    rows = tree([
        ("🆔 آیدی", f"`{uid}`"),
        ("💰 موجودی", f"{fmt(u['coins'])} سکه"),
        ("📦 خریدها", f"{u['used_configs'] or 0} سرویس"),
        ("💵 مجموع خرید", f"{fmt(u['total_spent'] or 0)} سکه"),
        ("🎮 بازی‌ها", f"{total_games} (برد {u['game_wins'] or 0} | {wr}%)"),
        ("👥 دعوت‌شده‌ها", f"{referred} نفر"),
        ("🔥 استریک", f"{u['streak'] or 0} روز"),
        ("📅 عضویت", md_escape(u["join_date"] or "-")),
    ])
    rows += [
        "",
        f"⭐ *سطح {lvl}*",
        f"{bar(xp - lo, hi - lo)}  {fmt(xp)}/{fmt(hi)} XP",
        "",
        f"🏅 *دستاوردها ({len(earned)}/{len(ach)})*",
        ach_line,
    ]
    await safe_edit(q, panel("👤 پروفایل من", rows),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([
                        [("🏆 رتبه‌بندی", "lb_coins"), ("👛 کیف پول", "wallet")],
                        [("🔙 بازگشت", "back_main")],
                    ]))

# ════════════════════ 👥 دعوت دوستان ════════════════════
async def invite_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user['referal_code']}"
    cur.execute("SELECT COUNT(*) c FROM users WHERE refered_by=?", (uid,))
    referred = cur.fetchone()["c"]
    rows = [
        f"به ازای هر دوستی که با لینکت عضو بشه *{REFERRAL_BONUS} سکه* می‌گیری! 🎉",
        "",
        "🔗 لینک اختصاصی تو:",
        f"`{link}`",
        "",
    ] + tree([
        ("👥 دعوت‌شده‌ها", f"{referred} نفر"),
        ("💰 درآمد از دعوت", f"{fmt(referred * REFERRAL_BONUS)} سکه"),
    ])
    share_text = f"با لینک من عضو شو و {NEW_USER_BONUS} سکه هدیه بگیر! {link}"
    ikb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 اشتراک‌گذاری لینک", switch_inline_query=share_text)],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
    ])
    await safe_edit(q, panel("👥 دعوت دوستان", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=ikb)

# ════════════════════ 🏆 رتبه‌بندی (۳ تب) ════════════════════
async def _lb_render(q, mode: str):
    uid = q.from_user.id
    medals = ["🥇", "🥈", "🥉"]
    if mode == "coins":
        title = "🏆 ثروتمندترین‌ها"
        cur.execute("SELECT first_name, coins FROM users WHERE is_banned=0 ORDER BY coins DESC LIMIT 10")
        rows_db = cur.fetchall()
        lines = []
        for i, r in enumerate(rows_db):
            m = medals[i] if i < 3 else f" {i + 1}."
            lines.append(f"{m} {md_escape(r['first_name'] or 'ناشناس')} — 💰{fmt(r['coins'])}")
        me = get_user(uid)
        cur.execute("SELECT COUNT(*) c FROM users WHERE coins > ? AND is_banned=0", (me["coins"],))
        my_rank = cur.fetchone()["c"] + 1
        lines += ["", f"📍 رتبه تو: *{my_rank}* با {fmt(me['coins'])} سکه"]
    elif mode == "wins":
        title = "🎮 برترین بازیکن‌ها"
        cur.execute("SELECT first_name, game_wins, game_losses FROM users "
                    "WHERE (game_wins + game_losses) > 0 AND is_banned=0 ORDER BY game_wins DESC LIMIT 10")
        rows_db = cur.fetchall()
        lines = []
        for i, r in enumerate(rows_db):
            m = medals[i] if i < 3 else f" {i + 1}."
            total = (r["game_wins"] or 0) + (r["game_losses"] or 0)
            wr = (r["game_wins"] or 0) * 100 // total if total else 0
            lines.append(f"{m} {md_escape(r['first_name'] or 'ناشناس')} — 🏆{r['game_wins']} برد ({wr}%)")
        if not rows_db:
            lines = ["هنوز کسی بازی نکرده — تو اولین باش! 🎲"]
    else:
        title = "⭐ بالاترین سطح‌ها"
        cur.execute("SELECT first_name, level, xp FROM users WHERE is_banned=0 ORDER BY xp DESC LIMIT 10")
        rows_db = cur.fetchall()
        lines = []
        for i, r in enumerate(rows_db):
            m = medals[i] if i < 3 else f" {i + 1}."
            lines.append(f"{m} {md_escape(r['first_name'] or 'ناشناس')} — ⭐ سطح {r['level'] or 1} ({fmt(r['xp'] or 0)} XP)")

    def tab(label, key):
        return (f"• {label} •" if key == mode else label,
                {"coins": "lb_coins", "wins": "lb_wins", "level": "lb_level"}[key])

    await safe_edit(q, panel(title, lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [tab("💰 ثروت", "coins"), tab("🎮 بردها", "wins"), tab("⭐ سطح", "level")],
        [("🔙 بازگشت", "back_main")],
    ]))

async def lb_coins_cb(update, context):
    await update.callback_query.answer()
    await _lb_render(update.callback_query, "coins")

async def lb_wins_cb(update, context):
    await update.callback_query.answer()
    await _lb_render(update.callback_query, "wins")

async def lb_level_cb(update, context):
    await update.callback_query.answer()
    await _lb_render(update.callback_query, "level")

# ════════════════════ 👛 کیف پول و تراکنش‌ها ════════════════════
async def wallet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = get_user(q.from_user.id)
    rows = tree([
        ("💰 موجودی", f"{fmt(u['coins'])} سکه"),
        ("📦 خریدها", f"{u['used_configs'] or 0} سرویس"),
        ("💵 مجموع خرید", f"{fmt(u['total_spent'] or 0)} سکه"),
    ])
    rows += ["", "راه‌های افزایش سکه: 🎁 جایزه روزانه • 🎮 بازی • 👥 دعوت • 🎟 کد هدیه"]
    await safe_edit(q, panel("👛 کیف پول", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("📜 تاریخچه تراکنش‌ها", "tx_hist_0")],
        [("🎟 کد هدیه", "redeem_entry"), ("🎁 جایزه روزانه", "daily")],
        [("🔙 بازگشت", "back_main")],
    ]))

async def tx_hist_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    page = int(context.match.group(1)) if context.match else 0
    uid = q.from_user.id
    per = 8
    cur.execute("SELECT COUNT(*) c FROM transactions WHERE user_id=?", (uid,))
    total = cur.fetchone()["c"]
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    cur.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (uid, per, page * per))
    rows_db = cur.fetchall()
    if not rows_db:
        lines = ["هنوز تراکنشی ثبت نشده."]
    else:
        lines = []
        for r in rows_db:
            sign = "🟢 +" if r["amount"] >= 0 else "🔴 "
            date = datetime.fromtimestamp(r["date"]).strftime("%m-%d %H:%M")
            lines.append(f"{sign}{fmt(r['amount'])} | {date} | {md_escape(r['description'])}")
    await safe_edit(q, panel(f"📜 تراکنش‌ها ({fmt(total)})", lines),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([
                        pager_row("tx_hist", page, pages),
                        [("🔙 کیف پول", "wallet")],
                    ]))

async def tx_hist_legacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.match = None
    await tx_hist_cb(update, context)

# ════════════════════ 🎁 جایزه روزانه با استریک ════════════════════
async def daily_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    user = get_user(uid)
    now = time.time()
    last = user["last_daily"]

    if last and now - last < 86400:
        remaining = int(86400 - (now - last))
        h, m = remaining // 3600, (remaining % 3600) // 60
        await q.answer("⏳ هنوز زوده!")
        rows = [
            f"جایزه بعدی: *{h} ساعت و {m} دقیقه* دیگه",
            "",
            bar(now - last, 86400) + " ⏰",
            "",
            f"🔥 استریک فعلی: {user['streak'] or 0} روز",
            "استریکت رو حفظ کن تا جایزه‌ت بیشتر شه!",
        ]
        await safe_edit(q, panel("🎁 جایزه روزانه", rows), parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb([[("🔙 بازگشت", "back_main")]]))
        return

    streak = (user["streak"] or 0) + 1 if (last and now - last < 172800) else 1
    dmin = int(get_setting("daily_min", "15"))
    dmax = int(get_setting("daily_max", "50"))
    base = random.randint(dmin, max(dmin, dmax))
    extra = min(20, (streak - 1) * 2)
    reward = base + extra

    cur.execute("UPDATE users SET coins=coins+?, last_daily=?, streak=? WHERE id=?",
                (reward, now, streak, uid))
    conn.commit()
    log_tx(uid, "daily_bonus", reward, f"جایزه روزانه (استریک {streak})")
    await add_xp(uid, XP_DAILY, context)

    await q.answer(f"🎁 +{reward} سکه!")
    rows = tree([
        ("🎁 جایزه پایه", f"{base} سکه"),
        ("🔥 بونوس استریک", f"+{extra} سکه"),
        ("💰 مجموع", f"*{reward} سکه*"),
    ])
    rows += ["", f"🔥 استریک: {streak} روز متوالی", "فردا هم بیا تا بونوست بیشتر شه!"]
    await safe_edit(q, panel("🎉 جایزه گرفتی!", rows), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([
                        [("🎮 سالن بازی", "games"), ("🛍 فروشگاه", "shop")],
                        [("🔙 بازگشت", "back_main")],
                    ]))

# ════════════════════ 🛍 فروشگاه ════════════════════
async def shop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cats = get_categories()
    cur.execute("SELECT category, COUNT(*) c FROM configs WHERE stock>0 AND is_active=1 GROUP BY category")
    counts = {r["category"]: r["c"] for r in cur.fetchall()}
    rows = ["دسته‌بندی مورد نظرت رو انتخاب کن:", ""]
    btns = []
    for key, label in cats.items():
        n = counts.get(key, 0)
        btns.append([(f"{label} ({n})", f"shopcat_{key}_0")])
    if not btns:
        rows = ["فعلاً دسته‌بندی‌ای تعریف نشده."]
    btns.append([("🔙 بازگشت", "back_main")])
    await safe_edit(q, panel("🛍 فروشگاه خدمات", rows), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb(btns))

async def _render_category(q, cat_key: str, page: int):
    cats = get_categories()
    label = cats.get(cat_key, cat_key)
    per = 6
    cur.execute("SELECT COUNT(*) c FROM configs WHERE category=? AND stock>0 AND is_active=1", (cat_key,))
    total = cur.fetchone()["c"]
    if total == 0:
        await safe_edit(q, panel(f"📂 {label}", ["📭 فعلاً سرویسی در این دسته موجود نیست.",
                                                "به‌زودی شارژ می‌شه — سر بزن! 👀"]),
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb([[("🔙 فروشگاه", "shop")]]))
        return
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    cur.execute("SELECT * FROM configs WHERE category=? AND stock>0 AND is_active=1 "
                "ORDER BY sales_count DESC LIMIT ? OFFSET ?", (cat_key, per, page * per))
    items = cur.fetchall()

    lines = []
    btns = []
    for cfg in items:
        tag = " 🔥" if (cfg["sales_count"] or 0) >= 10 else (" ⭐" if (cfg["sales_count"] or 0) >= 5 else "")
        lines.append(f"▫️ *{md_escape(cfg['name'])}*{tag}")
        lines.append(f"   💰 {fmt(cfg['price'])} سکه • 📦 {fmt(cfg['stock'])} عدد • 🛍 {fmt(cfg['sales_count'] or 0)} فروش")
        btns.append([(f"🛒 خرید {cfg['name']} • {fmt(cfg['price'])}💰", f"buy_{cfg['id']}")])
    btns.append(pager_row(f"shopcat_{cat_key}", page, pages))
    btns.append([("🔙 فروشگاه", "shop")])
    await safe_edit(q, panel(f"📂 {label} ({fmt(total)} سرویس)", lines),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=kb(btns))

async def shopcat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _render_category(q, context.match.group(1), int(context.match.group(2)))

async def shopcat_legacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _render_category(q, context.match.group(1), 0)

async def buy_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg or cfg["stock"] <= 0 or not cfg["is_active"]:
        await safe_edit(q, panel("❌ ناموجود", ["این سرویس دیگه موجود نیست."]),
                        parse_mode=ParseMode.MARKDOWN, reply_markup=kb([[("🔙 فروشگاه", "shop")]]))
        return
    u = get_user(q.from_user.id)
    after = (u["coins"] or 0) - cfg["price"]
    rows = tree([
        ("📦 سرویس", md_escape(cfg["name"])),
        ("💰 قیمت", f"{fmt(cfg['price'])} سکه"),
        ("📥 موجودی انبار", f"{fmt(cfg['stock'])} عدد"),
        ("👛 موجودی تو", f"{fmt(u['coins'])} سکه"),
        ("🧮 بعد از خرید", f"{fmt(after)} سکه" if after >= 0 else "❌ کافی نیست!"),
    ])
    rows += ["", "خرید رو تایید می‌کنی؟"]
    await safe_edit(q, panel("🧾 تایید خرید", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("✅ تایید و پرداخت", f"confirm_buy_{cfg_id}")],
        [("❌ انصراف", f"shopcat_{cfg['category']}_0")],
    ]))

async def buy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    cfg_id = int(context.match.group(1))

    cfg = get_config(cfg_id)
    if not cfg or cfg["stock"] <= 0 or not cfg["is_active"]:
        await q.answer("❌ تمام شد!", show_alert=True)
        await safe_edit(q, panel("❌ ناموجود", ["این سرویس دیگه موجود نیست."]),
                        parse_mode=ParseMode.MARKDOWN, reply_markup=kb([[("🔙 فروشگاه", "shop")]]))
        return

    user = get_user(uid)
    if user["coins"] < cfg["price"]:
        need = cfg["price"] - user["coins"]
        await q.answer("❌ سکه کافی نداری!", show_alert=True)
        await safe_edit(q, panel("💸 موجودی ناکافی", [
            f"قیمت سرویس: {fmt(cfg['price'])} سکه",
            f"موجودی تو: {fmt(user['coins'])} سکه",
            f"کسری: *{fmt(need)} سکه*",
            "",
            "با جایزه روزانه، بازی و دعوت دوستان سکه جمع کن! 💪",
        ]), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
            [("🎁 جایزه روزانه", "daily"), ("🎮 سالن بازی", "games")],
            [("🔙 فروشگاه", "shop")],
        ]))
        return

    cur.execute("UPDATE users SET coins=coins-?, used_configs=used_configs+1, total_spent=total_spent+? WHERE id=?",
                (cfg["price"], cfg["price"], uid))
    cur.execute("UPDATE configs SET stock=stock-1, sales_count=sales_count+1 WHERE id=?", (cfg_id,))
    conn.commit()
    log_tx(uid, "purchase", -cfg["price"], f"خرید {cfg['name']}")
    await add_xp(uid, max(1, cfg["price"]), context)

    if get_setting("purchase_notify") == "1":
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🛍 *خرید جدید*\n{DIV}\n"
                f"👤 {md_escape(user['first_name'] or '-')} (`{uid}`)\n"
                f"📦 {md_escape(cfg['name'])}\n"
                f"💰 {fmt(cfg['price'])} سکه",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    fresh = get_user(uid)
    await q.answer("✅ خرید موفق!")
    delivery = (
        f"◈ *✅ خرید موفق!*\n{DIV}\n"
        f"📦 سرویس: {md_escape(cfg['name'])}\n"
        f"👛 موجودی جدید: {fmt(fresh['coins'])} سکه\n\n"
        f"📥 *محتوای سرویس:*\n"
        f"```\n{cfg['config']}\n```\n"
        f"{DIV}\n"
        f"💡 مشکلی بود؟ از «پشتیبانی» پیام بده."
    )
    await safe_edit(q, delivery, parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🛒 خرید دوباره", f"shopcat_{cfg['category']}_0")],
        [("💬 پشتیبانی", "support_entry"), ("🏠 منوی اصلی", "back_main")],
    ]))

# ════════════════════ 🎟 کد هدیه (کاربر) ════════════════════
async def redeem_entry_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = [
        "کد هدیه داری؟ 🎁",
        "واردش کن و همون لحظه سکه بگیر!",
        "",
        "کدها رو از کانال ما و ایونت‌ها دنبال کن 👀",
    ]
    await safe_edit(q, panel("🎟 کد هدیه", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("✍️ وارد کردن کد", "redeem_start")],
        [("🔙 بازگشت", "back_main")],
    ]))

async def redeem_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await safe_edit(q, panel("🎟 کد هدیه", ["کدت رو همین الان بفرست:"]),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return REDEEM_CODE

async def receive_redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    code = update.message.text.strip().upper()

    cur.execute("SELECT * FROM gift_codes WHERE code=?", (code,))
    gift = cur.fetchone()

    if not gift or not gift["is_active"]:
        await update.message.reply_text(
            panel("❌ کد نامعتبر", ["این کد وجود نداره یا غیرفعال شده."]),
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
        return ConversationHandler.END

    if gift["used_count"] >= gift["max_uses"]:
        await update.message.reply_text(
            panel("😔 دیر رسیدی!", ["ظرفیت این کد تکمیل شده."]),
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
        return ConversationHandler.END

    cur.execute("SELECT 1 FROM gift_redemptions WHERE code=? AND user_id=?", (code, uid))
    if cur.fetchone():
        await update.message.reply_text(
            panel("⚠️ تکراری", ["تو قبلاً این کد رو استفاده کردی!"]),
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
        return ConversationHandler.END

    cur.execute("UPDATE gift_codes SET used_count=used_count+1 WHERE id=?", (gift["id"],))
    cur.execute("INSERT INTO gift_redemptions (code, user_id, date) VALUES (?,?,?)", (code, uid, time.time()))
    cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (gift["amount"], uid))
    conn.commit()
    log_tx(uid, "gift_code", gift["amount"], f"کد هدیه {code}")
    await add_xp(uid, XP_GIFT, context)

    fresh = get_user(uid)
    await update.message.reply_text(
        panel("🎉 کد فعال شد!", tree([
            ("🎟 کد", f"`{code}`"),
            ("💰 جایزه", f"+{fmt(gift['amount'])} سکه"),
            ("👛 موجودی جدید", f"{fmt(fresh['coins'])} سکه"),
        ])),
        parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    return ConversationHandler.END

# ════════════════════ 💬 پشتیبانی (سمت کاربر) ════════════════════
async def support_entry_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = [
        "سوال یا مشکلی داری؟ 🤝",
        "پیامت مستقیم به دست ادمین می‌رسه و جوابش برات ارسال می‌شه.",
        "",
        "⏱ میانگین زمان پاسخ: چند ساعت",
    ]
    await safe_edit(q, panel("💬 پشتیبانی", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("✍️ ارسال پیام", "support_start")],
        [("🔙 بازگشت", "back_main")],
    ]))

async def support_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await safe_edit(q, panel("✍️ پیام به پشتیبانی", ["پیامت رو همین الان بنویس و بفرست:"]),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return SUPPORT_MSG

async def receive_support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    msg_text = update.message.text

    cur.execute(
        "INSERT INTO support_messages (user_id, message, is_from_admin, date, is_read) VALUES (?,?,0,?,0)",
        (uid, msg_text, time.time()),
    )
    conn.commit()
    msg_id = cur.lastrowid

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 *پیام جدید پشتیبانی* #{msg_id}\n{DIV}\n"
            f"👤 {md_escape(user['first_name'] or 'ناشناس')} (`{uid}`)\n"
            f"🔗 @{md_escape(user['username'] or '-')}\n\n"
            f"💬 {md_escape(msg_text)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb([
                [("💬 پاسخ دادن", f"admin_reply_sel_{uid}_{msg_id}")],
                [("👤 پروفایل کاربر", f"act_manage_{uid}")],
            ]),
        )
    except Exception:
        pass

    await update.message.reply_text(
        panel("✅ ارسال شد!", [
            "پیامت به دست ادمین رسید.",
            "به محض پاسخ، برات ارسال می‌شه 📬",
        ]),
        parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    return ConversationHandler.END

# ════════════════════ 🎮 سالن بازی ════════════════════
WAITING = {"dice": None, "rps": None}
MATCHES = {}
_match_seq = {"n": 0}

def _new_match(kind: str, p1: int, p2: int) -> str:
    _match_seq["n"] += 1
    mid = f"{kind[0]}{_match_seq['n']}"
    MATCHES[mid] = {"kind": kind, "p1": p1, "p2": p2, "v1": None, "v2": None, "ts": time.time()}
    return mid

def game_reward() -> int:
    try:
        return int(get_setting("game_reward", "5"))
    except Exception:
        return 5

async def games_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    u = get_user(uid)
    total = (u["game_wins"] or 0) + (u["game_losses"] or 0)
    wr = (u["game_wins"] or 0) * 100 // total if total else 0
    rows = tree([
        ("🎮 بازی‌های PVP تو", f"{total} (برد {u['game_wins'] or 0} | {wr}%)"),
        ("🎰 اسلات امروز", f"{plays_today(uid, 'slots')}/{LIMIT_SLOTS}"),
        ("🎯 حدس عدد امروز", f"{plays_today(uid, 'guess')}/{LIMIT_GUESS}"),
        ("🪙 شیر یا خط امروز", f"{plays_today(uid, 'flip')}/{LIMIT_FLIP}"),
    ])
    rows += ["", "یه بازی انتخاب کن و سکه ببر! 💰"]
    await safe_edit(q, panel("🎮 سالن بازی", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🎲 تاس PVP", "g_find_dice"), ("✂️ سنگ‌کاغذقیچی PVP", "g_find_rps")],
        [("🎰 اسلات", "g_slots"), ("🪙 شیر یا خط", "g_flip")],
        [("🎯 حدس عدد", "g_guess")],
        [("🏆 جدول بازیکن‌ها", "lb_wins")],
        [("🔙 بازگشت", "back_main")],
    ]))

# ── 🎲 / ✂️ مسابقه‌یابی مشترک PVP ──
GAME_LABEL = {"dice": "🎲 تاس", "rps": "✂️ سنگ‌کاغذقیچی"}

def _dice_kb(mid, pnum):
    return kb([[("🎲 پرتاب تاس", f"dice_roll_{mid}_{pnum}")]])

def _rps_kb(mid, pnum):
    return kb([[
        ("✊ سنگ", f"rps_pick_{mid}_{pnum}_r"),
        ("✋ کاغذ", f"rps_pick_{mid}_{pnum}_p"),
        ("✌️ قیچی", f"rps_pick_{mid}_{pnum}_s"),
    ]])

async def _find_match(update, context, kind: str):
    q = update.callback_query
    uid = q.from_user.id

    if WAITING[kind] == uid:
        await q.answer("⚠️ تو همین الان توی صف انتظاری!", show_alert=True)
        return
    await q.answer()

    if WAITING[kind] is None:
        WAITING[kind] = uid
        await safe_edit(q, panel(f"{GAME_LABEL[kind]} — جستجوی حریف", [
            "⏳ در حال پیدا کردن حریف آنلاین...",
            "به محض پیدا شدن بهت خبر می‌دیم!",
        ]), parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb([[("❌ لغو جستجو", f"g_cancel_{kind}")]]))
        return

    opponent = WAITING[kind]
    WAITING[kind] = None
    mid = _new_match(kind, opponent, uid)

    p1_name = md_escape((get_user(opponent) or {"first_name": "ناشناس"})["first_name"] or "ناشناس")
    p2_name = md_escape(q.from_user.first_name or "ناشناس")
    kb1 = _dice_kb(mid, 1) if kind == "dice" else _rps_kb(mid, 1)
    kb2 = _dice_kb(mid, 2) if kind == "dice" else _rps_kb(mid, 2)
    action = "تاس بنداز" if kind == "dice" else "انتخابت رو بزن"

    try:
        await context.bot.send_message(
            opponent,
            panel(f"{GAME_LABEL[kind]} — حریف پیدا شد!", [
                f"🗡 حریف تو: *{p2_name}*",
                f"🏆 جایزه برنده: {game_reward()} سکه",
                "", f"حالا {action}! 👇",
            ]),
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb1)
    except Exception as e:
        logger.error("notify p1 failed %s: %s", opponent, e)
        MATCHES.pop(mid, None)
        await q.answer("❌ حریف آفلاین بود! دوباره جستجو کن.", show_alert=True)
        return

    await safe_edit(q, panel(f"{GAME_LABEL[kind]} — حریف پیدا شد!", [
        f"🗡 حریف تو: *{p1_name}*",
        f"🏆 جایزه برنده: {game_reward()} سکه",
        "", f"حالا {action}! 👇",
    ]), parse_mode=ParseMode.MARKDOWN, reply_markup=kb2)

async def g_find_dice_cb(update, context):
    await _find_match(update, context, "dice")

async def g_find_rps_cb(update, context):
    await _find_match(update, context, "rps")

async def g_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    kind = context.match.group(1)
    if WAITING.get(kind) == q.from_user.id:
        WAITING[kind] = None
    await q.answer("لغو شد")
    await games_cb(update, context)

async def _pvp_payout(mid_data, winner_num, context, lines_extra):
    """پرداخت جایزه و اعلام نتیجه به هر دو بازیکن"""
    p1, p2 = mid_data["p1"], mid_data["p2"]
    reward = game_reward()
    n1 = md_escape((get_user(p1) or {"first_name": "بازیکن ۱"})["first_name"] or "بازیکن ۱")
    n2 = md_escape((get_user(p2) or {"first_name": "بازیکن ۲"})["first_name"] or "بازیکن ۲")

    lines = list(lines_extra)
    if winner_num == 0:
        lines.append("🤝 *مساوی شد!* جایزه‌ای رد و بدل نشد.")
    else:
        w_uid = p1 if winner_num == 1 else p2
        l_uid = p2 if winner_num == 1 else p1
        w_name = n1 if winner_num == 1 else n2
        cur.execute("UPDATE users SET coins=coins+?, game_wins=game_wins+1 WHERE id=?", (reward, w_uid))
        cur.execute("UPDATE users SET game_losses=game_losses+1 WHERE id=?", (l_uid,))
        conn.commit()
        log_tx(w_uid, "game_win", reward, f"برد {GAME_LABEL[mid_data['kind']]}")
        await add_xp(w_uid, XP_WIN, context)
        await add_xp(l_uid, XP_GAME, context)
        lines.append(f"🏆 برنده: *{w_name}* (+{reward} سکه)")

    text = panel(f"{GAME_LABEL[mid_data['kind']]} — نتیجه", lines)
    buttons = kb([
        [("🔄 بازی مجدد", f"g_find_{mid_data['kind']}")],
        [("🎮 سالن بازی", "games"), ("🏠 منو", "back_main")],
    ])
    for uid in {p1, p2}:
        try:
            await context.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=buttons)
        except Exception:
            pass

# ── 🎲 تاس PVP ──
DICE_FACES = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

async def dice_roll_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    mid = context.match.group(1)
    pnum = int(context.match.group(2))
    match = MATCHES.get(mid)
    if not match or match["kind"] != "dice":
        await q.answer("❌ این بازی تموم شده یا وجود نداره.", show_alert=True)
        return
    key = f"v{pnum}"
    if match[key] is not None:
        await q.answer("⚠️ تو قبلاً تاس انداختی!", show_alert=True)
        return
    await q.answer()
    roll = random.randint(1, 6)
    match[key] = roll
    try:
        await q.edit_message_text(
            panel("🎲 تاس انداختی!", [
                f"تاس تو: {DICE_FACES[roll]} (*{roll}*)",
                "", "⏳ منتظر حریف...",
            ]), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

    if match["v1"] is not None and match["v2"] is not None:
        m = MATCHES.pop(mid, None)
        if not m:
            return
        n1 = md_escape((get_user(m["p1"]) or {"first_name": "بازیکن ۱"})["first_name"] or "بازیکن ۱")
        n2 = md_escape((get_user(m["p2"]) or {"first_name": "بازیکن ۲"})["first_name"] or "بازیکن ۲")
        r1, r2 = m["v1"], m["v2"]
        winner = 1 if r1 > r2 else (2 if r2 > r1 else 0)
        lines = [
            f"👤 {n1}: {DICE_FACES[r1]} ({r1})",
            f"👤 {n2}: {DICE_FACES[r2]} ({r2})",
            "",
        ]
        await _pvp_payout(m, winner, context, lines)

# ── ✂️ سنگ کاغذ قیچی PVP ──
RPS_NAME = {"r": "✊ سنگ", "p": "✋ کاغذ", "s": "✌️ قیچی"}
RPS_BEATS = {"r": "s", "p": "r", "s": "p"}

async def rps_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    mid = context.match.group(1)
    pnum = int(context.match.group(2))
    choice = context.match.group(3)
    match = MATCHES.get(mid)
    if not match or match["kind"] != "rps":
        await q.answer("❌ این بازی تموم شده یا وجود نداره.", show_alert=True)
        return
    key = f"v{pnum}"
    if match[key] is not None:
        await q.answer("⚠️ تو انتخابت رو کردی!", show_alert=True)
        return
    await q.answer(f"{RPS_NAME[choice]} انتخاب شد")
    match[key] = choice
    try:
        await q.edit_message_text(
            panel("✂️ انتخاب شد!", [
                f"انتخاب تو: {RPS_NAME[choice]}",
                "", "⏳ منتظر حریف...",
            ]), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

    if match["v1"] is not None and match["v2"] is not None:
        c1, c2 = match["v1"], match["v2"]
        if c1 == c2:
            # مساوی → دور مجدد
            match["v1"] = None
            match["v2"] = None
            for uid, pn in ((match["p1"], 1), (match["p2"], 2)):
                try:
                    await context.bot.send_message(
                        uid,
                        panel("🤝 مساوی!", [
                            f"هر دو {RPS_NAME[c1]} انتخاب کردین!",
                            "دوباره انتخاب کن 👇",
                        ]),
                        parse_mode=ParseMode.MARKDOWN, reply_markup=_rps_kb(mid, pn))
                except Exception:
                    pass
            return
        m = MATCHES.pop(mid, None)
        if not m:
            return
        n1 = md_escape((get_user(m["p1"]) or {"first_name": "بازیکن ۱"})["first_name"] or "بازیکن ۱")
        n2 = md_escape((get_user(m["p2"]) or {"first_name": "بازیکن ۲"})["first_name"] or "بازیکن ۲")
        winner = 1 if RPS_BEATS[c1] == c2 else 2
        lines = [
            f"👤 {n1}: {RPS_NAME[c1]}",
            f"👤 {n2}: {RPS_NAME[c2]}",
            "",
        ]
        await _pvp_payout(m, winner, context, lines)

# ── 🎰 اسلات ──
SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
SLOT_WEIGHTS = [30, 28, 22, 12, 8]

async def g_slots_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    used = plays_today(uid, "slots")
    u = get_user(uid)
    rows = tree([
        ("👛 موجودی", f"{fmt(u['coins'])} سکه"),
        ("🎰 امروز", f"{used}/{LIMIT_SLOTS} بازی"),
    ])
    rows += [
        "",
        "💎 جدول جایزه‌ها:",
        "7️⃣7️⃣7️⃣ = ۱۲ برابر  •  💎💎💎 = ۸ برابر",
        "سه‌تایی دیگر = ۵ برابر  •  جفت = ۱.۵ برابر",
        "",
        "مبلغ شرط رو انتخاب کن 👇",
    ]
    await safe_edit(q, panel("🎰 اسلات", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [(f"💰 {b}", f"g_slots_bet_{b}") for b in SLOT_BETS],
        [("🎮 سالن بازی", "games")],
    ]))

async def g_slots_bet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    bet = int(context.match.group(1))
    if bet not in SLOT_BETS:
        await q.answer("❌ شرط نامعتبر", show_alert=True)
        return
    if plays_today(uid, "slots") >= LIMIT_SLOTS:
        await q.answer("⏳ سهم امروزت تموم شد! فردا بیا.", show_alert=True)
        return
    u = get_user(uid)
    if u["coins"] < bet:
        await q.answer("❌ سکه کافی نداری!", show_alert=True)
        return
    await q.answer("🎰 چرخید...")

    cur.execute("UPDATE users SET coins=coins-? WHERE id=?", (bet, uid))
    conn.commit()
    inc_play(uid, "slots")
    await add_xp(uid, XP_GAME, context)

    reels = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
    a, b, c = reels
    if a == b == c == "7️⃣":
        mult, verdict = 12, "🎇 جکپات!!!"
    elif a == b == c == "💎":
        mult, verdict = 8, "💎 الماس سه‌گانه!"
    elif a == b == c:
        mult, verdict = 5, "🎉 سه‌تایی!"
    elif a == b or b == c or a == c:
        mult, verdict = 1.5, "✨ جفت شد!"
    else:
        mult, verdict = 0, "😔 این دفعه نشد..."

    win = int(bet * mult)
    if win > 0:
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (win, uid))
        conn.commit()
        log_tx(uid, "slots", win - bet, f"اسلات (شرط {bet})")
    else:
        log_tx(uid, "slots", -bet, f"اسلات (شرط {bet})")

    fresh = get_user(uid)
    net = win - bet
    net_str = f"+{fmt(net)}" if net > 0 else fmt(net)
    rows = [
        f"┏ 🎰 [ {a} │ {b} │ {c} ]",
        "",
        f"{verdict}",
    ] + tree([
        ("💰 شرط", f"{fmt(bet)} سکه"),
        ("🎁 برد", f"{fmt(win)} سکه"),
        ("📊 سود/زیان", f"{net_str} سکه"),
        ("👛 موجودی", f"{fmt(fresh['coins'])} سکه"),
    ])
    await safe_edit(q, panel("🎰 نتیجه اسلات", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [(f"🔄 دوباره ({bet}💰)", f"g_slots_bet_{bet}"), ("🎰 تغییر شرط", "g_slots")],
        [("🎮 سالن بازی", "games")],
    ]))

# ── 🎯 حدس عدد ──
async def g_guess_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    used = plays_today(uid, "guess")
    u = get_user(uid)
    rows = tree([
        ("👛 موجودی", f"{fmt(u['coins'])} سکه"),
        ("🎯 امروز", f"{used}/{LIMIT_GUESS} بازی"),
        ("💵 هزینه هر بازی", f"{GUESS_COST} سکه"),
        ("🏆 جایزه برد", f"{GUESS_PRIZE} سکه"),
    ])
    rows += ["", "من یه عدد بین ۱ تا ۵ انتخاب می‌کنم؛ اگه درست حدس بزنی جایزه مال توئه! 🎁"]
    await safe_edit(q, panel("🎯 حدس عدد", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🎯 شروع بازی", "g_guess_play")],
        [("🎮 سالن بازی", "games")],
    ]))

async def g_guess_play_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if plays_today(uid, "guess") >= LIMIT_GUESS:
        await q.answer("⏳ سهم امروزت تموم شد! فردا بیا.", show_alert=True)
        return
    u = get_user(uid)
    if u["coins"] < GUESS_COST:
        await q.answer(f"❌ حداقل {GUESS_COST} سکه لازمه!", show_alert=True)
        return
    await q.answer()
    cur.execute("UPDATE users SET coins=coins-? WHERE id=?", (GUESS_COST, uid))
    conn.commit()
    inc_play(uid, "guess")
    await add_xp(uid, XP_GAME, context)
    context.user_data["guess_target"] = random.randint(1, 5)
    await safe_edit(q, panel("🎯 حدس بزن!", [
        "عدد من بین *۱ تا ۵* ـه...",
        "کدومه؟ 🤔",
    ]), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [(str(n), f"g_guess_pick_{n}") for n in range(1, 6)],
    ]))

async def g_guess_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    target = context.user_data.pop("guess_target", None)
    if target is None:
        await q.answer("❌ بازی فعالی نداری! از «شروع بازی» بزن.", show_alert=True)
        return
    pick = int(context.match.group(1))
    won = pick == target
    if won:
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (GUESS_PRIZE, uid))
        conn.commit()
        log_tx(uid, "guess", GUESS_PRIZE - GUESS_COST, "حدس عدد (برد)")
        await q.answer("🎉 درست حدس زدی!")
    else:
        log_tx(uid, "guess", -GUESS_COST, "حدس عدد (باخت)")
        await q.answer("😔 نشد!")
    fresh = get_user(uid)
    rows = tree([
        ("🎯 حدس تو", str(pick)),
        ("🎲 عدد من", str(target)),
        ("📊 نتیجه", f"🎉 بردی +{GUESS_PRIZE} سکه" if won else f"😔 باختی -{GUESS_COST} سکه"),
        ("👛 موجودی", f"{fmt(fresh['coins'])} سکه"),
    ])
    await safe_edit(q, panel("🎯 نتیجه حدس عدد", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🔄 دوباره", "g_guess_play")],
        [("🎮 سالن بازی", "games")],
    ]))

# ── 🪙 شیر یا خط ──
FLIP_NAME = {"h": "🦁 شیر", "t": "⭕ خط"}

async def g_flip_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    used = plays_today(uid, "flip")
    u = get_user(uid)
    rows = tree([
        ("👛 موجودی", f"{fmt(u['coins'])} سکه"),
        ("🪙 امروز", f"{used}/{LIMIT_FLIP} بازی"),
    ])
    rows += ["", "اگه درست بیاد، *۱.۹ برابر* شرطت رو می‌بری! 🤑", "", "مبلغ شرط رو انتخاب کن 👇"]
    await safe_edit(q, panel("🪙 شیر یا خط", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [(f"💰 {b}", f"g_flip_bet_{b}") for b in FLIP_BETS],
        [("🎮 سالن بازی", "games")],
    ]))

async def g_flip_bet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bet = int(context.match.group(1))
    if bet not in FLIP_BETS:
        await q.answer("❌ شرط نامعتبر", show_alert=True)
        return
    uid = q.from_user.id
    if plays_today(uid, "flip") >= LIMIT_FLIP:
        await q.answer("⏳ سهم امروزت تموم شد! فردا بیا.", show_alert=True)
        return
    if get_user(uid)["coins"] < bet:
        await q.answer("❌ سکه کافی نداری!", show_alert=True)
        return
    await q.answer()
    await safe_edit(q, panel("🪙 شیر یا خط", [
        f"شرط: *{fmt(bet)} سکه*",
        "",
        "حدست چیه؟ 👇",
    ]), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🦁 شیر", f"g_flip_go_{bet}_h"), ("⭕ خط", f"g_flip_go_{bet}_t")],
        [("🔙 تغییر شرط", "g_flip")],
    ]))

async def g_flip_go_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bet = int(context.match.group(1))
    pick = context.match.group(2)
    uid = q.from_user.id
    if bet not in FLIP_BETS:
        await q.answer("❌ شرط نامعتبر", show_alert=True)
        return
    if plays_today(uid, "flip") >= LIMIT_FLIP:
        await q.answer("⏳ سهم امروزت تموم شد!", show_alert=True)
        return
    u = get_user(uid)
    if u["coins"] < bet:
        await q.answer("❌ سکه کافی نداری!", show_alert=True)
        return
    await q.answer("🪙 پرتاب شد...")

    cur.execute("UPDATE users SET coins=coins-? WHERE id=?", (bet, uid))
    conn.commit()
    inc_play(uid, "flip")
    await add_xp(uid, XP_GAME, context)

    result = random.choice(["h", "t"])
    won = pick == result
    if won:
        payout = bet + int(bet * 0.9)
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (payout, uid))
        conn.commit()
        log_tx(uid, "flip", payout - bet, f"شیر یا خط (شرط {bet})")
    else:
        log_tx(uid, "flip", -bet, f"شیر یا خط (شرط {bet})")

    fresh = get_user(uid)
    rows = tree([
        ("🎯 حدس تو", FLIP_NAME[pick]),
        ("🪙 نتیجه سکه", FLIP_NAME[result]),
        ("📊 نتیجه", f"🎉 بردی +{fmt(int(bet * 0.9))} سکه" if won else f"😔 باختی -{fmt(bet)} سکه"),
        ("👛 موجودی", f"{fmt(fresh['coins'])} سکه"),
    ])
    await safe_edit(q, panel("🪙 نتیجه پرتاب", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [(f"🔄 دوباره ({bet}💰)", f"g_flip_bet_{bet}"), ("🪙 تغییر شرط", "g_flip")],
        [("🎮 سالن بازی", "games")],
    ]))

# ════════════════════ 👮 پنل ادمین ════════════════════
async def guard_admin(update: Update) -> bool:
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("⛔ دسترسی غیرمجاز!", show_alert=True)
        return False
    return True

def admin_kb() -> InlineKeyboardMarkup:
    cur.execute("SELECT COUNT(*) c FROM support_messages WHERE is_from_admin=0 AND is_read=0")
    unread = cur.fetchone()["c"]
    inbox_label = f"💬 پشتیبانی ({unread})" if unread else "💬 پشتیبانی"
    return kb([
        [("👥 کاربران", "adm_users"), ("📦 کانفیگ‌ها", "adm_cfg")],
        [("🎟 کدهای هدیه", "adm_gifts"), ("📢 ارسال همگانی", "adm_bc")],
        [(inbox_label, "admin_support_inbox"), ("📊 آمار کامل", "admin_stats")],
        [("⚙️ تنظیمات", "admin_settings"), ("💾 بکاپ", "admin_backup")],
        [("🏠 منوی کاربری", "back_main")],
    ])

def admin_home_text() -> str:
    cur.execute("SELECT COUNT(*) c FROM users")
    total_users = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM users WHERE last_seen > ?", (time.time() - 86400,))
    active = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(coins),0) s FROM users")
    coins = cur.fetchone()["s"]
    cur.execute("SELECT COALESCE(SUM(sales_count),0) s FROM configs")
    sales = cur.fetchone()["s"]
    rows = tree([
        ("👥 کاربران", fmt(total_users)),
        ("🟢 فعال ۲۴ ساعت", fmt(active)),
        ("💰 سکه در گردش", fmt(coins)),
        ("🛍 مجموع فروش", fmt(sales)),
    ])
    rows += ["", "بخش مورد نظر رو انتخاب کن 👇"]
    return panel("👮 پنل مدیریت", rows)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی غیرمجاز!")
        return
    await update.message.reply_text(admin_home_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_kb())

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    await safe_edit(q, admin_home_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_kb())

# ── لغو گفتگو ──
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    is_admin = update.effective_user.id == ADMIN_ID
    markup = admin_kb() if is_admin else main_menu()
    text = "🚫 عملیات لغو شد."
    q = update.callback_query
    if q:
        await q.answer()
        await safe_edit(q, text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END

# ════════════════════ 👥 مدیریت کاربران ════════════════════
async def adm_users_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cur.execute("SELECT COUNT(*) c FROM users")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM users WHERE is_banned=1")
    banned = cur.fetchone()["c"]
    rows = tree([
        ("👥 کل کاربران", fmt(total)),
        ("⛔ مسدود", fmt(banned)),
    ])
    await safe_edit(q, panel("👥 مدیریت کاربران", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🔍 جستجوی کاربر", "adm_user_search")],
        [("🕒 کاربران اخیر", "adm_recent_0"), ("💎 خریداران برتر", "adm_topbuyers")],
        [("🔙 بازگشت", "admin_back")],
    ]))

def profile_text(user) -> str:
    ban = "⛔ مسدود" if user["is_banned"] else "✅ فعال"
    total_games = (user["game_wins"] or 0) + (user["game_losses"] or 0)
    wr = f"{(user['game_wins'] or 0) * 100 // total_games}%" if total_games else "-"
    rows = tree([
        ("🆔 آیدی", f"`{user['id']}`"),
        ("📛 نام", md_escape(user["first_name"] or "-")),
        ("🔗 یوزرنیم", "@" + md_escape(user["username"] or "-")),
        ("💰 سکه", fmt(user["coins"])),
        ("⭐ سطح", f"{user['level'] or 1} ({fmt(user['xp'] or 0)} XP)"),
        ("📦 خریدها", f"{user['used_configs'] or 0}"),
        ("💵 مجموع خرید", fmt(user["total_spent"] or 0)),
        ("🎮 بازی‌ها", f"{total_games} (برد {user['game_wins'] or 0} | {wr})"),
        ("🔥 استریک", f"{user['streak'] or 0} روز"),
        ("🌍 زبان/کشور", md_escape(user["country"] or "-")),
        ("📅 عضویت", md_escape(user["join_date"] or "-")),
        ("🕐 آخرین فعالیت", time_ago(user["last_seen"])),
        ("🚦 وضعیت", ban),
    ])
    return panel("👤 پروفایل کاربر", rows)

def profile_kb(user) -> InlineKeyboardMarkup:
    uid = user["id"]
    ban_btn = ("✅ رفع مسدودی", f"act_unban_{uid}") if user["is_banned"] else ("⛔ مسدود کردن", f"act_ban_{uid}")
    return kb([
        [("➕ افزایش سکه", f"act_addcoin_{uid}"), ("➖ کاهش سکه", f"act_subcoin_{uid}")],
        [("📜 تراکنش‌ها", f"act_usertx_{uid}"), ("📨 ارسال پیام", f"admin_send_to_{uid}")],
        [ban_btn],
        [("🔙 کاربران", "adm_users")],
    ])

async def adm_user_search_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, panel("🔍 جستجوی کاربر", [
        "یکی از این‌ها رو بفرست:",
        "▫️ آیدی عددی (مثل `123456789`)",
        "▫️ یوزرنیم (مثل `@user`)",
        "▫️ بخشی از اسم",
    ]), parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return USER_SEARCH

async def receive_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    term = update.message.text.strip().lstrip("@")
    if term.isdigit():
        user = get_user(int(term))
        if user:
            await update.message.reply_text(profile_text(user), parse_mode=ParseMode.MARKDOWN,
                                            reply_markup=profile_kb(user))
        else:
            await update.message.reply_text("❌ کاربری با این آیدی پیدا نشد.", reply_markup=admin_kb())
        return ConversationHandler.END

    like = f"%{term}%"
    cur.execute("SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? LIMIT 6", (like, like))
    rows_db = cur.fetchall()
    if not rows_db:
        await update.message.reply_text("❌ کاربری پیدا نشد.", reply_markup=admin_kb())
        return ConversationHandler.END
    if len(rows_db) == 1:
        user = rows_db[0]
        await update.message.reply_text(profile_text(user), parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=profile_kb(user))
        return ConversationHandler.END
    btns = [[(f"👤 {r['first_name'] or '-'} (@{r['username'] or '-'})", f"act_manage_{r['id']}")]
            for r in rows_db]
    btns.append([("🔙 بازگشت", "adm_users")])
    await update.message.reply_text(panel("🔍 نتایج جستجو", [f"{len(rows_db)} کاربر پیدا شد:"]),
                                    parse_mode=ParseMode.MARKDOWN, reply_markup=kb(btns))
    return ConversationHandler.END

async def adm_recent_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    page = int(context.match.group(1))
    per = 8
    cur.execute("SELECT COUNT(*) c FROM users")
    total = cur.fetchone()["c"]
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    cur.execute("SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?", (per, page * per))
    rows_db = cur.fetchall()
    lines = []
    btns = []
    for r in rows_db:
        flag = "⛔" if r["is_banned"] else "✅"
        lines.append(f"{flag} `{r['id']}` — {md_escape(r['first_name'] or '-')} — 💰{fmt(r['coins'])}")
        btns.append([(f"⚙️ {r['first_name'] or r['id']}", f"act_manage_{r['id']}")])
    btns.append(pager_row("adm_recent", page, pages))
    btns.append([("🔙 کاربران", "adm_users")])
    await safe_edit(q, panel(f"🕒 کاربران اخیر ({fmt(total)})", lines),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=kb(btns))

async def adm_topbuyers_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cur.execute("SELECT * FROM users WHERE total_spent > 0 ORDER BY total_spent DESC LIMIT 10")
    rows_db = cur.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    btns = []
    for i, r in enumerate(rows_db):
        m = medals[i] if i < 3 else f" {i + 1}."
        lines.append(f"{m} {md_escape(r['first_name'] or '-')} — 💵{fmt(r['total_spent'])} — 📦{r['used_configs']}")
        btns.append([(f"⚙️ {r['first_name'] or r['id']}", f"act_manage_{r['id']}")])
    if not rows_db:
        lines = ["هنوز خریدی ثبت نشده."]
    btns.append([("🔙 کاربران", "adm_users")])
    await safe_edit(q, panel("💎 خریداران برتر", lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb(btns))

async def manage_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    user = get_user(int(context.match.group(1)))
    if not user:
        await safe_edit(q, "❌ کاربر پیدا نشد.", reply_markup=admin_kb())
        return
    await safe_edit(q, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def act_usertx_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    uid = int(context.match.group(1))
    cur.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows_db = cur.fetchall()
    lines = []
    for r in rows_db:
        sign = "+" if r["amount"] >= 0 else ""
        date = datetime.fromtimestamp(r["date"]).strftime("%m-%d %H:%M")
        lines.append(f"{date} | {sign}{fmt(r['amount'])} | {md_escape(r['description'])}")
    if not lines:
        lines = ["تراکنشی ثبت نشده."]
    await safe_edit(q, panel(f"📜 تراکنش‌های `{uid}`", lines), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([[("🔙 پروفایل", f"act_manage_{uid}")]]))

async def ban_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    uid = int(context.match.group(1))
    cur.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))
    conn.commit()
    await q.answer("کاربر مسدود شد ⛔")
    user = get_user(uid)
    await safe_edit(q, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def unban_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    uid = int(context.match.group(1))
    cur.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))
    conn.commit()
    await q.answer("رفع مسدودیت شد ✅")
    user = get_user(uid)
    await safe_edit(q, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def coin_action_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    uid = int(context.match.group(1))
    action = "add" if q.data.startswith("act_addcoin_") else "sub"
    context.user_data["target_uid"] = uid
    context.user_data["coin_action"] = action
    verb = "افزایش" if action == "add" else "کاهش"
    await safe_edit(q, panel(f"💰 {verb} سکه", [f"چند سکه برای کاربر `{uid}` {verb} پیدا کنه؟",
                                               "(فقط عدد بفرست)"]),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return ASK_AMOUNT

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ فقط عدد مثبت بفرست یا لغو کن.", reply_markup=cancel_kb())
        return ASK_AMOUNT
    amount = int(text)
    uid = context.user_data.get("target_uid")
    action = context.user_data.get("coin_action")
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ این کاربر دیگر پیدا نشد.", reply_markup=admin_kb())
        context.user_data.clear()
        return ConversationHandler.END

    if action == "add":
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (amount, uid))
        log_tx(uid, "admin_add", amount, "افزایش دستی توسط ادمین")
        msg = f"✅ {fmt(amount)} سکه به کاربر `{uid}` اضافه شد."
        user_note = f"🎁 ادمین {fmt(amount)} سکه بهت هدیه داد!"
    else:
        cur.execute("UPDATE users SET coins=coins-? WHERE id=?", (amount, uid))
        log_tx(uid, "admin_sub", -amount, "کاهش دستی توسط ادمین")
        msg = f"✅ {fmt(amount)} سکه از کاربر `{uid}` کم شد."
        user_note = None
    conn.commit()
    if user_note:
        try:
            await context.bot.send_message(uid, user_note)
        except Exception:
            pass
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_kb())
    context.user_data.clear()
    return ConversationHandler.END

# ── 📨 ارسال پیام به کاربر ──
async def admin_send_msg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "📨 آیدی عددی کاربر مورد نظر رو بفرست:", reply_markup=cancel_kb())
    return SEND_MSG_UID

async def admin_send_to_user_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    uid = int(context.match.group(1))
    context.user_data["send_msg_target"] = uid
    await safe_edit(q, f"📨 پیامت رو برای کاربر `{uid}` بفرست:", parse_mode=ParseMode.MARKDOWN,
                    reply_markup=cancel_kb())
    return SEND_MSG_TEXT

async def receive_send_msg_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ فقط آیدی عددی بفرست یا لغو کن.", reply_markup=cancel_kb())
        return SEND_MSG_UID
    uid = int(text)
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ کاربری با این آیدی پیدا نشد.", reply_markup=admin_kb())
        context.user_data.clear()
        return ConversationHandler.END
    context.user_data["send_msg_target"] = uid
    await update.message.reply_text(
        f"👤 کاربر: {user['first_name'] or '-'} (`{uid}`)\n\n📨 پیامت رو بفرست:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return SEND_MSG_TEXT

async def receive_send_msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("send_msg_target")
    msg_text = update.message.text
    try:
        await context.bot.send_message(
            uid, f"📨 *پیام از ادمین:*\n{DIV}\n{md_escape(msg_text)}",
            parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(f"✅ پیام به کاربر {uid} ارسال شد.", reply_markup=admin_kb())
    except Exception:
        await update.message.reply_text("❌ ارسال ناموفق! (ممکنه کاربر بات رو بلاک کرده باشه)",
                                        reply_markup=admin_kb())
    context.user_data.clear()
    return ConversationHandler.END

# ── 💬 صندوق پشتیبانی ادمین ──
async def admin_support_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cur.execute("SELECT COUNT(*) c FROM support_messages WHERE is_from_admin=0 AND is_read=0")
    unread = cur.fetchone()["c"]
    cur.execute("SELECT * FROM support_messages WHERE is_from_admin=0 ORDER BY id DESC LIMIT 12")
    rows_db = cur.fetchall()
    if not rows_db:
        await safe_edit(q, panel("💬 صندوق پشتیبانی", ["📭 صندوق خالیه!"]),
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb([[("🔙 بازگشت", "admin_back")]]))
        return
    lines = [f"🔵 خوانده‌نشده: {unread}", ""]
    btns = []
    for r in rows_db:
        user = get_user(r["user_id"])
        name = md_escape(user["first_name"] or "ناشناس") if user else "حذف‌شده"
        flag = "📋" if r["is_read"] else "🔵"
        short = md_escape(r["message"][:28]) + ("..." if len(r["message"]) > 28 else "")
        lines.append(f"{flag} #{r['id']} | {name} | {short}")
        btns.append([(f"👁 #{r['id']} — {name}", f"admin_view_msg_{r['id']}")])
    btns.append([("🔙 بازگشت", "admin_back")])
    await safe_edit(q, panel("💬 صندوق پشتیبانی", lines), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb(btns))

async def admin_view_msg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    msg_id = int(context.match.group(1))
    cur.execute("SELECT * FROM support_messages WHERE id=?", (msg_id,))
    msg = cur.fetchone()
    if not msg:
        await safe_edit(q, "❌ پیام پیدا نشد.", reply_markup=admin_kb())
        return
    cur.execute("UPDATE support_messages SET is_read=1 WHERE id=?", (msg_id,))
    conn.commit()
    user = get_user(msg["user_id"])
    name = md_escape(user["first_name"] or "ناشناس") if user else "حذف‌شده"
    uid = msg["user_id"]
    rows = [
        f"👤 {name} (`{uid}`)",
        f"🕐 {time_ago(msg['date'])}",
        "",
        f"💬 {md_escape(msg['message'])}",
    ]
    await safe_edit(q, panel(f"📩 پیام #{msg_id}", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("💬 پاسخ دادن", f"admin_reply_sel_{uid}_{msg_id}")],
        [("👤 پروفایل کاربر", f"act_manage_{uid}")],
        [("🔙 صندوق", "admin_support_inbox")],
    ]))

async def admin_reply_sel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    uid = int(context.match.group(1))
    msg_id = int(context.match.group(2))
    context.user_data["reply_to_uid"] = uid
    context.user_data["reply_to_msg"] = msg_id
    await safe_edit(q, f"💬 پاسخت رو برای کاربر `{uid}` بفرست:", parse_mode=ParseMode.MARKDOWN,
                    reply_markup=cancel_kb())
    return ADMIN_REPLY_MSG

async def receive_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("reply_to_uid")
    msg_id = context.user_data.get("reply_to_msg")
    reply_text = update.message.text
    cur.execute(
        "INSERT INTO support_messages (user_id, message, is_from_admin, date, is_read, reply_to_id) VALUES (?,?,1,?,0,?)",
        (uid, reply_text, time.time(), msg_id))
    conn.commit()
    try:
        await context.bot.send_message(
            uid,
            f"📩 *پاسخ پشتیبانی:*\n{DIV}\n{md_escape(reply_text)}\n\n"
            f"💡 برای ادامه گفتگو دوباره از «پشتیبانی» پیام بده.",
            parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text("✅ پاسخ ارسال شد!", reply_markup=admin_kb())
    except Exception:
        await update.message.reply_text("❌ ارسال ناموفق! کاربر شاید بات رو بلاک کرده.", reply_markup=admin_kb())
    context.user_data.clear()
    return ConversationHandler.END

# ════════════════════ 📦 مدیریت کانفیگ‌ها ════════════════════
async def adm_cfg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cur.execute("SELECT COUNT(*) c FROM configs")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM configs WHERE is_active=1 AND stock>0")
    live = cur.fetchone()["c"]
    rows = tree([
        ("📦 کل کانفیگ‌ها", fmt(total)),
        ("🟢 قابل فروش", fmt(live)),
    ])
    await safe_edit(q, panel("📦 مدیریت کانفیگ‌ها", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("➕ افزودن کانفیگ", "adm_addcfg")],
        [("📋 لیست کانفیگ‌ها", "adm_listcfg_0")],
        [("🔙 بازگشت", "admin_back")],
    ]))

async def adm_listcfg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    page = int(context.match.group(1))
    per = 6
    cur.execute("SELECT COUNT(*) c FROM configs")
    total = cur.fetchone()["c"]
    if total == 0:
        await safe_edit(q, panel("📋 لیست کانفیگ‌ها", ["📭 هنوز کانفیگی ثبت نشده."]),
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb([[("➕ افزودن", "adm_addcfg")], [("🔙 بازگشت", "adm_cfg")]]))
        return
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    cur.execute("SELECT * FROM configs ORDER BY id DESC LIMIT ? OFFSET ?", (per, page * per))
    rows_db = cur.fetchall()
    cats = get_categories()
    lines = []
    btns = []
    for r in rows_db:
        flag = "✅" if r["is_active"] else "⛔"
        lines.append(f"{flag} #{r['id']} *{md_escape(r['name'])}*")
        lines.append(f"   {cats.get(r['category'], r['category'])} • 💰{fmt(r['price'])} • 📦{fmt(r['stock'])} • 🛍{fmt(r['sales_count'] or 0)}")
        btns.append([(f"⚙️ مدیریت #{r['id']} — {r['name']}", f"cfgmng_{r['id']}")])
    btns.append(pager_row("adm_listcfg", page, pages))
    btns.append([("🔙 بازگشت", "adm_cfg")])
    await safe_edit(q, panel(f"📋 کانفیگ‌ها ({fmt(total)})", lines),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=kb(btns))

async def cfgmng_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await safe_edit(q, "❌ کانفیگ پیدا نشد.", reply_markup=admin_kb())
        return
    cats = get_categories()
    rows = tree([
        ("📦 نام", md_escape(cfg["name"])),
        ("🗂 دسته", cats.get(cfg["category"], cfg["category"])),
        ("💰 قیمت", f"{fmt(cfg['price'])} سکه"),
        ("📥 موجودی", fmt(cfg["stock"])),
        ("🛍 فروش", fmt(cfg["sales_count"] or 0)),
        ("🚦 وضعیت", "✅ فعال" if cfg["is_active"] else "⛔ غیرفعال"),
        ("🕐 ساخت", time_ago(cfg["created_at"])),
    ])
    toggle_label = "⛔ غیرفعال کن" if cfg["is_active"] else "✅ فعال کن"
    await safe_edit(q, panel(f"⚙️ کانفیگ #{cfg_id}", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("👁 مشاهده محتوا", f"cfg_view_{cfg_id}"), ("✏️ قیمت/موجودی", f"cfg_edit_{cfg_id}")],
        [(toggle_label, f"cfg_toggle_{cfg_id}"), ("🗑 حذف", f"cfg_del_{cfg_id}")],
        [("🔙 لیست", "adm_listcfg_0")],
    ]))

async def cfg_view_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await safe_edit(q, "❌ پیدا نشد.", reply_markup=admin_kb())
        return
    text = (f"◈ *👁 محتوای «{md_escape(cfg['name'])}»*\n{DIV}\n"
            f"```\n{cfg['config']}\n```")
    await safe_edit(q, text, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([[("🔙 بازگشت", f"cfgmng_{cfg_id}")]]))

async def cfg_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await q.answer("❌ پیدا نشد!", show_alert=True)
        return
    new_state = 0 if cfg["is_active"] else 1
    cur.execute("UPDATE configs SET is_active=? WHERE id=?", (new_state, cfg_id))
    conn.commit()
    await q.answer("فعال شد ✅" if new_state else "غیرفعال شد ⛔")
    await cfgmng_cb(update, context)

async def cfg_del_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await safe_edit(q, "❌ پیدا نشد.", reply_markup=admin_kb())
        return
    await safe_edit(q, panel("⚠️ تایید حذف", [f"کانفیگ «{md_escape(cfg['name'])}» برای همیشه حذف بشه؟"]),
                    parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
                        [("✅ بله، حذف کن", f"cfg_delyes_{cfg_id}"), ("❌ خیر", f"cfgmng_{cfg_id}")],
                    ]))

async def cfg_del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    cfg_id = int(context.match.group(1))
    cur.execute("DELETE FROM configs WHERE id=?", (cfg_id,))
    conn.commit()
    await q.answer("حذف شد ✅")
    context.match = re.match(r"(0)", "0")
    await adm_listcfg_cb(update, context)

async def addcfg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    context.user_data["new_cfg"] = {}
    await safe_edit(q, "📝 نام کانفیگ رو بفرست:", reply_markup=cancel_kb())
    return ADDCFG_NAME

async def receive_cfg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cfg"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "📦 محتوای کانفیگ رو بفرست (چیزی که بعد از خرید تحویل کاربر می‌شه):",
        reply_markup=cancel_kb())
    return ADDCFG_CONTENT

async def receive_cfg_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cfg"]["config"] = update.message.text
    cats = get_categories()
    btns = [[(v, f"cfgcat_{k}")] for k, v in cats.items()]
    btns.append([("🚫 لغو", "cancel_conv")])
    await update.message.reply_text("🗂 دسته‌بندی رو انتخاب کن:", reply_markup=kb(btns))
    return ADDCFG_CATEGORY

async def receive_cfg_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["new_cfg"]["category"] = context.match.group(1)
    await safe_edit(q, "💰 قیمت و موجودی رو با فاصله بفرست (مثال: `20 50`):",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return ADDCFG_PRICE_STOCK

async def receive_cfg_price_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await update.message.reply_text("❌ فرمت اشتباهه. مثال: 20 50 (قیمت موجودی)", reply_markup=cancel_kb())
        return ADDCFG_PRICE_STOCK
    price, stock = int(parts[0]), int(parts[1])
    d = context.user_data["new_cfg"]
    cur.execute(
        "INSERT INTO configs (name, config, price, category, stock, created_at) VALUES (?,?,?,?,?,?)",
        (d["name"], d["config"], price, d["category"], stock, time.time()))
    conn.commit()
    await update.message.reply_text(f"✅ کانفیگ «{d['name']}» با موفقیت اضافه شد.", reply_markup=admin_kb())
    context.user_data.clear()
    return ConversationHandler.END

async def editcfg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await safe_edit(q, "❌ کانفیگ پیدا نشد.", reply_markup=admin_kb())
        return ConversationHandler.END
    context.user_data["edit_cfg_id"] = cfg_id
    await safe_edit(q, f"✏️ ویرایش «{cfg['name']}»\n"
                       f"قیمت و موجودی جدید رو با فاصله بفرست (فعلی: {cfg['price']} {cfg['stock']}):",
                    reply_markup=cancel_kb())
    return EDIT_PRICE_STOCK

async def receive_edit_price_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await update.message.reply_text("❌ فرمت اشتباهه. مثال: 20 50", reply_markup=cancel_kb())
        return EDIT_PRICE_STOCK
    price, stock = int(parts[0]), int(parts[1])
    cfg_id = context.user_data.get("edit_cfg_id")
    cur.execute("UPDATE configs SET price=?, stock=? WHERE id=?", (price, stock, cfg_id))
    conn.commit()
    await update.message.reply_text("✅ کانفیگ بروزرسانی شد.", reply_markup=admin_kb())
    context.user_data.clear()
    return ConversationHandler.END

# ════════════════════ 🎟 مدیریت کدهای هدیه ════════════════════
async def adm_gifts_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cur.execute("SELECT COUNT(*) c FROM gift_codes WHERE is_active=1")
    active = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(used_count),0) s FROM gift_codes")
    used = cur.fetchone()["s"]
    rows = tree([
        ("🎟 کدهای فعال", fmt(active)),
        ("✅ مجموع استفاده", fmt(used)),
    ])
    await safe_edit(q, panel("🎟 کدهای هدیه", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("➕ ساخت کد جدید", "gift_new")],
        [("📋 لیست کدها", "gift_list")],
        [("🔙 بازگشت", "admin_back")],
    ]))

async def gift_new_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, panel("➕ ساخت کد هدیه", [
        "در یک پیام بفرست: `کد مقدار حداکثر‌استفاده`",
        "",
        "مثال: `EYD1405 50 100`",
        "یا برای کد تصادفی: `random 50 100`",
    ]), parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return GIFT_CREATE

async def receive_gift_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await update.message.reply_text("❌ فرمت اشتباهه. مثال: EYD1405 50 100", reply_markup=cancel_kb())
        return GIFT_CREATE
    code = parts[0].upper()
    if code == "RANDOM":
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    amount, max_uses = int(parts[1]), int(parts[2])
    try:
        cur.execute("INSERT INTO gift_codes (code, amount, max_uses, created_at) VALUES (?,?,?,?)",
                    (code, amount, max_uses, time.time()))
        conn.commit()
    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ این کد قبلاً ساخته شده! یه کد دیگه انتخاب کن.",
                                        reply_markup=cancel_kb())
        return GIFT_CREATE
    await update.message.reply_text(
        panel("✅ کد ساخته شد!", tree([
            ("🎟 کد", f"`{code}`"),
            ("💰 مقدار", f"{fmt(amount)} سکه"),
            ("👥 ظرفیت", f"{fmt(max_uses)} نفر"),
        ]) + ["", "کد رو کپی کن و بین کاربرات پخش کن! 📣"]),
        parse_mode=ParseMode.MARKDOWN, reply_markup=admin_kb())
    return ConversationHandler.END

async def gift_list_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cur.execute("SELECT * FROM gift_codes ORDER BY id DESC LIMIT 15")
    rows_db = cur.fetchall()
    if not rows_db:
        await safe_edit(q, panel("📋 لیست کدها", ["هنوز کدی نساختی."]),
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb([[("➕ ساخت کد", "gift_new")], [("🔙 بازگشت", "adm_gifts")]]))
        return
    lines = []
    btns = []
    for r in rows_db:
        flag = "✅" if r["is_active"] else "⛔"
        lines.append(f"{flag} `{r['code']}` — 💰{fmt(r['amount'])} — {r['used_count']}/{r['max_uses']}")
        btns.append([
            (f"{'⛔' if r['is_active'] else '✅'} {r['code']}", f"gift_toggle_{r['id']}"),
            (f"🗑 {r['code']}", f"gift_del_{r['id']}"),
        ])
    btns.append([("🔙 بازگشت", "adm_gifts")])
    await safe_edit(q, panel("📋 لیست کدهای هدیه", lines), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb(btns))

async def gift_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    gid = int(context.match.group(1))
    cur.execute("SELECT is_active FROM gift_codes WHERE id=?", (gid,))
    row = cur.fetchone()
    if not row:
        await q.answer("❌ پیدا نشد!", show_alert=True)
        return
    cur.execute("UPDATE gift_codes SET is_active=? WHERE id=?", (0 if row["is_active"] else 1, gid))
    conn.commit()
    await q.answer("انجام شد ✅")
    await gift_list_cb(update, context)

async def gift_del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    gid = int(context.match.group(1))
    cur.execute("DELETE FROM gift_codes WHERE id=?", (gid,))
    conn.commit()
    await q.answer("حذف شد 🗑")
    await gift_list_cb(update, context)

# ════════════════════ 📢 ارسال همگانی ════════════════════
async def broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "📢 متن پیام همگانی رو بفرست:", reply_markup=cancel_kb())
    return BC_TEXT

async def receive_bc_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bc_text"] = update.message.text
    cur.execute("SELECT COUNT(*) c FROM users WHERE is_banned=0")
    n = cur.fetchone()["c"]
    await update.message.reply_text(
        panel("👁 پیش‌نمایش همگانی", [
            f"این پیام برای *{fmt(n)} کاربر* ارسال می‌شه:",
            "",
            md_escape(update.message.text),
        ]),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb([[("✅ ارسال به همه", "bc_yes"), ("❌ لغو", "cancel_conv")]]))
    return BC_CONFIRM

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = context.user_data.get("bc_text", "")
    cur.execute("SELECT id FROM users WHERE is_banned=0")
    ids = [r["id"] for r in cur.fetchall()]
    total = len(ids)
    await safe_edit(q, f"⏳ شروع ارسال به {fmt(total)} کاربر...")

    sent, failed = 0, 0
    for i, uid in enumerate(ids, 1):
        try:
            await context.bot.send_message(
                uid, f"📢 *اطلاعیه*\n{DIV}\n{md_escape(text)}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            try:
                await q.edit_message_text(f"⏳ در حال ارسال... {i}/{fmt(total)}\n{bar(i, total)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    try:
        await q.edit_message_text(
            panel("✅ ارسال همگانی تمام شد", tree([
                ("📨 موفق", fmt(sent)),
                ("❌ ناموفق", fmt(failed)),
            ])), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass
    await context.bot.send_message(ADMIN_ID, "👮 پنل مدیریت", reply_markup=admin_kb())
    context.user_data.clear()
    return ConversationHandler.END

# ════════════════════ 📊 آمار کامل ════════════════════
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("SELECT COUNT(*) c FROM users")
    total_users = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM users WHERE join_date LIKE ?", (today + "%",))
    new_today = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM users WHERE last_seen > ?", (time.time() - 86400,))
    active24 = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM users WHERE is_banned=1")
    banned = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(coins),0) s FROM users")
    total_coins = cur.fetchone()["s"]
    cur.execute("SELECT COUNT(*) c FROM configs")
    cfg_count = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(stock),0) s FROM configs WHERE is_active=1")
    total_stock = cur.fetchone()["s"]
    cur.execute("SELECT COALESCE(SUM(sales_count),0) s FROM configs")
    total_sales = cur.fetchone()["s"]
    cur.execute("SELECT COALESCE(SUM(-amount),0) s FROM transactions WHERE type='purchase'")
    revenue = cur.fetchone()["s"]
    cur.execute("SELECT name, sales_count FROM configs ORDER BY sales_count DESC LIMIT 3")
    tops = cur.fetchall()
    cur.execute("SELECT COALESCE(SUM(count),0) s FROM game_plays")
    solo_games = cur.fetchone()["s"]
    cur.execute("SELECT COUNT(*) c FROM transactions WHERE type='game_win'")
    pvp_wins = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM gift_redemptions")
    gifts_used = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM support_messages WHERE is_from_admin=0 AND is_read=0")
    unread = cur.fetchone()["c"]

    rows = ["*👥 کاربران*"] + tree([
        ("کل", fmt(total_users)),
        ("جدید امروز", fmt(new_today)),
        ("فعال ۲۴ ساعت", fmt(active24)),
        ("مسدود", fmt(banned)),
    ])
    rows += ["", "*💰 اقتصاد*"] + tree([
        ("سکه در گردش", fmt(total_coins)),
        ("درآمد کل", f"{fmt(revenue)} سکه"),
        ("مجموع فروش", fmt(total_sales)),
    ])
    rows += ["", "*📦 فروشگاه*"] + tree([
        ("کانفیگ‌ها", fmt(cfg_count)),
        ("موجودی فعال", fmt(total_stock)),
    ])
    if tops:
        rows += ["", "*🔥 پرفروش‌ها*"]
        for i, t in enumerate(tops, 1):
            rows.append(f"{i}. {md_escape(t['name'])} — {fmt(t['sales_count'] or 0)} فروش")
    rows += ["", "*🎮 بازی و تعامل*"] + tree([
        ("بازی‌های تک‌نفره", fmt(solo_games)),
        ("بردهای PVP", fmt(pvp_wins)),
        ("کد هدیه استفاده‌شده", fmt(gifts_used)),
        ("پیام بی‌پاسخ", fmt(unread)),
    ])
    await safe_edit(q, panel("📊 آمار کامل بات", rows), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb([[("🔄 بروزرسانی", "admin_stats")], [("🔙 بازگشت", "admin_back")]]))

# ════════════════════ 💾 بکاپ ════════════════════
async def admin_backup_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer("در حال آماده‌سازی بکاپ...")
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(DB_PATH, tmp_path)
        with open(tmp_path, "rb") as f:
            await context.bot.send_document(
                ADMIN_ID, document=f,
                caption=f"💾 بکاپ دیتابیس — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        os.remove(tmp_path)
    except Exception as e:
        await safe_edit(q, f"❌ خطا در بکاپ: {e}", reply_markup=admin_kb())

# ════════════════════ ⚙️ تنظیمات بات ════════════════════
async def admin_settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    m = get_setting("maintenance_mode", "0") == "1"
    pn = get_setting("purchase_notify", "1") == "1"
    jn = get_setting("join_notify", "1") == "1"
    fj = get_setting("force_join", "0") == "1"
    chans = get_channels()
    welcome = get_setting("welcome_msg", "")
    rows = tree([
        ("🏷 نام بات", md_escape(bot_name())),
        ("🔧 حالت تعمیر", "🔴 فعال" if m else "🟢 غیرفعال"),
        ("🔔 اطلاع خرید", "✅" if pn else "❌"),
        ("🆕 اطلاع عضو جدید", "✅" if jn else "❌"),
        ("📣 جوین اجباری", ("✅ (" + fmt(len(chans)) + " کانال)") if fj else "❌"),
        ("🎁 جایزه روزانه", get_setting("daily_min", "15") + " تا " + get_setting("daily_max", "50")),
        ("🏆 جایزه بازی PVP", get_setting("game_reward", "5")),
        ("👋 پیام خوش‌آمد", md_escape(welcome[:40]) + ("..." if len(welcome) > 40 else "")),
    ])
    await safe_edit(q, panel("⚙️ تنظیمات بات", rows), parse_mode=ParseMode.MARKDOWN, reply_markup=kb([
        [("🔧 تعمیر: " + ("خاموش کن" if m else "روشن کن"), "tgl_maint")],
        [("🔔 اطلاع خرید", "tgl_buynotif"), ("🆕 اطلاع عضو", "tgl_joinnotif")],
        [("📣 جوین اجباری", "tgl_forcejoin"), ("📡 کانال‌ها", "adm_channels")],
        [("👋 پیام خوش‌آمد", "set_welcome_entry"), ("🏷 نام بات", "set_botname_entry")],
        [("🎁 جایزه‌ها (روزانه/بازی)", "set_daily_entry"), ("🗂 دسته‌بندی‌ها", "adm_cats")],
        [("🔙 بازگشت", "admin_back")],
    ]))

async def _toggle_setting(update, context, key, default, on_label, off_label):
    if not await guard_admin(update):
        return
    q = update.callback_query
    new_val = "0" if get_setting(key, default) == "1" else "1"
    set_setting(key, new_val)
    await q.answer(on_label if new_val == "1" else off_label)
    await admin_settings_cb(update, context)

async def tgl_maint_cb(update, context):
    await _toggle_setting(update, context, "maintenance_mode", "0", "تعمیر فعال شد 🔴", "تعمیر غیرفعال شد 🟢")

async def tgl_buynotif_cb(update, context):
    await _toggle_setting(update, context, "purchase_notify", "1", "اطلاع خرید فعال ✅", "اطلاع خرید خاموش ❌")

async def tgl_joinnotif_cb(update, context):
    await _toggle_setting(update, context, "join_notify", "1", "اطلاع عضو جدید فعال ✅", "اطلاع عضو جدید خاموش ❌")

async def tgl_forcejoin_cb(update, context):
    if not await guard_admin(update):
        return
    if get_setting("force_join", "0") != "1" and not get_channels():
        await update.callback_query.answer("⚠️ اول از «کانال‌ها» حداقل یک کانال اضافه کن!", show_alert=True)
        return
    _join_cache.clear()
    await _toggle_setting(update, context, "force_join", "0", "جوین اجباری فعال ✅", "جوین اجباری خاموش ❌")

async def set_welcome_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "👋 پیام خوش‌آمدگویی جدید رو بفرست:", reply_markup=cancel_kb())
    return SET_WELCOME

async def receive_welcome_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("welcome_msg", update.message.text)
    await update.message.reply_text("✅ پیام خوش‌آمدگویی تغییر کرد!", reply_markup=admin_kb())
    return ConversationHandler.END

async def set_botname_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "🏷 نام جدید بات رو بفرست (با ایموجی هم می‌تونی):", reply_markup=cancel_kb())
    return SET_BOTNAME

async def receive_botname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("bot_name", update.message.text.strip())
    await update.message.reply_text("✅ نام بات تغییر کرد!", reply_markup=admin_kb())
    return ConversationHandler.END

async def set_daily_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, panel("🎁 تنظیم جایزه‌ها", [
        "سه عدد با فاصله بفرست:",
        "`حداقل‌روزانه حداکثر‌روزانه جایزه‌بازی`",
        "",
        "مثال: `15 50 5`",
    ]), parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return SET_DAILY

async def receive_daily_cfg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        await update.message.reply_text("❌ فرمت اشتباهه. مثال: 15 50 5", reply_markup=cancel_kb())
        return SET_DAILY
    dmin, dmax, greward = int(parts[0]), int(parts[1]), int(parts[2])
    if dmin > dmax:
        await update.message.reply_text("❌ حداقل نباید از حداکثر بیشتر باشه!", reply_markup=cancel_kb())
        return SET_DAILY
    set_setting("daily_min", str(dmin))
    set_setting("daily_max", str(dmax))
    set_setting("game_reward", str(greward))
    await update.message.reply_text(
        f"✅ ذخیره شد!\n🎁 روزانه: {dmin} تا {dmax}\n🏆 جایزه بازی: {greward}",
        reply_markup=admin_kb())
    return ConversationHandler.END

# ── 📡 مدیریت کانال‌های جوین اجباری ──
async def adm_channels_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    chans = get_channels()
    lines = ["⚠️ بات باید در همه کانال‌ها *ادمین* باشه!", ""]
    btns = []
    if chans:
        for i, ch in enumerate(chans):
            lines.append(f"📣 {md_escape(ch)}")
            btns.append([(f"🗑 حذف {ch}", f"ch_del_{i}")])
    else:
        lines.append("هنوز کانالی اضافه نشده.")
    btns.append([("➕ افزودن کانال", "ch_add")])
    btns.append([("🔙 تنظیمات", "admin_settings")])
    await safe_edit(q, panel("📡 کانال‌های جوین اجباری", lines), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb(btns))

async def ch_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "📡 یوزرنیم کانال رو با @ بفرست (مثل `@mychannel`):",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return ADD_CHANNEL

async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    if not re.fullmatch(r"@[A-Za-z0-9_]{4,32}", ch):
        await update.message.reply_text("❌ فرمت اشتباهه. مثل @mychannel بفرست.", reply_markup=cancel_kb())
        return ADD_CHANNEL
    chans = get_channels()
    if ch in chans:
        await update.message.reply_text("⚠️ این کانال قبلاً اضافه شده.", reply_markup=admin_kb())
        return ConversationHandler.END
    chans.append(ch)
    save_channels(chans)
    _join_cache.clear()
    await update.message.reply_text(f"✅ کانال {ch} اضافه شد.\n"
                                    f"یادت نره بات رو ادمین کانال کنی!", reply_markup=admin_kb())
    return ConversationHandler.END

async def ch_del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    idx = int(context.match.group(1))
    chans = get_channels()
    if 0 <= idx < len(chans):
        removed = chans.pop(idx)
        save_channels(chans)
        _join_cache.clear()
        await q.answer(f"{removed} حذف شد 🗑")
    else:
        await q.answer("❌ پیدا نشد", show_alert=True)
    await adm_channels_cb(update, context)

# ── 🗂 مدیریت دسته‌بندی‌ها ──
async def adm_cats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    await q.answer()
    cats = get_categories()
    lines = []
    btns = []
    for key, label in cats.items():
        cur.execute("SELECT COUNT(*) c FROM configs WHERE category=?", (key,))
        n = cur.fetchone()["c"]
        lines.append(f"▫️ {label} — {fmt(n)} کانفیگ")
        btns.append([(f"🗑 حذف {label}", f"cat_del_{key}")])
    btns.append([("➕ افزودن دسته", "cat_add")])
    btns.append([("🔙 تنظیمات", "admin_settings")])
    await safe_edit(q, panel("🗂 دسته‌بندی‌های فروشگاه", lines), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb(btns))

async def cat_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "🗂 نام دسته جدید رو بفرست (با ایموجی، مثل `🚀 پرسرعت`):",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return ADDCAT_NAME

async def receive_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = update.message.text.strip()
    if not label:
        await update.message.reply_text("❌ نام خالیه!", reply_markup=cancel_kb())
        return ADDCAT_NAME
    cats = get_categories()
    key = f"c{int(time.time()) % 1000000}"
    cats[key] = label
    save_categories(cats)
    await update.message.reply_text(f"✅ دسته «{label}» اضافه شد.", reply_markup=admin_kb())
    return ConversationHandler.END

async def cat_del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    q = update.callback_query
    key = context.match.group(1)
    cats = get_categories()
    if key not in cats:
        await q.answer("❌ پیدا نشد", show_alert=True)
        return
    if len(cats) <= 1:
        await q.answer("⚠️ حداقل یک دسته باید بمونه!", show_alert=True)
        return
    cur.execute("SELECT COUNT(*) c FROM configs WHERE category=?", (key,))
    n = cur.fetchone()["c"]
    cats.pop(key)
    save_categories(cats)
    await q.answer(f"حذف شد ({n} کانفیگ از فروشگاه مخفی می‌شه)", show_alert=bool(n))
    await adm_cats_cb(update, context)

# ════════════════════ ⚠️ خطاها ════════════════════
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update: %s", context.error, exc_info=context.error)

# ════════════════════ 🚀 اجرا ════════════════════
def main():
    app = Application.builder().token(TOKEN).build()

    # دروازه سراسری: ضد اسپم / بن / تعمیر / جوین اجباری
    app.add_handler(TypeHandler(Update, global_gate), group=-1)

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(adm_user_search_entry, pattern=r"^adm_user_search$"),
            CallbackQueryHandler(coin_action_entry, pattern=r"^act_addcoin_(\d+)$"),
            CallbackQueryHandler(coin_action_entry, pattern=r"^act_subcoin_(\d+)$"),
            CallbackQueryHandler(addcfg_entry, pattern=r"^adm_addcfg$"),
            CallbackQueryHandler(editcfg_entry, pattern=r"^cfg_edit_(\d+)$"),
            CallbackQueryHandler(broadcast_entry, pattern=r"^adm_bc$"),
            CallbackQueryHandler(admin_send_msg_entry, pattern=r"^admin_send_msg_entry$"),
            CallbackQueryHandler(admin_send_to_user_direct, pattern=r"^admin_send_to_(\d+)$"),
            CallbackQueryHandler(admin_reply_sel_cb, pattern=r"^admin_reply_sel_(\d+)_(\d+)$"),
            CallbackQueryHandler(support_start_cb, pattern=r"^support_start$"),
            CallbackQueryHandler(redeem_start_cb, pattern=r"^redeem_start$"),
            CallbackQueryHandler(gift_new_entry, pattern=r"^gift_new$"),
            CallbackQueryHandler(set_welcome_entry, pattern=r"^set_welcome_entry$"),
            CallbackQueryHandler(set_botname_entry, pattern=r"^set_botname_entry$"),
            CallbackQueryHandler(set_daily_entry, pattern=r"^set_daily_entry$"),
            CallbackQueryHandler(ch_add_entry, pattern=r"^ch_add$"),
            CallbackQueryHandler(cat_add_entry, pattern=r"^cat_add$"),
        ],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            ADDCFG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cfg_name)],
            ADDCFG_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cfg_content)],
            ADDCFG_CATEGORY: [CallbackQueryHandler(receive_cfg_category, pattern=r"^cfgcat_(\w+)$")],
            ADDCFG_PRICE_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cfg_price_stock)],
            EDIT_PRICE_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_price_stock)],
            BC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bc_text)],
            BC_CONFIRM: [CallbackQueryHandler(send_broadcast, pattern=r"^bc_yes$")],
            SEND_MSG_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_send_msg_uid)],
            SEND_MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_send_msg_text)],
            SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_support_msg)],
            ADMIN_REPLY_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_reply)],
            REDEEM_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_redeem_code)],
            GIFT_CREATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_create)],
            SET_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_welcome_msg)],
            SET_DAILY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_daily_cfg)],
            SET_BOTNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_botname)],
            ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel)],
            ADDCAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cat_name)],
            USER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_user_search)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern=r"^cancel_conv$"),
        ],
        per_user=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(conv)

    # ── کاربر ──
    app.add_handler(CallbackQueryHandler(back_main, pattern=r"^back_main$"))
    app.add_handler(CallbackQueryHandler(help_cb, pattern=r"^help$"))
    app.add_handler(CallbackQueryHandler(website_cb, pattern=r"^website$"))
    app.add_handler(CallbackQueryHandler(profile_cb, pattern=r"^profile$"))
    app.add_handler(CallbackQueryHandler(invite_cb, pattern=r"^invite$"))
    app.add_handler(CallbackQueryHandler(wallet_cb, pattern=r"^wallet$"))
    app.add_handler(CallbackQueryHandler(tx_hist_cb, pattern=r"^tx_hist_(\d+)$"))
    app.add_handler(CallbackQueryHandler(daily_cb, pattern=r"^daily$"))
    app.add_handler(CallbackQueryHandler(shop_cb, pattern=r"^shop$"))
    app.add_handler(CallbackQueryHandler(shopcat_cb, pattern=r"^shopcat_(\w+)_(\d+)$"))
    app.add_handler(CallbackQueryHandler(buy_ask, pattern=r"^buy_(\d+)$"))
    app.add_handler(CallbackQueryHandler(buy_confirm, pattern=r"^confirm_buy_(\d+)$"))
    app.add_handler(CallbackQueryHandler(support_entry_cb, pattern=r"^support_entry$"))
    app.add_handler(CallbackQueryHandler(redeem_entry_cb, pattern=r"^redeem_entry$"))
    app.add_handler(CallbackQueryHandler(lb_coins_cb, pattern=r"^lb_coins$"))
    app.add_handler(CallbackQueryHandler(lb_wins_cb, pattern=r"^lb_wins$"))
    app.add_handler(CallbackQueryHandler(lb_level_cb, pattern=r"^lb_level$"))
    app.add_handler(CallbackQueryHandler(chk_join_cb, pattern=r"^chk_join$"))
    app.add_handler(CallbackQueryHandler(noop_cb, pattern=r"^noop$"))

    # ── بازی‌ها ──
    app.add_handler(CallbackQueryHandler(games_cb, pattern=r"^games$"))
    app.add_handler(CallbackQueryHandler(g_find_dice_cb, pattern=r"^g_find_dice$"))
    app.add_handler(CallbackQueryHandler(g_find_rps_cb, pattern=r"^g_find_rps$"))
    app.add_handler(CallbackQueryHandler(g_cancel_cb, pattern=r"^g_cancel_(dice|rps)$"))
    app.add_handler(CallbackQueryHandler(dice_roll_cb, pattern=r"^dice_roll_(d\d+)_(1|2)$"))
    app.add_handler(CallbackQueryHandler(rps_pick_cb, pattern=r"^rps_pick_(r\d+)_(1|2)_(r|p|s)$"))
    app.add_handler(CallbackQueryHandler(g_slots_cb, pattern=r"^g_slots$"))
    app.add_handler(CallbackQueryHandler(g_slots_bet_cb, pattern=r"^g_slots_bet_(\d+)$"))
    app.add_handler(CallbackQueryHandler(g_guess_cb, pattern=r"^g_guess$"))
    app.add_handler(CallbackQueryHandler(g_guess_play_cb, pattern=r"^g_guess_play$"))
    app.add_handler(CallbackQueryHandler(g_guess_pick_cb, pattern=r"^g_guess_pick_(\d)$"))
    app.add_handler(CallbackQueryHandler(g_flip_cb, pattern=r"^g_flip$"))
    app.add_handler(CallbackQueryHandler(g_flip_bet_cb, pattern=r"^g_flip_bet_(\d+)$"))
    app.add_handler(CallbackQueryHandler(g_flip_go_cb, pattern=r"^g_flip_go_(\d+)_(h|t)$"))

    # ── ادمین ──
    app.add_handler(CallbackQueryHandler(admin_back, pattern=r"^admin_back$"))
    app.add_handler(CallbackQueryHandler(adm_users_cb, pattern=r"^adm_users$"))
    app.add_handler(CallbackQueryHandler(adm_recent_cb, pattern=r"^adm_recent_(\d+)$"))
    app.add_handler(CallbackQueryHandler(adm_topbuyers_cb, pattern=r"^adm_topbuyers$"))
    app.add_handler(CallbackQueryHandler(manage_user_cb, pattern=r"^act_manage_(\d+)$"))
    app.add_handler(CallbackQueryHandler(act_usertx_cb, pattern=r"^act_usertx_(\d+)$"))
    app.add_handler(CallbackQueryHandler(ban_user_cb, pattern=r"^act_ban_(\d+)$"))
    app.add_handler(CallbackQueryHandler(unban_user_cb, pattern=r"^act_unban_(\d+)$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_cb, pattern=r"^adm_cfg$"))
    app.add_handler(CallbackQueryHandler(adm_listcfg_cb, pattern=r"^adm_listcfg_(\d+)$"))
    app.add_handler(CallbackQueryHandler(cfgmng_cb, pattern=r"^cfgmng_(\d+)$"))
    app.add_handler(CallbackQueryHandler(cfg_view_cb, pattern=r"^cfg_view_(\d+)$"))
    app.add_handler(CallbackQueryHandler(cfg_toggle_cb, pattern=r"^cfg_toggle_(\d+)$"))
    app.add_handler(CallbackQueryHandler(cfg_del_ask, pattern=r"^cfg_del_(\d+)$"))
    app.add_handler(CallbackQueryHandler(cfg_del_confirm, pattern=r"^cfg_delyes_(\d+)$"))
    app.add_handler(CallbackQueryHandler(adm_gifts_cb, pattern=r"^adm_gifts$"))
    app.add_handler(CallbackQueryHandler(gift_list_cb, pattern=r"^gift_list$"))
    app.add_handler(CallbackQueryHandler(gift_toggle_cb, pattern=r"^gift_toggle_(\d+)$"))
    app.add_handler(CallbackQueryHandler(gift_del_cb, pattern=r"^gift_del_(\d+)$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern=r"^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_backup_cb, pattern=r"^admin_backup$"))
    app.add_handler(CallbackQueryHandler(admin_settings_cb, pattern=r"^admin_settings$"))
    app.add_handler(CallbackQueryHandler(admin_support_inbox, pattern=r"^admin_support_inbox$"))
    app.add_handler(CallbackQueryHandler(admin_view_msg_cb, pattern=r"^admin_view_msg_(\d+)$"))
    app.add_handler(CallbackQueryHandler(tgl_maint_cb, pattern=r"^tgl_maint$"))
    app.add_handler(CallbackQueryHandler(tgl_buynotif_cb, pattern=r"^tgl_buynotif$"))
    app.add_handler(CallbackQueryHandler(tgl_joinnotif_cb, pattern=r"^tgl_joinnotif$"))
    app.add_handler(CallbackQueryHandler(tgl_forcejoin_cb, pattern=r"^tgl_forcejoin$"))
    app.add_handler(CallbackQueryHandler(adm_channels_cb, pattern=r"^adm_channels$"))
    app.add_handler(CallbackQueryHandler(ch_del_cb, pattern=r"^ch_del_(\d+)$"))
    app.add_handler(CallbackQueryHandler(adm_cats_cb, pattern=r"^adm_cats$"))
    app.add_handler(CallbackQueryHandler(cat_del_cb, pattern=r"^cat_del_(\w+)$"))

    # ── سازگاری با دکمه‌های نسخه قبلی ──
    app.add_handler(CallbackQueryHandler(games_cb, pattern=r"^game_menu$"))
    app.add_handler(CallbackQueryHandler(g_find_dice_cb, pattern=r"^game_find$"))
    app.add_handler(CallbackQueryHandler(profile_cb, pattern=r"^my_stats$"))
    app.add_handler(CallbackQueryHandler(lb_coins_cb, pattern=r"^leaderboard$"))
    app.add_handler(CallbackQueryHandler(lb_wins_cb, pattern=r"^leaderboard_games$"))
    app.add_handler(CallbackQueryHandler(tx_hist_legacy, pattern=r"^tx_history$"))
    app.add_handler(CallbackQueryHandler(adm_users_cb, pattern=r"^admin_users$"))
    app.add_handler(CallbackQueryHandler(adm_users_cb, pattern=r"^admin_coins$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_cb, pattern=r"^admin_configs$"))
    app.add_handler(CallbackQueryHandler(shopcat_legacy, pattern=r"^cat_(\w+)$"))

    app.add_error_handler(error_handler)

    print("═" * 46)
    print("  💎 VIP SERVICES PRO — بات با موفقیت اجرا شد!")
    print("═" * 46)
    app.run_polling()

if __name__ == "__main__":
    main()
