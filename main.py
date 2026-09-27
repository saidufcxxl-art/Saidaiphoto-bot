import asyncio
import logging
import os
import base64
from io import BytesIO

from dotenv import load_dotenv
from aiohttp import web
from openai import OpenAI

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice

load_dotenv()

# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY не найден в .env")


# =========================================================
# CLIENTS
# =========================================================

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)

logging.basicConfig(
    level=logging.INFO
)


# =========================================================
# НАСТРОЙКИ
# =========================================================

FREE_GENERATIONS = 2

PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

# user_id -> {
#     "free_used": 0,
#     "paid_credits": 0
# }

users = {}

# user_id -> список Telegram file_id
pending_photos = {}


# =========================================================
# ПРОВЕРКИ
# =========================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_user(user_id: int):

    if user_id not in users:

        users[user_id] = {
            "free_used": 0,
            "paid_credits": 0
        }

    return users[user_id]


def available_generations(user_id: int) -> int:

    user = get_user(user_id)

    if is_admin(user_id):
        return 999999

    free_left = max(
        0,
        FREE_GENERATIONS - user["free_used"]
    )

    return free_left + user["paid_credits"]


def consume_generation(user_id: int):

    user = get_user(user_id)

    if is_admin(user_id):
        return

    if user["free_used"] < FREE_GENERATIONS:

        user["free_used"] += 1

    elif user["paid_credits"] > 0:

        user["paid_credits"] -= 1

    else:

        raise RuntimeError(
            "Нет доступных генераций"
        )


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):

    user_id = message.from_user.id
    user = get_user(user_id)

    if is_admin(user_id):

        text = (
            "👑 Привет, админ!\n\n"
            "У тебя безлимитная генерация.\n\n"
            "📸 Отправь фото и напиши, "
            "что нужно сделать."
        )

    else:

        free_left = max(
            0,
            FREE_GENERATIONS - user["free_used"]
        )

        text = (
            "🎨 AI PHOTO BOT\n\n"

            "Создавай и редактируй фотографии "
            "с помощью AI.\n\n"

            f"🎁 Бесплатно: "
            f"{free_left} из {FREE_GENERATIONS}\n\n"

            "Как пользоваться:\n"

            "1️⃣ Отправь свою фотографию\n"
            "2️⃣ При необходимости отправь "
            "вторую фотографию-пример\n"
            "3️⃣ Напиши, что нужно сделать\n"
            "4️⃣ Получи готовое фото\n\n"

            "Примеры:\n"

            "🏖 Поставь меня на пляж\n"
            "🖤 Сделай чёрно-белое фото\n"
            "🌆 Поставь меня в Нью-Йорк\n"
            "👔 Одень меня в костюм\n"
            "📸 Сделай профессиональную фотосессию\n\n"

            "⭐ После бесплатных генераций:\n\n"

            "⭐ 50 Stars — 5 фото\n"
            "⭐ 100 Stars — 10 фото\n"
            "⭐ 150 Stars — 15 фото\n\n"

            "📸 Просто отправь фото, чтобы начать."
        )

    await message.answer(text)


# =========================================================
# CLEAR
# =========================================================

@dp.message(Command("clear"))
async def cmd_clear(message: Message):

    user_id = message.from_user.id

    pending_photos.pop(
        user_id,
        None
    )

    await message.answer(
        "🗑 Очищено.\n\n"
        "Теперь отправь новые фотографии."
    )


# =========================================================
# BUY
# =========================================================

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
        "⭐ ВЫБЕРИ ПАКЕТ\n\n"

        "50 Stars → 5 фото\n"
        "100 Stars → 10 фото\n"
        "150 Stars → 15 фото",

        reply_markup=keyboard
    )


# =========================================================
# PAYMENT
# =========================================================

@dp.callback_query(F.data.startswith("buy_"))
async def buy_package(
    callback: types.CallbackQuery
):

    stars = int(
        callback.data.split("_")[1]
    )

    photos = PACKAGES[stars]

    await callback.answer()

    await bot.send_invoice(

        chat_id=callback.from_user.id,

        title=f"AI Photo — {photos} фото",

        description=(
            f"{photos} генераций "
            f"AI-фотографий "
            f"без водяного знака."
        ),

        payload=f"buy_{stars}_{photos}",

        currency="XTR",

        prices=[
            LabeledPrice(
                label=f"{photos} AI-фото",
                amount=stars
            )
        ]
    )


