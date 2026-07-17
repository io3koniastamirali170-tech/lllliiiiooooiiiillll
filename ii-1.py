import os
import re
import time
import random
import sqlite3
import logging
import json
from datetime import datetime

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ==================== تنظیمات ====================
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 7438138322
BOT_NAME = "🎮 VIP Config Shop"
WEBSITE_URL = "https://liiiiiooiiiillll.sryze.cc"

CATEGORIES = {"general": "اراک", "premium": "کرج", "hot": "خلیج نیگر"}
NEW_USER_BONUS = 10
REFERRAL_BONUS = 15
DAILY_MIN, DAILY_MAX = 15, 50
GAME_REWARD = 5

# ==================== متغیرهای مینی گیم (PVP) ====================
waiting_player = None
active_matches = {}
match_counter = 0

# ==================== دیتابیس ====================
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

conn.commit()

# اضافه کردن ستون‌های جدید بدون پاک شدن داده‌ها
for alter_sql in [
    "ALTER TABLE configs ADD COLUMN sales_count INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN total_spent INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN game_wins INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN game_losses INTEGER DEFAULT 0",
    "ALTER TABLE configs ADD COLUMN is_active INTEGER DEFAULT 1",
]:
    try:
        cur.execute(alter_sql)
        conn.commit()
    except sqlite3.OperationalError:
        pass

# ==================== توابع تنظیمات پایدار ====================
def get_setting(key: str, default: str = "") -> str:
    cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    cur.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

# تنظیمات اولیه
if not get_setting("maintenance_mode"):
    set_setting("maintenance_mode", "0")
if not get_setting("welcome_msg"):
    set_setting("welcome_msg", f"🌟 به {BOT_NAME} خوش آمدی!")
if not get_setting("purchase_notify"):
    set_setting("purchase_notify", "1")

# ==================== States ====================
(ASK_USER_ID, ASK_AMOUNT, ADDCFG_NAME, ADDCFG_CONTENT, ADDCFG_CATEGORY,
 ADDCFG_PRICE_STOCK, EDIT_PRICE_STOCK, BC_TEXT, BC_CONFIRM,
 SEND_MSG_UID, SEND_MSG_TEXT, SUPPORT_MSG, ADMIN_REPLY_MSG,
 ADMIN_REPLY_SEL) = range(14)

# ==================== توابع کمکی ====================
def md_escape(text) -> str:
    return re.sub(r'([_*`\[])', r'\\\1', str(text))

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

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚫 لغو عملیات", callback_data="cancel_conv")]])

def is_maintenance() -> bool:
    return get_setting("maintenance_mode") == "1"

def time_ago(timestamp) -> str:
    diff = time.time() - timestamp
    if diff < 60:
        return f"{int(diff)} ثانیه پیش"
    elif diff < 3600:
        return f"{int(diff // 60)} دقیقه پیش"
    elif diff < 86400:
        return f"{int(diff // 3600)} ساعت پیش"
    else:
        return f"{int(diff // 86400)} روز پیش"

