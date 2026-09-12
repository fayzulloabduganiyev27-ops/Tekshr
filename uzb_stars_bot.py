"""
UZB STARS BOT — pastki tugmali (reply keyboard) admin panel bilan

O'rnatish:
    pip install aiogram aiosqlite python-dotenv

.env fayl:
    BOT_TOKEN=1234567890:ABCDEF...
    BOT_USERNAME=your_bot_username
    ADMIN_IDS=123456789,987654321
    ADMIN_CONTACT_ID=123456789
    REQUIRED_CHANNELS=@kanal1,@kanal2      # boshlang'ich, keyin panel orqali o'zgartiriladi
    PAYMENT_CHANNEL=@tolov_kanali
    REWARD_STARS=10                        # boshlang'ich, keyin panel orqali o'zgartiriladi

Ishga tushirish:
    python uzb_stars_bot.py

ADMIN UCHUN: asosiy menyuda "🔧 Boshqaruv" tugmasi ko'rinadi (faqat ADMIN_IDS
ro'yxatidagilarga). Bosilganda pastki tugmalar "Stars Ishlash" uslubida
boshqaruv menyusiga almashadi: Statistika, Majburiy kanallar, Referal narxi,
Sovg'alar narxi, To'lov kanali, Foydalanuvchilarni boshqarish, Xabar yuborish.
"""

import asyncio
import logging
import os
from contextlib import suppress

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

load_dotenv()

