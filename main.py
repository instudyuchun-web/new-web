
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest


# ==================================================
# SOZLAMALAR
# ==================================================

BOT_TOKEN = "bot tokeni"

# Admin Telegram ID raqamlarini shu yerga yozing.
ADMIN_IDS = []

DB_NAME = "task_manager.db"
TZ = ZoneInfo("Asia/Tashkent")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


# ==================================================
# FSM HOLATLARI
# ==================================================

class TaskStates(StatesGroup):
    title = State()
    description = State()
    category = State()
    priority = State()
    due_date = State()
    edit_title = State()
    edit_description = State()
    search = State()


# ==================================================
# KLAVIATURALAR
# ==================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Vazifa qo‘shish"),
                KeyboardButton(text="📋 Vazifalarim")
            ],
            [
                KeyboardButton(text="📅 Bugungi reja"),
                KeyboardButton(text="📊 Statistika")
            ],
            [
                KeyboardButton(text="🔍 Qidirish"),
                KeyboardButton(text="📈 Haftalik hisobot")
            ],
            [
                KeyboardButton(text="❓ Yordam")
            ]
        ],
        resize_keyboard=True
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True
    )


def category_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📚 O‘qish"),
                KeyboardButton(text="💼 Ish")
            ],
            [
                KeyboardButton(text="👤 Shaxsiy"),
                KeyboardButton(text="🏠 Uy")
            ],
            [
                KeyboardButton(text="🎯 Boshqa"),
                KeyboardButton(text="❌ Bekor qilish")
            ]
        ],
        resize_keyboard=True
    )


def priority_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔴 Yuqori"),
                KeyboardButton(text="🟡 O‘rta")
            ],
            [
                KeyboardButton(text="🟢 Past"),
                KeyboardButton(text="❌ Bekor qilish")
            ]
        ],
        resize_keyboard=True
    )


def skip_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⏭ O‘tkazib yuborish"),
                KeyboardButton(text="❌ Bekor qilish")
            ]
        ],
        resize_keyboard=True
    )


def task_keyboard(task_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Bajarildi",
                    callback_data=f"done:{task_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Tahrirlash",
                    callback_data=f"edit:{task_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 O‘chirish",
                    callback_data=f"delete:{task_id}"
                )
            ]
        ]
    )


# ==================================================
# MA'LUMOTLAR BAZASI
# ==================================================

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'Boshqa',
                priority TEXT DEFAULT 'O‘rta',
                due_date TEXT,
                status TEXT DEFAULT 'pending',
                reminder_sent INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TEXT
            )
        """)

        await db.commit()


async def register_user(user):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users
            (user_id, username, full_name, joined_at)
            VALUES (
                ?,
                ?,
                ?,
                COALESCE(
                    (SELECT joined_at FROM users WHERE user_id = ?),
                    ?
                )
            )
        """, (
            user.id,
            user.username or "",
            user.full_name,
            user.id,
            datetime.now(TZ).isoformat()
        ))
        await db.commit()


async def create_task(user_id, data):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO tasks (
                user_id, title, description, category,
                priority, due_date, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            data["title"],
            data.get("description", ""),
            data.get("category", "Boshqa"),
            data.get("priority", "O‘rta"),
            data.get("due_date"),
            datetime.now(TZ).isoformat()
        ))
        await db.commit()


async def get_tasks(user_id, status=None):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        if status:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE user_id = ? AND status = ?
                ORDER BY
                    CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                    due_date ASC,
                    id DESC
            """, (user_id, status))
        else:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE user_id = ?
                ORDER BY id DESC
            """, (user_id,))

        return await cursor.fetchall()


async def get_task(task_id, user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("""
            SELECT * FROM tasks
            WHERE id = ? AND user_id = ?
        """, (task_id, user_id))

        return await cursor.fetchone()


async def update_task(task_id, user_id, field, value):
    allowed = ["title", "description"]

    if field not in allowed:
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            f"UPDATE tasks SET {field} = ? WHERE id = ? AND user_id = ?",
            (value, task_id, user_id)
        )
        await db.commit()


async def complete_task(task_id, user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE tasks SET status = 'completed'
            WHERE id = ? AND user_id = ?
        """, (task_id, user_id))
        await db.commit()


async def delete_task(task_id, user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            DELETE FROM tasks
            WHERE id = ? AND user_id = ?
        """, (task_id, user_id))
        await db.commit()


