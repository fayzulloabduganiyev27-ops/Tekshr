"""
UZB STARS BOT — referal orqali stars ishlash, gift yechish, admin tasdiqlash tizimi

O'rnatish:
    pip install aiogram aiosqlite python-dotenv

.env fayl:
    BOT_TOKEN=1234567890:ABCDEF...
    BOT_USERNAME=your_bot_username
    ADMIN_IDS=123456789,987654321
    REQUIRED_CHANNELS=@forum_savdouzzz,@Sombot_otzff,@sevgi_haqida_sherLar
    PAYMENT_CHANNEL=@your_payment_channel
    ADMIN_CONTACT_ID=123456789
    REWARD_STARS=10

Ishga tushirish:
    python uzb_stars_bot.py
"""

import asyncio
import logging
import os
from contextlib import suppress

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
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
REQUIRED_CHANNELS = [c.strip() for c in os.getenv("REQUIRED_CHANNELS", "").split(",") if c.strip()]
PAYMENT_CHANNEL = os.getenv("PAYMENT_CHANNEL", "")
ADMIN_CONTACT_ID = int(os.getenv("ADMIN_CONTACT_ID", "0")) if os.getenv("ADMIN_CONTACT_ID", "").isdigit() else 0
REWARD_STARS = int(os.getenv("REWARD_STARS", "10"))
DB_PATH = "uzb_stars_bot.db"

# Gift/sticker katalogi — narxlarni shu yerda o'zgartirishingiz mumkin
GIFTS = [
    {"id": "gift1", "name": "🧸 Teddy Bear", "cost": 50},
    {"id": "gift2", "name": "💝 Heart", "cost": 100},
    {"id": "gift3", "name": "🌹 Rose", "cost": 150},
    {"id": "gift4", "name": "🎂 Cake", "cost": 200},
    {"id": "gift5", "name": "💎 Diamond", "cost": 500},
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("uzb_stars_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())


# ----------------- FSM HOLATLARI -----------------
class UserStates(StatesGroup):
    waiting_admin_message = State()


# ----------------- DATABASE -----------------
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
                referral_credited INTEGER DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_id TEXT,
                gift_name TEXT,
                gift_cost INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
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


async def create_withdrawal(user_id: int, gift: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO withdrawals (user_id, gift_id, gift_name, gift_cost) VALUES (?, ?, ?, ?)",
            (user_id, gift["id"], gift["name"], gift["cost"]),
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


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ----------------- KLAVIATURALAR -----------------
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Stars Ishlash")],
            [KeyboardButton(text="💰 Balans"), KeyboardButton(text="💸 Stars yechish")],
            [KeyboardButton(text="📢 To'lov kanali"), KeyboardButton(text="👨‍💻 Admin bilan bog'lanish")],
        ],
        resize_keyboard=True,
    )


def channels_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for ch in REQUIRED_CHANNELS:
        clean = ch.lstrip("@")
        buttons.append([InlineKeyboardButton(text=f"📢 {ch}", url=f"https://t.me/{clean}")])
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def gifts_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"{g['name']} — {g['cost']} ⭐", callback_data=f"gift_{g['id']}")]
        for g in GIFTS
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


# ----------------- OBUNA TEKSHIRUV -----------------
async def check_all_subscriptions(user_id: int) -> bool:
    if not REQUIRED_CHANNELS:
        return True
    for ch in REQUIRED_CHANNELS:
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
        reply_markup=channels_keyboard(),
    )


async def send_welcome(chat_id: int, full_name: str) -> None:
    await bot.send_message(
        chat_id,
        f"Assalomu alaykum, {full_name}! 👋\n\n"
        f"Botimizga xush kelibsiz!\n\n"
        f"Bu bot orqali siz Telegram <b>STARS</b> ishlab olishingiz mumkin ⭐",
        reply_markup=main_menu_keyboard(),
    )


# ----------------- HANDLERLAR -----------------
@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name

    args = message.text.split(maxsplit=1)
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        candidate = int(args[1])
        if candidate != user_id:
            referrer_id = candidate

    await create_user(user_id, username, referrer_id)

    if not await check_all_subscriptions(user_id):
        await send_subscription_prompt(message.chat.id)
        return

    await mark_subscribed(user_id)
    await credit_referral_if_needed(user_id)
    await send_welcome(message.chat.id, message.from_user.full_name)


