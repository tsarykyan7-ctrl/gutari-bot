import asyncio
import csv
import io
import os
import random
import sqlite3
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_URL = os.getenv("SHEET_URL", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB_PATH = "gutar.db"

# Постепенное введение в язык: Урок 1 (Самые азы) и Урок 2 (Базовый разговор)
DEFAULT_LESSONS = [
    # УРОК 1: Приветствия, прощания и базовые реакции
    ("1. Первые слова", 1, "Здорово дневали!", "ЗдарОво дневали! (Традиционное казачье приветствие)", "Здравствуйте! / Привет!", "До свидания!; Спасибо!; Как дела?", ""),
    ("1. Первые слова", 1, "Слава Богу!", "СлАва БOгу! (Обычный ответ на приветствие «Здорово дневали!»)", "Привет! (ответ на приветствие)", "Прощай!; Не за что!; Пойдем!", ""),
    ("1. Первые слова", 1, "Ага / Да-то", "АгА / Да-тO (Твердое и уверенное согласие)", "Да / Конечно", "Нет; Не знаю; Может быть", ""),
    ("1. Первые слова", 1, "Не / Нѣма", "Не / НямА (Короткое «нет» и «нету»)", "Нет / Нету", "Да; Хорошо; Конечно", ""),
    ("1. Первые слова", 1, "Дóбрѣ", "дОбре (Ударение на О, на конце мягкое «е»)", "Хорошо / Ладно", "Плохо; Быстро; Далеко", ""),
    ("1. Первые слова", 1, "Спасінїя табе!", "СпасИния табЕ! (Вместо «спасибо», которое считается невежливым)", "Спасибо тебе!", "Извини меня; Прощай; Помоги мне", ""),
    ("1. Первые слова", 1, "Прощавай!", "ПращавАй! (Теплое прощание при расставании)", "Прощай! / До свидания!", "Здравствуй!; Садись!; Подойди!", ""),
    ("1. Первые слова", 1, "Бывай здоров!", "БывАй здарОф! (Пожелание здоровья на прощание)", "Будь здоров! / Пока!", "Доброе утро!; Приятного аппетита!; С праздником!", ""),

    # УРОК 2: Простые вопросы и общение (по учебнику Бублеёва)
    ("2. Живой разговор", 2, "Як діла?", "Як дилА? (Мягкое «я», четкое «и»)", "Как дела?", "Куда идешь?; Кто это?; Который час?", ""),
    ("2. Живой разговор", 2, "Иде ж ѝдєтѣ?", "ИдЕ ж йыдЁте? («Куды» говорить нельзя — дурная примета)", "Куда же идёте?", "Откуда идете?; Что делаете?; Где ты был?", ""),
    ("2. Живой разговор", 2, "Чѣво деїтѣ?", "ЧавО дЕйите? (Четкое окончание «-те»)", "Что делаете?", "Чего хотите?; О чем говорите?; Куда идете?", ""),
    ("2. Живой разговор", 2, "Каторай чяс?", "КатОрай час? (Правильный вопрос о времени)", "Который час?", "Какой сегодня день?; Сколько стоит?; Где это?", ""),
    ("2. Живой разговор", 2, "Чо грѣбтеть?", "Чо грябтЕть? (Мягкое «ть» на конце)", "Чего желаете? / Что хотите?", "Что случилось?; Кого ждете?; Куда спешите?", ""),
    ("2. Живой разговор", 2, "Ахалоньсі!", "АхалОньси! (Окончание «-си» вместо русского «-ся»)", "Остынь! / Успокойся!", "Просыпайся!; Поторопись!; Собирайся!", ""),
]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            xp INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT,
            lesson INTEGER,
            gutar TEXT,
            pronunciation TEXT,
            translation TEXT,
            wrong_options TEXT,
            audio_id TEXT
        )
    """)
    cur.execute("SELECT COUNT(*) FROM phrases")
    if cur.fetchone() == 0:
        cur.executemany(
            "INSERT INTO phrases (module, lesson, gutar, pronunciation, translation, wrong_options, audio_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            DEFAULT_LESSONS,
        )
    conn.commit()
    conn.close()


def get_rank(xp: int) -> str:
    if xp < 100:
        return "🗡 Джура (Ученик)"
    elif xp < 300:
        return "🛡 Приказный"
    elif xp < 700:
        return "⚔️ Урядник"
    elif xp < 1500:
        return "🎖 Хорунжий"
    return "👑 Есаул"


def add_xp(user_id: int, username: str, points: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, xp) VALUES (?, ?, 0)", (user_id, username))
    if username:
        cur.execute("UPDATE users SET xp = xp + ?, username = ? WHERE user_id = ?", (points, username, user_id))
    else:
        cur.execute("UPDATE users SET xp = xp + ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()


async def sync_google_sheet() -> str:
    if not SHEET_URL:
        return "Ссылка на Google Таблицу пока не добавлена. Работаю на базовых уроках из учебника."
    try:
        sheet_id = SHEET_URL.split("/d/").split("/")
        csv_url = f"https://google.com{sheet_id}/export?format=csv"
        async with aiohttp.ClientSession() as session:
            async with session.get(csv_url) as resp:
                if resp.status != 200:
                    return "Не удалось скачать таблицу. Проверь, открыт ли доступ по ссылке!"
                text = await resp.text()
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)[1:]
        valid_rows = []
        for r in rows:
            if len(r) >= 5 and r.strip() and r.strip():
                module = r.strip() or "Общий модуль"
                lesson = int(r.strip()) if r.strip().isdigit() else 1
                gutar = r.strip()
                pron = r.strip() if len(r) > 3 else ""
                trans = r.strip()
                wrong = r.strip() if len(r) > 5 else ""
                audio = r.strip() if len(r) > 6 else ""
                valid_rows.append((module, lesson, gutar, pron, trans, wrong, audio))
        if not valid_rows:
            return "В таблице пока нет заполненных строк."
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM phrases")
        cur.executemany(
            "INSERT INTO phrases (module, lesson, gutar, pronunciation, translation, wrong_options, audio_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            valid_rows,
        )
        conn.commit()
        conn.close()
        return f"✅ База успешно обновлена! Загружено фраз: {len(valid_rows)}"
    except Exception as e:
        return f"Ошибка при обновлении: {e}"


class LessonState(StatesGroup):
    studying = State()
    quiz = State()


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 Учить гутар"), KeyboardButton(text="📖 Словарь")],
            [KeyboardButton(text="🏆 Мой чин и рейтинг"), KeyboardButton(text="ℹ️ О языке")],
        ],
        resize_keyboard=True,
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    add_xp(message.from_user.id, message.from_user.username or message.from_user.first_name, 0)
    await message.answer(
        "Здорово дневали! 🐎\n\n"
        "Добро пожаловать в тренажер казачьего языка — **Гутар**.\n"
        "Начнем с самого простого: приветствия, прощания и живые фразы для общения.\n\n"
        "💡 *Совет:* в любой момент просто напиши слово в чат, и я переведу его!",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )


@router.message(Command("sync"))
async def cmd_sync(message: Message):
    msg = await message.answer("⏳ Синхронизирую базу с Google Таблицей...")
    res = await sync_google_sheet()
    await msg.edit_text(res)


@router.voice()
async def get_voice_id(message: Message):
    await message.reply(
        f"🎙 **Код этого голосового (вставь в столбец Аудио_ID):**\n`{message.voice.file_id}`",
        parse_mode="Markdown",
    )


@router.message(F.text == "ℹ️ О языке")
async def about_lang(message: Message):
    await message.answer(
        "📜 **Казачий гутар** — самобытный язык казачьего народа с богатой фонетикой и речевым этикетом.\n\n"
        "**Как устроено обучение:**\n"
        "1️⃣ Сначала ты разбираешь простые фразы и правильное произношение.\n"
        "2️⃣ Затем закрепляешь их в быстром тесте.\n"
        "3️⃣ За правильные ответы получаешь очки и растешь в казачьих чинах от *Джуры* до *Есаула*.",
        parse_mode="Markdown",
    )


@router.message(F.text == "🏆 Мой чин и рейтинг")
async def my_profile(message: Message):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT xp FROM users WHERE user_id = ?", (message.from_user.id,))
    row = cur.fetchone()
    xp = row if row else 0
    cur.execute("SELECT username, xp FROM users ORDER BY xp DESC LIMIT 5")
    top = cur.fetchall()
    conn.close()

    top_text = "\n".join([f"{i+1}. {u or 'Казак'} — {u} очков" for i, u in enumerate(top)])
    await message.answer(
        f"👤 **Твой профиль**\n"
        f"Чин: **{get_rank(xp)}**\n"
        f"Очки опыта: **{xp}**\n\n"
        f"🔥 **Топ-5 учеников:**\n{top_text}",
        parse_mode="Markdown",
    )


@router.message(F.text == "📖 Словарь")
async def dict_info(message: Message):
    await message.answer("🔍 Просто напиши мне любое слово или фразу на русском или гутаре, и я найду её в базе!")


@router.message(F.text == "🎯 Учить гутар")
async def choose_lesson(message: Message):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT lesson, module FROM phrases ORDER BY lesson")
    lessons = cur.fetchall()
    conn.close()

    buttons = []
    for l_num, mod in lessons:
        buttons.append([InlineKeyboardButton(text=f"Урок {l_num}: {mod}", callback_data=f"start_lesson_{l_num}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("📚 Выбери урок для тренировки:", reply_markup=kb)


@router.callback_query(F.data.startswith("start_lesson_"))
async def start_lesson(call: CallbackQuery, state: FSMContext):
