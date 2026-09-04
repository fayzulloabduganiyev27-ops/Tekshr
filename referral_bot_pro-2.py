"""
IDEAL REFERAL BOT — admin panel (/panel) bilan

O'rnatish:
    pip install aiogram aiosqlite python-dotenv

.env fayl:
    BOT_TOKEN=1234567890:ABCDEF...
    BOT_USERNAME=your_bot_username
    ADMIN_IDS=123456789,987654321
    REWARD_STARS=10          # boshlang'ich qiymat (keyin /panel orqali o'zgartiriladi)
    GIFT_THRESHOLD=100       # boshlang'ich qiymat (keyin /panel orqali o'zgartiriladi)
    GIFT_ID=                 # ixtiyoriy
    REQUIRED_CHANNEL=        # ixtiyoriy

Ishga tushirish:
    python referral_bot_pro.py

FOYDALANUVCHI BUYRUQLARI:
    /start, /balance, /referal, /top

ADMIN BUYRUQLARI:
    /panel — tugmali admin panel (statistika, ball qo'shish, sozlamalarni o'zgartirish)
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
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv()

# ----------------- SOZLAMALAR -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot_username")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
GIFT_ID = os.getenv("GIFT_ID", "")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "")
DB_PATH = "referral_bot.db"

DEFAULT_REWARD_STARS = int(os.getenv("REWARD_STARS", "10"))
DEFAULT_GIFT_THRESHOLD = int(os.getenv("GIFT_THRESHOLD", "100"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("referral_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())


# ----------------- FSM HOLATLARI (admin kiritish uchun) -----------------
class AdminStates(StatesGroup):
    waiting_addstars_id = State()
    waiting_addstars_amount = State()
    waiting_reward_value = State()
    waiting_gift_threshold_value = State()
    waiting_broadcast_text = State()


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
                gift_sent INTEGER DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('reward_stars', ?)",
            (str(DEFAULT_REWARD_STARS),),
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('gift_threshold', ?)",
            (str(DEFAULT_GIFT_THRESHOLD),),
        )
        await db.commit()


async def get_setting(key: str, default: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return int(row[0]) if row else default


async def set_setting(key: str, value: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
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


async def add_stars(user_id: int, amount: int, count_referral: bool = True) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if count_referral:
            await db.execute(
                "UPDATE users SET stars = stars + ?, referrals_count = referrals_count + 1 WHERE user_id = ?",
                (amount, user_id),
            )
        else:
            await db.execute(
                "UPDATE users SET stars = stars + ? WHERE user_id = ?",
                (amount, user_id),
            )
        await db.commit()
        cur = await db.execute("SELECT stars FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def mark_gift_sent(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET gift_sent = 1 WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_top_users(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT username, stars, referrals_count FROM users ORDER BY stars DESC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(stars),0) FROM users")
        return await cur.fetchone()


async def get_all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ----------------- YORDAMCHI FUNKSIYALAR -----------------
async def is_subscribed(user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    with suppress(Exception):
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status not in ("left", "kicked")
    return False


async def try_send_gift(user_id: int, stars_balance: int, user_row) -> None:
    threshold = await get_setting("gift_threshold", DEFAULT_GIFT_THRESHOLD)
    if not GIFT_ID or stars_balance < threshold or user_row[5] == 1:
        return
    try:
        await bot.send_gift(chat_id=user_id, gift_id=GIFT_ID)
        await mark_gift_sent(user_id)
        await bot.send_message(
            user_id,
            f"🎁 Tabriklaymiz! Siz {threshold} ⭐ ballga yetdingiz va sizga "
            f"haqiqiy Telegram sovg'asi yuborildi!",
        )
    except Exception as e:
        log.warning(f"Gift yuborishda xatolik (user {user_id}): {e}")


# ----------------- ADMIN PANEL KLAVIATURASI -----------------
def panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika", callback_data="panel_stats")],
            [InlineKeyboardButton(text="🏆 Top foydalanuvchilar", callback_data="panel_top")],
            [InlineKeyboardButton(text="⭐ Foydalanuvchiga ball qo'shish", callback_data="panel_addstars")],
            [InlineKeyboardButton(text="⚙️ Referal mukofotini o'zgartirish", callback_data="panel_setreward")],
            [InlineKeyboardButton(text="🎁 Gift chegarasini o'zgartirish", callback_data="panel_setgift")],
            [InlineKeyboardButton(text="📢 Hammaga xabar yuborish", callback_data="panel_broadcast")],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Ortga", callback_data="panel_back")]]
    )


# ----------------- FOYDALANUVCHI HANDLERLARI -----------------
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

    is_new = await create_user(user_id, username, referrer_id)
    reward = await get_setting("reward_stars", DEFAULT_REWARD_STARS)
    threshold = await get_setting("gift_threshold", DEFAULT_GIFT_THRESHOLD)

    if is_new and referrer_id:
        referrer = await get_user(referrer_id)
        if referrer and await is_subscribed(user_id):
            new_balance = await add_stars(referrer_id, reward)
            updated_referrer = await get_user(referrer_id)
            with suppress(Exception):
                await bot.send_message(
                    referrer_id,
                    f"🎉 Yangi referal qo'shildi!\n"
                    f"+{reward} ⭐ | Jami balans: <b>{new_balance}</b> ⭐",
                )
            await try_send_gift(referrer_id, new_balance, updated_referrer)
        elif referrer and REQUIRED_CHANNEL:
            with suppress(Exception):
                await bot.send_message(
                    referrer_id,
                    "⚠️ Sizning referalingiz kanalga obuna bo'lmagani uchun hozircha hisoblanmadi.",
                )

    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    extra = f"\n\n📢 Botdan foydalanish uchun avval {REQUIRED_CHANNEL} kanaliga obuna bo'ling." if REQUIRED_CHANNEL else ""
    await message.answer(
        f"Salom, {message.from_user.full_name}! 👋\n\n"
        f"Do'stlaringizni taklif qiling — har bir referal uchun {reward} ⭐ stars, "
        f"{threshold} ⭐ to'plasangiz haqiqiy Telegram sovg'asi olasiz!\n\n"
        f"🔗 Sizning referal havolangiz:\n<code>{ref_link}</code>{extra}\n\n"
        f"/balance — balansni ko'rish\n/top — reyting"
    )


@dp.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Iltimos, avval /start buyrug'ini yuboring.")
        return
    threshold = await get_setting("gift_threshold", DEFAULT_GIFT_THRESHOLD)
    await message.answer(
        f"⭐ Balansingiz: <b>{user[2]}</b> stars\n"
        f"👥 Jami referallar: <b>{user[4]}</b> ta\n"
        f"🎁 Gift chegarasi: {threshold} ⭐ ({'olingan ✅' if user[5] else 'hali yo‘q'})"
    )


@dp.message(Command("referal"))
async def referal_handler(message: Message) -> None:
    ref_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"
    await message.answer(f"🔗 Sizning referal havolangiz:\n<code>{ref_link}</code>")


@dp.message(Command("top"))
async def top_handler(message: Message) -> None:
    top = await get_top_users()
    if not top:
        await message.answer("Hozircha reytingda hech kim yo'q.")
        return
    text = "🏆 <b>Top foydalanuvchilar:</b>\n\n"
    for i, (username, stars, referrals) in enumerate(top, start=1):
        text += f"{i}. {username or 'Foydalanuvchi'} — {stars} ⭐ ({referrals} referal)\n"
    await message.answer(text)


# ----------------- ADMIN PANEL -----------------
@dp.message(Command("panel"))
async def panel_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("⚙️ <b>Admin panel</b>\n\nKerakli bo'limni tanlang:", reply_markup=panel_keyboard())


@dp.callback_query(F.data == "panel_back")
async def panel_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("⚙️ <b>Admin panel</b>\n\nKerakli bo'limni tanlang:", reply_markup=panel_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "panel_stats")
async def panel_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    total_users, total_stars = await get_stats()
    reward = await get_setting("reward_stars", DEFAULT_REWARD_STARS)
    threshold = await get_setting("gift_threshold", DEFAULT_GIFT_THRESHOLD)
    await callback.message.edit_text(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"⭐ Jami taqsimlangan stars: {total_stars}\n"
        f"🎯 Joriy referal mukofoti: {reward} ⭐\n"
        f"🎁 Joriy gift chegarasi: {threshold} ⭐",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "panel_top")
async def panel_top(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    top = await get_top_users()
    text = "🏆 <b>Top foydalanuvchilar:</b>\n\n"
    if not top:
        text += "Hozircha hech kim yo'q."
    else:
        for i, (username, stars, referrals) in enumerate(top, start=1):
            text += f"{i}. {username or 'Foydalanuvchi'} — {stars} ⭐ ({referrals} referal)\n"
    await callback.message.edit_text(text, reply_markup=back_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "panel_addstars")
async def panel_addstars(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_addstars_id)
    await callback.message.edit_text(
        "⭐ Ball qo'shmoqchi bo'lgan foydalanuvchining <b>Telegram ID</b> raqamini yuboring:",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_addstars_id)
async def addstars_get_id(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat raqam yuboring (Telegram ID).")
        return
    target_id = int(message.text)
    if not await get_user(target_id):
        await message.answer("Bunday foydalanuvchi bazada topilmadi. Qaytadan ID yuboring yoki /panel bilan qaytadan boshlang.")
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.waiting_addstars_amount)
    await message.answer("Endi qo'shmoqchi bo'lgan ⭐ miqdorini yuboring (masalan: 50, kamaytirish uchun -50):")


@dp.message(AdminStates.waiting_addstars_amount)
async def addstars_get_amount(message: Message, state: FSMContext) -> None:
    if not message.text.lstrip("-").isdigit():
        await message.answer("Iltimos, faqat raqam yuboring.")
        return
    amount = int(message.text)
    data = await state.get_data()
    target_id = data["target_id"]
    new_balance = await add_stars(target_id, amount, count_referral=False)
    await state.clear()
    await message.answer(
        f"✅ {target_id} foydalanuvchiga {amount} ⭐ qo'shildi.\nYangi balans: <b>{new_balance}</b> ⭐",
        reply_markup=panel_keyboard(),
    )
    with suppress(Exception):
        await bot.send_message(target_id, f"⭐ Balansingizga {amount} ⭐ qo'shildi! Yangi balans: {new_balance} ⭐")


@dp.callback_query(F.data == "panel_setreward")
async def panel_setreward(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    current = await get_setting("reward_stars", DEFAULT_REWARD_STARS)
    await state.set_state(AdminStates.waiting_reward_value)
    await callback.message.edit_text(
        f"⚙️ Joriy referal mukofoti: <b>{current} ⭐</b>\n\nYangi qiymatni yuboring (faqat raqam):",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_reward_value)
async def setreward_get_value(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat musbat raqam yuboring.")
        return
    value = int(message.text)
    await set_setting("reward_stars", value)
    await state.clear()
    await message.answer(f"✅ Referal mukofoti {value} ⭐ ga o'zgartirildi.", reply_markup=panel_keyboard())


@dp.callback_query(F.data == "panel_setgift")
async def panel_setgift(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    current = await get_setting("gift_threshold", DEFAULT_GIFT_THRESHOLD)
    await state.set_state(AdminStates.waiting_gift_threshold_value)
    await callback.message.edit_text(
        f"🎁 Joriy gift chegarasi: <b>{current} ⭐</b>\n\nYangi qiymatni yuboring (faqat raqam):",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_gift_threshold_value)
async def setgift_get_value(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat musbat raqam yuboring.")
        return
    value = int(message.text)
    await set_setting("gift_threshold", value)
    await state.clear()
    await message.answer(f"✅ Gift chegarasi {value} ⭐ ga o'zgartirildi.", reply_markup=panel_keyboard())


@dp.callback_query(F.data == "panel_broadcast")
async def panel_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_broadcast_text)
    await callback.message.edit_text(
        "📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabar matnini yuboring:",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_broadcast_text)
async def broadcast_send(message: Message, state: FSMContext) -> None:
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
    await message.answer("Admin panelga qaytish:", reply_markup=panel_keyboard())


# ----------------- ISHGA TUSHIRISH -----------------
async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env yoki Railway Variables'ga qo'shing.")
    await init_db()
    log.info("Bot ishga tushdi.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
