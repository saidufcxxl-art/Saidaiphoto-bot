import asyncio
import logging
import os
from io import BytesIO

import replicate
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Update


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# Render автоматически даёт этот адрес
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")

# Можно оставить пустым
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_PATH = "/telegram-webhook"


# =========================
# ПРОВЕРКА НАСТРОЕК
# =========================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден")

if not WEBHOOK_URL:
    raise RuntimeError(
        "RENDER_EXTERNAL_URL не найден. "
        "Убедись, что Render service создан как Web Service."
    )


os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


# =========================
# REPLICATE
# =========================

MODEL = "black-forest-labs/flux-2-max"


# =========================
# БАЛАНСЫ
# =========================

FREE_GENERATIONS = 2

PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}

users = {}
pending_photos = {}


# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================
# TELEGRAM
# =========================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# =========================
# ПОЛЬЗОВАТЕЛЬ
# =========================

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

    u = get_user(user_id)

    return (
        f"🎁 Бесплатных: {u['free']}\n"
        f"⭐ Платных: {u['balance']}"
    )


# =========================
# ГЕНЕРАЦИЯ
# =========================

async def generate_image(image_bytes_list, prompt):

    files = []

    try:

        for i, data in enumerate(image_bytes_list):

            f = BytesIO(data)
            f.name = f"reference_{i + 1}.jpg"

            files.append(f)


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
            }
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

        for f in files:
            f.close()


# =========================
# /START
# =========================

@dp.message(Command("start"))
async def start(message):

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


# =========================
# /BALANCE
# =========================

@dp.message(Command("balance"))
async def balance(message):

    await message.answer(
        balance_text(message.from_user.id)
    )


# =========================
# /CLEAR
# =========================

@dp.message(Command("clear"))
async def clear(message):

    pending_photos.pop(
        message.from_user.id,
        None
    )

    await message.answer(
        "🗑 Фото очищены."
    )


# =========================
# /BUY
# =========================

@dp.message(Command("buy"))
async def buy(message):

    await message.answer(
        "⭐ Пакеты:\n\n"
        "50 Stars → 5 генераций\n"
        "100 Stars → 10 генераций\n"
        "150 Stars → 15 генераций\n\n"
        "/buy50\n"
        "/buy100\n"
        "/buy150"
    )


# =========================
# INVOICE
# =========================

async def send_invoice(
    message,
    stars,
    generations
):

    await message.answer_invoice(
        title=f"{generations} генераций",

        description=(
            f"Пакет из {generations} "
            f"генераций фотографий"
        ),

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
async def buy50(message):

    await send_invoice(
        message,
        50,
        5
    )


@dp.message(Command("buy100"))
async def buy100(message):

    await send_invoice(
        message,
        100,
        10
    )


@dp.message(Command("buy150"))
async def buy150(message):

    await send_invoice(
        message,
        150,
        15
    )


# =========================
# PRE CHECKOUT
# =========================

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):

    await query.answer(ok=True)


# =========================
# УСПЕШНАЯ ОПЛАТА
# =========================

@dp.message(F.successful_payment)
async def successful_payment(message):

    try:

        (
            _,
            stars,
            generations
        ) = message.successful_payment.invoice_payload.split("_")

        stars = int(stars)
        generations = int(generations)

    except Exception:

        await message.answer(
            "⚠️ Оплата получена, "
            "но пакет не удалось определить."
        )

        return


    if (
        stars not in PACKAGES
        or PACKAGES[stars] != generations
    ):

        await message.answer(
            "⚠️ Некорректный пакет. "
            "Обратись к администратору."
        )

        return


    get_user(
        message.from_user.id
    )["balance"] += generations


    await message.answer(
        f"✅ Оплата прошла!\n\n"
        f"⭐ Добавлено: {generations}\n\n"
        f"{balance_text(message.from_user.id)}"
    )


# =========================
# ФОТО
# =========================

