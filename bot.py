import asyncio
import logging
import os
import tempfile
from io import BytesIO
from urllib.request import urlopen

import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")
if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN не найден")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ВАЖНО: это память процесса. После перезапуска Render балансы сбросятся.
users = {}
pending_photos = {}

FREE_GENERATIONS = 2

PACKAGES = {
    50: 5,
    100: 10,
    150: 15,
}

MODEL = "black-forest-labs/flux-2-max"

SYSTEM_PROMPT = """
Edit the provided reference photo(s) according to the user's request.

IMPORTANT:
- Preserve the real person's identity, facial structure, facial features, skin tone,
  hairstyle, body proportions and recognizable appearance whenever the user does not
  explicitly ask to change them.
- Do not randomly change the face.
- Keep natural realistic skin, anatomy, hands and eyes.
- Make the requested changes clearly and professionally.
- The final image should look like a real high-quality photograph, not an AI illustration.
- Keep lighting, shadows, perspective and composition coherent.
- If multiple reference photos are provided, use them together and keep the same person's
  identity consistent.
"""

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_user(user_id: int):
    if user_id not in users:
        users[user_id] = {"free": FREE_GENERATIONS, "balance": 0}
    return users[user_id]


def available_generations(user_id: int) -> str:
    if is_admin(user_id):
        return "♾️ без ограничений"
    u = get_user(user_id)
    return f"🎁 Бесплатных: {u['free']}\n⭐ Платных: {u['balance']}"


async def make_temp_file(data: bytes, suffix=".jpg"):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(data)
    f.close()
    return f.name


def run_replicate_sync(file_paths, prompt):
    files = []
    try:
        for path in file_paths:
            files.append(open(path, "rb"))

        output = replicate.run(
            MODEL,
            input={
                "prompt": SYSTEM_PROMPT + "\n\nUSER REQUEST:\n" + prompt,
                "input_images": files,
                "aspect_ratio": "match_input_image",
                "resolution": "2 MP",
                "output_format": "png",
                "output_quality": 100,
                "safety_tolerance": 2,
            },
        )

        # Replicate FileOutput normally supports .read().
        if hasattr(output, "read"):
            return output.read()

        # Some clients/models can return a list of outputs.
        if isinstance(output, (list, tuple)) and output:
            item = output[0]
            if hasattr(item, "read"):
                return item.read()
            if isinstance(item, str):
                with urlopen(item, timeout=120) as response:
                    return response.read()

        # Fallback for a direct URL string.
        if isinstance(output, str):
            with urlopen(output, timeout=120) as response:
                return response.read()

        raise RuntimeError(f"Неизвестный формат ответа Replicate: {type(output)}")

    finally:
        for f in files:
            try:
                f.close()
            except Exception:
                pass


@dp.message(Command("start"))
async def start(message: Message):
    get_user(message.from_user.id)
    await message.answer(
        "👋 Привет!\n\n"
        "📸 Отправь мне фото, затем напиши, что нужно изменить.\n"
        "Можно использовать до 2 фото.\n\n"
        f"{available_generations(message.from_user.id)}\n\n"
        "Команды:\n"
        "/buy — купить генерации ⭐\n"
        "/balance — баланс\n"
        "/clear — очистить загруженные фото"
    )


@dp.message(Command("balance"))
async def balance(message: Message):
    await message.answer(available_generations(message.from_user.id))


@dp.message(Command("clear"))
async def clear(message: Message):
    pending_photos.pop(message.from_user.id, None)
    await message.answer("🗑 Фото очищены. Можешь отправить новое фото.")


@dp.message(Command("buy"))
async def buy(message: Message):
    await message.answer(
        "⭐ Выбери пакет:\n\n"
        "⭐ 50 Stars → 5 генераций\n"
        "⭐ 100 Stars → 10 генераций\n"
        "⭐ 150 Stars → 15 генераций\n\n"
        "Отправь команду:\n"
        "/buy50\n"
        "/buy100\n"
        "/buy150"
    )


async def send_invoice(message: Message, stars: int, generations: int):
    await message.answer_invoice(
        title=f"{generations} генераций",
        description=f"Пакет из {generations} генераций фотографий",
        payload=f"photo_pack_{stars}_{generations}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
        provider_token="",
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
    payment = message.successful_payment
    payload = payment.invoice_payload

    try:
        _, stars, generations = payload.split("_")
        generations = int(generations)
    except Exception:
        await message.answer("⚠️ Оплата получена, но пакет не удалось определить. Напиши администратору.")
        return

    user = get_user(message.from_user.id)
    user["balance"] += generations

    await message.answer(
        f"✅ Оплата прошла!\n"
        f"⭐ Добавлено генераций: {generations}\n\n"
        f"{available_generations(message.from_user.id)}"
    )


@dp.message(F.photo)
async def photo_received(message: Message):
    user_id = message.from_user.id
    photos = pending_photos.setdefault(user_id, [])

    if len(photos) >= 2:
        await message.answer(
            "⚠️ Можно использовать максимум 2 фото.\n"
            "Теперь напиши, что нужно сделать с ними."
        )
        return

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)

    buffer = BytesIO()
    await bot.download_file(file.file_path, buffer)

    photos.append(buffer.getvalue())

    if len(photos) == 1:
        await message.answer(
            "📸 Первое фото получил.\n\n"
            "Можешь отправить второе фото или сразу написать, что сделать."
        )
    else:
        await message.answer(
            "📸 Второе фото получил.\n\n"
            "Теперь напиши, что нужно сделать."
        )


@dp.message(F.text)
async def text_prompt(message: Message):
    user_id = message.from_user.id
    prompt = message.text.strip()

    if prompt.startswith("/"):
        return

    photos = pending_photos.get(user_id, [])
    if not photos:
        await message.answer("📸 Сначала отправь фото.")
        return

    if not prompt:
        await message.answer("✍️ Напиши, что нужно изменить.")
        return

    user = get_user(user_id)

    if not is_admin(user_id) and user["free"] <= 0 and user["balance"] <= 0:
        await message.answer(
            "❌ Генерации закончились.\n\n"
            "Используй /buy, чтобы купить новые генерации ⭐"
        )
        return

    status = await message.answer("⏳ Создаю фотографию. Подожди немного...")

    temp_paths = []
    try:
        for data in photos:
            temp_paths.append(await make_temp_file(data))

        image_bytes = await asyncio.to_thread(
            run_replicate_sync,
            temp_paths,
            prompt,
        )

        # Списываем только после успешной генерации.
        if not is_admin(user_id):
            if user["free"] > 0:
                user["free"] -= 1
            else:
                user["balance"] -= 1

        await status.delete()
        await message.answer_photo(
            types.BufferedInputFile(image_bytes, filename="generated.png"),
            caption="✨ Готово!",
        )

        pending_photos.pop(user_id, None)

    except Exception:
        logger.exception("Ошибка генерации")
        await status.edit_text(
            "❌ Не удалось создать фотографию.\n"
            "Попробуй ещё раз через несколько секунд.\n\n"
            "Генерация не списана."
        )

        # Фото оставляем, чтобы пользователь мог повторить запрос.


async def main():
    logger.info("Bot started with Replicate model: %s", MODEL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
