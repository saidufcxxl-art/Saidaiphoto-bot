import asyncio
import logging
import os
from datetime import datetime

import replicate
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import LabeledPrice, PreCheckoutQuery, Update


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = "/telegram-webhook"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден")

if not WEBHOOK_URL:
    raise RuntimeError(
        "RENDER_EXTERNAL_URL не найден. Проверь, что Render service является Web Service."
    )

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN


# =========================
# МОДЕЛЬ
# =========================

MODEL = "black-forest-labs/flux-2-max"

FREE_GENERATIONS = 2

PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}


# =========================
# ДАННЫЕ
# =========================

users = {}
pending_photos = {}

stats = {
    "generations": 0,
    "paid_generations": 0,
    "stars": 0,
}


# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================
# BOT
# =========================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_user(user: types.User):
    user_id = user.id

    if user_id not in users:
        users[user_id] = {
            "free": FREE_GENERATIONS,
            "balance": 0,

            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "username": user.username or "",

            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        logger.info(
            "Новый пользователь: %s | %s | @%s",
            user_id,
            user.first_name,
            user.username
        )

    else:
        # Обновляем имя/username, если пользователь их поменял
        users[user_id]["first_name"] = user.first_name or ""
        users[user_id]["last_name"] = user.last_name or ""
        users[user_id]["username"] = user.username or ""

    return users[user_id]


def balance_text(user_id: int) -> str:
    if is_admin(user_id):
        return "👑 Админ: без ограничений"

    # Для совместимости
    user = users.get(user_id)

    if not user:
        return "🎁 Бесплатных: 2\n⭐ Платных: 0"

    return (
        f"🎁 Бесплатных: {user['free']}\n"
        f"⭐ Платных: {user['balance']}"
    )


def user_full_name(user_data: dict) -> str:
    name = (
        f"{user_data.get('first_name', '')} "
        f"{user_data.get('last_name', '')}"
    ).strip()

    return name or "Без имени"


# =========================
# START
# =========================

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user = get_user(message.from_user)

    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "📸 Отправь мне фото и напиши, что нужно сделать.\n\n"
        "🎁 У тебя есть 2 бесплатные генерации.\n\n"
        "Команды:\n"
        "💰 /balance — баланс\n"
        "⭐ /buy — купить генерации\n"
        "🗑 /clear — очистить загруженные фото"
    )


# =========================
# BALANCE
# =========================

@dp.message(Command("balance"))
async def balance_handler(message: types.Message):
    get_user(message.from_user)

    await message.answer(
        f"💰 Твой баланс:\n\n"
        f"{balance_text(message.from_user.id)}"
    )


# =========================
# CLEAR
# =========================

@dp.message(Command("clear"))
async def clear_handler(message: types.Message):
    pending_photos.pop(message.from_user.id, None)

    await message.answer(
        "🗑 Фото очищены.\n"
        "Можешь отправить новые."
    )


# =========================
# BUY
# =========================

@dp.message(Command("buy"))
async def buy_handler(message: types.Message):
    get_user(message.from_user)

    await message.answer(
        "⭐ Выбери пакет генераций:\n\n"
        "50 ⭐ → 5 генераций\n"
        "100 ⭐ → 10 генераций\n"
        "150 ⭐ → 15 генераций\n\n"
        "Для покупки:\n"
        "/buy50\n"
        "/buy100\n"
        "/buy150"
    )


@dp.message(Command("buy50"))
async def buy50_handler(message: types.Message):
    await send_invoice(message, 50, 5)


@dp.message(Command("buy100"))
async def buy100_handler(message: types.Message):
    await send_invoice(message, 100, 10)


@dp.message(Command("buy150"))
async def buy150_handler(message: types.Message):
    await send_invoice(message, 150, 15)


async def send_invoice(
    message: types.Message,
    stars: int,
    generations: int
):
    get_user(message.from_user)

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"{generations} генераций",
        description=f"Пакет на {generations} генераций фото",
        payload=f"generations_{generations}_{stars}",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"{generations} генераций",
                amount=stars
            )
        ]
    )


# =========================
# PAYMENT
# =========================

