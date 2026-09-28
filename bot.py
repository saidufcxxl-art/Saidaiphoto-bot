import asyncio
import logging
import os
from io import BytesIO

import replicate
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery


BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


MODEL = "black-forest-labs/flux-2-max"

FREE_GENERATIONS = 2

PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}

users = {}
pending_photos = {}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "free": FREE_GENERATIONS,
            "balance": 0
        }

    return users[user_id]


def balance_text(user_id):
    if is_admin(user_id):
        return "👑 Админ: без ограничений"

    user = get_user(user_id)

    return (
        f"🎁 Бесплатных: {user['free']}\n"
        f"⭐ Платных: {user['balance']}"
    )


async def generate_image(image_bytes_list, prompt):
    files = []

    try:
        for i, data in enumerate(image_bytes_list):
            file = BytesIO(data)
            file.name = f"reference_{i + 1}.jpg"
            files.append(file)

        result = await asyncio.to_thread(
            replicate.run,
            MODEL,
            input={
                "prompt": (
                    "Create a high-quality photorealistic edited photo. "
                    "Use the reference image(s) as the primary source. "
                    "Preserve the person's identity, face, facial features, "
                    "skin tone and recognizable appearance unless the user "
                    "explicitly asks to change them. "
                    "Keep realistic anatomy, hands, eyes, lighting and shadows. "
                    "Follow the user's requested edit precisely. "
                    "Do not make unnecessary changes.\n\n"
                    "USER REQUEST:\n"
                    + prompt
                ),
                "input_images": files,
                "resolution": "2 MP",
                "aspect_ratio": "match_input_image",
                "output_format": "jpg",
                "output_quality": 100,
                "safety_tolerance": 2,
            },
        )

        if hasattr(result, "read"):
            return result.read()

        if (
            isinstance(result, (list, tuple))
            and result
            and hasattr(result[0], "read")
        ):
            return result[0].read()

        raise RuntimeError(
            f"Неожиданный формат ответа Replicate: {type(result)}"
        )

    finally:
        for file in files:
            file.close()


@dp.message(Command("start"))
async def start(message: Message):
    get_user(message.from_user.id)

    await message.answer(
        "👋 Привет!\n\n"
        "📸 Отправь фото, затем напиши, что нужно изменить.\n"
        "Можно отправить до 2 фотографий.\n\n"
        + balance_text(message.from_user.id)
        + "\n\n"
        "Команды:\n"
        "/buy — купить генерации ⭐\n"
        "/balance — баланс\n"
        "/clear — очистить фото"
    )


@dp.message(Command("balance"))
async def balance(message: Message):
    await message.answer(
        balance_text(message.from_user.id)
    )


@dp.message(Command("clear"))
async def clear(message: Message):
    pending_photos.pop(message.from_user.id, None)

    await message.answer(
        "🗑 Фото очищены."
    )


@dp.message(Command("buy"))
async def buy(message: Message):
    await message.answer(
        "⭐ Пакеты:\n\n"
        "50 Stars → 5 генераций\n"
        "100 Stars → 10 генераций\n"
        "150 Stars → 15 генераций\n\n"
        "/buy50\n"
        "/buy100\n"
        "/buy150"
    )


async def send_invoice(message, stars, generations):
    await message.answer_invoice(
        title=f"{generations} генераций",
        description=f"Пакет из {generations} генераций фотографий",
        payload=f"photo_pack_{stars}_{generations}",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"{generations} генераций",
                amount=stars
            )
        ],
        provider_token=""
    )


@dp.message(Command("buy50"))
async def buy50(message: Message):
    await send_invoice(message, 50, 5)


@dp.message(Command("buy100"))
async def buy100(message: Message):
    await send_invoice(message, 100, 10)


@dp.message(Command("buy150"))
async def buy150(message: Message):
    await send_invoice(message, 150, 15)


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    try:
        _, stars, generations = (
            message.successful_payment.invoice_payload.split("_")
        )

        stars = int(stars)
        generations = int(generations)

    except Exception:
        await message.answer(
            "⚠️ Оплата получена, но пакет не удалось определить."
        )
        return

    if (
        stars not in PACKAGES
        or PACKAGES[stars] != generations
    ):
        await message.answer(
            "⚠️ Некорректный пакет. Обратись к администратору."
        )
        return

    get_user(message.from_user.id)["balance"] += generations

    await message.answer(
        f"✅ Оплата прошла!\n\n"
        f"⭐ Добавлено: {generations}\n\n"
        f"{balance_text(message.from_user.id)}"
    )


@dp.message(F.photo)
async def photo_received(message: Message):
    user_id = message.from_user.id

    photos = pending_photos.setdefault(
        user_id,
        []
    )

    if len(photos) >= 2:
        await message.answer(
            "⚠️ Максимум 2 фото. "
            "Теперь напиши, что нужно сделать."
        )
        return

    photo = message.photo[-1]

    tg_file = await bot.get_file(
        photo.file_id
    )

    buffer = BytesIO()

    await bot.download_file(
        tg_file.file_path,
        buffer
    )

    photos.append(
        buffer.getvalue()
    )

    if len(photos) == 1:
        await message.answer(
            "📸 Фото получил. "
            "Можешь отправить второе или написать, "
            "что изменить."
        )
    else:
        await message.answer(
            "📸 Второе фото получил. "
            "Теперь напиши, что нужно сделать."
        )


@dp.message(F.text)
async def text_prompt(message: Message):
    user_id = message.from_user.id

    prompt = message.text.strip()

    if prompt.startswith("/"):
        return

    photos = pending_photos.get(
        user_id,
        []
    )

    if not photos:
        await message.answer(
            "📸 Сначала отправь фотографию."
        )
        return

    user = get_user(user_id)

    if (
        not is_admin(user_id)
        and user["free"] <= 0
        and user["balance"] <= 0
    ):
        await message.answer(
            "❌ Генерации закончились.\n\n"
            "Используй /buy, чтобы купить новые ⭐"
        )
        return

    status = await message.answer(
        "⏳ Генерирую фотографию..."
    )

    try:
        image = await generate_image(
            photos,
            prompt
        )

        if not is_admin(user_id):
            if user["free"] > 0:
                user["free"] -= 1
            else:
                user["balance"] -= 1

        await status.delete()

        # Отправляем именно как фотографию,
        # а не как документ
        await message.answer_photo(
            types.BufferedInputFile(
                image,
                filename="generated.jpg"
            ),
            caption="✨ Готово!"
        )

        pending_photos.pop(
            user_id,
            None
        )

    except Exception:
        logger.exception(
            "Ошибка генерации через Replicate"
        )

        await status.edit_text(
            "❌ Не удалось создать фотографию.\n"
            "Попробуй ещё раз. "
            "Генерация не списана."
        )


async def health(request):
    return web.Response(
        text="OK"
    )


async def start_web_server():
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

    await web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    ).start()

    logger.info(
        "Health server started on port %s",
        PORT
    )

    return runner


async def main():
    logger.info(
        "Starting Telegram bot with %s",
        MODEL
    )

    runner = await start_web_server()

    try:
        await dp.start_polling(
            bot
        )

    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
