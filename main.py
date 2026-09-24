import asyncio
import logging
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    Message,
    LabeledPrice,
    URLInputFile,
)

from aiohttp import web


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("Не найден REPLICATE_API_TOKEN")


os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


# ============================================================
# BOT
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# DATABASE
# ============================================================

DB_FILE = "bot.db"


def db():
    return sqlite3.connect(
        DB_FILE,
        timeout=30
    )


def init_db():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_used INTEGER DEFAULT 0,
            paid_credits INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            charge_id TEXT PRIMARY KEY,
            user_id INTEGER,
            credits INTEGER,
            stars INTEGER,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def ensure_user(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    exists = cur.fetchone()

    if not exists:

        cur.execute(
            """
            INSERT INTO users
            (user_id, free_used, paid_credits, created_at)
            VALUES (?, 0, 0, ?)
            """,
            (
                user_id,
                datetime.utcnow().isoformat()
            )
        )

        conn.commit()

    conn.close()


def get_balance(user_id):

    ensure_user(user_id)

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT free_used, paid_credits
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cur.fetchone()

    conn.close()

    free_used = row[0]
    paid = row[1]

    free_left = max(0, 2 - free_used)

    return free_left, paid


def reserve_generation(user_id):

    """
    Списываем одну генерацию ДО запуска AI.

    Это защищает от ситуации, когда пользователь
    одновременно запускает несколько генераций.
    """

    if user_id in ADMIN_IDS:
        return "admin"

    ensure_user(user_id)

    conn = db()
    cur = conn.cursor()

    try:

        cur.execute("BEGIN IMMEDIATE")

        cur.execute(
            """
            SELECT free_used, paid_credits
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        free_used, paid_credits = cur.fetchone()

        # Сначала используем бесплатные
        if free_used < 2:

            cur.execute(
                """
                UPDATE users
                SET free_used = free_used + 1
                WHERE user_id = ?
                """,
                (user_id,)
            )

            conn.commit()

            return "free"

        # Потом платные
        if paid_credits > 0:

            cur.execute(
                """
                UPDATE users
                SET paid_credits = paid_credits - 1
                WHERE user_id = ?
                """,
                (user_id,)
            )

            conn.commit()

            return "paid"

        conn.rollback()

        return None

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


def refund_generation(user_id, source):

    if source in (None, "admin"):
        return

    conn = db()
    cur = conn.cursor()

    if source == "free":

        cur.execute(
            """
            UPDATE users
            SET free_used = MAX(0, free_used - 1)
            WHERE user_id = ?
            """,
            (user_id,)
        )

    elif source == "paid":

        cur.execute(
            """
            UPDATE users
            SET paid_credits = paid_credits + 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

    conn.commit()
    conn.close()


def add_payment(
    user_id,
    charge_id,
    credits,
    stars
):

    ensure_user(user_id)

    conn = db()
    cur = conn.cursor()

    try:

        cur.execute("BEGIN IMMEDIATE")

        cur.execute(
            """
            SELECT charge_id
            FROM payments
            WHERE charge_id = ?
            """,
            (charge_id,)
        )

        if cur.fetchone():

            conn.rollback()

            return False

        cur.execute(
            """
            INSERT INTO payments
            (charge_id, user_id, credits, stars, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                charge_id,
                user_id,
                credits,
                stars,
                datetime.utcnow().isoformat()
            )
        )

        cur.execute(
            """
            UPDATE users
            SET paid_credits = paid_credits + ?
            WHERE user_id = ?
            """,
            (
                credits,
                user_id
            )
        )

        conn.commit()

        return True

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


# ============================================================
# USER PHOTOS
# ============================================================

pending_photos = {}

MAX_PHOTOS = 8


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


# ============================================================
# START
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):

    user_id = message.from_user.id

    ensure_user(user_id)

    if is_admin(user_id):

        await message.answer(
            "👑 Админский режим\n\n"
            "Безлимитные генерации.\n\n"
            "Отправь до 8 фотографий.\n"
            "После этого напиши обычным текстом, "
            "что нужно сделать."
        )

        return

    free_left, paid = get_balance(user_id)

    await message.answer(
        "🤖 AI PHOTO\n\n"
        "Я могу редактировать фотографии "
        "по обычному текстовому запросу.\n\n"

        f"🎁 Бесплатно осталось: {free_left}\n"
        f"⭐ Платных генераций: {paid}\n\n"

        "Как использовать:\n"
        "1️⃣ Отправь фото\n"
        "2️⃣ Можно отправить до 8 фото\n"
        "3️⃣ Напиши, что сделать\n"
        "4️⃣ Получи готовый результат\n\n"

        "Пример:\n"
        "«Поставь рядом со мной чёрный BMW M5 "
        "и сделай фотографию максимально реалистичной»\n\n"

        "Команды:\n"
        "/balance — баланс\n"
        "/buy — купить генерации\n"
        "/clear — удалить загруженные фото"
    )


# ============================================================
# BALANCE
# ============================================================

@dp.message(Command("balance"))
async def balance(message: Message):

    user_id = message.from_user.id

    free_left, paid = get_balance(user_id)

    await message.answer(
        "💳 Ваш баланс\n\n"
        f"🎁 Бесплатных: {free_left}\n"
        f"⭐ Платных: {paid}"
    )


# ============================================================
# CLEAR
# ============================================================

@dp.message(Command("clear"))
async def clear(message: Message):

    user_id = message.from_user.id

    pending_photos.pop(user_id, None)

    await message.answer(
        "🗑 Фото очищены.\n\n"
        "Можешь отправить новые фотографии."
    )


# ============================================================
# PHOTO
# ============================================================

@dp.message(F.photo)
async def handle_photo(message: Message):

    user_id = message.from_user.id

    ensure_user(user_id)

    if user_id not in pending_photos:

        pending_photos[user_id] = []

    photos = pending_photos[user_id]

    if len(photos) >= MAX_PHOTOS:

        await message.answer(
            "Можно использовать максимум "
            f"{MAX_PHOTOS} фотографий.\n\n"
            "Теперь напиши, что нужно сделать."
        )

        return

    file_id = message.photo[-1].file_id

    photos.append(file_id)

    count = len(photos)

    await message.answer(
        f"📸 Фото {count}/{MAX_PHOTOS} получено.\n\n"

        "Можешь отправить ещё фото "
        "или уже написать, что нужно сделать.\n\n"

        "Например:\n"
        "«Возьми меня с первого фото "
        "и помести на пляж со второго фото»"
    )


# ============================================================
# TEXT REQUEST
# ============================================================

@dp.message(F.text)
async def handle_text(message: Message):

    user_id = message.from_user.id

    if message.text.startswith("/"):

        return

    photos = pending_photos.get(user_id)

    if not photos:

        await message.answer(
            "Сначала отправь фотографию 📸\n\n"
            "После этого напиши, что с ней сделать."
        )

        return

    prompt = message.text.strip()

    pending_photos[user_id] = []

    await generate_image(
        message,
        photos,
        prompt,
        user_id
    )


# ============================================================
# PROMPT BUILDER
# ============================================================

def build_prompt(user_prompt, image_count):

    """
    Здесь мы НЕ заменяем запрос пользователя.

    Мы добавляем инструкции, чтобы модель лучше понимала:

    - что именно надо изменить;
    - что нельзя случайно менять;
    - как работать с несколькими фотографиями;
    - как сохранять лицо;
    - как добавлять новые объекты.
    """

    prompt = f"""
EDIT THE PROVIDED IMAGE(S) ACCORDING TO THE USER'S INSTRUCTION.

USER INSTRUCTION:
{user_prompt}

IMPORTANT EDITING RULES:

1. Follow the user's requested changes precisely.
2. Do not ignore a requested object, person, location,
   clothing change, background change, color change,
   body/detail change, removal, or addition.
3. If the user asks to ADD something, actually add it.
4. If the user asks to REMOVE something, actually remove it.
5. If the user asks to CHANGE something, change that specific thing.
6. Preserve everything that the user did not ask to change.
7. Keep the person's identity, facial structure, eyes, nose,
   mouth, skin texture, hairstyle and recognizable appearance
   consistent with the reference image whenever the person
   is meant to remain the same person.
8. Do not replace the person's face with a generic AI face.
9. Keep realistic anatomy, hands, fingers, proportions and perspective.
10. Match lighting, shadows, reflections, colors and camera perspective
    between the original image and newly added elements.
11. Make added objects look physically present in the scene.
12. The final image must look like a real photograph,
    not an illustration or obvious AI generation.
13. If multiple reference images are provided, use them according
    to the user's instruction and combine them naturally.
14. When the user says "я", "меня", "мой", or "мне",
    identify that person from the primary reference image.
15. When the user asks to place the person from one image
    into another scene, preserve the person's identity and
    realistically integrate them into the target scene.
16. Do not make unrelated changes.

REFERENCE IMAGE ORDER:
"""

    for i in range(image_count):

        if i == 0:

            prompt += (
                "\nImage 1 = PRIMARY IMAGE / PERSON / MAIN SUBJECT."
            )

        else:

            prompt += (
                f"\nImage {i + 1} = ADDITIONAL REFERENCE IMAGE. "
                "Use it according to the user's instruction."
            )

    prompt += """

FINAL REQUIREMENT:

Return one coherent, photorealistic final image that follows
the user's exact request.
"""

    return prompt.strip()


# ============================================================
# GET TELEGRAM FILE URL
# ============================================================

async def telegram_file_url(file_id):

    file = await bot.get_file(file_id)

    return (
        f"https://api.telegram.org/file/bot"
        f"{BOT_TOKEN}/{file.file_path}"
    )


# ============================================================
# GENERATION
# ============================================================

async def generate_image(
    message,
    photo_ids,
    user_prompt,
    user_id
):

    # --------------------------------------------------------
    # CHECK BALANCE
    # --------------------------------------------------------

    source = reserve_generation(user_id)

    if source is None:

        await message.answer(
            "❌ У тебя закончились генерации.\n\n"
            "🎁 Бесплатные: 0\n"
            "⭐ Купи пакет через /buy"
        )

        # Вернуть фотографии пользователю в ожидание
        pending_photos[user_id] = photo_ids

        return


    await message.answer(
        "⏳ Генерирую фотографию...\n\n"
        "Это может занять некоторое время."
    )


    try:

        # ----------------------------------------------------
        # TELEGRAM URLS
        # ----------------------------------------------------

        image_urls = []

        for file_id in photo_ids[:MAX_PHOTOS]:

            url = await telegram_file_url(file_id)

            image_urls.append(url)


        # ----------------------------------------------------
        # PROMPT
        # ----------------------------------------------------

        final_prompt = build_prompt(
            user_prompt,
            len(image_urls)
        )


        logging.info(
            "User %s requested generation with %s images: %s",
            user_id,
            len(image_urls),
            user_prompt
        )


        # ----------------------------------------------------
        # FLUX.2 MAX
        # ----------------------------------------------------

        output = await asyncio.to_thread(
            replicate.run,
            "black-forest-labs/flux-2-max",
            input={
                "prompt": final_prompt,

                "input_images": image_urls,

                # Сохраняем пропорции первого изображения
                "aspect_ratio": "match_input_image",

                # Хороший баланс качества/стоимости
                "resolution": "1 MP",

                # PNG для максимального качества
                "output_format": "png",

                "output_quality": 100,

                "safety_tolerance": 2
            }
        )


        # ----------------------------------------------------
        # GET RESULT URL
        # ----------------------------------------------------

        if output is None:

            raise RuntimeError(
                "Модель не вернула изображение."
            )


        if isinstance(output, list):

            result_url = str(output[0])

        elif hasattr(output, "url"):

            result_url = str(output.url)

        else:

            result_url = str(output)


        if not result_url.startswith("http"):

            raise RuntimeError(
                "Получен неправильный URL изображения."
            )


        # ----------------------------------------------------
        # SEND FULL QUALITY IMAGE
        # ----------------------------------------------------

        document = URLInputFile(
            result_url,
            filename="ai_photo.png"
        )


        await message.answer_document(
            document=document,
            caption=(
                "✅ Готово!\n\n"
                f"Ваш запрос:\n{user_prompt}"
            )
        )


        # ----------------------------------------------------
        # BALANCE
        # ----------------------------------------------------

        if not is_admin(user_id):

            free_left, paid = get_balance(user_id)

            await message.answer(
                "💳 Остаток:\n"
                f"🎁 Бесплатных: {free_left}\n"
                f"⭐ Платных: {paid}"
            )


    except Exception as e:

        logging.exception(
            "Generation error for user %s",
            user_id
        )

        # ----------------------------------------------------
        # REFUND
        # ----------------------------------------------------

        refund_generation(
            user_id,
            source
        )

        # Возвращаем фото в ожидание
        pending_photos[user_id] = photo_ids

        error_text = str(e)

        if len(error_text) > 1000:

            error_text = error_text[:1000]

        await message.answer(
            "❌ Не удалось создать изображение.\n\n"
            "Твоя генерация возвращена.\n\n"
            f"Ошибка:\n{error_text}"
        )


# ============================================================
# BUY
# ============================================================

@dp.message(Command("buy"))
async def buy(message: Message):

    await message.answer(
        "⭐ Пакеты AI-фото\n\n"
        "50 ⭐ → 5 фотографий\n"
        "100 ⭐ → 10 фотографий\n"
        "150 ⭐ → 15 фотографий\n\n"
        "Выбери пакет:"
    )

    await message.answer_invoice(
        title="AI Photo — 5 генераций",
        description="5 AI-фотографий",
        payload="buy_5_credits",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="5 AI-фото",
                amount=50
            )
        ]
    )

    await message.answer_invoice(
        title="AI Photo — 10 генераций",
        description="10 AI-фотографий",
        payload="buy_10_credits",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="10 AI-фото",
                amount=100
            )
        ]
    )

    await message.answer_invoice(
        title="AI Photo — 15 генераций",
        description="15 AI-фотографий",
        payload="buy_15_credits",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="15 AI-фото",
                amount=150
            )
        ]
    )


# ============================================================
# PRE-CHECKOUT
# ============================================================

@dp.pre_checkout_query()
async def pre_checkout(
    query: types.PreCheckoutQuery
):

    await bot.answer_pre_checkout_query(
        query.id,
        ok=True
    )


# ============================================================
# PAYMENT
# ============================================================

@dp.message(F.successful_payment)
async def successful_payment(message: Message):

    user_id = message.from_user.id

    payment = message.successful_payment

    charge_id = payment.telegram_payment_charge_id

    payload = payment.invoice_payload

    packages = {
        "buy_5_credits": (5, 50),
        "buy_10_credits": (10, 100),
        "buy_15_credits": (15, 150)
    }

    if payload not in packages:

        await message.answer(
            "⚠️ Неизвестный платёж."
        )

        return


    credits, stars = packages[payload]


    added = add_payment(
        user_id=user_id,
        charge_id=charge_id,
        credits=credits,
        stars=stars
    )


    if not added:

        await message.answer(
            "Этот платёж уже был обработан."
        )

        return


    free_left, paid = get_balance(user_id)


    await message.answer(
        "✅ Оплата успешно получена!\n\n"
        f"⭐ Куплено: {credits} генераций\n"
        f"💳 Теперь доступно платных генераций: {paid}"
    )


# ============================================================
# WEB SERVER
# ============================================================

async def health(request):

    return web.Response(
        text="AI Photo Bot is running"
    )


async def run_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/health",
        health
    )

    runner = web.AppRunner(app)

    await runner.setup()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    logging.info(
        "Web server started on port %s",
        port
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    init_db()

    await run_web_server()

    logging.info(
        "AI Photo Bot started"
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(main())
