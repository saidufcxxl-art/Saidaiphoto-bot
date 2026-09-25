import asyncio
import logging
import os
from datetime import date

import replicate
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# НАСТРОЙКИ
# --------------------------------------------------

FREE_GENERATIONS = 2

# Пакеты Stars
PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}

# --------------------------------------------------
# ПОЛЬЗОВАТЕЛИ
# --------------------------------------------------

# user_id -> {
#     "free_used": 0,
#     "paid_credits": 0
# }
users = {}

# user_id -> список ожидающих фото
pending_photos = {}

# --------------------------------------------------
# ПРОВЕРКИ
# --------------------------------------------------

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

    free_left = max(0, FREE_GENERATIONS - user["free_used"])

    return free_left + user["paid_credits"]


def consume_generation(user_id: int):
    """
    Сначала используются бесплатные генерации.
    После них используются купленные кредиты.
    """

    user = get_user(user_id)

    if is_admin(user_id):
        return

    if user["free_used"] < FREE_GENERATIONS:
        user["free_used"] += 1
    elif user["paid_credits"] > 0:
        user["paid_credits"] -= 1
    else:
        raise RuntimeError("Нет доступных генераций")


# --------------------------------------------------
# START
# --------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: Message):

    user_id = message.from_user.id
    user = get_user(user_id)

    if is_admin(user_id):

        text = (
            "👑 Привет, админ!\n\n"
            "У тебя безлимитная генерация.\n\n"
            "📸 Отправь фото и напиши, что нужно сделать."
        )

    else:

        free_left = max(
            0,
            FREE_GENERATIONS - user["free_used"]
        )

        text = (
            "🎨 AI PHOTO BOT\n\n"
            "Создавай и редактируй фотографии с помощью AI.\n\n"
            f"🎁 Бесплатно: {free_left} из {FREE_GENERATIONS}\n\n"
            "Как пользоваться:\n"
            "1️⃣ Отправь свою фотографию\n"
            "2️⃣ При необходимости отправь вторую фотографию-пример\n"
            "3️⃣ Напиши, что нужно сделать\n"
            "4️⃣ Получи готовое фото\n\n"
            "Примеры:\n"
            "🏖 Поставь меня на пляж\n"
            "🖤 Сделай чёрно-белое фото\n"
            "🌆 Поставь меня в Нью-Йорк\n"
            "👔 Одень меня в костюм\n"
            "📸 Сделай профессиональную фотосессию\n\n"
            "⭐ После бесплатных генераций можно купить кредиты:\n\n"
            "⭐ 50 Stars — 5 фото\n"
            "⭐ 100 Stars — 10 фото\n"
            "⭐ 150 Stars — 15 фото\n\n"
            "📸 Просто отправь фото, чтобы начать."
        )

    await message.answer(text)


# --------------------------------------------------
# CLEAR
# --------------------------------------------------

@dp.message(Command("clear"))
async def cmd_clear(message: Message):

    user_id = message.from_user.id

    pending_photos.pop(user_id, None)

    await message.answer(
        "🗑 Очищено.\n\n"
        "Теперь отправь новые фотографии."
    )


# --------------------------------------------------
# BUY
# --------------------------------------------------

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


# --------------------------------------------------
# PAYMENT BUTTON
# --------------------------------------------------

@dp.callback_query(F.data.startswith("buy_"))
async def buy_package(callback: types.CallbackQuery):

    stars = int(callback.data.split("_")[1])
    photos = PACKAGES[stars]

    await callback.answer()

    await bot.send_invoice(
        chat_id=callback.from_user.id,

        title=f"AI Photo — {photos} фото",

        description=(
            f"{photos} генераций AI-фотографий "
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


# --------------------------------------------------
# PRE CHECKOUT
# --------------------------------------------------

@dp.pre_checkout_query()
async def process_pre_checkout_query(
    pre_checkout_query: types.PreCheckoutQuery
):

    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=True
    )


# --------------------------------------------------
# SUCCESSFUL PAYMENT
# --------------------------------------------------

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):

    user_id = message.from_user.id

    user = get_user(user_id)

    payment = message.successful_payment

    payload = payment.invoice_payload

    # buy_50_5
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


# --------------------------------------------------
# PHOTO
# --------------------------------------------------

@dp.message(F.photo)
async def handle_photo(message: Message):

    user_id = message.from_user.id

    # Проверяем кредиты
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

    # Максимум 2 изображения
    if len(pending_photos[user_id]) >= 2:

        await message.answer(
            "Можно использовать максимум 2 фотографии.\n\n"
            "Теперь напиши, что нужно сделать."
        )

        return

    pending_photos[user_id].append(file_id)

    # Если сразу есть подпись
    if caption:

        photos = pending_photos.pop(user_id)

        await generate_and_send(
            message,
            photos,
            caption,
            user_id
        )

        return

    count = len(pending_photos[user_id])

    if count == 1:

        await message.answer(
            "✅ Фото получил.\n\n"
            "Можно:\n"
            "📸 отправить второе фото-пример\n"
            "или\n"
            "✍️ написать, что нужно сделать.\n\n"
            "Например:\n"
            "«Поставь меня на пляж»"
        )

    else:

        await message.answer(
            "✅ Получил 2 фотографии.\n\n"
            "Теперь напиши, что нужно сделать.\n\n"
            "Например:\n"
            "«Поставь меня вместо человека "
            "на второй фотографии»"
        )