@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    get_user(message.from_user)

    payment = message.successful_payment

    payload = payment.invoice_payload

    try:
        parts = payload.split("_")

        generations = int(parts[1])
        stars = int(parts[2])

    except Exception:
        logger.exception("Ошибка чтения payment payload")
        await message.answer(
            "❌ Не удалось обработать оплату. "
            "Обратись к администратору."
        )
        return

    user = get_user(message.from_user)

    user["balance"] += generations

    stats["paid_generations"] += generations
    stats["stars"] += stars

    await message.answer(
        "✅ Оплата получена!\n\n"
        f"⭐ Добавлено генераций: {generations}\n"
        f"⭐ Теперь платных генераций: {user['balance']}"
    )


# =========================
# ADMIN STATS
# =========================

@dp.message(Command("stats"))
async def stats_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    today = datetime.now().strftime("%Y-%m-%d")

    new_today = sum(
        1
        for user in users.values()
        if user.get("created", "").startswith(today)
    )

    await message.answer(
        "📊 СТАТИСТИКА БОТА\n\n"
        f"👥 Пользователей: {len(users)}\n"
        f"🆕 Новых сегодня: {new_today}\n\n"
        f"📸 Всего генераций: {stats['generations']}\n"
        f"⭐ Платных генераций: {stats['paid_generations']}\n"
        f"💎 Получено Stars: {stats['stars']}"
    )


# =========================
# ADMIN USERS
# =========================

@dp.message(Command("users"))
async def users_handler(message: types.Message):
    # Только админ
    if not is_admin(message.from_user.id):
        return

    if not users:
        await message.answer("👥 Пользователей пока нет.")
        return

    lines = [
        "👥 СПИСОК ПОЛЬЗОВАТЕЛЕЙ\n"
    ]

    for number, (user_id, user) in enumerate(users.items(), start=1):

        name = user_full_name(user)

        username = user.get("username", "")

        if username:
            username_text = f"@{username}"
        else:
            username_text = "без username"

        lines.append(
            f"{number}. 👤 {name}\n"
            f"   {username_text}\n"
            f"   🆔 ID: {user_id}\n"
            f"   🎁 Бесплатных: {user.get('free', 0)}\n"
            f"   ⭐ Платных: {user.get('balance', 0)}\n"
            f"   📅 Первый запуск: {user.get('created', '-')}\n"
        )

    full_text = "\n".join(lines)

    # Telegram имеет ограничение на размер сообщения,
    # поэтому делим большой список на несколько сообщений.
    chunk_size = 3500

    for i in range(0, len(full_text), chunk_size):
        await message.answer(
            full_text[i:i + chunk_size]
        )


# =========================
# ADMIN USER INFO
# =========================

@dp.message(Command("user"))
async def user_handler(
    message: types.Message,
    command: CommandObject
):
    # Только админ
    if not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer(
            "Использование:\n"
            "/user ID\n\n"
            "Например:\n"
            "/user 123456789"
        )
        return

    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer(
            "❌ ID должен быть числом."
        )
        return

    user = users.get(user_id)

    if not user:
        await message.answer(
            "❌ Пользователь с таким ID не найден."
        )
        return

    name = user_full_name(user)

    username = user.get("username", "")

    if username:
        username_text = f"@{username}"
    else:
        username_text = "без username"

    await message.answer(
        "👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ\n\n"
        f"Имя: {name}\n"
        f"Username: {username_text}\n"
        f"🆔 Telegram ID: {user_id}\n\n"
        f"🎁 Бесплатных: {user.get('free', 0)}\n"
        f"⭐ Платных: {user.get('balance', 0)}\n"
        f"📅 Первый запуск: {user.get('created', '-')}"
    )


# =========================
# PHOTO
# =========================

@dp.message(F.photo)
async def photo_handler(message: types.Message):
    user = get_user(message.from_user)

    user_id = message.from_user.id

    if user_id not in pending_photos:
        pending_photos[user_id] = []

    photos = pending_photos[user_id]

    if len(photos) >= 2:
        await message.answer(
            "⚠️ Можно загрузить максимум 2 фотографии.\n\n"
            "Напиши описание того, что нужно сделать."
        )
        return

    photo = message.photo[-1]

    file = await bot.get_file(photo.file_id)

    buffer = await bot.download_file(file.file_path)

    photos.append(buffer.read())

    if len(photos) == 1:
        await message.answer(
            "📸 Фото 1 получено.\n\n"
            "Можешь отправить второе фото "
            "или сразу напиши, что нужно сделать."
        )

    else:
        await message.answer(
            "📸 Получено 2 фотографии.\n\n"
            "Теперь напиши, что нужно сделать."
        )


