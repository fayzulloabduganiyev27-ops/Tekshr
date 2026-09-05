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
BTN_BALANS = "💰 Balans"
BTN_STARS_YECHISH = "💸 Stars yechish"
BTN_TOLOV_KANALI = "📢 To'lov kanali"
BTN_ADMIN_BOGLANISH = "👨‍💻 Admin bilan bog'lanish"
BTN_BOSHQARUV = "🔧 Boshqaruv"

BTN_AP_STATS = "📊 Statistika"
BTN_AP_CHANNELS = "📢 Majburiy kanallar"
BTN_AP_REWARD = "⭐ Referal narxi"
BTN_AP_GIFTS = "🎁 Sovg'alar narxi"
BTN_AP_PAYCHANNEL = "💳 To'lov kanali sozlash"
BTN_AP_USERS = "👥 Foydalanuvchilarni boshqarish"
BTN_AP_BROADCAST = "📤 Hammaga xabar yuborish"
BTN_AP_INFO = "📔 Ma'lumotlar"
BTN_AP_BACK = "⬅️ Asosiy menyu"

ADMIN_PANEL_TEXTS = {
    BTN_AP_STATS, BTN_AP_CHANNELS, BTN_AP_REWARD, BTN_AP_GIFTS,
    BTN_AP_PAYCHANNEL, BTN_AP_USERS, BTN_AP_BROADCAST, BTN_AP_INFO, BTN_AP_BACK,
}
MAIN_MENU_TEXTS = {
    BTN_STARS_ISHLASH, BTN_BALANS, BTN_STARS_YECHISH,
    BTN_TOLOV_KANALI, BTN_ADMIN_BOGLANISH, BTN_BOSHQARUV,
}
ALL_NAV_TEXTS = ADMIN_PANEL_TEXTS | MAIN_MENU_TEXTS


class UserStates(StatesGroup):
    waiting_admin_message = State()
    waiting_withdraw_username = State()


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


async def cancel_if_nav_button(message: Message, state: FSMContext) -> bool:
    if message.text in ALL_NAV_TEXTS:
        await state.clear()
        return True
    return False


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


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=BTN_STARS_ISHLASH)],
        [KeyboardButton(text=BTN_BALANS), KeyboardButton(text=BTN_STARS_YECHISH)],
        [KeyboardButton(text=BTN_TOLOV_KANALI), KeyboardButton(text=BTN_ADMIN_BOGLANISH)],
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
    reward = int(await get_setting("reward_stars", str(DEFAULT_REWARD_STARS)))
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
    await message.answer(f"💰 <b>Balansingiz:</b> {user[2]} ⭐\n👥 <b>Jami referallar:</b> {user[4]} ta")


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
        )
    await message.answer("✅ Xabaringiz adminga yuborildi. Tez orada javob berishadi.")


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
    gift_id = data.get("pending_gift_id")
    gift_name = data.get("pending_gift_name")
    gift_cost = data.get("pending_gift_cost")
    await state.clear()

    user = await get_user(message.from_user.id)
    if not user or user[2] < gift_cost:
        await message.answer("❌ Balansingiz yetarli emas.")
        return

    withdrawal_id = await create_withdrawal(message.from_user.id, gift_id, gift_name, gift_cost, username)

    await message.answer(
        f"✅ So'rovingiz qabul qilindi!\n\n"
        f"🎁 {gift_name} — {gift_cost} ⭐\n"
        f"📩 Yuboriladigan akkaunt: {username}\n\n"
        f"Admin tasdiqlagach, sizga xabar beriladi.",
        reply_markup=main_menu_keyboard(message.from_user.id),
    )

    user_info = message.from_user
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
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(stars),0) FROM users")
        total_users, total_stars = await cur.fetchone()
        cur2 = await db.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
        pending = (await cur2.fetchone())[0]
        cur3 = await db.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved'")
        approved = (await cur3.fetchone())[0]
    reward = await get_setting("reward_stars", str(DEFAULT_REWARD_STARS))
    channels = await get_channels()
    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"⭐ Jami stars balansi: {total_stars}\n"
        f"⏳ Kutilayotgan so'rovlar: {pending}\n"
        f"✅ Tasdiqlangan yechishlar: {approved}\n"
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
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat musbat raqam yuboring.")
        return
    await set_setting("reward_stars", message.text)
    await state.clear()
    await message.answer(f"✅ Referal narxi {message.text} ⭐ ga o'zgartirildi.")


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
    _, username, stars, referrer_id, referrals_count, subscribed, referral_credited, banned = user
    status = "🚫 Bloklangan" if banned else "✅ Faol"
    return (
        f"👤 <b>Foydalanuvchi ma'lumoti</b>\n\n"
        f"🆔 ID: <code>{user[0]}</code>\n"
        f"👤 Username: @{username or '—'}\n"
        f"⭐ Balans: {stars}\n"
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
