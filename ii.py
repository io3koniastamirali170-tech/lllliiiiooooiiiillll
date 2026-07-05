import os
import re
import time
import random
import sqlite3
import logging
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

CATEGORIES = {"general": "اراک ", "premium": "کرج", "hot": "خلیج نیگر "}
NEW_USER_BONUS = 10
REFERRAL_BONUS = 15
DAILY_MIN, DAILY_MAX = 15, 50
GAME_REWARD = 5  # سکه پاداش برنده مینی گیم

# ==================== متغیرهای مینی گیم (PVP) ====================
waiting_player = None  # آیدی کاربری که در حال انتظار حریف است
active_matches = {}    # دیکشنری برای بازی های در حال انجام
match_counter = 0      # شمارنده برای ساخت آیدی یکتای هر بازی

# ==================== دیتابیس ====================
conn = sqlite3.connect("vip_bot.db", check_same_thread=False)
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
    refered_by INTEGER DEFAULT 0
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
    created_at REAL
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
conn.commit()

try:
    cur.execute("ALTER TABLE configs ADD COLUMN sales_count INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass

# ==================== States گفتگو ====================
(ASK_USER_ID, ASK_AMOUNT, ADDCFG_NAME, ADDCFG_CONTENT, ADDCFG_CATEGORY,
 ADDCFG_PRICE_STOCK, EDIT_PRICE_STOCK, BC_TEXT, BC_CONFIRM) = range(9)

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

# ==================== منوها ====================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("✨️دریافت کانفیگ ", callback_data="shop")],
        [InlineKeyboardButton("🤌امتیاز ها ", callback_data="wallet"),
         InlineKeyboardButton("😇امتیاز روزانه ", callback_data="daily")],
        [InlineKeyboardButton("🚧درحال توسعه", callback_data="game_menu")], # دکمه مینی گیم اضافه شد
        [InlineKeyboardButton("🌍 اطلاعات من ", callback_data="my_stats"),
         InlineKeyboardButton("🏗درحال توسعه ", callback_data="invite")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_menu():
    keyboard = [
        [InlineKeyboardButton("💰 مدیریت امتیازات", callback_data="admin_coins")],
        [InlineKeyboardButton("📦 مدیریت کانفیگ", callback_data="admin_configs")],
        [InlineKeyboardButton("👤 مدیریت کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("📢 ارسال همگانی", callback_data="admin_broadcast_entry")],
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def shop_menu():
    keyboard = [[InlineKeyboardButton(label, callback_data=f"cat_{key}")] for key, label in CATEGORIES.items()]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def profile_text(user) -> str:
    ban = "⛔ مسدود" if user["is_banned"] else "✅ فعال"
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
        f"وضعیت: {ban}"
    )

def profile_kb(user):
    uid = user["id"]
    ban_btn = (
        InlineKeyboardButton("✅ رفع مسدودیت", callback_data=f"act_unban_{uid}")
        if user["is_banned"]
        else InlineKeyboardButton("⛔ مسدود کردن", callback_data=f"act_ban_{uid}")
    )
    keyboard = [
        [InlineKeyboardButton("➕ افزایش سکه", callback_data=f"act_addcoin_{uid}"),
         InlineKeyboardButton("➖ کاهش سکه", callback_data=f"act_subcoin_{uid}")],
        [ban_btn],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ==================== شروع ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
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

        await update.message.reply_text(
            f"🌟 به {BOT_NAME} خوش آمدی!\n\n🎁 {NEW_USER_BONUS} سکه هدیه گرفتی!\n🔰 کد معرف تو: `{ref_code}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(),
        )
    else:
        if existing["is_banned"]:
            await update.message.reply_text("⛔ شما مسدود هستید.")
            return
        await update.message.reply_text(f"🔄 خوش برگشتی، {user.first_name}!", reply_markup=main_menu())


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, f"🏠 {BOT_NAME}\n\nیکی از گزینه‌ها رو انتخاب کن:", reply_markup=main_menu())


async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "❓ *راهنما*\n"
        "━━━━━━━━━━━━━━\n"
        "id owner @liiiiiooiiiillll\n"
        "🎁 هر ۲۴ ساعت یک‌بار «جایزه روزانه» بگیر\n"
        "🎮 در بخش «مینی گیم» با کاربران آنلاین تاس بزن و سکه ببر\n"
        "🎉 با «دعوت دوستان» به ازای هر معرفی سکه بگیر\n"
        "📊 وضعیت خودت رو در «آمار من» ببین\n"
        "💰 موجودی و تاریخچه در «کیف پول»\n"
    )
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


async def my_stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    cur.execute("SELECT COUNT(*) c FROM users WHERE refered_by=?", (uid,))
    referred = cur.fetchone()["c"]
    text = (
        f"📊 *آمار من*\n━━━━━━━━━━━━━━\n"
        f"💰 سکه فعلی: {user['coins']}\n"
        f"📦 کانفیگ خریداری‌شده: {user['used_configs']}\n"
        f"💵 مجموع خرید: {user['total_spent']}\n"
        f"👥 دوستان دعوت‌شده: {referred}\n"
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
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


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
    await safe_edit(query, "اراک یا کرج؟؟:", reply_markup=shop_menu())


async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = context.match.group(1)
    cur.execute("SELECT * FROM configs WHERE category=? AND stock>0 ORDER BY sales_count DESC", (cat,))
    configs = cur.fetchall()

    if not configs:
        await safe_edit(query, "به موکی بگو کانفیگ بزاره .", reply_markup=shop_menu())
        return

    label = CATEGORIES.get(cat, cat)
    text = f"{label}\n━━━━━━━━━━━━━━\n"
    keyboard = []
    for cfg in configs:
        tag = " 🔥" if cfg["sales_count"] >= 10 else ""
        text += f"🔹 {md_escape(cfg['name'])}{tag} — 💰{cfg['price']} سکه — موجودی: {cfg['stock']}\n"
        keyboard.append([InlineKeyboardButton(f"🛍 خرید {cfg['name']}", callback_data=f"buy_{cfg['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shop")])
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


async def buy_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cfg_id = int(context.match.group(1))
    cfg = get_config(cfg_id)
    if not cfg or cfg["stock"] <= 0:
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
    if not cfg or cfg["stock"] <= 0:
        await query.answer("❌ تمام شد!", show_alert=True)
        await safe_edit(query, "❌ این کانفیگ دیگر موجود نیست.", reply_markup=shop_menu())
        return

    user = get_user(uid)
    if user["coins"] < cfg["price"]:
        await query.answer("❌امتیاز نداری ک !", show_alert=True)
        await safe_edit(query, f"❌ سکه نداری : {cfg['price']} سکه", reply_markup=shop_menu())
        return

    cur.execute("UPDATE users SET coins=coins-?, used_configs=used_configs+1, total_spent=total_spent+? WHERE id=?",
                (cfg["price"], cfg["price"], uid))
    cur.execute("UPDATE configs SET stock=stock-1, sales_count=sales_count+1 WHERE id=?", (cfg_id,))
    conn.commit()
    log_tx(uid, "purchase", -cfg["price"], f"خرید {cfg['name']}")

    await query.answer("✅ دریافت موفق !")
    delivery = (
        f"✅ *خرید با موفقیت انجام شد!*\n\n📥 محتوای کانفیگ «{md_escape(cfg['name'])}»:\n```\n{cfg['config']}\n```"
    )
    await safe_edit(query, delivery, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())


# ==================== مینی گیم PVP (تاس) ====================
async def game_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🎮 *مینی گیم: نبرد تاس*\n"
        "━━━━━━━━━━━━━━\n"
        f"در این بازی با یک کاربر آنلاین دیگر مسابقه می‌دی.\n"
        f"هر دو نفر تاس می‌زنید و کسی که عدد بزرگ‌تری بیاره برنده‌ست!\n"
        f"🏆 جایزه برنده: {GAME_REWARD} سکه\n\n"
        f"آماده‌ای حریف پیدا کنی؟"
    )
    kb = [
        [InlineKeyboardButton("🔍 جستجوی حریف", callback_data="game_find")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]
    ]
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def game_find_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_player, match_counter
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    # اگر کاربر قبلا در صف هست
    if waiting_player == uid:
        await query.answer("⚠️ تو الان داری توی صف انتظاری!", show_alert=True)
        return

    # اگر کسی در صف نباشد، کاربر وارد صف میشه
    if waiting_player is None:
        waiting_player = uid
        kb = [[InlineKeyboardButton("❌ لغو جستجو", callback_data="game_cancel_search")]]
        await safe_edit(query, "⏳ در حال جستجوی حریف...\nلطفا صبر کن (برای لغو دکمه رو بزن).", reply_markup=InlineKeyboardMarkup(kb))
    else:
        # حریف پیدا شد!
        opponent_id = waiting_player
        waiting_player = None  # خالی کردن صف
        
        match_counter += 1
        match_id = f"match_{match_counter}"
        
        # ثبت مسابقه در حافظه
        active_matches[match_id] = {
            "p1": opponent_id,
            "p2": uid,
            "r1": None,
            "r2": None
        }
        
        p1_name = get_user(opponent_id)["first_name"] or "ناشناس"
        p2_name = query.from_user.first_name or "ناشناس"
        
        kb = [[InlineKeyboardButton("🎲 پرتاب تاس", callback_data=f"game_roll_{match_id}_1")]]
        
        # اطلاع به حریف اول (کسی که زودتر وارد صف شده بود)
        try:
            await context.bot.send_message(
                opponent_id, 
                f"🎮 حریف پیدا شد!\n━━━━━━━━━━━━━━\n🗡 مقابله تو با: {p2_name}\n\nآماده‌ای تاس بزنی؟",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            logger.error(f"Failed to notify p1 {opponent_id}: {e}")
            # اگر حریف اول بلاک کرده بود یا خطایی داد، مسابقه کنسل بشه
            del active_matches[match_id]
            await query.answer("❌ حریف پیدا شد اما دیگه آنلاین نبود! دوباره امتحان کن.", show_alert=True)
            return

        # اطلاع به کاربر فعلی (حریف دوم)
        kb2 = [[InlineKeyboardButton("🎲 پرتاب تاس", callback_data=f"game_roll_{match_id}_2")]]
        await safe_edit(
            query, 
            f"🎮 حریف پیدا شد!\n━━━━━━━━━━━━━━\n🗡 مقابله تو با: {p1_name}\n\nآماده‌ای تاس بزنی؟",
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
    
    # ثبت نتیجه تاس
    if player_num == 1:
        match["r1"] = roll
    else:
        match["r2"] = roll
        
    await query.edit_message_text(
        f"🎲 تو {dice_emojis[roll]} ({roll}) انداختی!\n⏳ الان منتظر نتیجه حریف هستیم..."
    )
    
    # اگر هر دو تاس انداختند، نتیجه رو اعلام کن
    if match["r1"] is not None and match["r2"] is not None:
        await resolve_match(match_id, context)

async def resolve_match(match_id: str, context: ContextTypes.DEFAULT_TYPE):
    match = active_matches.pop(match_id, None)
    if not match: return

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
    if r1 > r2:
        winner_id = p1
        text += f"🏆 برنده: {p1_name} (+'{GAME_REWARD} سکه)"
    elif r2 > r1:
        winner_id = p2
        text += f"🏆 برنده: {p2_name} (+'{GAME_REWARD} سکه)"
    else:
        text += "🤝 مساوی شد! سکه‌ای تقسیم نمیشه."

    # پاداش به برنده
    if winner_id:
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (GAME_REWARD, winner_id))
        conn.commit()
        log_tx(winner_id, "game_win", GAME_REWARD, "برد در مینی گیم تاس")

    kb = [[InlineKeyboardButton("🔄 بازی مجدد", callback_data="game_find")],
          [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_main")]]

    # ارسال نتیجه به هر دو بازیکن
    try:
        await context.bot.send_message(p1, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
    except Exception: pass
    try:
        if p1 != p2: # اگر خودش با خودش بازی نکرده (که تو منطق ما محال ه)
            await context.bot.send_message(p2, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
    except Exception: pass

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
    if not await guard_admin(update): return
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🔍 جستجوی کاربر با آیدی", callback_data="admin_search_entry")],
        [InlineKeyboardButton("🕒 کاربران اخیر", callback_data="admin_recent_users")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, "💰 برای افزایش/کاهش سکه، اول کاربر رو پیدا کن:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🔍 جستجوی کاربر با آیدی", callback_data="admin_search_entry")],
        [InlineKeyboardButton("🕒 کاربران اخیر", callback_data="admin_recent_users")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, "👤 مدیریت کاربران", reply_markup=InlineKeyboardMarkup(kb))

async def search_user_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return ConversationHandler.END
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
    if not await guard_admin(update): return
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
    if not await guard_admin(update): return
    query = update.callback_query
    await query.answer()
    uid = int(context.match.group(1))
    user = get_user(uid)
    if not user:
        await safe_edit(query, "❌ کاربر پیدا نشد.", reply_markup=admin_menu())
        return
    await safe_edit(query, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def ban_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    query = update.callback_query
    uid = int(context.match.group(1))
    cur.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))
    conn.commit()
    await query.answer("کاربر مسدود شد ⛔")
    user = get_user(uid)
    await safe_edit(query, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def unban_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    query = update.callback_query
    uid = int(context.match.group(1))
    cur.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))
    conn.commit()
    await query.answer("رفع مسدودیت شد ✅")
    user = get_user(uid)
    await safe_edit(query, profile_text(user), parse_mode=ParseMode.MARKDOWN, reply_markup=profile_kb(user))

async def coin_action_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return ConversationHandler.END
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

# ---- مدیریت کانفیگ ----
async def admin_configs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("➕ افزودن کانفیگ", callback_data="admin_addcfg")],
        [InlineKeyboardButton("📋 لیست کانفیگ‌ها", callback_data="admin_listcfg")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    await safe_edit(query, "📦 مدیریت کانفیگ", reply_markup=InlineKeyboardMarkup(kb))

async def list_configs_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
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
        text += (f"🔹 #{r['id']} {md_escape(r['name'])} | {CATEGORIES.get(r['category'], r['category'])} | "
                  f"💰{r['price']} | موجودی:{r['stock']} | فروش:{r['sales_count']}\n")
        kb.append([
            InlineKeyboardButton(f"✏️ ویرایش #{r['id']}", callback_data=f"editcfg_{r['id']}"),
            InlineKeyboardButton(f"🗑 حذف #{r['id']}", callback_data=f"delcfg_{r['id']}"),
        ])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_configs")])
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def addcfg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return ConversationHandler.END
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
    if not await guard_admin(update): return ConversationHandler.END
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
    if not await guard_admin(update): return
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
    if not await guard_admin(update): return
    query = update.callback_query
    cfg_id = int(context.match.group(1))
    cur.execute("DELETE FROM configs WHERE id=?", (cfg_id,))
    conn.commit()
    await query.answer("حذف شد ✅")
    await list_configs_cb(update, context)

# ---- ارسال همگانی ----
async def broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return ConversationHandler.END
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
            await context.bot.send_message(uid, f"موکی گفت  {text}")
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
    if not await guard_admin(update): return
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
    cur.execute("SELECT COALESCE(SUM(stock),0) s FROM configs")
    total_stock = cur.fetchone()["s"]
    cur.execute("SELECT COALESCE(SUM(sales_count),0) s FROM configs")
    total_sales = cur.fetchone()["s"]
    cur.execute("SELECT COALESCE(SUM(-amount),0) s FROM transactions WHERE type='purchase'")
    total_revenue = cur.fetchone()["s"]
    cur.execute("SELECT name FROM configs ORDER BY sales_count DESC LIMIT 1")
    top = cur.fetchone()
    top_name = top["name"] if top else "-"

    text = (
        f"📊 *آمار کلی*\n━━━━━━━━━━━━━━\n"
        f"👥 کاربران: {total_users} (⛔ مسدود: {banned})\n"
        f"💰 مجموع سکه در گردش: {total_coins}\n"
        f"📦 تعداد کانفیگ‌ها: {cfg_count}\n"
        f"📥 موجودی کل: {total_stock}\n"
        f"🛍 مجموع فروش: {total_sales}\n"
        f"💵 درآمد کل (سکه): {total_revenue}\n"
        f"🔥 پرفروش‌ترین: {md_escape(top_name)}"
    )
    await safe_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_menu())

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
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern=r"^cancel_conv$"),
        ],
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
    
    # هندلرهای مینی گیم
    app.add_handler(CallbackQueryHandler(game_menu_cb, pattern=r"^game_menu$"))
    app.add_handler(CallbackQueryHandler(game_find_cb, pattern=r"^game_find$"))
    app.add_handler(CallbackQueryHandler(game_roll_cb, pattern=r"^game_roll_(match_\d+)_(\d+)$"))
    app.add_handler(CallbackQueryHandler(game_cancel_search_cb, pattern=r"^game_cancel_search$"))

    # پنل ادمین (ناوبری + اکشن‌های آنی)
    app.add_handler(CallbackQueryHandler(admin_back, pattern=r"^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_coins, pattern=r"^admin_coins$"))
    app.add_handler(CallbackQueryHandler(admin_users_menu, pattern=r"^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_configs_menu, pattern=r"^admin_configs$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern=r"^admin_stats$"))
    app.add_handler(CallbackQueryHandler(recent_users_cb, pattern=r"^admin_recent_users$"))
    app.add_handler(CallbackQueryHandler(manage_user_cb, pattern=r"^act_manage_(\d+)$"))
    app.add_handler(CallbackQueryHandler(ban_user_cb, pattern=r"^act_ban_(\d+)$"))
    app.add_handler(CallbackQueryHandler(unban_user_cb, pattern=r"^act_unban_(\d+)$"))
    app.add_handler(CallbackQueryHandler(list_configs_cb, pattern=r"^admin_listcfg$"))
    app.add_handler(CallbackQueryHandler(delcfg_ask, pattern=r"^delcfg_(\d+)$"))
    app.add_handler(CallbackQueryHandler(delcfg_confirm, pattern=r"^delcfg_yes_(\d+)$"))

    app.add_error_handler(error_handler)

    print("🚀 بات اجرا شد!")
    app.run_polling()

if __name__ == "__main__":
    main()