# ----------------- SOZLAMALAR -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot_username")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ADMIN_CONTACT_ID = int(os.getenv("ADMIN_CONTACT_ID", "0")) if os.getenv("ADMIN_CONTACT_ID", "").isdigit() else 0
PAYMENT_CHANNEL_DEFAULT = os.getenv("PAYMENT_CHANNEL", "")
DEFAULT_REWARD_STARS = int(os.getenv("REWARD_STARS", "10"))
DEFAULT_CHANNELS = [c.strip() for c in os.getenv("REQUIRED_CHANNELS", "").split(",") if c.strip()]
DB_PATH = os.getenv("DB_PATH", "uzb_stars_bot.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("uzb_stars_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

BTN_STARS_ISHLASH = "⭐ Stars Ishlash"
BTN_BALANS = "💰 Hisobim"
BTN_STARS_YECHISH = "💸 Stars yechish"
BTN_SHOP = "🛍️ Do'kon"
BTN_TOLOV_KANALI = "📢 To'lov kanali"
BTN_ADMIN_BOGLANISH = "👨‍💻 Admin bilan bog'lanish"
BTN_INFO = "📔 Ma'lumot"
BTN_BOSHQARUV = "🔧 Boshqaruv"

BTN_AP_STATS = "📊 Statistika"
BTN_AP_CHANNELS = "📢 Majburiy kanallar"
BTN_AP_REWARD = "⭐ Referal narxi"
BTN_AP_GIFTS = "🎁 Sovg'alar narxi"
BTN_AP_PAYCHANNEL = "💳 To'lov kanali sozlash"
BTN_AP_USERS = "👥 Foydalanuvchilarni boshqarish"
BTN_AP_SHOP = "🛍️ Do'kon boshqaruvi"
BTN_AP_CARDS = "💳 Kartalar"
BTN_AP_BROADCAST = "📤 Hammaga xabar yuborish"
BTN_AP_INFO = "📔 Ma'lumotlar"
BTN_AP_BACK = "⬅️ Asosiy menyu"

ADMIN_PANEL_TEXTS = {
    BTN_AP_STATS, BTN_AP_CHANNELS, BTN_AP_REWARD, BTN_AP_GIFTS,
    BTN_AP_PAYCHANNEL, BTN_AP_USERS, BTN_AP_SHOP, BTN_AP_CARDS,
    BTN_AP_BROADCAST, BTN_AP_INFO, BTN_AP_BACK,
}
MAIN_MENU_TEXTS = {
    BTN_STARS_ISHLASH, BTN_BALANS, BTN_STARS_YECHISH, BTN_SHOP,
    BTN_TOLOV_KANALI, BTN_ADMIN_BOGLANISH, BTN_INFO, BTN_BOSHQARUV,
}
ALL_NAV_TEXTS = ADMIN_PANEL_TEXTS | MAIN_MENU_TEXTS


class UserStates(StatesGroup):
    waiting_admin_message = State()
    waiting_withdraw_username = State()
    waiting_topup_amount = State()
    waiting_topup_receipt = State()
    waiting_shop_username = State()


class AdminStates(StatesGroup):
    waiting_new_channel = State()
    waiting_reward_value = State()
    waiting_new_gift_name = State()
    waiting_new_gift_cost = State()
    waiting_edit_gift_cost = State()
    waiting_broadcast_text = State()
    waiting_info_text = State()
    waiting_payment_channel = State()
    waiting_user_search_id = State()
    waiting_adjust_stars_amount = State()
    waiting_reply_text = State()
    waiting_new_category = State()
    waiting_new_product_name = State()
    waiting_new_product_price = State()
    waiting_new_product_description = State()
    waiting_new_card_number = State()
    waiting_new_card_holder = State()


async def cancel_if_nav_button(message: Message, state: FSMContext) -> bool:
    if message.text in ALL_NAV_TEXTS:
        await state.clear()
        return True
    return False


SKIP_WORDS = {"/skip", "o'tkazib yuborish", "otkazib yuborish", "yo'q", "yoq"}


def is_skip(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in SKIP_WORDS


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                stars INTEGER DEFAULT 0,
                referrer_id INTEGER,
                referrals_count INTEGER DEFAULT 0,
                subscribed INTEGER DEFAULT 0,
                referral_credited INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0
            )
            """
        )
        # eski bazalarda balance_som ustuni yo'q bo'lishi mumkin — mavjud bo'lmasa qo'shamiz
        cur_cols = await db.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in await cur_cols.fetchall()]
        if "balance_som" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN balance_som INTEGER DEFAULT 0")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_id INTEGER,
                gift_name TEXT,
                gift_cost INTEGER,
                recipient_username TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT UNIQUE)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                cost INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT,
                price_som INTEGER,
                description TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER,
                product_name TEXT,
                price_som INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur_shop_cols = await db.execute("PRAGMA table_info(shop_orders)")
        shop_columns = [row[1] for row in await cur_shop_cols.fetchall()]
        if "recipient_username" not in shop_columns:
            await db.execute("ALTER TABLE shop_orders ADD COLUMN recipient_username TEXT")
        if "anonymous" not in shop_columns:
            await db.execute("ALTER TABLE shop_orders ADD COLUMN anonymous INTEGER DEFAULT 0")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_number TEXT,
                card_holder TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS topup_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_som INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur_topup_cols = await db.execute("PRAGMA table_info(topup_requests)")
        topup_columns = [row[1] for row in await cur_topup_cols.fetchall()]
        if "receipt_file_id" not in topup_columns:
            await db.execute("ALTER TABLE topup_requests ADD COLUMN receipt_file_id TEXT")
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('reward_stars', ?)",
            (str(DEFAULT_REWARD_STARS),),
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('payment_channel', ?)",
            (PAYMENT_CHANNEL_DEFAULT,),
        )
        for ch in DEFAULT_CHANNELS:
            await db.execute("INSERT OR IGNORE INTO channels (channel) VALUES (?)", (ch,))
        cur = await db.execute("SELECT COUNT(*) FROM gifts")
        if (await cur.fetchone())[0] == 0:
            default_gifts = [
                ("🧸 Teddy Bear", 50),
                ("💝 Heart", 100),
                ("🌹 Rose", 150),
                ("🎂 Cake", 200),
                ("💎 Diamond", 500),
            ]
            await db.executemany("INSERT INTO gifts (name, cost) VALUES (?, ?)", default_gifts)
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def get_channels() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT channel FROM channels")
        return [r[0] for r in await cur.fetchall()]


async def add_channel(channel: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO channels (channel) VALUES (?)", (channel,))
        await db.commit()


async def remove_channel(channel: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE channel = ?", (channel,))
        await db.commit()


async def get_gifts() -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name, cost FROM gifts ORDER BY cost ASC")
        return await cur.fetchall()


async def get_gift(gift_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name, cost FROM gifts WHERE id = ?", (gift_id,))
        return await cur.fetchone()


async def add_gift(name: str, cost: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO gifts (name, cost) VALUES (?, ?)", (name, cost))
        await db.commit()


async def update_gift_cost(gift_id: int, cost: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE gifts SET cost = ? WHERE id = ?", (cost, gift_id))
        await db.commit()


async def delete_gift(gift_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()


async def create_user(user_id: int, username: str, referrer_id: int | None) -> bool:
    if await get_user(user_id):
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)",
            (user_id, username, referrer_id),
        )
        await db.commit()
    return True


async def mark_subscribed(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET subscribed = 1 WHERE user_id = ?", (user_id,))
        await db.commit()


async def mark_referral_credited(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET referral_credited = 1 WHERE user_id = ?", (user_id,))
        await db.commit()


async def add_stars(user_id: int, amount: int, count_referral: bool = False) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if count_referral:
            await db.execute(
                "UPDATE users SET stars = stars + ?, referrals_count = referrals_count + 1 WHERE user_id = ?",
                (amount, user_id),
            )
        else:
            await db.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
        cur = await db.execute("SELECT stars FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def create_withdrawal(user_id: int, gift_id: int, gift_name: str, gift_cost: int, recipient_username: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO withdrawals (user_id, gift_id, gift_name, gift_cost, recipient_username) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, gift_id, gift_name, gift_cost, recipient_username),
        )
        await db.commit()
        return cur.lastrowid


async def get_withdrawal(withdrawal_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,))
        return await cur.fetchone()


async def update_withdrawal_status(withdrawal_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (status, withdrawal_id))
        await db.commit()


async def set_banned(user_id: int, banned: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET banned = ? WHERE user_id = ?", (1 if banned else 0, user_id))
        await db.commit()


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]


async def add_som(user_id: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance_som = balance_som + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
        cur = await db.execute("SELECT balance_som FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


# --- Do'kon: bo'limlar ---
async def get_categories() -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name FROM shop_categories ORDER BY id ASC")
        return await cur.fetchall()


async def get_category(category_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name FROM shop_categories WHERE id = ?", (category_id,))
        return await cur.fetchone()


async def add_category(name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO shop_categories (name) VALUES (?)", (name,))
        await db.commit()
        return cur.lastrowid


async def delete_category(category_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM shop_categories WHERE id = ?", (category_id,))
        await db.execute("DELETE FROM shop_products WHERE category_id = ?", (category_id,))
        await db.commit()


# --- Do'kon: mahsulotlar ---
async def get_products(category_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name, price_som, description FROM shop_products WHERE category_id = ? ORDER BY id ASC",
            (category_id,),
        )
        return await cur.fetchall()


async def get_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, category_id, name, price_som, description FROM shop_products WHERE id = ?",
            (product_id,),
        )
        return await cur.fetchone()


async def add_product(category_id: int, name: str, price_som: int, description: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO shop_products (category_id, name, price_som, description) VALUES (?, ?, ?, ?)",
            (category_id, name, price_som, description),
        )
        await db.commit()
        return cur.lastrowid


async def delete_product(product_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM shop_products WHERE id = ?", (product_id,))
        await db.commit()


# --- Do'kon: buyurtmalar ---
async def create_shop_order(
    user_id: int, product_id: int, product_name: str, price_som: int, recipient_username: str, anonymous: bool
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO shop_orders (user_id, product_id, product_name, price_som, recipient_username, anonymous) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, product_id, product_name, price_som, recipient_username, 1 if anonymous else 0),
        )
        await db.commit()
        return cur.lastrowid



async def get_shop_order(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM shop_orders WHERE id = ?", (order_id,))
        return await cur.fetchone()


async def update_shop_order_status(order_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE shop_orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()


# --- To'lov kartalari ---
async def get_cards() -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, card_number, card_holder FROM payment_cards ORDER BY id ASC")
        return await cur.fetchall()


async def add_card(card_number: str, card_holder: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO payment_cards (card_number, card_holder) VALUES (?, ?)", (card_number, card_holder)
        )
        await db.commit()
        return cur.lastrowid


async def delete_card(card_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM payment_cards WHERE id = ?", (card_id,))
        await db.commit()


# --- Pul kiritish so'rovlari ---
async def create_topup_request(user_id: int, amount_som: int, receipt_file_id: str | None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO topup_requests (user_id, amount_som, receipt_file_id) VALUES (?, ?, ?)",
            (user_id, amount_som, receipt_file_id),
        )
        await db.commit()
        return cur.lastrowid


async def get_topup_request(request_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM topup_requests WHERE id = ?", (request_id,))
        return await cur.fetchone()


async def update_topup_status(request_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE topup_requests SET status = ? WHERE id = ?", (status, request_id))
        await db.commit()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=BTN_STARS_ISHLASH)],
        [KeyboardButton(text=BTN_BALANS), KeyboardButton(text=BTN_STARS_YECHISH)],
        [KeyboardButton(text=BTN_SHOP), KeyboardButton(text=BTN_TOLOV_KANALI)],
        [KeyboardButton(text=BTN_ADMIN_BOGLANISH), KeyboardButton(text=BTN_INFO)],
    ]
    if is_admin(user_id):
        keyboard.append([KeyboardButton(text=BTN_BOSHQARUV)])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def admin_panel_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_AP_STATS)],
            [KeyboardButton(text=BTN_AP_CHANNELS)],
            [KeyboardButton(text=BTN_AP_REWARD), KeyboardButton(text=BTN_AP_GIFTS)],
            [KeyboardButton(text=BTN_AP_PAYCHANNEL), KeyboardButton(text=BTN_AP_USERS)],
            [KeyboardButton(text=BTN_AP_SHOP), KeyboardButton(text=BTN_AP_CARDS)],
            [KeyboardButton(text=BTN_AP_BROADCAST)],
            [KeyboardButton(text=BTN_AP_INFO)],
            [KeyboardButton(text=BTN_AP_BACK)],
        ],
        resize_keyboard=True,
    )


async def channels_keyboard() -> InlineKeyboardMarkup:
    channels = await get_channels()
    buttons = []
    for ch in channels:
        clean = ch.lstrip("@")
        buttons.append([InlineKeyboardButton(text=f"📢 {ch}", url=f"https://t.me/{clean}")])
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def gifts_keyboard() -> InlineKeyboardMarkup:
    gifts = await get_gifts()
    buttons = [
        [InlineKeyboardButton(text=f"{name} — {cost} ⭐", callback_data=f"gift_{gid}")]
        for gid, name, cost in gifts
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_decision_keyboard(withdrawal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{withdrawal_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{withdrawal_id}"),
            ]
        ]
    )


async def check_all_subscriptions(user_id: int) -> bool:
    channels = await get_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True


async def send_subscription_prompt(chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "❗️ <b>Botdan foydalanish uchun majburiy kanallarga obuna bo'ling.</b>\n\n"
        "Avval barcha kanallarga obuna bo'ling, keyin «✅ Tekshirish» tugmasini bosing.",
        reply_markup=await channels_keyboard(),
    )


async def send_welcome(chat_id: int, user_id: int, full_name: str) -> None:
    await bot.send_message(
        chat_id,
        f"Assalomu alaykum, {full_name}! 👋\n\n"
        f"Botimizga xush kelibsiz!\n\n"
        f"Bu bot orqali siz Telegram <b>STARS</b> ishlab olishingiz mumkin ⭐",
        reply_markup=main_menu_keyboard(user_id),
    )


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name

    args = message.text.split(maxsplit=1)
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        candidate = int(args[1])
        if candidate != user_id:
            referrer_id = candidate

    await create_user(user_id, username, referrer_id)

    existing = await get_user(user_id)
    if existing and existing[7] == 1:
        await message.answer("🚫 Siz botdan foydalanishdan bloklangansiz.")
        return

    if not await check_all_subscriptions(user_id):
        await send_subscription_prompt(message.chat.id)
        return

    await mark_subscribed(user_id)
    await credit_referral_if_needed(user_id)
    await send_welcome(message.chat.id, user_id, message.from_user.full_name)


async def credit_referral_if_needed(user_id: int) -> None:
    user = await get_user(user_id)
    if not user or user[3] is None or user[6] == 1:
        return
    referrer_id = user[3]
    referrer = await get_user(referrer_id)
    if not referrer:
        return
    reward = float(await get_setting("reward_stars", str(DEFAULT_REWARD_STARS)))
    if reward == int(reward):
        reward = int(reward)
    new_balance = await add_stars(referrer_id, reward, count_referral=True)
    await mark_referral_credited(user_id)
    with suppress(Exception):
        await bot.send_message(
            referrer_id,
            f"🎉 Yangi referal qo'shildi!\n+{reward} ⭐ | Jami balans: <b>{new_balance}</b> ⭐",
        )


@dp.callback_query(F.data == "check_subs")
async def check_subs_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    if not await check_all_subscriptions(user_id):
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmagansiz!", show_alert=True)
        return
    await mark_subscribed(user_id)
    await credit_referral_if_needed(user_id)
    with suppress(Exception):
        await callback.message.edit_text("✅ Barcha majburiy kanallarga obuna bo'lgansiz.")
    await send_welcome(callback.message.chat.id, user_id, callback.from_user.full_name)
    await callback.answer()


@dp.message(F.text == BTN_STARS_ISHLASH)
async def stars_ishlash_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await check_all_subscriptions(message.from_user.id):
        await send_subscription_prompt(message.chat.id)
        return
    reward = await get_setting("reward_stars", str(DEFAULT_REWARD_STARS))
    ref_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"
    await message.answer(
        f"⭐ <b>Stars ishlash</b>\n\n"
        f"Do'stlaringizni shu havola orqali botga taklif qiling — har bir yangi "
        f"foydalanuvchi uchun <b>{reward} ⭐</b> stars olasiz!\n\n"
        f"🔗 Sizning referal havolangiz:\n<code>{ref_link}</code>"
    )


@dp.message(F.text == BTN_BALANS)
async def balans_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Iltimos, avval /start bosing.")
        return
    balance_som = user[8] if len(user) > 8 else 0
    await message.answer(
        f"💰 <b>Hisobim</b>\n\n"
        f"⭐ Stars hisobi: <b>{user[2]}</b>\n"
        f"💵 Pul hisobi: <b>{balance_som}</b> so'm\n"
        f"👥 Jami referallar: {user[4]} ta",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💳 Pul kiritish", callback_data="topup_start")]]
        ),
    )


@dp.message(F.text == BTN_STARS_YECHISH)
async def stars_yechish_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await check_all_subscriptions(message.from_user.id):
        await send_subscription_prompt(message.chat.id)
        return
    gifts = await get_gifts()
    if not gifts:
        await message.answer("Hozircha sovg'alar mavjud emas.")
        return
    await message.answer(
        "💸 <b>Stars yechish</b>\n\nQuyidagi gift/sovg'alardan birini tanlang:",
        reply_markup=await gifts_keyboard(),
    )


@dp.message(F.text == BTN_TOLOV_KANALI)
async def tolov_kanali_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    channel = await get_setting("payment_channel", PAYMENT_CHANNEL_DEFAULT)
    if not channel:
        await message.answer("To'lov kanali hozircha sozlanmagan.")
        return
    clean = channel.lstrip("@")
    await message.answer(f"📢 To'lovlar tasdiqlangani haqida shu kanalda e'lon qilinadi:\nhttps://t.me/{clean}")


@dp.message(F.text == BTN_ADMIN_BOGLANISH)
async def admin_contact_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(UserStates.waiting_admin_message)
    await message.answer("✍️ Xabaringizni yozing, u adminga yuboriladi:")


@dp.message(F.text == BTN_INFO)
async def info_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    info_text = await get_setting("info_text", "")
    if not info_text:
        await message.answer("📔 Hozircha ma'lumot kiritilmagan.")
        return
    await message.answer(f"📔 <b>Ma'lumot</b>\n\n{info_text}")


@dp.message(UserStates.waiting_admin_message)
async def forward_to_admin(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await state.clear()
    user = message.from_user
    target_admin = ADMIN_CONTACT_ID or (next(iter(ADMIN_IDS)) if ADMIN_IDS else None)
    if not target_admin:
        await message.answer("Kechirasiz, hozircha admin bilan bog'lanish ishlamayapti.")
        return
    with suppress(Exception):
        await bot.send_message(
            target_admin,
            f"✉️ <b>Yangi xabar</b>\n"
            f"👤 {user.full_name} (@{user.username or '—'}, ID: <code>{user.id}</code>)\n\n"
            f"{message.text}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="✉️ Javob berish", callback_data=f"reply_{user.id}")]]
            ),
        )
    await message.answer("✅ Xabaringiz adminga yuborildi. Tez orada javob berishadi.")


@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    target_user_id = int(callback.data.replace("reply_", ""))
    await state.update_data(reply_target_id=target_user_id)
    await state.set_state(AdminStates.waiting_reply_text)
    await bot.send_message(callback.from_user.id, f"✍️ <code>{target_user_id}</code> ga javob matnini yozing:")
    await callback.answer()


@dp.message(AdminStates.waiting_reply_text)
async def admin_reply_send(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    data = await state.get_data()
    target_user_id = data.get("reply_target_id")
    await state.clear()
    if not target_user_id:
        await message.answer("Xatolik yuz berdi, qaytadan urinib ko'ring.")
        return
    with suppress(Exception):
        await bot.send_message(target_user_id, f"✉️ <b>Admindan javob:</b>\n\n{message.text}")
    await message.answer("✅ Javobingiz yuborildi.")


@dp.callback_query(F.data.startswith("gift_"))
async def gift_selected(callback: CallbackQuery, state: FSMContext) -> None:
    gift_id = int(callback.data.replace("gift_", ""))
    gift = await get_gift(gift_id)
    if not gift:
        await callback.answer("Gift topilmadi.", show_alert=True)
        return
    _, gift_name, gift_cost = gift

    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Xatolik yuz berdi.", show_alert=True)
        return

    if user[2] < gift_cost:
        await callback.answer(
            f"❌ Balansingiz yetarli emas! Kerak: {gift_cost} ⭐, sizda: {user[2]} ⭐",
            show_alert=True,
        )
        return

    await state.update_data(pending_gift_id=gift_id, pending_gift_name=gift_name, pending_gift_cost=gift_cost)
    await state.set_state(UserStates.waiting_withdraw_username)

    with suppress(Exception):
        await callback.message.edit_text(f"🎁 Tanlandi: {gift_name} — {gift_cost} ⭐")
    await bot.send_message(
        callback.from_user.id,
        "✍️ Gift qaysi Telegram akkauntga yuborilishi kerak?\n"
        "Iltimos, <b>@username</b> ko'rinishida yuboring (masalan: <code>@ibroximovich</code>):",
    )
    await callback.answer()


@dp.message(UserStates.waiting_withdraw_username)
async def withdraw_username_received(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return

    username = message.text.strip()
    if not username.startswith("@") or len(username) < 3:
        await message.answer("Iltimos, to'g'ri @username yuboring (masalan: @ibroximovich).")
        return

    data = await state.get_data()
    gift_name = data.get("pending_gift_name")
    gift_cost = data.get("pending_gift_cost")
    await state.update_data(pending_username=username)

    user = await get_user(message.from_user.id)
    if not user or user[2] < gift_cost:
        await state.clear()
        await message.answer("❌ Balansingiz yetarli emas.")
        return

    await message.answer(
        f"🎁 <b>So'rovni tekshiring</b>\n\n"
        f"Sovg'a: {gift_name}\n"
        f"Narxi: {gift_cost} ⭐\n"
        f"Yuboriladigan akkaunt: {username}\n\n"
        f"Ma'lumotlar to'g'rimi? Tasdiqlaysizmi?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="✅ Ha, yuborilsin", callback_data="wd_confirm"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="wd_cancel"),
            ]]
        ),
    )


@dp.callback_query(F.data == "wd_confirm")
async def withdraw_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    gift_id = data.get("pending_gift_id")
    gift_name = data.get("pending_gift_name")
    gift_cost = data.get("pending_gift_cost")
    username = data.get("pending_username")
    await state.clear()

    if not gift_id or not username:
        await callback.answer("So'rov muddati tugagan, qaytadan urinib ko'ring.", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    if not user or user[2] < gift_cost:
        with suppress(Exception):
            await callback.message.edit_text("❌ Balansingiz yetarli emas.")
        await callback.answer()
        return

    withdrawal_id = await create_withdrawal(callback.from_user.id, gift_id, gift_name, gift_cost, username)

    with suppress(Exception):
        await callback.message.edit_text(
            f"✅ So'rovingiz qabul qilindi!\n\n"
            f"🎁 {gift_name} — {gift_cost} ⭐\n"
            f"📩 Yuboriladigan akkaunt: {username}\n\n"
            f"Admin tasdiqlagach, sizga xabar beriladi."
        )
    await callback.answer()

    user_info = callback.from_user
    for admin_id in ADMIN_IDS:
        with suppress(Exception):
            await bot.send_message(
                admin_id,
                f"💸 <b>Yangi yechib olish so'rovi</b>\n\n"
                f"👤 {user_info.full_name} (@{user_info.username or '—'})\n"
                f"🆔 <code>{user_info.id}</code>\n"
                f"🎁 {gift_name}\n"
                f"⭐ Narxi: {gift_cost}\n"
                f"💰 Balansi: {user[2]} ⭐\n"
                f"📩 Yuboriladigan akkaunt: {username}",
                reply_markup=admin_decision_keyboard(withdrawal_id),
            )


@dp.callback_query(F.data == "wd_cancel")
async def withdraw_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with suppress(Exception):
        await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


@dp.callback_query(F.data.startswith("approve_"))
async def approve_withdrawal(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    withdrawal_id = int(callback.data.replace("approve_", ""))
    withdrawal = await get_withdrawal(withdrawal_id)
    if not withdrawal or withdrawal[6] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    _, user_id, gift_id, gift_name, gift_cost, recipient_username, status, _ = withdrawal
    user = await get_user(user_id)
    if not user or user[2] < gift_cost:
        await callback.answer("Foydalanuvchi balansi yetarli emas!", show_alert=True)
        await update_withdrawal_status(withdrawal_id, "rejected")
        return

    await add_stars(user_id, -gift_cost, count_referral=False)
    await update_withdrawal_status(withdrawal_id, "approved")

    with suppress(Exception):
        await callback.message.edit_text(callback.message.text + "\n\n✅ TASDIQLANDI")
    with suppress(Exception):
        await bot.send_message(
            user_id,
            f"✅ Tabriklaymiz! Sizning <b>{gift_name}</b> so'rovingiz ({recipient_username} ga) "
            f"tasdiqlandi va yuborildi! 🎉",
        )

    payment_channel = await get_setting("payment_channel", PAYMENT_CHANNEL_DEFAULT)
    if payment_channel:
        user_obj = await bot.get_chat(user_id)
        display_name = f"@{user_obj.username}" if user_obj.username else user_obj.full_name
        with suppress(Exception):
            await bot.send_message(
                payment_channel,
                f"✅ <b>{display_name}</b> muvaffaqiyatli <b>{gift_name}</b> ({gift_cost} ⭐) yechib oldi!",
            )
    await callback.answer("Tasdiqlandi ✅")


@dp.callback_query(F.data.startswith("reject_"))
async def reject_withdrawal(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    withdrawal_id = int(callback.data.replace("reject_", ""))
    withdrawal = await get_withdrawal(withdrawal_id)
    if not withdrawal or withdrawal[6] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    _, user_id, gift_id, gift_name, gift_cost, recipient_username, status, _ = withdrawal
    await update_withdrawal_status(withdrawal_id, "rejected")
    with suppress(Exception):
        await callback.message.edit_text(callback.message.text + "\n\n❌ RAD ETILDI")
    with suppress(Exception):
        await bot.send_message(user_id, f"❌ Afsuski, sizning <b>{gift_name}</b> so'rovingiz rad etildi.")
    await callback.answer("Rad etildi ❌")


# ----------------- FOYDALANUVCHI: DO'KON -----------------
@dp.message(F.text == BTN_SHOP)
async def shop_menu_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await check_all_subscriptions(message.from_user.id):
        await send_subscription_prompt(message.chat.id)
        return
    categories = await get_categories()
    if not categories:
        await message.answer("Hozircha do'konda bo'limlar mavjud emas.")
        return
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"shopcat_{cid}")] for cid, name in categories
    ]
    await message.answer("🛍️ <b>Do'kon</b>\n\nBo'limni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("shopcat_"))
async def shop_category_callback(callback: CallbackQuery) -> None:
    category_id = int(callback.data.replace("shopcat_", ""))
    category = await get_category(category_id)
    if not category:
        await callback.answer("Bo'lim topilmadi.", show_alert=True)
        return
    products = await get_products(category_id)
    if not products:
        await callback.answer("Bu bo'limda hozircha mahsulot yo'q.", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(text=f"{name} — {price} so'm", callback_data=f"shopprod_{pid}")]
        for pid, name, price, description in products
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Bo'limlarga qaytish", callback_data="shopback")])
    with suppress(Exception):
        await callback.message.edit_text(f"🛍️ <b>{category[1]}</b>\n\nMahsulotni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data == "shopback")
async def shop_back_callback(callback: CallbackQuery) -> None:
    categories = await get_categories()
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"shopcat_{cid}")] for cid, name in categories
    ]
    with suppress(Exception):
        await callback.message.edit_text("🛍️ <b>Do'kon</b>\n\nBo'limni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("shopprod_"))
async def shop_product_callback(callback: CallbackQuery, state: FSMContext) -> None:
    product_id = int(callback.data.replace("shopprod_", ""))
    product = await get_product(product_id)
    if not product:
        await callback.answer("Mahsulot topilmadi.", show_alert=True)
        return
    _, category_id, name, price_som, description = product

    user = await get_user(callback.from_user.id)
    balance_som = user[8] if user and len(user) > 8 else 0
    if not user or balance_som < price_som:
        await callback.answer(
            f"❌ Balansingiz yetarli emas! Kerak: {price_som} so'm, sizda: {balance_som} so'm.\n"
            f"Hisobim bo'limidan pul kiriting.",
            show_alert=True,
        )
        return

    await state.update_data(
        pending_product_id=product_id,
        pending_product_name=name,
        pending_product_price=price_som,
        pending_product_desc=description,
    )
    await state.set_state(UserStates.waiting_shop_username)

    with suppress(Exception):
        await callback.message.edit_text(f"🛍️ Tanlandi: {name} — {price_som} so'm")
    await bot.send_message(
        callback.from_user.id,
        "✍️ Mahsulot qaysi Telegram akkauntga yuborilishi kerak?\n"
        "Iltimos, <b>@username</b> ko'rinishida yuboring (masalan: <code>@ibroximovich</code>):",
    )
    await callback.answer()


@dp.message(UserStates.waiting_shop_username)
async def shop_username_received(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    username = message.text.strip()
    if not username.startswith("@") or len(username) < 3:
        await message.answer("Iltimos, to'g'ri @username yuboring (masalan: @ibroximovich).")
        return
    await state.update_data(pending_shop_username=username)
    await message.answer(
        "🕵️ Xarid <b>anonim</b> yuborilsinmi? (ya'ni sizning ismingiz yashirin qolsinmi)",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="✅ Ha, anonim", callback_data="shopanon_yes"),
                InlineKeyboardButton(text="❌ Yo'q, oddiy", callback_data="shopanon_no"),
            ]]
        ),
    )


@dp.callback_query(F.data.in_({"shopanon_yes", "shopanon_no"}))
async def shop_anonymous_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    anonymous = callback.data == "shopanon_yes"
    await state.update_data(pending_shop_anonymous=anonymous)
    data = await state.get_data()
    name = data.get("pending_product_name")
    price_som = data.get("pending_product_price")
    description = data.get("pending_product_desc")
    username = data.get("pending_shop_username")
    desc_line = f"\n{description}" if description else ""
    anon_text = "Ha (anonim)" if anonymous else "Yo'q (oddiy)"

    with suppress(Exception):
        await callback.message.edit_text(
            f"🛍️ <b>Xaridni tasdiqlang</b>\n\n"
            f"📦 {name} — {price_som} so'm{desc_line}\n"
            f"📩 Yuboriladigan akkaunt: {username}\n"
            f"🕵️ Anonim: {anon_text}\n\n"
            f"Sotib olishni tasdiqlaysizmi?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Ha, sotib olaman", callback_data="shopconfirm"),
                    InlineKeyboardButton(text="❌ Bekor qilish", callback_data="shopcancel"),
                ]]
            ),
        )
    await callback.answer()


@dp.callback_query(F.data == "shopcancel")
async def shop_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with suppress(Exception):
        await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


@dp.callback_query(F.data == "shopconfirm")
async def shop_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data.get("pending_product_id")
    name = data.get("pending_product_name")
    price_som = data.get("pending_product_price")
    description = data.get("pending_product_desc")
    username = data.get("pending_shop_username")
    anonymous = data.get("pending_shop_anonymous", False)
    await state.clear()

    if not product_id or not username:
        await callback.answer("So'rov muddati tugagan, qaytadan urinib ko'ring.", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    balance_som = user[8] if user and len(user) > 8 else 0
    if not user or balance_som < price_som:
        with suppress(Exception):
            await callback.message.edit_text(
                f"❌ Balansingiz yetarli emas! Kerak: {price_som} so'm, sizda: {balance_som} so'm."
            )
        await callback.answer()
        return

    order_id = await create_shop_order(callback.from_user.id, product_id, name, price_som, username, anonymous)
    desc_line = f"\n{description}" if description else ""
    with suppress(Exception):
        await callback.message.edit_text(
            f"✅ So'rovingiz qabul qilindi!\n\n🛍️ {name} — {price_som} so'm{desc_line}\n"
            f"📩 Akkaunt: {username}\n\n"
            f"Admin tasdiqlagach, sizga xabar beriladi."
        )
    await callback.answer()

    anon_text = "Ha (anonim)" if anonymous else "Yo'q (oddiy)"
    user_info = callback.from_user
    for admin_id in ADMIN_IDS:
        with suppress(Exception):
            await bot.send_message(
                admin_id,
                f"🛍️ <b>Yangi do'kon buyurtmasi</b>\n\n"
                f"👤 {user_info.full_name} (@{user_info.username or '—'})\n"
                f"🆔 <code>{user_info.id}</code>\n"
                f"📦 {name}\n"
                f"💵 Narxi: {price_som} so'm\n"
                f"💰 Pul balansi: {balance_som} so'm\n"
                f"📩 Yuboriladigan akkaunt: {username}\n"
                f"🕵️ Anonim: {anon_text}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"apshop_{order_id}"),
                        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"rejshop_{order_id}"),
                    ]]
                ),
            )


@dp.callback_query(F.data.startswith("apshop_"))
async def approve_shop_order(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    order_id = int(callback.data.replace("apshop_", ""))
    order = await get_shop_order(order_id)
    if not order or order[5] != "pending":
        await callback.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    _, user_id, product_id, product_name, price_som, status, created_at, recipient_username, anonymous = order
    user = await get_user(user_id)
    balance_som = user[8] if user and len(user) > 8 else 0
    if not user or balance_som < price_som:
        await callback.answer("Foydalanuvchi balansi yetarli emas!", show_alert=True)
        await update_shop_order_status(order_id, "rejected")
        return
    await add_som(user_id, -price_som)
    await update_shop_order_status(order_id, "approved")
    with suppress(Exception):
        await callback.message.edit_text(callback.message.text + "\n\n✅ TASDIQLANDI")
    with suppress(Exception):
        await bot.send_message(user_id, f"✅ Sizning <b>{product_name}</b> buyurtmangiz tasdiqlandi va tez orada yetkaziladi! 🎉")
    await callback.answer("Tasdiqlandi ✅")


@dp.callback_query(F.data.startswith("rejshop_"))
async def reject_shop_order(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    order_id = int(callback.data.replace("rejshop_", ""))
    order = await get_shop_order(order_id)
    if not order or order[5] != "pending":
        await callback.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    _, user_id, product_id, product_name, price_som, status, created_at, recipient_username, anonymous = order
    await update_shop_order_status(order_id, "rejected")
    with suppress(Exception):
        await callback.message.edit_text(callback.message.text + "\n\n❌ RAD ETILDI")
    with suppress(Exception):
        await bot.send_message(user_id, f"❌ Afsuski, sizning <b>{product_name}</b> buyurtmangiz rad etildi.")
    await callback.answer("Rad etildi ❌")


# ----------------- FOYDALANUVCHI: PUL KIRITISH -----------------
@dp.callback_query(F.data == "topup_start")
async def topup_start_callback(callback: CallbackQuery) -> None:
    cards = await get_cards()
    if not cards:
        await callback.answer("Hozircha to'lov kartalari kiritilmagan. Admin bilan bog'laning.", show_alert=True)
        return
    text = "💳 <b>Pul kiritish</b>\n\nQuyidagi kartalardan biriga pul o'tkazing:\n\n"
    for cid, number, holder in cards:
        text += f"💳 <code>{number}</code>\n👤 {holder}\n\n"
    text += "Pul o'tkazgach, pastdagi tugmani bosing."
    with suppress(Exception):
        await bot.send_message(
            callback.from_user.id,
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="✅ Pul o'tkazdim", callback_data="topup_confirm")]]
            ),
        )
    await callback.answer()


@dp.callback_query(F.data == "topup_confirm")
async def topup_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserStates.waiting_topup_amount)
    with suppress(Exception):
        await callback.message.edit_text("✍️ O'tkazgan summangizni kiriting (faqat raqam, so'mda):")
    await callback.answer()


@dp.message(UserStates.waiting_topup_amount)
async def topup_amount_received(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Iltimos, faqat musbat son yuboring.")
        return
    amount = int(message.text)
    await state.update_data(topup_amount=amount)
    await state.set_state(UserStates.waiting_topup_receipt)
    await message.answer("📎 Endi to'lov chekini (skrinshot/rasm ko'rinishida) yuboring:")


@dp.message(UserStates.waiting_topup_receipt, F.photo)
async def topup_receipt_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    amount = data.get("topup_amount")
    await state.clear()
    if not amount:
        await message.answer("Xatolik yuz berdi, qaytadan urinib ko'ring.", reply_markup=main_menu_keyboard(message.from_user.id))
        return

    receipt_file_id = message.photo[-1].file_id
    request_id = await create_topup_request(message.from_user.id, amount, receipt_file_id)

    await message.answer(
        "✅ So'rovingiz qabul qilindi! Admin tasdiqlagach, hisobingizga pul qo'shiladi.",
        reply_markup=main_menu_keyboard(message.from_user.id),
    )

    user_info = message.from_user
    caption = (
        f"💳 <b>Yangi pul kiritish so'rovi</b>\n\n"
        f"👤 {user_info.full_name} (@{user_info.username or '—'})\n"
        f"🆔 <code>{user_info.id}</code>\n"
        f"💵 Summa: {amount} so'm"
    )
    for admin_id in ADMIN_IDS:
        with suppress(Exception):
            await bot.send_photo(
                admin_id,
                photo=receipt_file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"aptopup_{request_id}"),
                        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"rejtopup_{request_id}"),
                    ]]
                ),
            )


@dp.message(UserStates.waiting_topup_receipt, F.text)
async def topup_receipt_skip_check(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await message.answer("Iltimos, chekni rasm (screenshot) ko'rinishida yuboring.")


@dp.callback_query(F.data.startswith("aptopup_"))
async def approve_topup(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    request_id = int(callback.data.replace("aptopup_", ""))
    request = await get_topup_request(request_id)
    if not request or request[3] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    _, user_id, amount_som, status, _, receipt_file_id = request
    new_balance = await add_som(user_id, amount_som)
    await update_topup_status(request_id, "approved")
    with suppress(Exception):
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ TASDIQLANDI")
    with suppress(Exception):
        await bot.send_message(user_id, f"✅ Hisobingizga {amount_som} so'm qo'shildi!\n💰 Yangi balans: {new_balance} so'm")
    await callback.answer("Tasdiqlandi ✅")


@dp.callback_query(F.data.startswith("rejtopup_"))
async def reject_topup(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return
    request_id = int(callback.data.replace("rejtopup_", ""))
    request = await get_topup_request(request_id)
    if not request or request[3] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    _, user_id, amount_som, status, _, receipt_file_id = request
    await update_topup_status(request_id, "rejected")
    with suppress(Exception):
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ RAD ETILDI")
    with suppress(Exception):
        await bot.send_message(user_id, f"❌ Afsuski, {amount_som} so'mlik pul kiritish so'rovingiz rad etildi.")
    await callback.answer("Rad etildi ❌")


@dp.message(F.text == BTN_BOSHQARUV)
async def admin_panel_entry(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("🔧 <b>Boshqaruv paneli</b>\n\nKerakli bo'limni tanlang:", reply_markup=admin_panel_menu_keyboard())


@dp.message(F.text == BTN_AP_BACK)
async def admin_panel_exit(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(message.from_user.id))


@dp.message(F.text == BTN_AP_STATS)
async def ap_stats(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(stars),0), COALESCE(SUM(balance_som),0) FROM users")
        total_users, total_stars, total_som = await cur.fetchone()
        cur2 = await db.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
        pending = (await cur2.fetchone())[0]
        cur3 = await db.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved'")
        approved = (await cur3.fetchone())[0]
        cur4 = await db.execute("SELECT COUNT(*) FROM shop_orders WHERE status='pending'")
        pending_orders = (await cur4.fetchone())[0]
        cur5 = await db.execute("SELECT COUNT(*) FROM topup_requests WHERE status='pending'")
        pending_topups = (await cur5.fetchone())[0]
    reward = await get_setting("reward_stars", str(DEFAULT_REWARD_STARS))
    channels = await get_channels()
    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"⭐ Jami stars balansi: {total_stars}\n"
        f"💵 Jami pul balansi: {total_som} so'm\n"
        f"⏳ Kutilayotgan stars so'rovlari: {pending}\n"
        f"✅ Tasdiqlangan yechishlar: {approved}\n"
        f"🛍️ Kutilayotgan do'kon buyurtmalari: {pending_orders}\n"
        f"💳 Kutilayotgan pul kiritishlar: {pending_topups}\n"
        f"🎯 Referal narxi: {reward} ⭐\n"
        f"📢 Majburiy kanallar soni: {len(channels)}"
    )


async def send_channels_view(chat_id: int) -> None:
    channels = await get_channels()
    buttons = [
        [InlineKeyboardButton(text=f"❌ {ch}", callback_data=f"ap_delch_{i}")]
        for i, ch in enumerate(channels)
    ]
    buttons.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="ap_addch")])
    text = "📢 <b>Majburiy kanallar</b>\n\n"
    text += "\n".join(channels) if channels else "Hozircha kanal qo'shilmagan."
    text += "\n\nO'chirish uchun kanal ustiga bosing."
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.message(F.text == BTN_AP_CHANNELS)
async def ap_channels(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await send_channels_view(message.chat.id)


@dp.callback_query(F.data.startswith("ap_delch_"))
async def ap_delete_channel(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    idx = int(callback.data.replace("ap_delch_", ""))
    channels = await get_channels()
    if 0 <= idx < len(channels):
        await remove_channel(channels[idx])
        await callback.answer("O'chirildi ✅")
    with suppress(Exception):
        await callback.message.delete()
    await send_channels_view(callback.message.chat.id)


@dp.callback_query(F.data == "ap_addch")
async def ap_add_channel_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_new_channel)
    await bot.send_message(
        callback.from_user.id,
        "➕ Yangi kanal username'ini yuboring (masalan: <code>@mening_kanalim</code>).\n\n"
        "⚠️ Bot shu kanalda admin bo'lishi shart, aks holda obunani tekshira olmaydi.",
    )
    await callback.answer()


@dp.message(AdminStates.waiting_new_channel)
async def ap_add_channel_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    channel = message.text.strip()
    if not channel.startswith("@"):
        await message.answer("Iltimos, @ bilan boshlanadigan username yuboring.")
        return
    await add_channel(channel)
    await state.clear()
    await message.answer(f"✅ {channel} qo'shildi.")
    await send_channels_view(message.chat.id)


@dp.message(F.text == BTN_AP_REWARD)
async def ap_reward(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    current = await get_setting("reward_stars", str(DEFAULT_REWARD_STARS))
    await state.set_state(AdminStates.waiting_reward_value)
    await message.answer(f"⭐ Joriy referal narxi: <b>{current} ⭐</b>\n\nYangi qiymatni yuboring (faqat raqam):")


@dp.message(AdminStates.waiting_reward_value)
async def ap_reward_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    text = message.text.strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        await message.answer("Iltimos, faqat musbat son yuboring (masalan 10 yoki 1.5).")
        return
    if value <= 0:
        await message.answer("Iltimos, faqat musbat son yuboring (masalan 10 yoki 1.5).")
        return
    # butun son bo'lsa "10.0" emas "10" ko'rinishida saqlaymiz
    stored_value = int(value) if value == int(value) else value
    await set_setting("reward_stars", str(stored_value))
    await state.clear()
    await message.answer(f"✅ Referal narxi {stored_value} ⭐ ga o'zgartirildi.")


async def send_gifts_view(chat_id: int) -> None:
    gifts = await get_gifts()
    buttons = [
        [
            InlineKeyboardButton(text=f"{name} — {cost} ⭐", callback_data=f"ap_editgift_{gid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"ap_delgift_{gid}"),
        ]
        for gid, name, cost in gifts
    ]
    buttons.append([InlineKeyboardButton(text="➕ Yangi sovg'a qo'shish", callback_data="ap_addgift")])
    await bot.send_message(
        chat_id,
        "🎁 <b>Sovg'alar narxi</b>\n\nNarxini o'zgartirish uchun nomiga, o'chirish uchun 🗑 belgisiga bosing.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.message(F.text == BTN_AP_GIFTS)
async def ap_gifts(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await send_gifts_view(message.chat.id)


@dp.callback_query(F.data.startswith("ap_delgift_"))
async def ap_delete_gift(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    gift_id = int(callback.data.replace("ap_delgift_", ""))
    await delete_gift(gift_id)
    await callback.answer("O'chirildi ✅")
    with suppress(Exception):
        await callback.message.delete()
    await send_gifts_view(callback.message.chat.id)


@dp.callback_query(F.data.startswith("ap_editgift_"))
async def ap_edit_gift_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    gift_id = int(callback.data.replace("ap_editgift_", ""))
    gift = await get_gift(gift_id)
    if not gift:
        await callback.answer("Topilmadi.", show_alert=True)
        return
    await state.update_data(edit_gift_id=gift_id)
    await state.set_state(AdminStates.waiting_edit_gift_cost)
    await bot.send_message(callback.from_user.id, f"✏️ <b>{gift[1]}</b> uchun yangi narxni yuboring (⭐):")
    await callback.answer()


@dp.message(AdminStates.waiting_edit_gift_cost)
async def ap_edit_gift_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat musbat raqam yuboring.")
        return
    data = await state.get_data()
    await update_gift_cost(data["edit_gift_id"], int(message.text))
    await state.clear()
    await message.answer(f"✅ Narx {message.text} ⭐ ga o'zgartirildi.")


@dp.callback_query(F.data == "ap_addgift")
async def ap_add_gift_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_new_gift_name)
    await bot.send_message(callback.from_user.id, "➕ Yangi sovg'a nomini yuboring (masalan: 🎁 Gift Box):")
    await callback.answer()


@dp.message(AdminStates.waiting_new_gift_name)
async def ap_add_gift_name(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await state.update_data(new_gift_name=message.text.strip())
    await state.set_state(AdminStates.waiting_new_gift_cost)
    await message.answer("Endi narxini yuboring (⭐, faqat raqam):")


@dp.message(AdminStates.waiting_new_gift_cost)
async def ap_add_gift_cost(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat musbat raqam yuboring.")
        return
    data = await state.get_data()
    await add_gift(data["new_gift_name"], int(message.text))
    await state.clear()
    await message.answer(f"✅ {data['new_gift_name']} — {message.text} ⭐ qo'shildi.")


# --- Do'kon boshqaruvi: bo'limlar va mahsulotlar ---
async def send_shop_categories_view(chat_id: int) -> None:
    categories = await get_categories()
    buttons = [
        [
            InlineKeyboardButton(text=f"📂 {name}", callback_data=f"ap_viewcat_{cid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"ap_delcat_{cid}"),
        ]
        for cid, name in categories
    ]
    buttons.append([InlineKeyboardButton(text="➕ Yangi bo'lim qo'shish", callback_data="ap_addcat")])
    text = "🛍️ <b>Do'kon bo'limlari</b>\n\n"
    text += "Bo'lim ichidagi mahsulotlarni ko'rish uchun nomiga bosing." if categories else "Hozircha bo'lim qo'shilmagan."
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.message(F.text == BTN_AP_SHOP)
async def ap_shop(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await send_shop_categories_view(message.chat.id)


@dp.callback_query(F.data == "ap_addcat")
async def ap_add_category_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_new_category)
    await bot.send_message(callback.from_user.id, "➕ Yangi bo'lim nomini yuboring (masalan: Giftlar):")
    await callback.answer()


@dp.message(AdminStates.waiting_new_category)
async def ap_add_category_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await add_category(message.text.strip())
    await state.clear()
    await message.answer(f"✅ \"{message.text.strip()}\" bo'limi qo'shildi.")
    await send_shop_categories_view(message.chat.id)


@dp.callback_query(F.data.startswith("ap_delcat_"))
async def ap_delete_category(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    category_id = int(callback.data.replace("ap_delcat_", ""))
    await delete_category(category_id)
    await callback.answer("O'chirildi ✅")
    with suppress(Exception):
        await callback.message.delete()
    await send_shop_categories_view(callback.message.chat.id)


async def send_shop_products_view(chat_id: int, category_id: int) -> None:
    category = await get_category(category_id)
    if not category:
        return
    products = await get_products(category_id)
    buttons = [
        [InlineKeyboardButton(text=f"🗑 {name} — {price} so'm", callback_data=f"ap_delprod_{pid}")]
        for pid, name, price, description in products
    ]
    buttons.append([InlineKeyboardButton(text="➕ Mahsulot qo'shish", callback_data=f"ap_addprod_{category_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Bo'limlarga qaytish", callback_data="ap_backcat")])
    text = f"📂 <b>{category[1]}</b>\n\n"
    text += "O'chirish uchun mahsulot ustiga bosing." if products else "Bu bo'limda hozircha mahsulot yo'q."
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("ap_viewcat_"))
async def ap_view_category(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    category_id = int(callback.data.replace("ap_viewcat_", ""))
    with suppress(Exception):
        await callback.message.delete()
    await send_shop_products_view(callback.message.chat.id, category_id)
    await callback.answer()


@dp.callback_query(F.data == "ap_backcat")
async def ap_back_to_categories(callback: CallbackQuery) -> None:
    with suppress(Exception):
        await callback.message.delete()
    await send_shop_categories_view(callback.message.chat.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("ap_delprod_"))
async def ap_delete_product(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    product_id = int(callback.data.replace("ap_delprod_", ""))
    product = await get_product(product_id)
    category_id = product[1] if product else None
    await delete_product(product_id)
    await callback.answer("O'chirildi ✅")
    with suppress(Exception):
        await callback.message.delete()
    if category_id:
        await send_shop_products_view(callback.message.chat.id, category_id)


@dp.callback_query(F.data.startswith("ap_addprod_"))
async def ap_add_product_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    category_id = int(callback.data.replace("ap_addprod_", ""))
    await state.update_data(new_product_category_id=category_id)
    await state.set_state(AdminStates.waiting_new_product_name)
    await bot.send_message(callback.from_user.id, "➕ Mahsulot nomini yuboring:")
    await callback.answer()


@dp.message(AdminStates.waiting_new_product_name)
async def ap_add_product_name(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await state.update_data(new_product_name=message.text.strip())
    await state.set_state(AdminStates.waiting_new_product_price)
    await message.answer("💵 Narxini yuboring (so'mda, faqat raqam):")


@dp.message(AdminStates.waiting_new_product_price)
async def ap_add_product_price(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat musbat raqam yuboring.")
        return
    await state.update_data(new_product_price=int(message.text))
    await state.set_state(AdminStates.waiting_new_product_description)
    await message.answer("📝 Qisqacha tavsif yuboring (yoki /skip):")


@dp.message(AdminStates.waiting_new_product_description)
async def ap_add_product_description(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    description = "" if is_skip(message.text) else message.text.strip()
    data = await state.get_data()
    await add_product(data["new_product_category_id"], data["new_product_name"], data["new_product_price"], description)
    await state.clear()
    await message.answer(f"✅ {data['new_product_name']} — {data['new_product_price']} so'm qo'shildi.")
    await send_shop_products_view(message.chat.id, data["new_product_category_id"])


# --- To'lov kartalari boshqaruvi ---
async def send_cards_view(chat_id: int) -> None:
    cards = await get_cards()
    buttons = [
        [InlineKeyboardButton(text=f"🗑 {number} — {holder}", callback_data=f"ap_delcard_{cid}")]
        for cid, number, holder in cards
    ]
    buttons.append([InlineKeyboardButton(text="➕ Karta qo'shish", callback_data="ap_addcard")])
    text = "💳 <b>To'lov kartalari</b>\n\n"
    text += "O'chirish uchun karta ustiga bosing." if cards else "Hozircha karta qo'shilmagan."
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.message(F.text == BTN_AP_CARDS)
async def ap_cards(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await send_cards_view(message.chat.id)


@dp.callback_query(F.data == "ap_addcard")
async def ap_add_card_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_new_card_number)
    await bot.send_message(callback.from_user.id, "💳 Karta raqamini yuboring (masalan: 8600 1234 5678 9012):")
    await callback.answer()


@dp.message(AdminStates.waiting_new_card_number)
async def ap_add_card_number(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await state.update_data(new_card_number=message.text.strip())
    await state.set_state(AdminStates.waiting_new_card_holder)
    await message.answer("👤 Karta egasining F.I.Sh (yoki ismini) yuboring:")


@dp.message(AdminStates.waiting_new_card_holder)
async def ap_add_card_holder(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    data = await state.get_data()
    await add_card(data["new_card_number"], message.text.strip())
    await state.clear()
    await message.answer("✅ Karta qo'shildi.")
    await send_cards_view(message.chat.id)


@dp.callback_query(F.data.startswith("ap_delcard_"))
async def ap_delete_card(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    card_id = int(callback.data.replace("ap_delcard_", ""))
    await delete_card(card_id)
    await callback.answer("O'chirildi ✅")
    with suppress(Exception):
        await callback.message.delete()
    await send_cards_view(callback.message.chat.id)


@dp.message(F.text == BTN_AP_PAYCHANNEL)
async def ap_paychannel(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    current = await get_setting("payment_channel", PAYMENT_CHANNEL_DEFAULT)
    await state.set_state(AdminStates.waiting_payment_channel)
    await message.answer(
        f"💳 Joriy to'lov kanali: <b>{current or 'sozlanmagan'}</b>\n\n"
        f"Yangi kanal username'ini yuboring (masalan: <code>@tolov_kanali</code>):"
    )


@dp.message(AdminStates.waiting_payment_channel)
async def ap_paychannel_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    channel = message.text.strip()
    if not channel.startswith("@"):
        await message.answer("Iltimos, @ bilan boshlanadigan username yuboring.")
        return
    await set_setting("payment_channel", channel)
    await state.clear()
    await message.answer(f"✅ To'lov kanali {channel} ga o'zgartirildi.")


@dp.message(F.text == BTN_AP_USERS)
async def ap_users_prompt(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_user_search_id)
    await message.answer("👥 <b>Foydalanuvchilarni boshqarish</b>\n\nQidirmoqchi bo'lgan foydalanuvchining Telegram ID raqamini yuboring:")


def user_info_text(user) -> str:
    _, username, stars, referrer_id, referrals_count, subscribed, referral_credited, banned, balance_som = user
    status = "🚫 Bloklangan" if banned else "✅ Faol"
    return (
        f"👤 <b>Foydalanuvchi ma'lumoti</b>\n\n"
        f"🆔 ID: <code>{user[0]}</code>\n"
        f"👤 Username: @{username or '—'}\n"
        f"⭐ Stars balansi: {stars}\n"
        f"💵 Pul balansi: {balance_som} so'm\n"
        f"👥 Referallar: {referrals_count} ta\n"
        f"📌 Holati: {status}"
    )


def user_actions_keyboard(user_id: int, banned: bool) -> InlineKeyboardMarkup:
    ban_button = (
        InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data=f"ap_unban_{user_id}")
        if banned
        else InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"ap_ban_{user_id}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Ball qo'shish/ayirish", callback_data=f"ap_adjstars_{user_id}")],
            [InlineKeyboardButton(text="✉️ Xabar yuborish", callback_data=f"reply_{user_id}")],
            [ban_button],
        ]
    )


@dp.message(AdminStates.waiting_user_search_id)
async def ap_users_search(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat raqam (Telegram ID) yuboring.")
        return
    target_id = int(message.text)
    user = await get_user(target_id)
    await state.clear()
    if not user:
        await message.answer("Bunday foydalanuvchi bazada topilmadi.")
        return
    await message.answer(user_info_text(user), reply_markup=user_actions_keyboard(target_id, user[7] == 1))


@dp.callback_query(F.data.startswith("ap_adjstars_"))
async def ap_adjust_stars_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.replace("ap_adjstars_", ""))
    await state.update_data(adjust_target_id=target_id)
    await state.set_state(AdminStates.waiting_adjust_stars_amount)
    await bot.send_message(
        callback.from_user.id,
        f"⭐ <code>{target_id}</code> uchun miqdorni yuboring "
        f"(qo'shish uchun masalan <code>50</code>, ayirish uchun <code>-50</code>):",
    )
    await callback.answer()


@dp.message(AdminStates.waiting_adjust_stars_amount)
async def ap_adjust_stars_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    if not message.text.lstrip("-").isdigit():
        await message.answer("Iltimos, faqat raqam yuboring.")
        return
    amount = int(message.text)
    data = await state.get_data()
    target_id = data["adjust_target_id"]
    new_balance = await add_stars(target_id, amount, count_referral=False)
    await state.clear()
    await message.answer(f"✅ {target_id} uchun balans yangilandi: <b>{new_balance}</b> ⭐")
    with suppress(Exception):
        await bot.send_message(target_id, f"⭐ Balansingiz o'zgartirildi. Yangi balans: {new_balance} ⭐")


@dp.callback_query(F.data.startswith("ap_ban_"))
async def ap_ban_user(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.replace("ap_ban_", ""))
    await set_banned(target_id, True)
    user = await get_user(target_id)
    await callback.message.edit_text(user_info_text(user), reply_markup=user_actions_keyboard(target_id, True))
    await callback.answer("Bloklandi 🚫")


@dp.callback_query(F.data.startswith("ap_unban_"))
async def ap_unban_user(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.replace("ap_unban_", ""))
    await set_banned(target_id, False)
    user = await get_user(target_id)
    await callback.message.edit_text(user_info_text(user), reply_markup=user_actions_keyboard(target_id, False))
    await callback.answer("Blokdan chiqarildi ✅")


@dp.message(F.text == BTN_AP_BROADCAST)
async def ap_broadcast_prompt(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_broadcast_text)
    await message.answer("📤 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabar matnini yuboring:")


@dp.message(AdminStates.waiting_broadcast_text)
async def ap_broadcast_send(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    user_ids = await get_all_user_ids()
    await state.clear()
    sent, failed = 0, 0
    status_msg = await message.answer(f"📤 Yuborilmoqda... (0/{len(user_ids)})")
    for uid in user_ids:
        try:
            await bot.send_message(uid, message.text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"✅ Yuborildi: {sent} ta\n❌ Yuborilmadi: {failed} ta")


@dp.message(F.text == BTN_AP_INFO)
async def ap_info_prompt(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    current = await get_setting("info_text", "")
    await state.set_state(AdminStates.waiting_info_text)
    if current:
        await message.answer(f"📔 <b>Joriy ma'lumot:</b>\n\n{current}\n\n✍️ Yangi matnni yuboring (eskisi almashadi):")
    else:
        await message.answer("📔 Hozircha ma'lumot kiritilmagan.\n\n✍️ Matnni yuboring:")


@dp.message(AdminStates.waiting_info_text)
async def ap_info_save(message: Message, state: FSMContext) -> None:
    if await cancel_if_nav_button(message, state):
        return
    await set_setting("info_text", message.text)
    await state.clear()
    await message.answer("✅ Ma'lumot saqlandi.")


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env yoki Railway Variables'ga qo'shing.")
    await init_db()
    log.info("Bot ishga tushdi.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
