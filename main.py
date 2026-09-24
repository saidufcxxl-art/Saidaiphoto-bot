<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Photo Bot</title>
<style>
* {
    box-sizing: border-box;
}
body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    background: #f5f7fa;
    color: #222;
}
.header {
    background: white;
    border-bottom: 1px solid #e5e5e5;
    padding: 18px 25px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.logo {
    font-size: 25px;
    font-weight: 800;
    color: #168de2;
}
.telegram {
    background: #168de2;
    color: white;
    padding: 11px 18px;
    border-radius: 10px;
    text-decoration: none;
    font-weight: 700;
}
.container {
    max-width: 900px;
    margin: 35px auto;
    padding: 0 18px;
}
.hero {
    background: white;
    border-radius: 22px;
    padding: 45px 25px;
    text-align: center;
    box-shadow: 0 5px 25px rgba(0,0,0,.05);
}
.hero h1 {
    font-size: 34px;
    margin-bottom: 12px;
}
.hero p {
    color: #707070;
    font-size: 17px;
    line-height: 1.6;
}
.start {
    display: inline-block;
    margin-top: 20px;
    background: #168de2;
    color: white;
    text-decoration: none;
    padding: 15px 28px;
    border-radius: 12px;
    font-size: 17px;
    font-weight: bold;
}
.section {
    background: white;
    margin-top: 20px;
    padding: 25px;
    border-radius: 20px;
}
.section h2 {
    margin-top: 0;
}
.steps {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 15px;
}
.step {
    background: #f7f8fa;
    padding: 20px;
    border-radius: 16px;
}
.number {
    width: 35px;
    height: 35px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #168de2;
    color: white;
    border-radius: 50%;
    font-weight: bold;
    margin-bottom: 12px;
}
.prices {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 15px;
}
.price {
    border: 1px solid #e2e2e2;
    border-radius: 17px;
    padding: 25px 15px;
    text-align: center;
}
.price strong {
    font-size: 27px;
    display: block;
}
.price .photos {
    color: #777;
    margin: 10px 0 18px;
}
.buy {
    display: block;
    background: #168de2;
    color: white;
    text-decoration: none;
    padding: 11px;
    border-radius: 10px;
    font-weight: bold;
}
.free {
    background: #e9f7ee;
    border: 1px solid #b8e4c5;
    border-radius: 16px;
    padding: 18px;
    margin-top: 15px;
}
.examples {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}
.example {
    background: #f7f8fa;
    padding: 17px;
    border-radius: 13px;
}
.footer {
    text-align: center;
    color: #888;
    padding: 35px 10px;
    font-size: 13px;
}
@media(max-width: 650px) {
    .steps,
    .prices,
    .examples {
        grid-template-columns: 1fr;
    }
    .hero h1 {
        font-size: 27px;
    }
}
</style>
</head>
<body>
<header class="header">
    <div class="logo">
        AI PHOTO
    </div>
    <a
        class="telegram"
        href="https://t.me/YOUR_BOT_USERNAME"
        target="_blank"
    >
        Открыть бота
    </a>
</header>
<main class="container">
    <section class="hero">
        <h1>
            Создавай фотографии с помощью ИИ
        </h1>
        <p>
            Загрузи фотографию и напиши обычными словами,
            что хочешь изменить.
            ИИ создаст новую реалистичную фотографию.
        </p>
        <a
            class="start"
            href="https://t.me/YOUR_BOT_USERNAME"
            target="_blank"
        >
            🚀 Запустить бота
        </a>
    </section>
    <section class="section">
        <h2>
            🎁 2 фотографии бесплатно
        </h2>
        <div class="free">
            Каждый новый пользователь получает
            <b>2 бесплатные генерации</b>.
            <br><br>
            После использования бесплатных генераций
            можно купить дополнительные фотографии
            за Telegram Stars ⭐.
        </div>
    </section>
    <section class="section">
        <h2>
            Как это работает
        </h2>
        <div class="steps">
            <div class="step">
                <div class="number">
                    1
                </div>
                <b>Отправь фото</b>
                <p>
                    Отправь одну или несколько фотографий
                    в Telegram-бот.
                </p>
            </div>
            <div class="step">
                <div class="number">
                    2
                </div>
                <b>Напиши запрос</b>
                <p>
                    Напиши обычными словами,
                    что нужно изменить.
                </p>
            </div>
            <div class="step">
                <div class="number">
                    3
                </div>
                <b>Получи результат</b>
                <p>
                    ИИ обработает фотографию
                    и отправит готовый результат.
                </p>
            </div>
        </div>
    </section>
    <section class="section">
        <h2>
            Что можно сделать?
        </h2>
        <div class="examples">
            <div class="example">
                🚗 Добавить рядом машину
            </div>
            <div class="example">
                🏖️ Поменять фон
            </div>
            <div class="example">
                👕 Изменить одежду
            </div>
            <div class="example">
                🏙️ Переместить в другое место
            </div>
            <div class="example">
                🖤 Сделать чёрно-белое фото
            </div>
            <div class="example">
                ✨ Улучшить качество
            </div>
            <div class="example">
                👤 Изменить отдельные детали
            </div>
            <div class="example">
                🎬 Создать кинематографический стиль
            </div>
        </div>
    </section>
    <section class="section">
        <h2>
            ⭐ Пакеты генераций
        </h2>
        <div class="prices">
            <div class="price">
                <strong>
                    50 ⭐
                </strong>
                <div class="photos">
                    5 фотографий
                </div>
                <a
                    class="buy"
                    href="https://t.me/YOUR_BOT_USERNAME"
                >
                    Купить
                </a>
            </div>
            <div class="price">
                <strong>
                    100 ⭐
                </strong>
                <div class="photos">
                    10 фотографий
                </div>
                <a
                    class="buy"
                    href="https://t.me/YOUR_BOT_USERNAME"
                >
                    Купить
                </a>
            </div>
            <div class="price">
                <strong>
                    150 ⭐
                </strong>
                <div class="photos">
                    15 фотографий
                </div>
                <a
                    class="buy"
                    href="https://t.me/YOUR_BOT_USERNAME"
                >
                    Купить
                </a>
            </div>
        </div>
    </section>
    <section class="section">
        <h2>
            🔐 Безопасность
        </h2>
        <p>
            Фотографии используются только для выполнения
            запроса пользователя. Не отправляй документы,
            банковские данные и другую конфиденциальную информацию.
        </p>
    </section>
    <section class="hero" style="margin-top:20px;">
        <h2>
            Готов попробовать?
        </h2>
        <p>
            Получи 2 фотографии бесплатно.
        </p>
        <a
            class="start"
            href="https://t.me/YOUR_BOT_USERNAME"
            target="_blank"
        >
            🚀 Запустить AI Photo
        </a>
    </section>
    <footer class="footer">
        AI Photo © 2026
    </footer>
</main>
</body>
</html>