@dp.message(F.photo)
async def photo_received(message):

    uid = message.from_user.id

    photos = pending_photos.setdefault(
        uid,
        []
    )


    if len(photos) >= 2:

        await message.answer(
            "⚠️ Максимум 2 фото.\n"
            "Теперь напиши, что нужно сделать."
        )

        return


    photo = message.photo[-1]

    tg_file = await bot.get_file(
        photo.file_id
    )

    buf = BytesIO()

    await bot.download_file(
        tg_file.file_path,
        buf
    )

    photos.append(
        buf.getvalue()
    )


    if len(photos) == 1:

        await message.answer(
            "📸 Фото получил.\n\n"
            "Можешь отправить второе "
            "или написать, что изменить."
        )

    else:

        await message.answer(
            "📸 Второе фото получил.\n\n"
            "Теперь напиши, что нужно сделать."
        )


# =========================
# ТЕКСТ
# =========================

@dp.message(F.text)
async def text_prompt(message):

    uid = message.from_user.id

    prompt = message.text.strip()


    if prompt.startswith("/"):
        return


    photos = pending_photos.get(
        uid,
        []
    )


    if not photos:

        await message.answer(
            "📸 Сначала отправь фотографию."
        )

        return


    u = get_user(uid)


    if (
        not is_admin(uid)
        and u["free"] <= 0
        and u["balance"] <= 0
    ):

        await message.answer(
            "❌ Генерации закончились.\n\n"
            "Используй /buy, "
            "чтобы купить новые ⭐"
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


        # Списываем только после успешной генерации
        if not is_admin(uid):

            if u["free"] > 0:
                u["free"] -= 1
            else:
                u["balance"] -= 1


        await status.delete()


        await message.answer_photo(
            types.BufferedInputFile(
                image,
                filename="generated.jpg"
            ),
            caption="✨ Готово!"
        )


        pending_photos.pop(
            uid,
            None
        )


    except Exception:

        logger.exception(
            "Ошибка генерации через Replicate"
        )

        await status.edit_text(
            "❌ Не удалось создать фотографию.\n\n"
            "Попробуй ещё раз.\n"
            "Генерация не списана."
        )


# =========================
# HEALTH
# =========================

async def health(request):

    return web.Response(
        text="OK"
    )


# =========================
# TELEGRAM WEBHOOK
# =========================

async def telegram_webhook(request):

    # Если секрет задан — проверяем его
    if WEBHOOK_SECRET:

        received_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if received_secret != WEBHOOK_SECRET:

            return web.Response(
                status=403,
                text="Forbidden"
            )


    try:

        data = await request.json()

        update = Update.model_validate(data)

        await dp.feed_update(
            bot,
            update
        )

        return web.Response(
            text="OK"
        )


    except Exception:

        logger.exception(
            "Ошибка Telegram webhook"
        )

        return web.Response(
            status=500,
            text="ERROR"
        )


# =========================
# WEB SERVER
# =========================

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


    app.router.add_post(
        WEBHOOK_PATH,
        telegram_webhook
    )


    runner = web.AppRunner(app)

    await runner.setup()


    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()


    logger.info(
        "Web server started on port %s",
        PORT
    )


    return runner


# =========================
# MAIN
# =========================

async def main():

    logger.info(
        "Starting Telegram bot with %s",
        MODEL
    )


    runner = await start_web_server()


    webhook_full_url = (
        WEBHOOK_URL.rstrip("/")
        + WEBHOOK_PATH
    )


    try:

        await bot.set_webhook(
            url=webhook_full_url,

            secret_token=(
                WEBHOOK_SECRET
                if WEBHOOK_SECRET
                else None
            ),

            drop_pending_updates=False
        )


        logger.info(
            "Telegram webhook установлен: %s",
            webhook_full_url
        )


        # Сервер работает постоянно
        await asyncio.Event().wait()


    finally:

        await runner.cleanup()

        await bot.session.close()


# =========================
# START
# =========================

if __name__ == "__main__":

    asyncio.run(main())
