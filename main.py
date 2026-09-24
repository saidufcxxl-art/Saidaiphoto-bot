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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)
users = {}

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        users[user_id] = {'last_free_date': None, 'paid_credits': 0}
    await message.answer(
        "Привет! Я бот для создания ИИ-фото. 🤖\n\n"
        "📸 1 фото в день — бесплатно!\n"
        "Остальное — за звёзды ⭐\n\n"
        "Просто отправь мне своё фото!"
    )

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    user_data = users.get(user_id, {'last_free_date': None, 'paid_credits': 0})
    today = "2026-09-24"
    if user_data['last_free_date'] == today and user_data['paid_credits'] <= 0:
        await message.answer("На сегодня бесплатные фото закончились. 😔\nКупи пакет за звёзды! Напиши /buy.")
        return
    await message.answer("Фото получил! Генерирую... ⏳")
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    ttry:
        face_output = replicate.run(
            "fofr/face-to-many:a07f252abbbd832009640b27f063ea52d87d7a23a185ca165bec23b5adc8deaf",
            input={
                "image": file_url,
                "style": "Video game",
                "prompt": "high quality, detailed face, cinematic lighting",
                "negative_prompt": "blurry, low quality, distorted",
                "instant_id_strength": 1.0
            }
        )
        face_image_url = face_output[0].url() if isinstance(face_output, list) else str(face_output)

        final_output = replicate.run(
            "black-forest-labs/flux-kontext-dev",
            input={
                "image": face_image_url,
                "prompt": "change the background to a beach, keep the person exactly the same",
                "aspect_ratio": "1:1"
            }
        )
        
        if isinstance(final_output, list):
            result_url = final_output[0]
        else:
            result_url = str(final_output)
            
        await message.answer_photo(result_url, caption="Готово! 🎉")
        users[user_id]['last_free_date'] = today

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