# ==================== منوها ====================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("✨ دریافت کانفیگ", callback_data="shop")],
        [InlineKeyboardButton("🤌 امتیاز ها", callback_data="wallet"),
         InlineKeyboardButton("😇 امتیاز روزانه", callback_data="daily")],
        [InlineKeyboardButton("🎮 مینی گیم", callback_data="game_menu")],
        [InlineKeyboardButton("🌍 اطلاعات من", callback_data="my_stats"),
         InlineKeyboardButton("🎉 دعوت دوستان", callback_data="invite")],
        [InlineKeyboardButton("🏆 جدول رتبه‌بندی", callback_data="leaderboard")],
        [InlineKeyboardButton("💬 پشتیبانی", callback_data="support_entry"),
         InlineKeyboardButton("🌐 وبسایت ما", callback_data="website")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_menu():
    keyboard = [
        [InlineKeyboardButton("💰 مدیریت امتیازات", callback_data="admin_coins")],
        [InlineKeyboardButton("📦 مدیریت کانفیگ", callback_data="admin_configs")],
        [InlineKeyboardButton("👤 مدیریت کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("📨 ارسال پیام به کاربر", callback_data="admin_send_msg_entry")],
        [InlineKeyboardButton("💬 صندوق پشتیبانی", callback_data="admin_support_inbox")],
        [InlineKeyboardButton("📢 ارسال همگانی", callback_data="admin_broadcast_entry")],
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin_stats")],
        [InlineKeyboardButton("💾 بکاپ دیتابیس", callback_data="admin_backup")],
        [InlineKeyboardButton("⚙️ تنظیمات بات", callback_data="admin_settings")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def shop_menu():
    keyboard = [[InlineKeyboardButton(label, callback_data=f"cat_{key}")] for key, label in CATEGORIES.items()]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def profile_text(user) -> str:
    ban = "⛔ مسدود" if user["is_banned"] else "✅ فعال"
    win_rate = "N/A"
    total_games = (user["game_wins"] or 0) + (user["game_losses"] or 0)
    if total_games > 0:
        win_rate = f"{(user['game_wins'] or 0) * 100 // total_games}%"
    return (
        f"👤 *پروفایل کاربر*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: `{user['id']}`\n"
        f"📛 نام: {md_escape(user['first_name'] or '-')}\n"
        f"🔗 یوزرنیم: @{md_escape(user['username'] or '-')}\n"
        f"💰 سکه: {user['coins']}\n"
        f"📦 کانفیگ استفاده‌شده: {user['used_configs']}\n"
        f"💵 مجموع خرید: {user['total_spent']}\n"
        f"🌍 کشور: {md_escape(user['country'] or '-')}\n"
        f"📅 تاریخ عضویت: {user['join_date']}\n"
        f"🎮 بازی‌ها: {total_games} (برد: {user['game_wins'] or 0} | نرخ برد: {win_rate})\n"
        f"وضعیت: {ban}"
    )

def profile_kb(user):
    uid = user["id"]
    ban_btn = (
        InlineKeyboardButton("✅ رفع مسدودتت", callback_data=f"act_unban_{uid}")
        if user["is_banned"]
        else InlineKeyboardButton("⛔ مسدود کردن", callback_data=f"act_ban_{uid}")
    )
    keyboard = [
        [InlineKeyboardButton("➕ افزایش سکه", callback_data=f"act_addcoin_{uid}"),
         InlineKeyboardButton("➖ کاهش سکه", callback_data=f"act_subcoin_{uid}")],
        [InlineKeyboardButton("📨 ارسال پیام", callback_data=f"admin_send_to_{uid}")],
        [ban_btn],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ==================== شروع ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if is_maintenance() and uid != ADMIN_ID:
        await update.message.reply_text(
            "🔧 بات در حال تعمیر و نگهداری است.\nلطفاً بعداً مراجعه کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌐 وبسایت ما", url=WEBSITE_URL)]])
        )
        return

    existing = get_user(uid)

    if not existing:
        country = "Unknown"
        try:
            res = requests.get("https://ipapi.co/json/", timeout=3).json()
            country = res.get("country_name", "Unknown")
        except Exception:
            pass

        ref_code = f"VIP{uid % 1000000:06d}"
        join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        referrer_id = 0
        if context.args:
            arg = context.args[0]
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
            try:
                await context.bot.send_message(
                    referrer_id, f"🎉 یک نفر با لینک دعوت تو عضو شد! +{REFERRAL_BONUS} سکه گرفتی."
                )
            except Exception:
                pass

        # اطلاع به ادمین about new user
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🆕 کاربر جدید:\n👤 {user.first_name}\n🆔 `{uid}`\n🔗 @{user.username or '-'}\n🌍 {country}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        welcome = get_setting("welcome_msg", f"🌟 به {BOT_NAME} خوش آمدی!")
        await update.message.reply_text(
            f"{welcome}\n\n🎁 {NEW_USER_BONUS} سکه هدیه گرفتی!\n🔰 کد معرف تو: `{ref_code}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(),
        )
    else:
        if existing["is_banned"]:
            await update.message.reply_text("⛔ شما مسدود هستید.\nبرای اعتراض از بخش پشتیبانی استفاده کنید.")
            return
        # بروزرسانی نام و یوزرنیم
        cur.execute("UPDATE users SET first_name=?, username=? WHERE id=?",
                     (user.first_name, user.username, uid))
        conn.commit()
        await update.message.reply_text(f"🔄 خوش برگشتی، {user.first_name}!", reply_markup=main_menu())


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, f"🏠 {BOT_NAME}\n\nیکی از گزینه‌ها رو انتخاب کن:", reply_markup=main_menu())


async def website_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🌐 *وبسایت ما*\n"
        "━━━━━━━━━━━━━━\n"
        f"برای مشاهده وبسایت ما روی دکمه زیر کلیک کن:\n\n"
        f"🔗 آدرس: `{WEBSITE_URL}`"
    )
    kb = [
        [InlineKeyboardButton("🚀 باز کردن وبسایت", url=WEBSITE_URL)],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "❓ *راهنما*\n"
        "━━━━━━━━━━━━━━\n"
        "🆔 ایدی اونر: @liiiiiooiiiillll\n"
        "🌐 وبسایت: liiiiiooiiiillll.sryze.cc\n\n"
        "🎁 هر ۲۴ ساعت یک‌بار «جایزه روزانه» بگیر\n"
        "🎮 در بخش «مینی گیم» با کاربران آنلاین تاس بزن و سکه ببر\n"
        "🎉 با «دعوت دوستان» به ازای هر معرفی سکه بگیر\n"
        "🏆 «جدول رتبه‌بندی» بهترین‌ها رو ببین\n"
        "📊 وضعیت خودت رو در «آمار من» ببین\n"
        "💰 موجودی و تاریخچه در «کیف پول»\n"
        "💬 سوال داری؟ «پشتیبانی» پیام بده\n"
        "🌐 از «وبسایت ما» دیدن کن"
    )
    kb = [
        [InlineKeyboardButton("🌐 وبسایت", url=WEBSITE_URL)],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def my_stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    cur.execute("SELECT COUNT(*) c FROM users WHERE refered_by=?", (uid,))
    referred = cur.fetchone()["c"]
    total_games = (user["game_wins"] or 0) + (user["game_losses"] or 0)
    text = (
        f"📊 *آمار من*\n━━━━━━━━━━━━━━\n"
        f"💰 سکه فعلی: {user['coins']}\n"
        f"📦 کانفیگ خریداری‌شده: {user['used_configs']}\n"
        f"💵 مجموع خرید: {user['total_spent']}\n"
        f"👥 دوستان دعوت‌شده: {referred}\n"
        f"🎮 بازی‌ها: {total_games} (برد: {user['game_wins'] or 0})\n"
        f"📅 عضویت از: {user['join_date']}"
    )
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


async def invite_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user['referal_code']}"
    cur.execute("SELECT COUNT(*) c FROM users WHERE refered_by=?", (uid,))
    referred = cur.fetchone()["c"]
    text = (
        f"🎉 *دعوت دوستان*\n━━━━━━━━━━━━━━\n"
        f"به ازای هر دوست که با لینک تو عضو بشه، {REFERRAL_BONUS} سکه می‌گیری!\n\n"
        f"🔗 لینک اختصاصی تو:\n{link}\n\n"
        f"👥 تعداد دعوت‌شده‌ها: {referred}"
    )
    kb = [
        [InlineKeyboardButton("📤 اشتراک‌گذاری لینک", switch_inline_query=f"با لینک من تو بات VIP عضو شو و {NEW_USER_BONUS} سکه هدیه بگیر!")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ==================== جدول رتبه‌بندی ====================
async def leaderboard_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur.execute("SELECT * FROM users ORDER BY coins DESC LIMIT 10")
    rows = cur.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 *جدول رتبه‌بندی (ثروتمندترین‌ها)*\n━━━━━━━━━━━━━━\n"
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"  {i+1}."
        name = md_escape(r['first_name'] or 'ناشناس')
        text += f"{medal} {name} — 💰{r['coins']}\n"
    kb = [
        [InlineKeyboardButton("🎮 رتبه بازیکنان", callback_data="leaderboard_games")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def leaderboard_games_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur.execute("SELECT * FROM users WHERE (game_wins + game_losses) > 0 ORDER BY game_wins DESC LIMIT 10")
    rows = cur.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    text = "🎮 *جدول رتبه‌بندی بازیکنان*\n━━━━━━━━━━━━━━\n"
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"  {i+1}."
        name = md_escape(r['first_name'] or 'ناشناس')
        total = (r['game_wins'] or 0) + (r['game_losses'] or 0)
        wr = (r['game_wins'] or 0) * 100 // total if total > 0 else 0
        text += f"{medal} {name} — 🏆{r['game_wins'] or 0} برد | نرخ: {wr}%\n"
    if not rows:
        text += "هنوز کسی بازی نکرده!"
    kb = [[InlineKeyboardButton("🏆 رتبه ثروت", callback_data="leaderboard")],
          [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ==================== کیف پول ====================
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    text = (
        f"💰 *کیف پول*\n━━━━━━━━━━━━━━\n"
        f"موجودی: {user['coins']} سکه\n"
        f"کانفیگ‌های خریداری‌شده: {user['used_configs']}\n"
        f"مجموع خرید: {user['total_spent']} سکه"
    )
    kb = [
        [InlineKeyboardButton("📜 تاریخچه تراکنش‌ها", callback_data="tx_history")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def tx_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    cur.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    if not rows:
        text = "📜 هنوز تراکنشی ثبت نشده."
    else:
        lines = ["📜 *۱۰ تراکنش اخیر*", "━━━━━━━━━━━━━━"]
        for r in rows:
            sign = "+" if r["amount"] >= 0 else ""
            date = datetime.fromtimestamp(r["date"]).strftime("%m-%d %H:%M")
            lines.append(f"{date} | {sign}{r['amount']} | {md_escape(r['description'])}")
        text = "\n".join(lines)
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="wallet")]]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ==================== روزانه ====================
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    now = time.time()
    last = user["last_daily"]

    if last and now - last < 86400:
        remaining = int(86400 - (now - last))
        h, m = remaining // 3600, (remaining % 3600) // 60
        await safe_edit(query, f"⏳ {h} ساعت و {m} دقیقه دیگه بیا سراغ جایزه روزانه!", reply_markup=main_menu())
        return

    reward = random.randint(DAILY_MIN, DAILY_MAX)
    cur.execute("UPDATE users SET coins=coins+?, last_daily=? WHERE id=?", (reward, now, uid))
    conn.commit()
    log_tx(uid, "daily_bonus", reward, "جایزه روزانه")
    await safe_edit(query, f"🎁 جایزه روزانه‌ت رسید: +{reward} سکه!", reply_markup=main_menu())


# ==================== فروشگاه ====================
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "📦 یکی از دسته‌بندی‌ها رو انتخاب کن:", reply_markup=shop_menu())


async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = context.match.group(1)
    cur.execute("SELECT * FROM configs WHERE category=? AND stock>0 AND is_active=1 ORDER BY sales_count DESC", (cat,))
    configs = cur.fetchall()

    if not configs:
        await safe_edit(query, "📭 فعلاً کانفیگی موجود نیست. به موکی بگو کانفیگ بزاره!", reply_markup=shop_menu())
        return

    label = CATEGORIES.get(cat, cat)
    text = f"📂 *{label}*\n━━━━━━━━━━━━━━\n"
    keyboard = []
    for cfg in configs:
        tag = " 🔥" if cfg["sales_count"] >= 10 else (" ⭐" if cfg["sales_count"] >= 5 else "")
        text += f"🔹 {md_escape(cfg['name'])}{tag} — 💰{cfg['price']} سکه — موجودی: {cfg['stock']}\n"
        keyboard.append([InlineKeyboardButton(f"🛍 خرید {cfg['name']}", callback_data=f"buy_{cfg['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shop")])
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


async def buy_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg or cfg["stock"] <= 0 or not cfg.get("is_active", 1):
        await safe_edit(query, "❌ این کانفیگ دیگر موجود نیست.", reply_markup=shop_menu())
        return
    text = (
        f"🧾 *تایید خرید*\n━━━━━━━━━━━━━━\n"
        f"نام: {md_escape(cfg['name'])}\n"
        f"قیمت: {cfg['price']} سکه\n"
        f"موجودی: {cfg['stock']}\n\nآیا خرید رو تایید می‌کنی؟"
    )
    kb = [
        [InlineKeyboardButton("✅ تایید خرید", callback_data=f"confirm_buy_{cfg_id}")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"cat_{cfg['category']}")],
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def buy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    cfg_id = int(context.match.group(1))

    cfg = get_config(cfg_id)
    if not cfg or cfg["stock"] <= 0 or not cfg.get("is_active", 1):
        await query.answer("❌ تمام شد!", show_alert=True)
        await safe_edit(query, "❌ این کانفیگ دیگر موجود نیست.", reply_markup=shop_menu())
        return

    user = get_user(uid)
    if user["coins"] < cfg["price"]:
        await query.answer("❌ سکه کافی نداری!", show_alert=True)
        await safe_edit(query, f"❌ سکه نداری! لازم: {cfg['price']} سکه | موجودی تو: {user['coins']} سکه", reply_markup=shop_menu())
        return

    cur.execute("UPDATE users SET coins=coins-?, used_configs=used_configs+1, total_spent=total_spent+? WHERE id=?",
                (cfg["price"], cfg["price"], uid))
    cur.execute("UPDATE configs SET stock=stock-1, sales_count=sales_count+1 WHERE id=?", (cfg_id,))
    conn.commit()
    log_tx(uid, "purchase", -cfg["price"], f"خرید {cfg['name']}")

    # اطلاع به ادمین
    if get_setting("purchase_notify") == "1":
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🛍 *خرید جدید*\n━━━━━━━━━━━━━━\n"
                f"👤 {user['first_name']} (`{uid}`)\n"
                f"📦 {cfg['name']}\n"
                f"💰 {cfg['price']} سکه",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

    await query.answer("✅ دریافت موفق!")
    delivery = (
        f"✅ *خرید با موفقیت انجام شد!*\n\n"
        f"📥 محتوای کانفیگ «{md_escape(cfg['name'])}»:\n"
        f"```\n{cfg['config']}\n```\n\n"
        f"💡 اگر مشکلی بود از بخش «پشتیبانی» پیام بده."
    )
    await safe_edit(query, delivery, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


# ==================== پشتیبانی (کاربر به ادمین) ====================
async def support_entry_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "💬 *پشتیبانی*\n"
        "━━━━━━━━━━━━━━\n"
        "پیامت رو بفرست تا مستقیم به ادمین برسه.\n"
        "ادمین می‌تونه جوابت رو بده.\n\n"
        "برای شروع روی دکمه زیر کلیک کن:"
    )
    kb = [
        [InlineKeyboardButton("✍️ ارسال پیام", callback_data="support_start")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def support_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "✍️ پیامت رو الان بفرست:", reply_markup=cancel_kb())
    return SUPPORT_MSG

async def receive_support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    msg_text = update.message.text

    # ذخیره در دیتابیس
    cur.execute(
        "INSERT INTO support_messages (user_id, message, is_from_admin, date, is_read) VALUES (?,?,0,?,0)",
        (uid, msg_text, time.time())
    )
    conn.commit()
    msg_id = cur.lastrowid

    # ارسال به ادمین
    try:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 پاسخ دادن", callback_data=f"admin_reply_sel_{uid}_{msg_id}")],
            [InlineKeyboardButton("👤 پروفایل", callback_data=f"act_manage_{uid}")]
        ])
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 *پیام جدید از پشتیبانی*\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 {user['first_name'] or 'ناشناس'} (`{uid}`)\n"
            f"🔗 @{user['username'] or '-'}\n\n"
            f"💬 {md_escape(msg_text)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
    except Exception:
        pass

    await update.message.reply_text(
        "✅ پیامت ارسال شد!\nبه محض اینکه ادمین جوابت رو بده، بهت اطلاع می‌دیم.",
        reply_markup=main_menu()
    )
    return ConversationHandler.END


# ==================== مینی گیم PVP ====================
async def game_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    total = (user["game_wins"] or 0) + (user["game_losses"] or 0)
    wr = (user["game_wins"] or 0) * 100 // total if total > 0 else 0
    text = (
        "🎮 *مینی گیم: نبرد تاس*\n"
        "━━━━━━━━━━━━━━\n"
        f"در این بازی با یک کاربر آنلاین دیگر مسابقه می‌دی.\n"
        f"هر دو نفر تاس می‌زنید و کسی که عدد بزرگ‌تری بیاره برنده‌ست!\n"
        f"🏆 جایزه برنده: {GAME_REWARD} سکه\n\n"
        f"📊 آمار تو: {total} بازی | {user['game_wins'] or 0} برد | نرخ برد: {wr}%\n\n"
        f"آماده‌ای حریف پیدا کنی؟"
    )
    kb = [
        [InlineKeyboardButton("🔍 جستجوی حریف", callback_data="game_find")],
        [InlineKeyboardButton("🏆 جدول بازیکنان", callback_data="leaderboard_games")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def game_find_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_player, match_counter
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if waiting_player == uid:
        await query.answer("⚠️ تو الان داری توی صف انتظاری!", show_alert=True)
        return

    if waiting_player is None:
        waiting_player = uid
        kb = [[InlineKeyboardButton("❌ لغو جستجو", callback_data="game_cancel_search")]]
        await safe_edit(query, "⏳ در حال جستجوی حریف...\nلطفا صبر کن (برای لغو دکمه رو بزن).", reply_markup=InlineKeyboardMarkup(kb))
    else:
        opponent_id = waiting_player
        waiting_player = None

        match_counter += 1
        match_id = f"match_{match_counter}"

        active_matches[match_id] = {
            "p1": opponent_id,
            "p2": uid,
            "r1": None,
            "r2": None
        }

        p1_name = get_user(opponent_id)["first_name"] or "ناشناس"
        p2_name = query.from_user.first_name or "ناشناس"

        kb = [[InlineKeyboardButton("🎲 پرتاب تاس", callback_data=f"game_roll_{match_id}_1")]]

        try:
            await context.bot.send_message(
                opponent_id,
                f"🎮 حریف پیدا شد!\n━━━━━━━━━━━━━━\n"
                f"🗡 مقابله تو با: {p2_name}\n\nآماده‌ای تاس بزنی؟",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            logger.error(f"Failed to notify p1 {opponent_id}: {e}")
            del active_matches[match_id]
            await query.answer("❌ حریف پیدا شد اما دیگه آنلاین نبود! دوباره امتحان کن.", show_alert=True)
            return

        kb2 = [[InlineKeyboardButton("🎲 پرتاب تاس", callback_data=f"game_roll_{match_id}_2")]]
        await safe_edit(
            query,
            f"🎮 حریف پیدا شد!\n━━━━━━━━━━━━━━\n"
            f"🗡 مقابله تو با: {p1_name}\n\nآماده‌ای تاس بزنی؟",
            reply_markup=InlineKeyboardMarkup(kb2)
        )

async def game_roll_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    match_id = context.match.group(1)
    player_num = int(context.match.group(2))

    match = active_matches.get(match_id)
    if not match:
        await query.answer("❌ این بازی دیگر وجود ندارد.", show_alert=True)
        return

    roll = random.randint(1, 6)
    dice_emojis = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

    if player_num == 1:
        match["r1"] = roll
    else:
        match["r2"] = roll

    await query.edit_message_text(
        f"🎲 تو {dice_emojis[roll]} ({roll}) انداختی!\n⏳ الان منتظر نتیجه حریف هستیم..."
    )

    if match["r1"] is not None and match["r2"] is not None:
        await resolve_match(match_id, context)

async def resolve_match(match_id: str, context: ContextTypes.DEFAULT_TYPE):
    match = active_matches.pop(match_id, None)
    if not match:
        return

    p1, p2 = match["p1"], match["p2"]
    r1, r2 = match["r1"], match["r2"]
    dice = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

    p1_user = get_user(p1)
    p2_user = get_user(p2)
    p1_name = p1_user["first_name"] or "بازیکن ۱"
    p2_name = p2_user["first_name"] or "بازیکن ۲"

    text = (
        f"🎮 *نتیجه نبرد تاس*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 {p1_name}: {dice[r1]} ({r1})\n"
        f"👤 {p2_name}: {dice[r2]} ({r2})\n"
        f"━━━━━━━━━━━━━━\n"
    )

    winner_id = None
    loser_id = None
    if r1 > r2:
        winner_id = p1
        loser_id = p2
        text += f"🏆 برنده: {p1_name} (+{GAME_REWARD} سکه)"
    elif r2 > r1:
        winner_id = p2
        loser_id = p1
        text += f"🏆 برنده: {p2_name} (+{GAME_REWARD} سکه)"
    else:
        text += "🤝 مساوی شد! سکه‌ای تقسیم نمیشه."

    if winner_id:
        cur.execute("UPDATE users SET coins=coins+?, game_wins=game_wins+1 WHERE id=?", (GAME_REWARD, winner_id))
        conn.commit()
        log_tx(winner_id, "game_win", GAME_REWARD, "برد در مینی گیم تاس")
    if loser_id and winner_id:
        cur.execute("UPDATE users SET game_losses=game_losses+1 WHERE id=?", (loser_id,))
        conn.commit()

    kb = [
        [InlineKeyboardButton("🔄 بازی مجدد", callback_data="game_find")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_main")]
    ]

    try:
        await context.bot.send_message(p1, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        pass
    try:
        if p1 != p2:
            await context.bot.send_message(p2, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        pass

async def game_cancel_search_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_player
    query = update.callback_query
    uid = query.from_user.id

    if waiting_player == uid:
        waiting_player = None

    await query.answer()
    await safe_edit(query, "❌ جستجوی حریف لغو شد.", reply_markup=main_menu())


# ==================== لغو گفتگو ====================
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    query = update.callback_query
    if query:
        await query.answer()
        await safe_edit(query, "🚫 عملیات لغو شد.", reply_markup=admin_menu())
    else:
        await update.message.reply_text("🚫 عملیات لغو شد.", reply_markup=admin_menu())
    return ConversationHandler.END


# ==================== پنل ادمین ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی غیرمجاز!")
        return
    await update.message.reply_text("👮 پنل ادمین", reply_markup=admin_menu())

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "👮 پنل ادمین", reply_markup=admin_menu())

async def guard_admin(update: Update) -> bool:
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("⛔ دسترسی غیرمجاز!", show_alert=True)
        return False
    return True

# ---- مدیریت امتیازات ----
async def admin_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🔍 جستجوی کاربر با آیدی", callback_data="admin_search_entry")],
        [InlineKeyboardButton("🕒 کاربران اخیر", callback_data="admin_recent_users")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, "💰 برای افزایش/کاهش سکه، اول کاربر رو پیدا کن:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🔍 جستجوی کاربر با آیدی", callback_data="admin_search_entry")],
        [InlineKeyboardButton("🕒 کاربران اخیر", callback_data="admin_recent_users")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, "👤 مدیریت کاربران", reply_markup=InlineKeyboardMarkup(kb))

async def search_user_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "🔎 آیدی عددی کاربر رو ارسال کن:", reply_markup=cancel_kb())
    return ASK_USER_ID

async def receive_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ فقط آیدی عددی بفرست یا لغو کن.", reply_markup=cancel_kb())
        return ASK_USER_ID
    uid = int(text)
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ کاربری با این آیدی پیدا نشد.", reply_markup=admin_menu())
        return ConversationHandler.END
    await update.message.reply_text(profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))
    return ConversationHandler.END

async def recent_users_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    cur.execute("SELECT * FROM users ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    if not rows:
        await safe_edit(query, "کاربری ثبت نشده.", reply_markup=admin_menu())
        return
    text = "🕒 *۱۰ کاربر اخیر*\n━━━━━━━━━━━━━━\n"
    kb = []
    for r in rows:
        flag = "⛔" if r["is_banned"] else "✅"
        text += f"{flag} `{r['id']}` — {md_escape(r['first_name'] or '-')} — 💰{r['coins']}\n"
        kb.append([InlineKeyboardButton(f"مدیریت {r['id']}", callback_data=f"act_manage_{r['id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")])
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def manage_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    uid = int(context.match.group(1))
    user = get_user(uid)
    if not user:
        await safe_edit(query, "❌ کاربر پیدا نشد.", reply_markup=admin_menu())
        return
    await safe_edit(query, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def ban_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    uid = int(context.match.group(1))
    cur.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))
    conn.commit()
    await query.answer("کاربر مسدود شد ⛔")
    user = get_user(uid)
    await safe_edit(query, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def unban_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    uid = int(context.match.group(1))
    cur.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))
    conn.commit()
    await query.answer("رفع مسدودیت شد ✅")
    user = get_user(uid)
    await safe_edit(query, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def coin_action_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    uid = int(context.match.group(1))
    action = "add" if query.data.startswith("act_addcoin_") else "sub"
    context.user_data["target_uid"] = uid
    context.user_data["coin_action"] = action
    verb = "افزایش" if action == "add" else "کاهش"
    await safe_edit(query, f"چند سکه {verb} پیدا کنه کاربر `{uid}`؟ (فقط عدد بفرست)",
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
        await update.message.reply_text("❌ این کاربر دیگر پیدا نشد.", reply_markup=admin_menu())
        context.user_data.clear()
        return ConversationHandler.END

    if action == "add":
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (amount, uid))
        log_tx(uid, "admin_add", amount, "افزایش دستی توسط ادمین")
        msg = f"✅ {amount} سکه به کاربر {uid} اضافه شد."
    else:
        cur.execute("UPDATE users SET coins=coins-? WHERE id=?", (amount, uid))
        log_tx(uid, "admin_sub", -amount, "کاهش دستی توسط ادمین")
        msg = f"✅ {amount} سکه از کاربر {uid} کم شد."
    conn.commit()
    await update.message.reply_text(msg, reply_markup=admin_menu())
    context.user_data.clear()
    return ConversationHandler.END

# ---- ارسال پیام به کاربر (ادمین) ----
async def admin_send_msg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "📨 آیدی عددی کاربر مورد نظر رو بفرست:", reply_markup=cancel_kb())
    return SEND_MSG_UID

async def admin_send_to_user_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام مستقیم از پروفایل کاربر"""
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    uid = int(context.match.group(1))
    context.user_data["send_msg_target"] = uid
    await safe_edit(query, f"📨 پیامت رو برای کاربر `{uid}` بفرست:", parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return SEND_MSG_TEXT

async def receive_send_msg_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ فقط آیدی عددی بفرست یا لغو کن.", reply_markup=cancel_kb())
        return SEND_MSG_UID
    uid = int(text)
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ کاربری با این آیدی پیدا نشد.", reply_markup=admin_menu())
        context.user_data.clear()
        return ConversationHandler.END
    context.user_data["send_msg_target"] = uid
    await update.message.reply_text(
        f"👤 کاربر: {user['first_name'] or '-'} (`{uid}`)\n\n📨 پیامت رو بفرست:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_kb()
    )
    return SEND_MSG_TEXT

async def receive_send_msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("send_msg_target")
    msg_text = update.message.text
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ کاربر پیدا نشد.", reply_markup=admin_menu())
        context.user_data.clear()
        return ConversationHandler.END

    try:
        await context.bot.send_message(
            uid,
            f"📨 *پیام از ادمین:*\n━━━━━━━━━━━━━━\n{md_escape(msg_text)}",
            parse_mode=ParseMode.MARKDOWN
        )
        await update.message.reply_text(f"✅ پیام به کاربر {uid} ارسال شد.", reply_markup=admin_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ ارسال ناموفق! (ممکنه کاربر بات رو بلاک کرده باشه)\nخطا: {e}", reply_markup=admin_menu())

    context.user_data.clear()
    return ConversationHandler.END

# ---- صندوق پشتیبانی (ادمین) ----
async def admin_support_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()

    # شمارش پیام‌های خوانده نشده
    cur.execute("SELECT COUNT(*) c FROM support_messages WHERE is_from_admin=0 AND is_read=0")
    unread = cur.fetchone()["c"]

    cur.execute("SELECT * FROM support_messages WHERE is_from_admin=0 ORDER BY id DESC LIMIT 15")
    rows = cur.fetchall()

    if not rows:
        text = "📭 صندوق پشتیبانی خالیه!"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")]]
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb))
        return

    text = f"💬 *صندوق پشتیبانی* ({unread} خوانده‌نشده)\n━━━━━━━━━━━━━━\n"
    kb = []
    for r in rows:
        user = get_user(r["user_id"])
        name = md_escape(user["first_name"] or "ناشناس") if user else "حذف‌شده"
        read_flag = "📋" if r["is_read"] else "🔵"
        short_msg = md_escape(r["message"][:30]) + ("..." if len(r["message"]) > 30 else "")
        text += f"{read_flag} #{r['id']} | {name} | {short_msg}\n"
        kb.append([InlineKeyboardButton(
            f"👁 مشاهده #{r['id']} ({name})",
            callback_data=f"admin_view_msg_{r['id']}"
        )])

    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")])
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def admin_view_msg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    msg_id = int(context.match.group(1))

    cur.execute("SELECT * FROM support_messages WHERE id=?", (msg_id,))
    msg = cur.fetchone()
    if not msg:
        await safe_edit(query, "❌ پیام پیدا نشد.", reply_markup=admin_menu())
        return

    # علامت‌گذاری به عنوان خوانده‌شده
    cur.execute("UPDATE support_messages SET is_read=1 WHERE id=?", (msg_id,))
    conn.commit()

    user = get_user(msg["user_id"])
    name = md_escape(user["first_name"] or "ناشناس") if user else "حذف‌شده"
    uid = msg["user_id"]
    date_str = time_ago(msg["date"])

    text = (
        f"📩 *پیام #{msg_id}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 {name} (`{uid}`)\n"
        f"🕐 {date_str}\n\n"
        f"💬 {md_escape(msg['message'])}"
    )

    kb = [
        [InlineKeyboardButton("💬 پاسخ دادن", callback_data=f"admin_reply_sel_{uid}_{msg_id}")],
        [InlineKeyboardButton("👤 پروفایل کاربر", callback_data=f"act_manage_{uid}")],
        [InlineKeyboardButton("🔙 صندوق پشتیبانی", callback_data="admin_support_inbox")],
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def admin_reply_sel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    uid = int(context.match.group(1))
    msg_id = int(context.match.group(2))
    context.user_data["reply_to_uid"] = uid
    context.user_data["reply_to_msg"] = msg_id
    await safe_edit(query, f"💬 پاسخت رو برای کاربر `{uid}` بفرست:", parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_kb())
    return ADMIN_REPLY_MSG

async def receive_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("reply_to_uid")
    msg_id = context.user_data.get("reply_to_msg")
    reply_text = update.message.text

    # ذخیره پاسخ در دیتابیس
    cur.execute(
        "INSERT INTO support_messages (user_id, message, is_from_admin, date, is_read, reply_to_id) VALUES (?,?,1,?,0,?)",
        (uid, reply_text, time.time(), msg_id)
    )
    conn.commit()

    # ارسال به کاربر
    try:
        await context.bot.send_message(
            uid,
            f"📩 *پاسخ از ادمین:*\n━━━━━━━━━━━━━━\n{md_escape(reply_text)}\n\n"
            f"💡 برای ادامه مکالمه از بخش «پشتیبانی» استفاده کن.",
            parse_mode=ParseMode.MARKDOWN
        )
        await update.message.reply_text("✅ پاسخ ارسال شد!", reply_markup=admin_menu())
    except Exception:
        await update.message.reply_text("❌ ارسال ناموفق! کاربر ممکنه بات رو بلاک کرده باشه.", reply_markup=admin_menu())

    context.user_data.clear()
    return ConversationHandler.END

# ---- مدیریت کانفیگ ----
async def admin_configs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("➕ افزودن کانفیگ", callback_data="admin_addcfg")],
        [InlineKeyboardButton("📋 لیست کانفیگ‌ها", callback_data="admin_listcfg")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, "📦 مدیریت کانفیگ", reply_markup=InlineKeyboardMarkup(kb))

async def list_configs_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()
    cur.execute("SELECT * FROM configs ORDER BY id DESC LIMIT 20")
    rows = cur.fetchall()
    if not rows:
        await safe_edit(query, "📭 هنوز کانفیگی ثبت نشده.", reply_markup=admin_menu())
        return
    text = "📋 *لیست کانفیگ‌ها (۲۰ مورد آخر)*\n━━━━━━━━━━━━━━\n"
    kb = []
    for r in rows:
        active_flag = "✅" if r.get("is_active", 1) else "⛔"
        text += (
            f"{active_flag} #{r['id']} {md_escape(r['name'])} | "
            f"{CATEGORIES.get(r['category'], r['category'])} | "
            f"💰{r['price']} | موجودی:{r['stock']} | فروش:{r['sales_count']}\n"
        )
        kb.append([
            InlineKeyboardButton(f"✏️ ویرایش #{r['id']}", callback_data=f"editcfg_{r['id']}"),
            InlineKeyboardButton(f"{'⛔' if r.get('is_active', 1) else '✅'} #{r['id']}", callback_data=f"togglecfg_{r['id']}"),
            InlineKeyboardButton(f"🗑 حذف #{r['id']}", callback_data=f"delcfg_{r['id']}"),
        ])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_configs")])
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def toggle_cfg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await query.answer("❌ پیدا نشد!", show_alert=True)
        return
    new_state = 0 if cfg.get("is_active", 1) else 1
    cur.execute("UPDATE configs SET is_active=? WHERE id=?", (new_state, cfg_id))
    conn.commit()
    status = "فعال ✅" if new_state else "غیرفعال ⛔"
    await query.answer(f"کانفیگ {status} شد!")
    await list_configs_cb(update, context)

async def addcfg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    context.user_data["new_cfg"] = {}
    await safe_edit(query, "📝 نام کانفیگ رو ارسال کن:", reply_markup=cancel_kb())
    return ADDCFG_NAME

async def receive_cfg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cfg"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "📦 محتوای کانفیگ رو ارسال کن (متنی که بعد از خرید تحویل کاربر میشه):", reply_markup=cancel_kb()
    )
    return ADDCFG_CONTENT

async def receive_cfg_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cfg"]["config"] = update.message.text
    kb = [[InlineKeyboardButton(v, callback_data=f"cfgcat_{k}")] for k, v in CATEGORIES.items()]
    kb.append([InlineKeyboardButton("🚫 لغو", callback_data="cancel_conv")])
    await update.message.reply_text("🗂 دسته‌بندی رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
    return ADDCFG_CATEGORY

async def receive_cfg_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = context.match.group(1)
    context.user_data["new_cfg"]["category"] = cat
    await safe_edit(query, "💰 قیمت و موجودی رو با فاصله بفرست (مثال: 20 50):", reply_markup=cancel_kb())
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
        (d["name"], d["config"], price, d["category"], stock, time.time()),
    )
    conn.commit()
    await update.message.reply_text(f"✅ کانفیگ «{d['name']}» با موفقیت اضافه شد.", reply_markup=admin_menu())
    context.user_data.clear()
    return ConversationHandler.END

async def editcfg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg:
        await safe_edit(query, "❌ کانفیگ پیدا نشد.", reply_markup=admin_menu())
        return ConversationHandler.END
    context.user_data["edit_cfg_id"] = cfg_id
    await safe_edit(
        query,
        f"✏️ ویرایش «{cfg['name']}»\nقیمت و موجودی جدید رو با فاصله بفرست (فعلی: {cfg['price']} {cfg['stock']}):",
        reply_markup=cancel_kb(),
    )
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
    await update.message.reply_text("✅ کانفیگ بروزرسانی شد.", reply_markup=admin_menu())
    context.user_data.clear()
    return ConversationHandler.END

async def delcfg_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    await query.answer()
    if not cfg:
        await safe_edit(query, "❌ پیدا نشد.", reply_markup=admin_menu())
        return
    kb = [[
        InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"delcfg_yes_{cfg_id}"),
        InlineKeyboardButton("❌ خیر", callback_data="admin_listcfg"),
    ]]
    await safe_edit(query, f"⚠️ آیا کانفیگ «{cfg['name']}» حذف بشه؟", reply_markup=InlineKeyboardMarkup(kb))

async def delcfg_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    cfg_id = int(context.match.group(1))
    cur.execute("DELETE FROM configs WHERE id=?", (cfg_id,))
    conn.commit()
    await query.answer("حذف شد ✅")
    await list_configs_cb(update, context)

# ---- ارسال همگانی ----
async def broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "📢 متن پیام همگانی رو ارسال کن:", reply_markup=cancel_kb())
    return BC_TEXT

async def receive_bc_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bc_text"] = update.message.text
    kb = [[
        InlineKeyboardButton("✅ ارسال به همه", callback_data="bc_yes"),
        InlineKeyboardButton("❌ لغو", callback_data="cancel_conv"),
    ]]
    await update.message.reply_text(
        f"پیام زیر برای *همه کاربران* ارسال میشه:\n\n{update.message.text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return BC_CONFIRM

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = context.user_data.get("bc_text", "")
    cur.execute("SELECT id FROM users WHERE is_banned=0")
    ids = [r["id"] for r in cur.fetchall()]
    await safe_edit(query, f"⏳ در حال ارسال به {len(ids)} کاربر...")

    sent, failed = 0, 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, f"📢 *اطلاعیه*\n━━━━━━━━━━━━━━\n{md_escape(text)}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except Exception:
            failed += 1

    await context.bot.send_message(
        ADMIN_ID, f"✅ ارسال همگانی تمام شد.\nموفق: {sent} | ناموفق: {failed}", reply_markup=admin_menu()
    )
    context.user_data.clear()
    return ConversationHandler.END

# ---- آمار ----
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()

    cur.execute("SELECT COUNT(*) c FROM users")
    total_users = cur.fetchone()["c"]
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
    total_revenue = cur.fetchone()["s"]
    cur.execute("SELECT name FROM configs ORDER BY sales_count DESC LIMIT 1")
    top = cur.fetchone()
    top_name = top["name"] if top else "-"
    cur.execute("SELECT COUNT(*) c FROM support_messages WHERE is_from_admin=0 AND is_read=0")
    unread_support = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM users WHERE last_daily > ?", (time.time() - 86400,))
    active_today = cur.fetchone()["c"]

    text = (
        f"📊 *آمار کلی*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 کل کاربران: {total_users}\n"
        f"👤 فعال امروز: {active_today}\n"
        f"⛔ مسدود: {banned}\n"
        f"💰 مجموع سکه در گردش: {total_coins}\n"
        f"📦 تعداد کانفیگ‌ها: {cfg_count}\n"
        f"📥 موجودی کل (فعال): {total_stock}\n"
        f"🛍 مجموع فروش: {total_sales}\n"
        f"💵 درآمد کل (سکه): {total_revenue}\n"
        f"🔥 پرفروش‌ترین: {md_escape(top_name)}\n"
        f"💬 پیام‌های پشتیبانی خوانده‌نشده: {unread_support}"
    )
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_menu())

# ---- بکاپ دیتابیس ----
async def admin_backup_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()

    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        # کپی دیتابیس
        import shutil
        shutil.copy2(DB_PATH, tmp_path)

        with open(tmp_path, "rb") as f:
            await context.bot.send_document(
                ADMIN_ID,
                document=f,
                caption=f"💾 بکاپ دیتابیس — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                reply_markup=admin_menu()
            )
        os.remove(tmp_path)
    except Exception as e:
        await safe_edit(query, f"❌ خطا در بکاپ: {e}", reply_markup=admin_menu())

# ---- تنظیمات بات ----
async def admin_settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    await query.answer()

    maintenance = get_setting("maintenance_mode", "0")
    purchase_notify = get_setting("purchase_notify", "1")
    welcome_msg = get_setting("welcome_msg", "")

    m_text = "🔴 فعال" if maintenance == "1" else "🟢 غیرفعال"
    n_text = "✅ فعال" if purchase_notify == "1" else "❌ غیرفعال"

    text = (
        f"⚙️ *تنظیمات بات*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔧 حالت تعمیر: {m_text}\n"
        f"🔔 اطلاع خرید: {n_text}\n"
        f"📝 پیام خوش‌آمدگویی: {md_escape(welcome_msg[:50])}{'...' if len(welcome_msg) > 50 else ''}"
    )
    kb = [
        [InlineKeyboardButton(f"🔧 تعمیر: {'خاموش کردن' if maintenance == '1' else 'روشن کردن'}",
                               callback_data="toggle_maintenance")],
        [InlineKeyboardButton(f"🔔 اطلاع خرید: {'خاموش' if purchase_notify == '1' else 'روشن'}",
                               callback_data="toggle_purchase_notify")],
        [InlineKeyboardButton("📝 تغییر پیام خوش‌آمدگویی", callback_data="set_welcome_entry")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def toggle_maintenance_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    current = get_setting("maintenance_mode", "0")
    new_val = "0" if current == "1" else "1"
    set_setting("maintenance_mode", new_val)
    status = "غیرفعال 🟢" if new_val == "0" else "فعال 🔴"
    await query.answer(f"حالت تعمیر: {status}")
    await admin_settings_cb(update, context)

async def toggle_purchase_notify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return
    query = update.callback_query
    current = get_setting("purchase_notify", "1")
    new_val = "0" if current == "1" else "1"
    set_setting("purchase_notify", new_val)
    status = "فعال ✅" if new_val == "1" else "غیرفعال ❌"
    await query.answer(f"اطلاع خرید: {status}")
    await admin_settings_cb(update, context)

async def set_welcome_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "📝 پیام خوش‌آمدگویی جدید رو بفرست:", reply_markup=cancel_kb())
    # استفاده از state موجود
    context.user_data["_special"] = "set_welcome"
    return SUPPORT_MSG  # reuse state

async def receive_welcome_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """این هندلر باید قبل از receive_support_msg ثبت بشه"""
    if context.user_data.get("_special") == "set_welcome":
        new_msg = update.message.text
        set_setting("welcome_msg", new_msg)
        await update.message.reply_text(f"✅ پیام خوش‌آمدگویی تغییر کرد!", reply_markup=admin_menu())
        context.user_data.clear()
        return ConversationHandler.END
    # در غیر این صورت بره به هندلر پشتیبانی
    return await receive_support_msg(update, context)


# ==================== خطاها ====================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update: %s", context.error, exc_info=context.error)

# ==================== اجرا ====================
def main():
    app = Application.builder().token(TOKEN).build()

    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(search_user_entry, pattern=r"^admin_search_entry$"),
            CallbackQueryHandler(coin_action_entry, pattern=r"^act_addcoin_(\d+)$"),
            CallbackQueryHandler(coin_action_entry, pattern=r"^act_subcoin_(\d+)$"),
            CallbackQueryHandler(addcfg_entry, pattern=r"^admin_addcfg$"),
            CallbackQueryHandler(editcfg_entry, pattern=r"^editcfg_(\d+)$"),
            CallbackQueryHandler(broadcast_entry, pattern=r"^admin_broadcast_entry$"),
            CallbackQueryHandler(admin_send_msg_entry, pattern=r"^admin_send_msg_entry$"),
            CallbackQueryHandler(admin_send_to_user_direct, pattern=r"^admin_send_to_(\d+)$"),
            CallbackQueryHandler(admin_reply_sel_cb, pattern=r"^admin_reply_sel_(\d+)_(\d+)$"),
            CallbackQueryHandler(support_start_cb, pattern=r"^support_start$"),
            CallbackQueryHandler(set_welcome_entry, pattern=r"^set_welcome_entry$"),
        ],
        states={
            ASK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_user_id)],
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
            SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_welcome_msg)],
            ADMIN_REPLY_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_reply)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern=r"^cancel_conv$"),
        ],
        per_user=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(admin_conv)

    # کاربر عادی
    app.add_handler(CallbackQueryHandler(back_main, pattern=r"^back_main$"))
    app.add_handler(CallbackQueryHandler(help_cb, pattern=r"^help$"))
    app.add_handler(CallbackQueryHandler(my_stats_cb, pattern=r"^my_stats$"))
    app.add_handler(CallbackQueryHandler(invite_cb, pattern=r"^invite$"))
    app.add_handler(CallbackQueryHandler(wallet, pattern=r"^wallet$"))
    app.add_handler(CallbackQueryHandler(tx_history, pattern=r"^tx_history$"))
    app.add_handler(CallbackQueryHandler(daily, pattern=r"^daily$"))
    app.add_handler(CallbackQueryHandler(shop, pattern=r"^shop$"))
    app.add_handler(CallbackQueryHandler(category, pattern=r"^cat_(\w+)$"))
    app.add_handler(CallbackQueryHandler(buy_ask, pattern=r"^buy_(\d+)$"))
    app.add_handler(CallbackQueryHandler(buy_confirm, pattern=r"^confirm_buy_(\d+)$"))
    app.add_handler(CallbackQueryHandler(website_cb, pattern=r"^website$"))
    app.add_handler(CallbackQueryHandler(leaderboard_cb, pattern=r"^leaderboard$"))
    app.add_handler(CallbackQueryHandler(leaderboard_games_cb, pattern=r"^leaderboard_games$"))
    app.add_handler(CallbackQueryHandler(support_entry_cb, pattern=r"^support_entry$"))

    # هندلرهای مینی گیم
    app.add_handler(CallbackQueryHandler(game_menu_cb, pattern=r"^game_menu$"))
    app.add_handler(CallbackQueryHandler(game_find_cb, pattern=r"^game_find$"))
    app.add_handler(CallbackQueryHandler(game_roll_cb, pattern=r"^game_roll_(match_\d+)_(\d+)$"))
    app.add_handler(CallbackQueryHandler(game_cancel_search_cb, pattern=r"^game_cancel_search$"))

    # پنل ادمین
    app.add_handler(CallbackQueryHandler(admin_back, pattern=r"^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_coins, pattern=r"^admin_coins$"))
    app.add_handler(CallbackQueryHandler(admin_users_menu, pattern=r"^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_configs_menu, pattern=r"^admin_configs$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern=r"^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_backup_cb, pattern=r"^admin_backup$"))
    app.add_handler(CallbackQueryHandler(admin_settings_cb, pattern=r"^admin_settings$"))
    app.add_handler(CallbackQueryHandler(admin_support_inbox, pattern=r"^admin_support_inbox$"))
    app.add_handler(CallbackQueryHandler(admin_view_msg_cb, pattern=r"^admin_view_msg_(\d+)$"))
    app.add_handler(CallbackQueryHandler(recent_users_cb, pattern=r"^admin_recent_users$"))
    app.add_handler(CallbackQueryHandler(manage_user_cb, pattern=r"^act_manage_(\d+)$"))
    app.add_handler(CallbackQueryHandler(ban_user_cb, pattern=r"^act_ban_(\d+)$"))
    app.add_handler(CallbackQueryHandler(unban_user_cb, pattern=r"^act_unban_(\d+)$"))
    app.add_handler(CallbackQueryHandler(list_configs_cb, pattern=r"^admin_listcfg$"))
    app.add_handler(CallbackQueryHandler(toggle_cfg_cb, pattern=r"^togglecfg_(\d+)$"))
    app.add_handler(CallbackQueryHandler(delcfg_ask, pattern=r"^delcfg_(\d+)$"))
    app.add_handler(CallbackQueryHandler(delcfg_confirm, pattern=r"^delcfg_yes_(\d+)$"))
    app.add_handler(CallbackQueryHandler(toggle_maintenance_cb, pattern=r"^toggle_maintenance$"))
    app.add_handler(CallbackQueryHandler(toggle_purchase_notify_cb, pattern=r"^toggle_purchase_notify$"))

    app.add_error_handler(error_handler)

    print("🚀 بات اجرا شد!")
    app.run_polling()

if __name__ == "__main__":
    main()
