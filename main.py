import asyncio
import logging
import os
import replicate
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice
from aiohttp import web

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)
users = {}

# Хранилище: user_id -> список file_id фото, которые ждут обработки
pending_photos = {}   # user_id -> [file_id1, file_id2, ...]
waiting_for_prompt = {}  # user_id -> [file_id1, ...]

def is_admin(user_id):
    return user_id in ADMIN_IDS

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        users[user_id] = {'last_free_date': None, 'paid_credits': 0}
    if is_admin(user_id):
        text = (
            "Привет, админ! 👑\n\nУ тебя безлимит.\n\n"
            "📸 Отправь 1 или несколько фото, потом напиши, что сделать."
        )
    else:
        text = (
            "Привет! Я бот для создания ИИ-фото. 🤖\n\n"
            "📸 1 фото в день — бесплатно!\nОстальное — за звёзды ⭐\n\n"
            "Как пользоваться:\n"
            "1. Отправь 1 или 2 фото (себя + пример сцены)\n"
            "2. Напиши, что сделать\n"
            "3. Получи результат!"
        )
    await message.answer(text)

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    pending_photos.pop(user_id, None)
    waiting_for_prompt.pop(user_id, None)
    await message.answer("Очищено. Отправь новые фото. 📸")

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    user_data = users.get(user_id, {'last_free_date': None, 'paid_credits': 0})
    today = "2026-09-24"

    if not is_admin(user_id):
        if user_data['last_free_date'] == today and user_data['paid_credits'] <= 0:
            await message.answer("На сегодня бесплатные фото закончились. 😔\nКупи пакет: /buy")
            return

    file_id = message.photo[-1].file_id
    caption = message.caption

    # Добавляем фото в список
    if user_id not in pending_photos:
        pending_photos[user_id] = []
    pending_photos[user_id].append(file_id)

    # Если есть подпись — сразу генерируем
    if caption:
        photos = pending_photos.pop(user_id)
        await generate_and_send(message, photos, caption, user_id)
        return

    # Иначе — сообщаем, сколько уже собрано
    count = len(pending_photos[user_id])
    if count == 1:
        await message.answer(
            "Фото получил! 📸\n\n"
            "Можешь:\n"
            "• Отправить **второе фото** (пример сцены)\n"
            "• Или написать, что сделать с одним фото\n\n"
            "Если хочешь начать заново — /clear"
        )
    else:
        await message.answer(
            f"Фото получил! Всего: {count} 📸\n\n"
            "Теперь напиши, что сделать (например: «Помести меня в эту сцену»)."
        )

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    if message.text.startswith("/"):
        return

    # Если у юзера есть фото в очереди — генерируем
    if user_id in pending_photos and pending_photos[user_id]:
        photos = pending_photos.pop(user_id)
        await generate_and_send(message, photos, message.text, user_id)
        return

    await message.answer("Сначала отправь мне фото, потом напиши, что с ним сделать. 📸")

async def generate_and_send(message: Message, photo_ids: list, prompt: str, user_id: int):
    await message.answer("Генерирую... ⏳ (до 2 минут)")
    try:
        file_urls = []
        for fid in photo_ids[:2]:  # максимум 2 фото
            f = await bot.get_file(fid)
            file_urls.append(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}")

        high_quality = "Photorealistic, ultra high quality, 8k, detailed, cinematic lighting, sharp focus, professional photography"
        full_prompt = f"{prompt}. {high_quality}"

        # ОДНО фото — просто редактируем
        if len(file_urls) == 1:
            output = replicate.run(
                "black-forest-labs/flux-kontext-dev",
                input={
                    "input_image": file_urls[0],
                    "prompt": full_prompt,
                    "aspect_ratio": "1:1",
                    "output_format": "png",
                    "safety_tolerance": 2
                }
            )
        # ДВА+ фото — multi-image (перенос персонажа в сцену)
        else:
            output = replicate.run(
                "flux-kontext-apps/multi-image-kontext-max",
                input={
                    "prompt": full_prompt,
                    "input_image_1": file_urls[0],
                    "input_image_2": file_urls[1],
                    "aspect_ratio": "1:1",
                    "output_format": "png",
                    "safety_tolerance": 2
                }
            )

        if isinstance(output, list):
            result_url = output[0]
        else:
            result_url = str(output)
        await message.answer_photo(result_url, caption="Готово! 🎉")
        users[user_id]['last_free_date'] = "2026-09-24"
    except Exception as e:
        await message.answer(f"Ошибка генерации: {e}")

@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    prices = [LabeledPrice(label="Пакет 'Мини' (5 фото)", amount=150)]
    await message.answer_invoice(
        title="Пакет ИИ-фото", description="5 генераций без водяного знака",
        payload="buy_5_credits", currency="XTR", prices=prices
    )

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        users[user_id] = {'last_free_date': None, 'paid_credits': 0}
    users[user_id]['paid_credits'] += 5
    await message.answer("Оплата прошла! Начислено 5 кредитов. 🎉")

async def handle(request):
    return web.Response(text="Bot is running")

async def main():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