# =========================
# GENERATION
# =========================

async def generate_image(
    prompt: str,
    photos: list[bytes]
):
    input_data = {
        "prompt": prompt,
        "resolution": "2 MP",
        "aspect_ratio": "match_input_image",
        "output_format": "jpg",
        "output_quality": 100,
        "safety_tolerance": 2,
    }

    if photos:
        input_data["input_images"] = photos

    logger.info(
        "Запуск генерации. Фото: %s",
        len(photos)
    )

    output = await asyncio.to_thread(
        replicate.run,
        MODEL,
        input=input_data
    )

    if output is None:
        raise RuntimeError("Replicate вернул пустой результат")

    # Обычно Replicate возвращает FileOutput/URL
    if hasattr(output, "read"):
        data = await asyncio.to_thread(output.read)

        if isinstance(data, bytes):
            return data

    if isinstance(output, list):
        output = output[0]

    if hasattr(output, "url"):
        url = output.url

        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.read()

    if isinstance(output, str):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(output) as response:
                response.raise_for_status()
                return await response.read()

    raise RuntimeError(
        f"Неизвестный формат ответа Replicate: {type(output)}"
    )


# =========================
# TEXT / PROMPT
# =========================

@dp.message(F.text)
async def text_handler(message: types.Message):
    # Команды здесь не обрабатываем
    if message.text.startswith("/"):
        return

    user = get_user(message.from_user)

    user_id = message.from_user.id

    photos = pending_photos.get(user_id, [])

    if not photos:
        await message.answer(
            "📸 Сначала отправь фотографию."
        )
        return

    # Проверяем баланс
    if not is_admin(user_id):

        if user["free"] <= 0 and user["balance"] <= 0:
            await message.answer(
                "❌ Бесплатные генерации закончились.\n\n"
                "⭐ Купи новые генерации через /buy"
            )
            return

    prompt = message.text.strip()

    if not prompt:
        await message.answer(
            "✍️ Напиши, что нужно сделать с фотографией."
        )
        return

    await message.answer(
        "⏳ Генерирую изображение...\n"
        "Это может занять некоторое время."
    )

    try:

        image = await generate_image(
            prompt=prompt,
            photos=photos
        )

    except Exception as e:

        logger.exception("Ошибка генерации")

        await message.answer(
            "❌ Не удалось создать изображение.\n\n"
            "Попробуй ещё раз."
        )

        return

    # Списываем генерацию ТОЛЬКО после успешной генерации
    if not is_admin(user_id):

        if user["free"] > 0:
            user["free"] -= 1

        elif user["balance"] > 0:
            user["balance"] -= 1

    stats["generations"] += 1

    # Очищаем фотографии после успешной генерации
    pending_photos.pop(user_id, None)

    await message.answer_photo(
        types.BufferedInputFile(
            image,
            filename="generated.jpg"
        ),
        caption="✨ Готово!"
    )


# =========================
# WEB SERVER
# =========================

async def health_handler(request):
    return web.Response(
        text="OK"
    )


async def root_handler(request):
    return web.Response(
        text="Photo AI Bot is running"
    )


async def telegram_webhook(request):
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
            "Ошибка обработки Telegram webhook"
        )

        return web.Response(
            text="ERROR",
            status=500
        )


# =========================
# MAIN
# =========================

async def main():

    webhook_full_url = (
        WEBHOOK_URL.rstrip("/")
        + WEBHOOK_PATH
    )

    app = web.Application()

    app.router.add_get(
        "/",
        root_handler
    )

    app.router.add_get(
        "/health",
        health_handler
    )

    app.router.add_post(
        WEBHOOK_PATH,
        telegram_webhook
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT
    )

    await site.start()

    logger.info(
        "Web server запущен на порту %s",
        PORT
    )

    # Устанавливаем Telegram webhook
    await bot.set_webhook(
        url=webhook_full_url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=False
    )

    logger.info(
        "Webhook установлен: %s",
        webhook_full_url
    )

    # Работаем постоянно
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
