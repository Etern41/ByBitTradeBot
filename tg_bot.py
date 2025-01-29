import asyncio
import logging
from telegram import Update, Bot, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
)
from autotrade import start_auto_trade, stop_auto_trade, auto_trade_active
from bybit_client import BybitAPI
from indicators import IndicatorCalculator
from config import TELEGRAM_API_TOKEN, TRADE_PAIRS, ADMIN_CHAT_ID

# Настройка логов
logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger("telegram").setLevel(logging.CRITICAL)

print("✅ Бот запущен и готов к работе!")

bot = Bot(token=TELEGRAM_API_TOKEN)
bybit_client = BybitAPI()
indicator_calc = IndicatorCalculator()


def main_menu():
    """Возвращает клавиатуру главного меню"""
    return ReplyKeyboardMarkup(
        [
            ["▶️ Запустить автоторговлю", "⏹ Остановить автоторговлю"],
            ["📊 Баланс", "📈 Индикаторы"],
            ["⚙️ Управление парами"],
            ["🔄 Перезапустить"],
        ],
        resize_keyboard=True,
    )


async def send_startup_message(application: Application):
    """Асинхронно отправляет сообщение о запуске бота"""
    try:
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="✅ Бот успешно запущен и готов к работе!\nВы можете управлять ботом через меню.",
        )
    except Exception as e:
        logging.error(f"❌ Ошибка отправки startup message: {e}")


async def start(update: Update, context: CallbackContext) -> None:
    """Команда /start: отображает главное меню"""
    await update.message.reply_text(
        "Привет! Я трейд-бот для Bybit.\n\n"
        "📌 Доступные команды:\n"
        "▶️ Запустить автоторговлю - Включает автоторговлю\n"
        "⏹ Остановить автоторговлю - Останавливает автоторговлю\n"
        "📊 Баланс - Проверить баланс\n"
        "📈 Индикаторы - Показать RSI, MACD, SMA\n"
        "⚙️ Управление парами - Изменить список торговых пар\n"
        "🔄 Перезапустить - Перезапускает бота",
        reply_markup=main_menu(),
    )


async def indicators(update: Update, context: CallbackContext) -> None:
    """Команда /indicators: показывает RSI, MACD, SMA, BB в таблице"""
    try:
        result = indicator_calc.calculate_indicators()
        if not result:
            await update.message.reply_text("❌ Ошибка получения индикаторов")
            return
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"❌ Ошибка в /indicators: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def balance(update: Update, context: CallbackContext) -> None:
    """Команда /balance: показывает баланс аккаунта"""
    try:
        result = bybit_client.get_wallet_balance()
        if not result:
            await update.message.reply_text("❌ Ошибка получения баланса")
            return
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"❌ Ошибка в /balance: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def button_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает кнопки меню"""
    text = update.message.text

    if text == "▶️ Запустить автоторговлю":
        await update.message.reply_text(start_auto_trade())

    elif text == "⏹ Остановить автоторговлю":
        await update.message.reply_text(stop_auto_trade())

    elif text == "📊 Баланс":
        await balance(update, context)

    elif text == "📈 Индикаторы":
        await indicators(update, context)


def main():
    """Запуск бота"""
    app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # ✅ Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("indicators", indicators))
    app.add_handler(CommandHandler("balance", balance))

    # ✅ Обработчик текстовых сообщений (кнопки)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    loop = asyncio.get_event_loop()
    loop.create_task(send_startup_message(app))

    print("📡 Бот запущен, начинаю polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
