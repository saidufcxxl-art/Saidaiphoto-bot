import asyncio
import logging
import os
from io import BytesIO
from datetime import datetime

import replicate
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Update


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# Render автоматически предоставляет этот адрес
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")

# Необязательно
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_PATH = "/telegram-webhook"


# =========================================================
# ПРОВЕРКА
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден")

if not WEBHOOK_URL:
    raise RuntimeError(
        "RENDER_EXTERNAL_URL не найден. "
        "Проверь, что Render service является Web Service."
    )

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


# =========================================================
# REPLICATE
# =========================================================

MODEL = "black-forest-labs/flux-2-max"


# =========================================================
# БАЛАНСЫ
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

users = {}

pending_photos = {}


# =========================================================
# СТАТИСТИКА
# =========================================================

stats = {
    "generations": 0,
    "paid_generations": 0,
    "stars": 0,
}


# =========================================================
# ЛОГИ
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# TELEGRAM
# =========================================================

bot = Bot(BOT_TOKEN)

dp = Dispatcher()


# =========================================================
# ПОЛЬЗОВАТЕЛЬ
# =========================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


def get_user(user_id):

    if user_id not in users:

        users[user_id] = {
            "free": FREE_GENERATIONS,
            "balance": 0,
            "created": datetime.now().strftime("%Y-%m-%d")
        }

        logger.info(
            "Новый пользователь: %s",
            user_id
        )

    return users[user_id]


def balance_text(user_id):

    if is_admin(user_id):
        return "👑 Админ: без ограничений"

    user = get_user(user_id)

    return (
        f"🎁 Бесплатных: {user['free']}\n"
        f"⭐ Платных: {user['balance']}"
    )


# =========================================================
# /START
# =========================================================

@dp.message(Command("start"))
async def start(message):

    get_user(message.from_user.id)

    await message.answer(
        "👋 Привет!\n\n"
        "📸 Отправь фото, затем напиши, что нужно изменить.\n"
        "Можно отправить до 2 фотографий.\n\n"
        f"{balance_text(message.from_user.id)}\n\n"
        "Команды:\n"
        "/buy — купить генерации ⭐\n"
        "/balance — баланс\n"
        "/clear — очистить фото"
    )


# =========================================================
# /BALANCE
# =========================================================

@dp.message(Command("balance"))
async def balance(message):

    await message.answer(
        balance_text(message.from_user.id)
    )


# =========================================================
# /CLEAR
# =========================================================

@dp.message(Command("clear"))
async def clear(message):

    pending_photos.pop(
        message.from_user.id,
        None
    )

    await message.answer(
        "🗑 Фото очищены."
    )


# =========================================================
# /BUY
# =========================================================

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


# =========================================================
# ОПЛАТА
# =========================================================

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


# =========================================================
# PRE CHECKOUT
# =========================================================

@dp.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery
):

    await query.answer(
        ok=True
    )


# =========================================================
# УСПЕШНАЯ ОПЛАТА
# =========================================================

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
            "⚠️ Некорректный пакет."
        )

        return


    user = get_user(
        message.from_user.id
    )

    user["balance"] += generations


    # Статистика
    stats["paid_generations"] += generations
    stats["stars"] += stars


    await message.answer(
        "✅ Оплата прошла!\n\n"
        f"⭐ Добавлено: {generations}\n\n"
        f"{balance_text(message.from_user.id)}"
    )


# =========================================================
# /STATS
# =========================================================

@dp.message(Command("stats"))
async def statistics(message):

    user_id = message.from_user.id

    # Только админ
    if not is_admin(user_id):

        await message.answer(
            "⛔ Эта команда доступна только администратору."
        )

        return


    today = datetime.now().strftime(
        "%Y-%m-%d"
    )


    total_users = len(users)


    today_users = sum(
        1
        for user in users.values()
        if user.get("created") == today
    )


    await message.answer(
        "📊 СТАТИСТИКА БОТА\n\n"

        f"👥 Всего пользователей: "
        f"{total_users}\n"

        f"🆕 Новых сегодня: "
        f"{today_users}\n\n"

        f"📸 Всего успешных генераций: "
        f"{stats['generations']}\n"

        f"⭐ Куплено генераций: "
        f"{stats['paid_generations']}\n"

        f"💰 Получено Stars: "
        f"{stats['stars']}\n"
    )


# =========================================================
# ФОТО
# =========================================================

@dp.message(F.photo)
async def photo_received(message):

    uid = message.from_user.id

    get_user(uid)

    photos = pending_photos.setdefault(
        uid,
        []
    )


    if len(photos) >= 2:

        await message.answer(
            "⚠️ Максимум 2 фото.\n\n"
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


# =========================================================
# ГЕНЕРАЦИЯ
# =========================================================

async def generate_image(
    image_bytes_list,
    prompt
):

    files = []


    try:

        for i, data in enumerate(
            image_bytes_list
        ):

            file = BytesIO(data)

            file.name = (
                f"reference_{i + 1}.jpg"
            )

            files.append(file)


        result = await asyncio.to_thread(

            replicate.run,

            MODEL,

            input={

                "prompt": (
                    "Create a high-quality "
                    "photorealistic edited photo. "

                    "Use the reference image(s) "
                    "as the primary source. "

                    "Preserve the person's identity, "
                    "face, facial features, skin tone "
                    "and recognizable appearance "
                    "unless the user explicitly "
                    "asks to change them. "

                    "Keep realistic anatomy, "
                    "hands, eyes, lighting and shadows. "

                    "Follow the user's requested "
                    "edit precisely. "

                    "Do not make unnecessary changes.\n\n"

                    "USER REQUEST:\n"
                    + prompt
                ),

                "input_images": files,

                "resolution": "2 MP",

                "aspect_ratio":
                    "match_input_image",

                "output_format": "jpg",

                "output_quality": 100,

                "safety_tolerance": 2,
            }
        )


        if hasattr(result, "read"):

            return result.read()


        if (
            isinstance(
                result,
                (list, tuple)
            )
            and result
            and hasattr(
                result[0],
                "read"
            )
        ):

            return result[0].read()


        raise RuntimeError(
            "Неожиданный формат "
            f"ответа Replicate: {type(result)}"
        )


    finally:

        for file in files:
            file.close()


# =========================================================
# ТЕКСТОВЫЙ ПРОМПТ
# =========================================================

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


    user = get_user(uid)


    # Проверяем баланс
    if (
        not is_admin(uid)
        and user["free"] <= 0
        and user["balance"] <= 0
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

            if user["free"] > 0:

                user["free"] -= 1

            else:

                user["balance"] -= 1


        # Статистика
        stats["generations"] += 1


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


# =========================================================
# HEALTH CHECK
# =========================================================

async def health(request):

    return web.Response(
        text="OK"
    )


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

async def telegram_webhook(request):

    # Проверяем секрет, если он установлен
    if WEBHOOK_SECRET:

        received_secret = (
            request.headers.get(
                "X-Telegram-Bot-Api-Secret-Token"
            )
        )


        if received_secret != WEBHOOK_SECRET:

            return web.Response(
                status=403,
                text="Forbidden"
            )


    try:

        data = await request.json()


        update = Update.model_validate(
            data
        )


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


# =========================================================
# WEB SERVER
# =========================================================

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


    runner = web.AppRunner(
        app
    )


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


# =========================================================
# MAIN
# =========================================================

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


        # Держим сервер запущенным
        await asyncio.Event().wait()


    finally:

        await runner.cleanup()

        await bot.session.close()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())