async def get_statistics(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT
                COUNT(*),
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)
            FROM tasks
            WHERE user_id = ?
        """, (user_id,))

        row = await cursor.fetchone()

        total = row[0] or 0
        completed = row[1] or 0
        pending = row[2] or 0

        percent = round(completed / total * 100) if total else 0

        return total, completed, pending, percent


# ==================================================
# YORDAMCHI FUNKSIYALAR
# ==================================================

def format_task(task):
    priority_icons = {
        "Yuqori": "🔴",
        "O‘rta": "🟡",
        "Past": "🟢"
    }

    status = (
        "✅ Bajarilgan"
        if task["status"] == "completed"
        else "⏳ Kutilmoqda"
    )

    due = "Belgilanmagan"

    if task["due_date"]:
        try:
            due = datetime.fromisoformat(
                task["due_date"]
            ).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            due = task["due_date"]

    return (
        f"<b>{task['title']}</b>\n\n"
        f"📝 Tavsif: {task['description'] or 'Yo‘q'}\n"
        f"📂 Kategoriya: {task['category']}\n"
        f"⚡ Muhimlik: "
        f"{priority_icons.get(task['priority'], '🟡')} "
        f"{task['priority']}\n"
        f"🕒 Muddat: {due}\n"
        f"📌 Holat: {status}\n"
        f"🆔 ID: <code>{task['id']}</code>"
    )


def parse_date(value):
    try:
        date = datetime.strptime(
            value, "%Y-%m-%d %H:%M"
        )
        return date.replace(tzinfo=TZ)
    except ValueError:
        return None


async def cancel_process(message, state):
    await state.clear()
    await message.answer(
        "❌ Jarayon bekor qilindi.",
        reply_markup=main_keyboard()
    )


# ==================================================
# START
# ==================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await register_user(message.from_user)

    text = (
        "👋 <b>Task Manager Bot'ga xush kelibsiz!</b>\n\n"
        "Bu bot orqali kundalik vazifalaringizni "
        "oson boshqarishingiz mumkin.\n\n"
        "🚀 <b>Imkoniyatlar:</b>\n"
        "➕ Vazifalar yaratish\n"
        "📅 Kunlik rejalarni ko‘rish\n"
        "⏰ Eslatmalar olish\n"
        "📊 Statistikani kuzatish\n\n"
        "Quyidagi menyudan foydalaning:"
    )

    await message.answer(text, reply_markup=main_keyboard())


@dp.message(Command("help"))
@dp.message(F.text == "❓ Yordam")
async def help_command(message: Message):
    await message.answer(
        "<b>📖 Task Manager Bot qo‘llanmasi</b>\n\n"
        "/start — Botni boshlash\n"
        "/tasks — Vazifalarni ko‘rish\n"
        "/stats — Statistikani ko‘rish\n"
        "/cancel — Jarayonni bekor qilish\n\n"
        "Vazifa qo‘shish uchun ➕ tugmasini bosing.\n\n"
        "⏰ Eslatma formati:\n"
        "<code>2026-11-25 14:30</code>",
        reply_markup=main_keyboard()
    )


@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_command(message: Message, state: FSMContext):
    await cancel_process(message, state)


# ==================================================
# VAZIFA QO‘SHISH
# ==================================================

@dp.message(F.text == "➕ Vazifa qo‘shish")
async def add_task_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(TaskStates.title)

    await message.answer(
        "➕ <b>Yangi vazifa yaratish</b>\n\n"
        "Vazifa nomini kiriting:",
        reply_markup=cancel_keyboard()
    )


@dp.message(TaskStates.title)
async def add_title(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Matn kiriting.")

    if len(message.text) > 150:
        return await message.answer(
            "Vazifa nomi 150 ta belgidan oshmasin."
        )

    await state.update_data(title=message.text)
    await state.set_state(TaskStates.description)

    await message.answer(
        "📝 Vazifa haqida qisqacha ma'lumot kiriting.\n"
        "Agar kerak bo‘lmasa, o‘tkazib yuboring.",
        reply_markup=skip_keyboard()
    )


@dp.message(TaskStates.description)
async def add_description(message: Message, state: FSMContext):
    description = (
        "" if message.text == "⏭ O‘tkazib yuborish"
        else message.text
    )

    if description and len(description) > 1000:
        return await message.answer(
            "Tavsif 1000 ta belgidan oshmasin."
        )

    await state.update_data(description=description)
    await state.set_state(TaskStates.category)

    await message.answer(
        "📂 Vazifa kategoriyasini tanlang:",
        reply_markup=category_keyboard()
    )


@dp.message(TaskStates.category)
async def add_category(message: Message, state: FSMContext):
    categories = {
        "📚 O‘qish": "O‘qish",
        "💼 Ish": "Ish",
        "👤 Shaxsiy": "Shaxsiy",
        "🏠 Uy": "Uy",
        "🎯 Boshqa": "Boshqa"
    }

    if message.text not in categories:
        return await message.answer(
            "Iltimos, menyudan kategoriyani tanlang."
        )

    await state.update_data(category=categories[message.text])
    await state.set_state(TaskStates.priority)

    await message.answer(
        "⚡ Vazifaning muhimlik darajasini tanlang:",
        reply_markup=priority_keyboard()
    )


@dp.message(TaskStates.priority)
async def add_priority(message: Message, state: FSMContext):
    priorities = {
        "🔴 Yuqori": "Yuqori",
        "🟡 O‘rta": "O‘rta",
        "🟢 Past": "Past"
    }

    if message.text not in priorities:
        return await message.answer(
            "Iltimos, muhimlik darajasini tanlang."
        )

    await state.update_data(priority=priorities[message.text])
    await state.set_state(TaskStates.due_date)

    await message.answer(
        "⏰ Vazifa uchun eslatma vaqtini kiriting.\n\n"
        "Format: <code>2026-11-25 14:30</code>\n\n"
        "Eslatma kerak bo‘lmasa, o‘tkazib yuboring.",
        reply_markup=skip_keyboard()
    )


@dp.message(TaskStates.due_date)
async def add_due_date(message: Message, state: FSMContext):
    due_date = None

    if message.text != "⏭ O‘tkazib yuborish":
        due = parse_date(message.text)

        if not due:
            return await message.answer(
                "❌ Sana noto‘g‘ri!\n"
                "Masalan: <code>2026-11-25 14:30</code>"
            )

        if due <= datetime.now(TZ):
            return await message.answer(
                "❌ Kelajakdagi vaqtni kiriting."
            )

        due_date = due.isoformat()

    data = await state.get_data()
    data["due_date"] = due_date

    await create_task(message.from_user.id, data)
    await state.clear()

    await message.answer(
        "🎉 <b>Vazifa muvaffaqiyatli yaratildi!</b>\n\n"
        f"📌 {data['title']}\n"
        f"📂 {data['category']}\n"
        f"⚡ {data['priority']}\n\n"
        "Endi vazifangiz saqlandi.",
        reply_markup=main_keyboard()
    )


# ==================================================
# VAZIFALARNI KO‘RISH
# ==================================================

async def show_tasks(message: Message, user_id):
    tasks = await get_tasks(user_id)

    if not tasks:
        return await message.answer(
            "📭 Hozircha vazifalaringiz yo‘q.\n\n"
            "➕ Yangi vazifa qo‘shishingiz mumkin."
        )

    await message.answer(
        f"📋 <b>Vazifalaringiz: {len(tasks)} ta</b>"
    )

    for task in tasks[:30]:
        await message.answer(
            format_task(task),
            reply_markup=task_keyboard(task["id"])
        )

    if len(tasks) > 30:
        await message.answer(
            "Birinchi 30 ta vazifa ko‘rsatildi."
        )


@dp.message(F.text == "📋 Vazifalarim")
@dp.message(Command("tasks"))
async def tasks_command(message: Message):
    await show_tasks(message, message.from_user.id)


# ==================================================
# VAZIFA AMALLARI
# ==================================================

@dp.callback_query(F.data.startswith("done:"))
async def done_callback(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])

    task = await get_task(task_id, callback.from_user.id)

    if not task:
        return await callback.answer(
            "Vazifa topilmadi.",
            show_alert=True
        )

    await complete_task(task_id, callback.from_user.id)

    await callback.answer("Vazifa bajarildi! ✅")

    try:
        await callback.message.edit_text(
            format_task({
                **dict(task),
                "status": "completed"
            })
        )
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data.startswith("delete:"))
async def delete_callback(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])

    task = await get_task(task_id, callback.from_user.id)

    if not task:
        return await callback.answer(
            "Vazifa topilmadi.",
            show_alert=True
        )

    await delete_task(task_id, callback.from_user.id)

    await callback.answer("Vazifa o‘chirildi! 🗑")

    try:
        await callback.message.edit_text(
            "🗑 <b>Vazifa muvaffaqiyatli o‘chirildi.</b>"
        )
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data.startswith("edit:"))
async def edit_callback(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split(":")[1])

    task = await get_task(task_id, callback.from_user.id)

    if not task:
        return await callback.answer(
            "Vazifa topilmadi.",
            show_alert=True
        )

    await state.clear()
    await state.update_data(task_id=task_id)
    await state.set_state(TaskStates.edit_title)

    await callback.message.answer(
        f"✏️ Yangi nom kiriting.\n\n"
        f"Eski nom: {task['title']}",
        reply_markup=cancel_keyboard()
    )

    await callback.answer()


@dp.message(TaskStates.edit_title)
async def edit_title(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Yangi nom kiriting.")

    if len(message.text) > 150:
        return await message.answer("Nom juda uzun.")

    data = await state.get_data()

    await update_task(
        data["task_id"],
        message.from_user.id,
        "title",
        message.text
    )

    await state.clear()

    await message.answer(
        "✅ Vazifa nomi yangilandi!",
        reply_markup=main_keyboard()
    )


# ==================================================
# BUGUNGI REJA
# ==================================================

@dp.message(F.text == "📅 Bugungi reja")
async def today_plan(message: Message):
    tasks = await get_tasks(message.from_user.id)

    today = datetime.now(TZ).date()

    today_tasks = []

    for task in tasks:
        if task["due_date"]:
            try:
                due = datetime.fromisoformat(task["due_date"])
                if due.date() == today:
                    today_tasks.append(task)
            except ValueError:
                continue

    if not today_tasks:
        return await message.answer(
            "📅 <b>Bugungi reja</b>\n\n"
            "Bugun uchun belgilangan vazifalar yo‘q."
        )

    await message.answer(
        f"📅 <b>Bugungi vazifalar: {len(today_tasks)} ta</b>"
    )

    for task in today_tasks:
        await message.answer(
            format_task(task),
            reply_markup=task_keyboard(task["id"])
        )


# ==================================================
# STATISTIKA
# ==================================================

@dp.message(F.text == "📊 Statistika")
@dp.message(Command("stats"))
async def statistics(message: Message):
    total, completed, pending, percent = await get_statistics(
        message.from_user.id
    )

    progress = "🟩" * (percent // 10) + "⬜" * (10 - percent // 10)

    await message.answer(
        "📊 <b>SIZNING STATISTIKANGIZ</b>\n\n"
        f"📌 Jami vazifalar: <b>{total}</b>\n"
        f"✅ Bajarilgan: <b>{completed}</b>\n"
        f"⏳ Kutilayotgan: <b>{pending}</b>\n\n"
        f"📈 Natija: <b>{percent}%</b>\n"
        f"{progress}\n\n"
        "Har kuni yangi maqsadlar sari! 🚀"
    )


# ==================================================
# QIDIRUV
# ==================================================

@dp.message(F.text == "🔍 Qidirish")
async def search_start(message: Message, state: FSMContext):
    await state.set_state(TaskStates.search)

    await message.answer(
        "🔍 Qidirmoqchi bo‘lgan vazifa nomini yozing:",
        reply_markup=cancel_keyboard()
    )


@dp.message(TaskStates.search)
async def search_tasks(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Qidiruv so‘zini kiriting.")

    keyword = message.text.strip().lower()

    tasks = await get_tasks(message.from_user.id)

    results = [
        task for task in tasks
        if keyword in task["title"].lower()
        or keyword in task["description"].lower()
    ]

    await state.clear()

    if not results:
        return await message.answer(
            "🔎 Hech qanday vazifa topilmadi.",
            reply_markup=main_keyboard()
        )

    await message.answer(
        f"🔍 <b>{len(results)} ta natija topildi:</b>",
        reply_markup=main_keyboard()
    )

    for task in results[:20]:
        await message.answer(
            format_task(task),
            reply_markup=task_keyboard(task["id"])
        )


# ==================================================
# HAFTALIK HISOBOT
# ==================================================

@dp.message(F.text == "📈 Haftalik hisobot")
async def weekly_report(message: Message):
    tasks = await get_tasks(message.from_user.id)

    now = datetime.now(TZ)
    week_ago = now - timedelta(days=7)

    weekly = []

    for task in tasks:
        try:
            created = datetime.fromisoformat(task["created_at"])
            if created >= week_ago:
                weekly.append(task)
        except ValueError:
            continue

    completed = sum(
        1 for task in weekly
        if task["status"] == "completed"
    )

    total = len(weekly)
    percent = round(completed / total * 100) if total else 0

    await message.answer(
        "📈 <b>HAFTALIK HISOBOT</b>\n\n"
        f"📅 Oxirgi 7 kun\n"
        f"📌 Yaratilgan vazifalar: <b>{total}</b>\n"
        f"✅ Bajarilgan vazifalar: <b>{completed}</b>\n"
        f"⏳ Qolgan vazifalar: <b>{total - completed}</b>\n"
        f"📊 Bajarilish: <b>{percent}%</b>\n\n"
        "💪 Keyingi haftada yanada yaxshi natija!"
    )


# ==================================================
# ADMIN PANELI
# ==================================================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer(
            "⛔ Sizda admin huquqi yo‘q."
        )

    async with aiosqlite.connect(DB_NAME) as db:
        users = await (
            await db.execute("SELECT COUNT(*) FROM users")
        ).fetchone()

        tasks = await (
            await db.execute("SELECT COUNT(*) FROM tasks")
        ).fetchone()

        completed = await (
            await db.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'completed'"
            )
        ).fetchone()

    await message.answer(
        "🛡 <b>ADMIN PANEL</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users[0]}</b>\n"
        f"📋 Jami vazifalar: <b>{tasks[0]}</b>\n"
        f"✅ Bajarilgan: <b>{completed[0]}</b>"
    )


# ==================================================
# AVTOMATIK ESLATMALAR
# ==================================================

async def reminder_worker():
    while True:
        try:
            now = datetime.now(TZ)

            async with aiosqlite.connect(DB_NAME) as db:
                db.row_factory = aiosqlite.Row

                cursor = await db.execute("""
                    SELECT * FROM tasks
                    WHERE status = 'pending'
                    AND reminder_sent = 0
                    AND due_date IS NOT NULL
                """)

                tasks = await cursor.fetchall()

                for task in tasks:
                    due = datetime.fromisoformat(task["due_date"])

                    if due <= now:
                        try:
                            await bot.send_message(
                                task["user_id"],
                                "⏰ <b>VAZIFA ESLATMASI!</b>\n\n"
                                f"📌 {task['title']}\n"
                                f"📂 {task['category']}\n\n"
                                "Vazifangizni bajarishni unutmang! 💪"
                            )

                            await db.execute("""
                                UPDATE tasks
                                SET reminder_sent = 1
                                WHERE id = ?
                            """, (task["id"],))

                            await db.commit()

                        except TelegramForbiddenError:
                            logging.warning(
                                "Foydalanuvchi botni bloklagan: %s",
                                task["user_id"]
                            )

                            await db.execute("""
                                UPDATE tasks SET reminder_sent = 1
                                WHERE id = ?
                            """, (task["id"],))

                            await db.commit()

                        except Exception:
                            logging.exception(
                                "Eslatma yuborishda xatolik"
                            )

        except Exception:
            logging.exception("Reminder worker xatoligi")

        await asyncio.sleep(20)


# ==================================================
# BOTNI ISHGA TUSHIRISH
# ==================================================

async def main():
    if not BOT_TOKEN or BOT_TOKEN.startswith("BU_YERGA"):
        raise ValueError(
            "main.py ichidagi BOT_TOKEN maydoniga "
            "BotFather tokenini kiriting!"
        )

    await init_db()

    logging.info("Task Manager Bot ishga tushdi!")

    reminder_task = asyncio.create_task(reminder_worker())

    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()

        try:
            await reminder_task
        except asyncio.CancelledError:
            pass

        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to‘xtatildi.")