async def credit_referral_if_needed(user_id: int) -> None:
    user = await get_user(user_id)
    if not user or user[3] is None or user[6] == 1:  # referrer_id yo'q yoki allaqachon hisoblangan
        return
    referrer_id = user[3]
    referrer = await get_user(referrer_id)
    if not referrer:
        return
    new_balance = await add_stars(referrer_id, REWARD_STARS, count_referral=True)
    await mark_referral_credited(user_id)
    with suppress(Exception):
        await bot.send_message(
            referrer_id,
            f"🎉 Yangi referal qo'shildi!\n+{REWARD_STARS} ⭐ | Jami balans: <b>{new_balance}</b> ⭐",
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

    await send_welcome(callback.message.chat.id, callback.from_user.full_name)
    await callback.answer()


# ----------------- ASOSIY MENYU TUGMALARI -----------------
@dp.message(F.text == "⭐ Stars Ishlash")
async def stars_ishlash_handler(message: Message) -> None:
    if not await check_all_subscriptions(message.from_user.id):
        await send_subscription_prompt(message.chat.id)
        return
    ref_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"
    await message.answer(
        f"⭐ <b>Stars ishlash</b>\n\n"
        f"Do'stlaringizni shu havola orqali botga taklif qiling — har bir yangi "
        f"foydalanuvchi uchun <b>{REWARD_STARS} ⭐</b> stars olasiz!\n\n"
        f"🔗 Sizning referal havolangiz:\n<code>{ref_link}</code>"
    )


@dp.message(F.text == "💰 Balans")
async def balans_handler(message: Message) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Iltimos, avval /start bosing.")
        return
    await message.answer(
        f"💰 <b>Balansingiz:</b> {user[2]} ⭐\n👥 <b>Jami referallar:</b> {user[4]} ta"
    )


@dp.message(F.text == "💸 Stars yechish")
async def stars_yechish_handler(message: Message) -> None:
    if not await check_all_subscriptions(message.from_user.id):
        await send_subscription_prompt(message.chat.id)
        return
    await message.answer(
        "💸 <b>Stars yechish</b>\n\nQuyidagi gift/sovg'alardan birini tanlang:",
        reply_markup=gifts_keyboard(),
    )


@dp.message(F.text == "📢 To'lov kanali")
async def tolov_kanali_handler(message: Message) -> None:
    if not PAYMENT_CHANNEL:
        await message.answer("To'lov kanali hozircha sozlanmagan.")
        return
    clean = PAYMENT_CHANNEL.lstrip("@")
    await message.answer(
        f"📢 To'lovlar tasdiqlangani haqida shu kanalda e'lon qilinadi:\nhttps://t.me/{clean}"
    )


@dp.message(F.text == "👨‍💻 Admin bilan bog'lanish")
async def admin_contact_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(UserStates.waiting_admin_message)
    await message.answer("✍️ Xabaringizni yozing, u adminga yuboriladi:")


@dp.message(UserStates.waiting_admin_message)
async def forward_to_admin(message: Message, state: FSMContext) -> None:
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


# ----------------- GIFT TANLASH -----------------
@dp.callback_query(F.data.startswith("gift_"))
async def gift_selected(callback: CallbackQuery) -> None:
    gift_id = callback.data.replace("gift_", "")
    gift = next((g for g in GIFTS if g["id"] == gift_id), None)
    if not gift:
        await callback.answer("Gift topilmadi.", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Xatolik yuz berdi.", show_alert=True)
        return

    if user[2] < gift["cost"]:
        await callback.answer(
            f"❌ Balansingiz yetarli emas! Kerak: {gift['cost']} ⭐, sizda: {user[2]} ⭐",
            show_alert=True,
        )
        return

    withdrawal_id = await create_withdrawal(callback.from_user.id, gift)

    await callback.message.edit_text(
        f"✅ So'rovingiz qabul qilindi!\n\n"
        f"🎁 {gift['name']} — {gift['cost']} ⭐\n\n"
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
                f"🎁 {gift['name']}\n"
                f"⭐ Narxi: {gift['cost']}\n"
                f"💰 Balansi: {user[2]} ⭐",
                reply_markup=admin_decision_keyboard(withdrawal_id),
            )


# ----------------- ADMIN: TASDIQLASH / RAD ETISH -----------------
@dp.callback_query(F.data.startswith("approve_"))
async def approve_withdrawal(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Sizga ruxsat yo'q.", show_alert=True)
        return

    withdrawal_id = int(callback.data.replace("approve_", ""))
    withdrawal = await get_withdrawal(withdrawal_id)
    if not withdrawal or withdrawal[5] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    _, user_id, gift_id, gift_name, gift_cost, status, _ = withdrawal
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
            f"✅ Tabriklaymiz! Sizning <b>{gift_name}</b> so'rovingiz tasdiqlandi va yuborildi! 🎉",
        )

    if PAYMENT_CHANNEL:
        username_display = f"@{callback.from_user.username}" if False else None
        user_obj = await bot.get_chat(user_id)
        display_name = f"@{user_obj.username}" if user_obj.username else user_obj.full_name
        with suppress(Exception):
            await bot.send_message(
                PAYMENT_CHANNEL,
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
    if not withdrawal or withdrawal[5] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    _, user_id, gift_id, gift_name, gift_cost, status, _ = withdrawal
    await update_withdrawal_status(withdrawal_id, "rejected")

    with suppress(Exception):
        await callback.message.edit_text(callback.message.text + "\n\n❌ RAD ETILDI")

    with suppress(Exception):
        await bot.send_message(user_id, f"❌ Afsuski, sizning <b>{gift_name}</b> so'rovingiz rad etildi.")

    await callback.answer("Rad etildi ❌")


# ----------------- ADMIN: STATISTIKA -----------------
@dp.message(Command("stats"))
async def stats_handler(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(stars),0) FROM users")
        total_users, total_stars = await cur.fetchone()
        cur2 = await db.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
        pending = (await cur2.fetchone())[0]
    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"⭐ Jami stars balansi: {total_stars}\n"
        f"⏳ Kutilayotgan so'rovlar: {pending}"
    )


# ----------------- ISHGA TUSHIRISH -----------------
async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env yoki Railway Variables'ga qo'shing.")
    await init_db()
    log.info("Bot ishga tushdi.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