# =========================================================
# PRE CHECKOUT
# =========================================================

@dp.pre_checkout_query()
async def process_pre_checkout_query(
    pre_checkout_query: types.PreCheckoutQuery
):

    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=True
    )


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

@dp.message(F.successful_payment)
async def process_successful_payment(
    message: Message
):

    user_id = message.from_user.id

    user = get_user(user_id)

    payment = message.successful_payment

    payload = payment.invoice_payload

    parts = payload.split("_")

    if len(parts) == 3:

        stars = int(parts[1])

        photos = int(parts[2])

        user["paid_credits"] += photos

        await message.answer(

            "✅ Оплата прошла успешно!\n\n"

            f"⭐ Оплачено: {stars} Stars\n"
            f"📸 Начислено: {photos} фото\n\n"

            f"Доступно генераций: "
            f"{available_generations(user_id)}"
        )


# =========================================================
# PHOTO
# =========================================================

@dp.message(F.photo)
async def handle_photo(message: Message):

    user_id = message.from_user.id

    if available_generations(user_id) <= 0:

        await message.answer(
            "❌ Бесплатные генерации закончились.\n\n"

            "⭐ Купи пакет:\n\n"

            "⭐ 50 Stars — 5 фото\n"
            "⭐ 100 Stars — 10 фото\n"
            "⭐ 150 Stars — 15 фото\n\n"

            "Команда: /buy"
        )

        return

    file_id = message.photo[-1].file_id

    caption = message.caption

    if user_id not in pending_photos:

        pending_photos[user_id] = []

    if len(pending_photos[user_id]) >= 2:

        await message.answer(
            "Можно использовать максимум "
            "2 фотографии.\n\n"

            "Теперь напиши, "
            "что нужно сделать."
        )

        return

    pending_photos[user_id].append(
        file_id
    )

    # Фото + описание сразу
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

            "✅ Фото получил.\n\n"

            "Можно:\n"

            "📸 отправить второе "
            "фото-пример\n"

            "или\n"

            "✍️ написать, "
            "что нужно сделать.\n\n"

            "Например:\n"

            "«Поставь меня на пляж»"
        )

    else:

        await message.answer(

            "✅ Получил 2 фотографии.\n\n"

            "Теперь напиши, "
            "что нужно сделать.\n\n"

            "Например:\n"

            "«Поставь меня вместо "
            "человека на второй "
            "фотографии»"
        )


# =========================================================
# TEXT
# =========================================================

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

        "📸 Сначала отправь фотографию.\n\n"

        "Можно отправить до 2 фотографий."
    )


# =========================================================
# СКАЧИВАЕМ ФОТО ИЗ TELEGRAM
# =========================================================

async def download_telegram_photo(
    file_id: str
) -> bytes:

    telegram_file = await bot.get_file(
        file_id
    )

    buffer = BytesIO()

    await bot.download_file(
        telegram_file.file_path,
        buffer
    )

    return buffer.getvalue()


# =========================================================
# OPENAI GENERATION
# =========================================================

