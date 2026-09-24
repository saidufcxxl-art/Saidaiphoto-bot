import asyncio
import logging
import os
import sqlite3
from datetime import datetime

import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice

from aiohttp import web


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден в .env")


os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


# ============================================================
# SETTINGS
# ============================================================

FREE_GENERATIONS = 2

DATABASE = "bot.db"

PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}


# ============================================================
# BOT
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(
    level=logging.INFO
)


# ============================================================
# SQLITE
# ============================================================

def db_connect():
    conn = sqlite3.connect(
        DATABASE,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = db_connect()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_used INTEGER NOT NULL DEFAULT 0,
            paid_credits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            credits INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def get_user(user_id: int):

    conn = db_connect()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    )

    user = cursor.fetchone()

    if user is None:

        cursor.execute(
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

        cursor.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )

        user = cursor.fetchone()

    conn.close()

    return user


def get_balance(user_id: int):

    user = get_user(user_id)

    free_left = max(
        0,
        FREE_GENERATIONS - user["free_used"]
    )

    paid = user["paid_credits"]

    return free_left + paid


def consume_generation(user_id: int):

    if user_id in ADMIN_IDS:
        return True

    conn = db_connect()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT free_used, paid_credits
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()
        return False

    # Сначала бесплатные
    if user["free_used"] < FREE_GENERATIONS:

        cursor.execute(
            """
            UPDATE users
            SET free_used = free_used + 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

        conn.commit()
        conn.close()

        return True

    # Потом платные
    if user["paid_credits"] > 0:

        cursor.execute(
            """
            UPDATE users
            SET paid_credits = paid_credits - 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

        conn.commit()
        conn.close()

        return True

    conn.close()

    return False


def payment_exists(payment_id: str):

    conn = db_connect()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT payment_id
        FROM payments
        WHERE payment_id = ?
        """,
        (payment_id,)
    )

    result = cursor.fetchone()

    conn.close()

    return result is not None


def save_payment(
    payment_id: str,
    user_id: int,
    stars: int,
    credits: int
):

    conn = db_connect()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO payments
        (payment_id, user_id, stars, credits, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            payment_id,
            user_id,
            stars,
            credits,
            datetime.utcnow().isoformat()
        )
    )

    cursor.execute(
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

    conn.close()


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id: int):

    return user_id in ADMIN_IDS


# ============================================================
# START
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):

    user_id = message.from_user.id

    user = get_user(user_id)

    if is_admin(user_id):

        text = """
👑 AI PHOTO BOT

Ты администратор.

Безлимитные генерации.

📸 Отправь фото и напиши, что нужно сделать.
"""

    else:

        free_left = max(
            0,
            FREE_GENERATIONS - user["free_used"]
        )

        text = f"""
🎨 AI PHOTO

Создавай реалистичные фотографии с помощью AI.

🎁 Бесплатно: {free_left} из {FREE_GENERATIONS}

Как пользоваться:

1️⃣ Отправь свою фотографию.

2️⃣ Если нужно перенести себя в другую сцену —
отправь вторую фотографию-пример.

3️⃣ Напиши, что нужно сделать.

Пример:

«Поставь меня на пляж вместо человека
на второй фотографии».

Другие примеры:

🏖 Поставь меня на пляж
🌆 Сделай меня в Нью-Йорке
🖤 Сделай чёрно-белое фото
👔 Одень меня в костюм
📸 Сделай профессиональную фотосессию

⭐ Пакеты:

50 Stars — 5 фото
100 Stars — 10 фото
150 Stars — 15 фото

📊 /balance
⭐ /buy
🗑 /clear
"""

    await message.answer(text)


# ============================================================
# BALANCE
# ============================================================

@dp.message(Command("balance"))
async def cmd_balance(message: Message):

    user_id = message.from_user.id

    if is_admin(user_id):

        await message.answer(
            "👑 Администратор\n\n"
            "Безлимитные генерации."
        )

        return

    user = get_user(user_id)

    free_left = max(
        0,
        FREE_GENERATIONS - user["free_used"]
    )

    paid = user["paid_credits"]

    total = free_left + paid

    await message.answer(
        "📊 ТВОЙ БАЛАНС\n\n"
        f"🎁 Бесплатных: {free_left}\n"
        f"⭐ Купленных: {paid}\n\n"
        f"📸 Всего доступно: {total}"
    )


# ============================================================
# CLEAR
# ============================================================

pending_photos = {}


@dp.message(Command("clear"))
async def cmd_clear(message: Message):

    user_id = message.from_user.id

    pending_photos.pop(
        user_id,
        None
    )

    await message.answer(
        "🗑 Очищено.\n\n"
        "Отправь новые фотографии."
    )


# ============================================================
# BUY
# ============================================================

@dp.message(Command("buy"))
async def cmd_buy(message: Message):

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="⭐ 50 Stars — 5 фото",
                    callback_data="buy_50"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⭐ 100 Stars — 10 фото",
                    callback_data="buy_100"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⭐ 150 Stars — 15 фото",
                    callback_data="buy_150"
                )
            ]
        ]
    )

    await message.answer(
        """
⭐ КУПИТЬ ФОТО

Выбери пакет:

⭐ 50 Stars → 5 фото
⭐ 100 Stars → 10 фото
⭐ 150 Stars → 15 фото
""",
        reply_markup=keyboard
    )


# ============================================================
# CREATE INVOICE
# ============================================================

@dp.callback_query(F.data.startswith("buy_"))
async def buy_package(
    callback: types.CallbackQuery
):

    stars = int(
        callback.data.split("_")[1]
    )

    credits = PACKAGES[stars]

    await callback.answer()

    await bot.send_invoice(
        chat_id=callback.from_user.id,

        title=f"AI Photo — {credits} фото",

        description=(
            f"{credits} генераций "
            f"AI-фотографий."
        ),

        payload=f"buy_{stars}_{credits}",

        currency="XTR",

        prices=[
            LabeledPrice(
                label=f"{credits} AI-фото",
                amount=stars
            )
        ]
    )


# ============================================================
# PRE CHECKOUT
# ============================================================

@dp.pre_checkout_query()
async def process_pre_checkout(
    pre_checkout_query: types.PreCheckoutQuery
):

    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=True
    )


# ============================================================
# SUCCESS PAYMENT
# ============================================================

@dp.message(F.successful_payment)
async def process_successful_payment(
    message: Message
):

    user_id = message.from_user.id

    payment = message.successful_payment

    payment_id = payment.telegram_payment_charge_id

    payload = payment.invoice_payload

    # Защита от повторного начисления
    if payment_exists(payment_id):

        await message.answer(
            "ℹ️ Этот платёж уже обработан."
        )

        return

    parts = payload.split("_")

    if len(parts) != 3:

        await message.answer(
            "❌ Ошибка платежа."
        )

        return

    stars = int(parts[1])

    credits = int(parts[2])

    save_payment(
        payment_id=payment_id,
        user_id=user_id,
        stars=stars,
        credits=credits
    )

    balance = get_balance(user_id)

    await message.answer(
        "✅ ОПЛАТА УСПЕШНА!\n\n"
        f"⭐ Оплачено: {stars} Stars\n"
        f"📸 Начислено: {credits} фото\n\n"
        f"📊 Доступно всего: {balance} генераций."
    )


# ============================================================
# RECEIVE PHOTO
# ============================================================

@dp.message(F.photo)
async def handle_photo(message: Message):

    user_id = message.from_user.id

    if get_balance(user_id) <= 0:

        await message.answer(
            "❌ У тебя закончились генерации.\n\n"
            "⭐ Купи новый пакет:\n\n"
            "50 Stars — 5 фото\n"
            "100 Stars — 10 фото\n"
            "150 Stars — 15 фото\n\n"
            "/buy"
        )

        return

    file_id = message.photo[-1].file_id

    caption = message.caption

    if user_id not in pending_photos:

        pending_photos[user_id] = []

    if len(pending_photos[user_id]) >= 2:

        await message.answer(
            "⚠️ Максимум 2 фотографии.\n\n"
            "Теперь напиши, что нужно сделать."
        )

        return

    pending_photos[user_id].append(
        file_id
    )

    # Если инструкция написана прямо под фото
    if caption:

        photos = pending_photos.pop(
            user_id
        )

        await generate_and_send(
            message,
            photos,
            caption,
            user_id
        )

        return

    count = len(
        pending_photos[user_id]
    )

    if count == 1:

        await message.answer(
            """
✅ Первое фото получил.

Теперь можешь:

📸 отправить второе фото-пример

или

✍️ написать инструкцию.

Например:

«Поставь меня на пляж».
"""
        )

    else:

        await message.answer(
            """
✅ Получил 2 фотографии.

Теперь напиши, что нужно сделать.

Например:

«Поставь меня вместо человека
на второй фотографии».
"""
        )


# ============================================================
# TEXT PROMPT
# ============================================================

@dp.message(F.text)
async def handle_text(message: Message):

    user_id = message.from_user.id

    if message.text.startswith("/"):
        return

    if (
        user_id in pending_photos
        and pending_photos[user_id]
    ):

        photos = pending_photos.pop(
            user_id
        )

        await generate_and_send(
            message,
            photos,
            message.text,
            user_id
        )

        return

    await message.answer(
        "📸 Сначала отправь фотографию."
    )


# ============================================================
# AI GENERATION
# ============================================================

async def generate_and_send(
    message: Message,
    photo_ids: list,
    prompt: str,
    user_id: int
):

    # Проверка перед запуском
    if get_balance(user_id) <= 0:

        await message.answer(
            "❌ Нет доступных генераций.\n\n"
            "Используй /buy"
        )

        return

    await message.answer(
        """
🎨 Создаю фотографию...

⏳ Подожди немного.
"""
    )

    try:

        file_urls = []

        for file_id in photo_ids[:2]:

            telegram_file = await bot.get_file(
                file_id
            )

            file_url = (
                f"https://api.telegram.org/file/bot"
                f"{BOT_TOKEN}/"
                f"{telegram_file.file_path}"
            )

            file_urls.append(
                file_url
            )

        # ====================================================
        # QUALITY PROMPT
        # ====================================================

        quality_prompt = """
Create a highly realistic professional photograph.

Preserve the person's identity and recognizable facial
features.

Preserve natural face shape, skin texture, hairstyle
and important characteristics.

Do not unnecessarily alter the person's identity.

Maintain realistic anatomy, hands, fingers, eyes,
body proportions and facial symmetry.

Use physically realistic lighting and shadows.

Match perspective, depth of field, color temperature,
reflections and environmental lighting.

Make the final result look like a real photograph
taken with a professional camera.

Natural skin texture.

Detailed hair.

Detailed clothing.

Sharp subject.

Realistic environment.

Photorealistic.

Professional photography.

Do not create an illustration.

Do not create a cartoon.

Do not create CGI-looking skin.

Do not over-smooth the face.
"""

        full_prompt = f"""
USER REQUEST:

{prompt}

IMAGE EDITING INSTRUCTIONS:

{quality_prompt}
"""

        # ====================================================
        # ONE PHOTO
        # ====================================================

        if len(file_urls) == 1:

            output = replicate.run(
                "black-forest-labs/flux-kontext-max",

                input={
                    "input_image": file_urls[0],

                    "prompt": full_prompt,

                    "aspect_ratio": "match_input_image",

                    "output_format": "png",

                    "safety_tolerance": 2,

                    "prompt_upsampling": True
                }
            )

        # ====================================================
        # TWO PHOTOS
        # ====================================================

        else:

            full_prompt = f"""
Use IMAGE 1 as the main person's identity.

Use IMAGE 2 as the reference scene/environment.

USER REQUEST:

{prompt}

Place the person from IMAGE 1 naturally into
the environment from IMAGE 2.

Preserve the person's identity.

Match:

- lighting
- shadows
- perspective
- camera angle
- depth of field
- color temperature
- environment
- scale
- body proportions

Make the person look naturally photographed
in the second scene.

Do not make it look like a collage.

Do not simply paste the person onto the background.

Create a seamless realistic photograph.

{quality_prompt}
"""

            output = replicate.run(
                "flux-kontext-apps/multi-image-kontext-max",

                input={
                    "prompt": full_prompt,

                    "input_image_1": file_urls[0],

                    "input_image_2": file_urls[1],

                    "aspect_ratio": "match_input_image",

                    "output_format": "png",

                    "safety_tolerance": 2
                }
            )

        # ====================================================
        # RESULT
        # ====================================================

        if isinstance(output, list):

            result_url = str(
                output[0]
            )

        elif hasattr(output, "url"):

            result_url = str(
                output.url
            )

        else:

            result_url = str(
                output
            )

        # ====================================================
        # CONSUME CREDIT
        # ====================================================

        consumed = consume_generation(
            user_id
        )

        if not consumed:

            await message.answer(
                "❌ Не удалось списать генерацию."
            )

            return

        remaining = get_balance(
            user_id
        )

        await message.answer_photo(
            result_url,

            caption=(
                "✅ Готово!\n\n"
                f"📸 Осталось: {remaining}"
            )
        )

    except Exception:

        logging.exception(
            "AI generation error"
        )

        await message.answer(
            """
❌ Не удалось создать изображение.

Попробуй ещё раз.

Твоя генерация за ошибку
не должна списываться.
"""
        )


# ============================================================
# WEB SERVER
# ============================================================

async def handle(request):

    return web.Response(
        text="AI Photo Bot is running"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    init_db()

    app = web.Application()

    app.router.add_get(
        "/",
        handle
    )

    runner = web.AppRunner(
        app
    )

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
        f"Web server started on port {port}"
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(main())