# --------------------------------------------------
# TEXT
# --------------------------------------------------

@dp.message(F.text)
async def handle_text(message: Message):

    user_id = message.from_user.id

    if message.text.startswith("/"):
        return

    if user_id in pending_photos and pending_photos[user_id]:

        photos = pending_photos.pop(user_id)

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


# --------------------------------------------------
# AI GENERATION
# --------------------------------------------------

async def generate_and_send(
    message: Message,
    photo_ids: list,
    prompt: str,
    user_id: int
):

    # Повторно проверяем кредит перед дорогой операцией
    if available_generations(user_id) <= 0:

        await message.answer(
            "❌ У тебя закончились генерации.\n\n"
            "Используй /buy"
        )

        return

    await message.answer(
        "🎨 Генерирую фотографию...\n\n"
        "⏳ Обычно это занимает до 2 минут."
    )

    try:

        file_urls = []

        # Получаем Telegram URL
        for fid in photo_ids[:2]:

            f = await bot.get_file(fid)

            file_url = (
                f"https://api.telegram.org/file/bot"
                f"{BOT_TOKEN}/{f.file_path}"
            )

            file_urls.append(file_url)

        # --------------------------------------------------
        # QUALITY PROMPT
        # --------------------------------------------------

        quality_prompt = """
Create a highly realistic professional photograph.

Preserve the person's identity, facial features,
face shape, skin texture, hairstyle and natural appearance.

Do not unnecessarily change the person's face.

Keep realistic anatomy, hands, fingers, eyes and proportions.

Use realistic natural lighting, realistic shadows,
accurate perspective and physically consistent reflections.

Make the result look like a real photograph taken
with a professional camera.

High detail, natural skin texture, realistic hair,
sharp subject, detailed clothing, realistic background,
professional photography, photorealistic result.

Do not make the image look like an illustration,
cartoon, CGI or painting.
"""

        full_prompt = f"""
{prompt}

IMPORTANT:
If two images are provided, use the first image
as the person's identity/reference and the second image
as the scene/reference.

Place the person naturally into the requested scene.

Match lighting, perspective, shadows, color temperature
and depth of field between the person and the environment.

Keep the person's identity recognizable.

{quality_prompt}
"""

        # --------------------------------------------------
        # ONE IMAGE
        # --------------------------------------------------

        if len(file_urls) == 1:

            output = replicate.run(
                "black-forest-labs/flux-kontext-max",

                input={
                    "input_image": file_urls[0],

                    "prompt": full_prompt,

                    # Сохраняем исходное соотношение сторон
                    "aspect_ratio": "match_input_image",

                    # PNG для минимизации потерь
                    "output_format": "png",

                    "safety_tolerance": 2,

                    # Улучшение понимания инструкции
                    "prompt_upsampling": True
                }
            )

        # --------------------------------------------------
        # TWO IMAGES
        # --------------------------------------------------

        else:

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

        # --------------------------------------------------
        # RESULT URL
        # --------------------------------------------------

        if isinstance(output, list):

            result_url = str(output[0])

        else:

            # Replicate FileOutput
            if hasattr(output, "url"):

                result_url = str(output.url)

            else:

                result_url = str(output)

        # --------------------------------------------------
        # СПИСЫВАЕМ ГЕНЕРАЦИЮ
        # --------------------------------------------------

        consume_generation(user_id)

        remaining = available_generations(user_id)

        await message.answer_photo(
            result_url,

            caption=(
                "✅ Готово!\n\n"
                f"📸 Осталось генераций: {remaining}"
            )
        )

    except Exception as e:

        logging.exception("Generation error")

        await message.answer(
            "❌ Не удалось создать фотографию.\n\n"
            "Попробуй ещё раз через несколько секунд."
        )


# --------------------------------------------------
# STATUS
# --------------------------------------------------

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

    await message.answer(
        "📊 ТВОЙ БАЛАНС\n\n"
        f"🎁 Бесплатные: {free_left}\n"
        f"⭐ Купленные: {user['paid_credits']}\n\n"
        f"📸 Всего доступно: "
        f"{available_generations(user_id)}"
    )


# --------------------------------------------------
# WEB SERVER
# --------------------------------------------------

async def handle(request):

    return web.Response(
        text="AI Photo Bot is running"
    )


async def main():

    app = web.Application()

    app.router.add_get(
        "/",
        handle
    )

    runner = web.AppRunner(app)

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

    await dp.start_polling(bot)


# --------------------------------------------------
# START
# --------------------------------------------------

if __name__ == "__main__":

    asyncio.run(main())