def generate_openai_image(
    image_bytes_list: list[bytes],
    prompt: str
):

    """
    Синхронный вызов OpenAI.
    Вызывается через asyncio.to_thread(),
    чтобы не блокировать Telegram-бота.
    """

    quality_prompt = """
Create a highly realistic professional photograph.

Preserve the identity of the person from the
reference photo as accurately as possible.

Preserve:
- facial identity
- facial proportions
- face shape
- eyes
- nose
- mouth
- hairstyle
- skin tone
- natural skin texture
- age and overall appearance

Do not unnecessarily change the person's face.

Keep realistic anatomy and proportions.

Hands and fingers must look natural.

Create realistic:
- lighting
- shadows
- reflections
- perspective
- depth of field
- skin texture
- hair
- clothing
- environment

The final image must look like a real photograph
taken with a professional camera.

Do not make it look like:
- an illustration
- a cartoon
- CGI
- 3D render
- painting

Prioritize photorealism and identity preservation.
"""

    full_prompt = f"""
USER REQUEST:

{prompt}

REFERENCE IMAGE INSTRUCTIONS:

The first image is the main identity reference.

If a second image is provided, use it as a
secondary visual reference for the requested
scene, clothing, composition, pose or environment.

Do not copy unrelated people from the reference.

Integrate the person naturally into the requested
scene.

Match:
- lighting
- perspective
- shadows
- color temperature
- camera angle
- depth of field

The person must look naturally photographed
inside the new environment.

{quality_prompt}
"""

    # -----------------------------------------------------
    # OPENAI IMAGE EDIT
    # -----------------------------------------------------

    # Передаём изображения как файлы в память.
    # OpenAI SDK поддерживает редактирование
    # с входными изображениями.

    image_files = []

    for index, image_bytes in enumerate(
        image_bytes_list
    ):

        image_files.append(
            (
                f"reference_{index}.png",
                image_bytes,
                "image/png"
            )
        )

    result = openai_client.images.edit(

        model="gpt-image-2",

        image=image_files,

        prompt=full_prompt,

        quality="high",

        size="1024x1024",

        output_format="png",

        output_compression=100,

        input_fidelity="high"
    )

    if not result.data:
        raise RuntimeError(
            "OpenAI не вернул изображение."
        )

    image_base64 = result.data[0].b64_json

    if not image_base64:
        raise RuntimeError(
            "OpenAI не вернул b64_json."
        )

    return base64.b64decode(
        image_base64
    )


# =========================================================
# GENERATE + SEND
# =========================================================

async def generate_and_send(
    message: Message,
    photo_ids: list,
    prompt: str,
    user_id: int
):

    # Ещё раз проверяем баланс
    if available_generations(user_id) <= 0:

        await message.answer(
            "❌ У тебя закончились генерации.\n\n"
            "Используй /buy"
        )

        return

    status_message = await message.answer(

        "🎨 Создаю фотографию...\n\n"

        "✨ Использую OpenAI Image AI.\n"

        "⏳ Это может занять некоторое время."
    )

    try:

        # -------------------------------------------------
        # DOWNLOAD TELEGRAM IMAGES
        # -------------------------------------------------

        image_bytes_list = []

        for file_id in photo_ids[:2]:

            image_bytes = (
                await download_telegram_photo(
                    file_id
                )
            )

            image_bytes_list.append(
                image_bytes
            )

        # -------------------------------------------------
        # OPENAI
        # -------------------------------------------------

        result_bytes = await asyncio.to_thread(

            generate_openai_image,

            image_bytes_list,

            prompt
        )

        # -------------------------------------------------
        # CONSUME CREDIT
        # -------------------------------------------------

        consume_generation(
            user_id
        )

        remaining = available_generations(
            user_id
        )

        # -------------------------------------------------
        # SEND PHOTO
        # -------------------------------------------------

        result_file = BytesIO(
            result_bytes
        )

        result_file.name = "ai_photo.png"

        await message.answer_photo(

            types.BufferedInputFile(
                result_bytes,
                filename="ai_photo.png"
            ),

            caption=(

                "✅ Готово!\n\n"

                f"📸 Осталось генераций: "
                f"{remaining}"
            )
        )

        await status_message.delete()

    except Exception as e:

        logging.exception(
            "OpenAI generation error"
        )

        try:
            await status_message.edit_text(
                "❌ Не удалось создать фотографию.\n\n"
                "Попробуй ещё раз через несколько секунд."
            )

        except Exception:
            pass


# =========================================================
# BALANCE
# =========================================================

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
        FREE_GENERATIONS
        - user["free_used"]
    )

    await message.answer(

        "📊 ТВОЙ БАЛАНС\n\n"

        f"🎁 Бесплатные: {free_left}\n"

        f"⭐ Купленные: "
        f"{user['paid_credits']}\n\n"

        f"📸 Всего доступно: "
        f"{available_generations(user_id)}"
    )


# =========================================================
# WEB SERVER
# =========================================================

async def handle(request):

    return web.Response(
        text="AI Photo Bot is running"
    )


# =========================================================
# MAIN
# =========================================================

async def main():

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
            10000
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

    logging.info(
        "AI Photo Bot started"
    )

    await dp.start_polling(
        bot
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
