import asyncio
import logging
import os
import sqlite3
from datetime import datetime

import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice, URLInputFile

from aiohttp import web


# ============================================================
# CONFIG
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
    raise RuntimeError("BOT_TOKEN не найден в .env")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден в .env")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


# ============================================================
# SETTINGS
# ============================================================

FREE_GENERATIONS = 2

DATABASE = "bot.db"

MAX_INPUT_IMAGES = 8

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
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# PENDING PHOTOS
# ============================================================

pending_photos = {}


# ============================================================
# DATABASE
# ============================================================

def db_connect():

    conn = sqlite3.connect(
        DATABASE,
        check_same_thread=False,
        timeout=30
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


# ============================================================
# RESERVE GENERATION
# ============================================================

def reserve_generation(user_id: int):

    """
    Резервирует одну генерацию ДО запуска AI.

    Возвращает:
        "admin"
        "free"
        "paid"
        None
    """

    if is_admin(user_id):

        return "admin"

    conn = db_connect()

    cursor = conn.cursor()

    try:

        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT free_used, paid_credits
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if user is None:

            conn.rollback()

            return None

        # Бесплатная генерация
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

            return "free"

        # Платная генерация
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

            return "paid"

        conn.rollback()

        return None

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


# ============================================================
# REFUND GENERATION
# ============================================================

def refund_generation(
    user_id: int,
    source: str
):

    if source == "admin":
        return

    conn = db_connect()

    cursor = conn.cursor()

    if source == "free":

        cursor.execute(
            """
            UPDATE users
            SET free_used = MAX(0, free_used - 1)
            WHERE user_id = ?
            """,
            (user_id,)
        )

    elif source == "paid":

        cursor.execute(
            """
            UPDATE users
            SET paid_credits = paid_credits + 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

    conn.commit()

    conn.close()


# ============================================================
# PAYMENTS
# ============================================================

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
👑 AI PHOTO

Ты администратор.

♾ Безлимитные генерации.

📸 Можно отправить до 8 фотографий.

После фотографий просто напиши,
что хочешь получить.
"""

    else:

        free_left = max(
            0,
            FREE_GENERATIONS - user["free_used"]
        )

        paid = user["paid_credits"]

        text = f"""
🎨 AI PHOTO

Создавай и редактируй фотографии
с помощью искусственного интеллекта.

🎁 Бесплатно: {free_left}

⭐ Платных генераций: {paid}

━━━━━━━━━━━━━━

📸 КАК ПОЛЬЗОВАТЬСЯ

1️⃣ Отправь фотографию.

2️⃣ Можешь отправить несколько
фотографий-референсов.

3️⃣ Напиши обычными словами,
что хочешь сделать.

4️⃣ Получи готовое фото.

━━━━━━━━━━━━━━

💡 ПРИМЕРЫ

🏖 «Поставь меня на пляж».

🚗 «Поставь рядом со мной
чёрный BMW M5».

🖤 «Сделай фотографию
чёрно-белой».

👔 «Одень меня в дорогой
чёрный костюм».

🌆 «Поставь меня ночью
в центре Нью-Йорка».

📸 «Сделай профессиональную
фотосессию».

━━━━━━━━━━━━━━

🎁 Первые 2 фото — бесплатно.

⭐ 50 Stars → 5 фото
⭐ 100 Stars → 10 фото
⭐ 150 Stars → 15 фото

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
            "♾ Безлимитные генерации."
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

@dp.message(Command("clear"))
async def cmd_clear(message: Message):

    user_id = message.from_user.id

    pending_photos.pop(
        user_id,
        None
    )

    await message.answer(
        "🗑 Фотографии очищены.\n\n"
        "Можешь отправить новые."
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
⭐ КУПИТЬ ГЕНЕРАЦИИ

🎁 Бесплатно: 2 фото

После этого:

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
            f"AI-фотографий"
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
# PAYMENT
# ============================================================

@dp.message(F.successful_payment)
async def process_successful_payment(
    message: Message
):

    user_id = message.from_user.id

    payment = message.successful_payment

    payment_id = (
        payment.telegram_payment_charge_id
    )

    payload = payment.invoice_payload

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
        f"📊 Всего доступно: {balance}"
    )


# ============================================================
# RECEIVE PHOTO
# ============================================================

@dp.message(F.photo)
async def handle_photo(message: Message):

    user_id = message.from_user.id

    # Проверяем баланс только при первом фото
    if user_id not in pending_photos:

        if get_balance(user_id) <= 0:

            await message.answer(
                "❌ Генерации закончились.\n\n"
                "⭐ Купи новый пакет:\n\n"
                "50 Stars — 5 фото\n"
                "100 Stars — 10 фото\n"
                "150 Stars — 15 фото\n\n"
                "/buy"
            )

            return

        pending_photos[user_id] = []

    photos = pending_photos[user_id]

    if len(photos) >= MAX_INPUT_IMAGES:

        await message.answer(
            f"⚠️ Максимум {MAX_INPUT_IMAGES} фотографий.\n\n"
            "Теперь напиши, что нужно сделать."
        )

        return

    file_id = message.photo[-1].file_id

    photos.append(file_id)

    # Если инструкция написана в caption
    if message.caption:

        collected = pending_photos.pop(
            user_id
        )

        await generate_and_send(
            message,
            collected,
            message.caption,
            user_id
        )

        return

    count = len(photos)

    if count == 1:

        await message.answer(
            """
✅ Первое фото получено.

Можешь:

📸 отправить ещё фотографии
или
✍️ написать запрос.

Например:

«Поставь меня на пляж».

«Добавь рядом со мной машину».

«Сделай чёрно-белым».
"""
        )

    else:

        await message.answer(
            f"""
✅ Получено фотографий: {count}

Теперь напиши, что нужно сделать.

Например:

«Возьми меня с первого фото
и поставь в сцену со второго».

Можно использовать до
{MAX_INPUT_IMAGES} фотографий.
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

    photos = pending_photos.get(user_id)

    if photos:

        collected = pending_photos.pop(
            user_id
        )

        await generate_and_send(
            message,
            collected,
            message.text.strip(),
            user_id
        )

        return

    await message.answer(
        "📸 Сначала отправь фотографию."
    )


# ============================================================
# TELEGRAM FILE URL
# ============================================================

async def get_telegram_file_url(
    file_id: str
):

    telegram_file = await bot.get_file(
        file_id
    )

    return (
        f"https://api.telegram.org/file/bot"
        f"{BOT_TOKEN}/"
        f"{telegram_file.file_path}"
    )


# ============================================================
# SMART PROMPT
# ============================================================

def build_ai_prompt(
    user_prompt: str,
    image_count: int
):

    """
    Не заменяем запрос пользователя.
    Мы добавляем инструкции, которые помогают
    модели понять, что именно менять.
    """

    references = []

    for i in range(image_count):

        if i == 0:

            references.append(
                """
IMAGE 1:
Primary image.
Treat the person/main subject in this image
as the main identity reference.
"""
            )

        else:

            references.append(
                f"""
IMAGE {i + 1}:
Additional reference image.
Use it according to the user's request.
"""
            )

    reference_text = "\n".join(references)

    prompt = f"""
You are an expert professional photo editor.

EDIT THE PROVIDED REFERENCE IMAGE(S).

USER'S EXACT REQUEST:
{user_prompt}

REFERENCE IMAGES:
{reference_text}

CORE INSTRUCTIONS:

Follow the user's request exactly.

The user's requested change has priority.

If the user asks to add something,
actually add that thing.

If the user asks to remove something,
actually remove it.

If the user asks to change something,
change that specific thing.

If the user asks to move a person,
move the person into the requested scene.

If the user asks to change the background,
change the background while preserving
the main person.

If the user asks to change clothing,
change clothing while preserving identity.

If the user asks to add a vehicle,
person, animal, object or other element,
create it realistically inside the scene.

If the user asks for black and white,
make the image genuinely black and white
without changing unrelated details.

If the user asks for a specific visual style,
apply that style while preserving the subject
unless the user explicitly requests otherwise.

IDENTITY PRESERVATION:

When the main person should remain the same person,
preserve their recognizable identity.

Preserve:

- facial structure
- face shape
- eyes
- eyebrows
- nose
- mouth
- jaw
- hairstyle
- skin texture
- natural facial details
- body proportions
- recognizable characteristics

Do NOT replace the person with
a generic AI-generated face.

Do NOT unnecessarily change
the person's age, ethnicity, facial structure
or recognizable appearance.

REALISM:

The result must look like one real photograph.

Match:

- perspective
- camera angle
- focal length
- lighting
- shadows
- reflections
- color temperature
- depth of field
- scale
- atmospheric perspective
- contact shadows
- environmental lighting

When inserting a person into another scene,
do not make a cut-and-paste collage.

Integrate the person naturally into
the target environment.

Make the light on the person match
the environment.

Make shadows physically believable.

Keep realistic anatomy.

Keep realistic hands and fingers.

Keep realistic eyes and facial proportions.

Keep realistic skin texture.

Do not over-smooth the face.

Do not make plastic skin.

Do not create an illustration.

Do not create a cartoon.

Do not create obvious CGI.

Do not make the result look like
a low-quality AI image.

UNREQUESTED CHANGES:

Do not change things that the user
did not ask to change.

Preserve the original composition
wherever possible.

OUTPUT:

Create one coherent,
high-quality,
photorealistic final image.

The result should look like
a professional photograph taken
with a high-end camera.

USER REQUEST AGAIN:

{user_prompt}
"""

    return prompt.strip()


# ============================================================
# GET RESULT URL
# ============================================================

def get_result_url(output):

    if output is None:

        raise RuntimeError(
            "Replicate не вернул результат."
        )

    # Обычный объект FileOutput
    if hasattr(output, "url"):

        try:

            value = output.url

            if callable(value):

                value = value()

            return str(value)

        except Exception:

            pass

    # Иногда output является списком
    if isinstance(output, (list, tuple)):

        if not output:

            raise RuntimeError(
                "Пустой результат Replicate."
            )

        first = output[0]

        if hasattr(first, "url"):

            try:

                value = first.url

                if callable(value):

                    value = value()

                return str(value)

            except Exception:

                pass

        return str(first)

    return str(output)


# ============================================================
# AI GENERATION
# ============================================================

async def generate_and_send(
    message: Message,
    photo_ids: list,
    prompt: str,
    user_id: int
):

    if not prompt:

        await message.answer(
            "✍️ Напиши, что нужно сделать."
        )

        pending_photos[user_id] = photo_ids

        return

    # --------------------------------------------------------
    # RESERVE CREDIT
    # --------------------------------------------------------

    credit_source = reserve_generation(
        user_id
    )

    if credit_source is None:

        await message.answer(
            "❌ Нет доступных генераций.\n\n"
            "⭐ Используй /buy"
        )

        pending_photos[user_id] = photo_ids

        return

    await message.answer(
        "🎨 Создаю фотографию...\n\n"
        "⏳ Работаю над изображением.\n"
        "Качество важнее скорости."
    )

    try:

        # ----------------------------------------------------
        # GET TELEGRAM URLS
        # ----------------------------------------------------

        file_urls = []

        for file_id in photo_ids[:MAX_INPUT_IMAGES]:

            url = await get_telegram_file_url(
                file_id
            )

            file_urls.append(url)

        # ----------------------------------------------------
        # SMART PROMPT
        # ----------------------------------------------------

        final_prompt = build_ai_prompt(
            prompt,
            len(file_urls)
        )

        logging.info(
            "AI generation: user=%s images=%s prompt=%s",
            user_id,
            len(file_urls),
            prompt
        )

        # ----------------------------------------------------
        # FLUX.2 MAX
        # ----------------------------------------------------

        output = await asyncio.to_thread(
            replicate.run,
            "black-forest-labs/flux-2-max",
            input={
                "prompt": final_prompt,

                # До 8 reference images
                "input_images": file_urls[:MAX_INPUT_IMAGES],

                # Сохраняем пропорции первой фотографии
                "aspect_ratio": "match_input_image",

                # Максимально разумное качество
                # до 4 MP поддерживается моделью
                "resolution": "2 MP",

                # PNG — без JPEG/WebP потерь
                "output_format": "png",

                # Для PNG этот параметр не ухудшает изображение
                "output_quality": 100,

                # Обычный уровень безопасности
                "safety_tolerance": 2
            }
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        result_url = get_result_url(
            output
        )

        if not result_url.startswith("http"):

            raise RuntimeError(
                "Replicate вернул некорректный URL."
            )

        # ----------------------------------------------------
        # SEND AS DOCUMENT
        # ----------------------------------------------------
        #
        # Отправляем PNG как документ.
        # Telegram не будет превращать его
        # в обычную сжатую фотографию.
        #

        result_file = URLInputFile(
            result_url,
            filename="AI_Photo.png"
        )

        remaining = get_balance(
            user_id
        )

        if is_admin(user_id):

            remaining_text = "♾ Безлимит"

        else:

            remaining_text = str(
                remaining
            )

        await message.answer_document(
            document=result_file,
            caption=(
                "✅ ГОТОВО!\n\n"
                f"📸 Осталось генераций: "
                f"{remaining_text}"
            )
        )

        logging.info(
            "Generation completed: user=%s",
            user_id
        )

    except Exception as error:

        logging.exception(
            "AI generation error: user=%s",
            user_id
        )

        # ----------------------------------------------------
        # RETURN CREDIT
        # ----------------------------------------------------

        refund_generation(
            user_id,
            credit_source
        )

        # Возвращаем фотографии,
        # чтобы пользователь мог повторить запрос
        pending_photos[user_id] = photo_ids

        error_text = str(error)

        if len(error_text) > 800:

            error_text = (
                error_text[:800]
                + "..."
            )

        await message.answer(
            "❌ Не удалось создать фотографию.\n\n"
            "⭐ Генерация возвращена на баланс.\n\n"
            "Попробуй ещё раз или измени запрос.\n\n"
            f"Техническая ошибка:\n{error_text}"
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

    app.router.add_get(
        "/health",
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
        "Web server started on port %s",
        port
    )

    logging.info(
        "AI Photo Bot started"
    )

    await dp.start_polling(
        bot
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())
