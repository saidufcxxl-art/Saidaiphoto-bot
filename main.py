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

# Хранилище: кто ждёт второе фото или промпт
waiting_for_second_photo = {}  # user_id -> {"first_photo": file_id}
waiting_for_prompt = {}        # user_id -> {"first_photo": file_id, "second_photo": file_id}

def is_admin(user_id):
    return user_id in ADMIN_IDS

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        users[user_id] = {'last_free_date': None, 'paid_credits': 0}
    if is_admin(user_id):
        text = (
            "Привет, админ! 👑\n\n"
            "У тебя безлимит.\n\n"
            "📸 Отправь первое фото (себя), потом второе (пример сцены)."
        )
    else:
        text = (
            "Привет! Я бот для создания ИИ-фото. 🤖\n\n"
            "📸 1 фото в день — бесплатно!\n"
            "Остальное — за звёзды ⭐\n\n"
            "Как пользоваться:\n"
            "1. Отправь своё фото (себя)\n"
            "2. Потом отправь второе фото (пример: где хочешь оказаться)\n"
            "3. Получи готовое фото!"
        )
    await message.answer(text)

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    user_data = users.get(user_id, {'last_free_date': None, 'paid_credits': 0})
    today = "2026-09-24"

    if not is_admin(user_id):
        if user_data['last_free_date'] == today and user_data['paid_credits'] <= 0:
            await message.answer("На сегодня бесплатные фото закончились. 😔\nКупи пакет за звёзды! Напиши /buy.")
            return

    file_id = message.photo[-1].file_id
    caption = message.caption

    # Если это первое фото (ещё нет waiting_for_second_photo)
    if user_id not in waiting_for_second_photo:
        waiting_for_second_photo[user_id] = {"first_photo": file_id}
        await message.answer(
            "Первое фото получил! 📸\n\n"
            "Теперь отправь **второе фото** — пример сцены, куда хочешь попасть.\n"
            "Например: фото пляжа, гор, другого города."
        )
        return

    # Если это второе фото
    if user_id in waiting_for_second_photo:
        first_photo = waiting_for_second_photo[user_id]["first_photo"]
        second_photo = file_id
        waiting_for_second_photo.pop(user_id)

        # Если есть подпись — сразу генерируем
        if caption:
            await generate_and_send(message, first_photo, second_photo, caption, user_id)
        else:
            # Если подписи нет — просим написать, что сделать
            waiting_for_prompt[user_id] = {"first_photo": first_photo, "second_photo": second_photo}
            await message.answer(
                "Второе фото получил! 📸\n\n"
                "Теперь напиши, что сделать. Например:\n"
                "«Помести меня на этот пляж» или «Сделай меня в этой сцене»."
            )
        return

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    if user_id in waiting_for_prompt:
        data = waiting_for_prompt.pop(user_id)
        await generate_and_send(message, data["first_photo"], data["second_photo"], message.text, user_id)
        return
    if message.text.startswith("/"):
        return
    await message.answer("Отправь мне первое фото, потом второе — и я сделаю с ними то, что ты попросишь. 📸")

async def generate_and_send(message: Message, first_photo_id: str, second_photo_id: str, prompt: str, user_id: int):
    await message.answer("Генерирую... ⏳ (это займёт до 1 минуты)")
    try:
        # Получаем ссылки на оба фото
        file1 = await bot.get_file(first_photo_id)
        file_url1 = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file1.file_path}"

        file2 = await bot.get_file(second_photo_id)
        file_url2 = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file2.file_path}"

        # Вызываем модель multi-image-kontext-max
        final_output = replicate.run(
            "flux-kontext-apps/multi-image-kontext-max",
            input={
                "prompt": prompt,
                "input_image_1": file_url1,
                "input_image_2": file_url2,
                "aspect_ratio": "1:1",
                "output_format": "jpg",
                "safety_tolerance": 2
            }
        )
        if isinstance(final_output, list):
            result_url = final_output[0]
        else:
            result_url = str(final_output)
        await message.answer_photo(result_url, caption="Готово! 🎉")
        users[user_id]['last_free_date'] = "2026-09-24"
    except Exception as e:
        await message.answer(f"Ошибка генерации: {e}")

@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    prices = [LabeledPrice(label="Пакет 'Мини' (5 фото)", amount=150)]
    await message.answer_invoice(
        title="Пакет ИИ-фото",
        description="5 генераций без водяного знака",
        payload="buy_5_credits",
        currency="XTR",
        prices=prices
    )

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = message.from_user.id
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
