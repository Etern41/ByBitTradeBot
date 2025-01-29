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
from config import TELEGRAM_API_TOKEN, ADMIN_CHAT_ID, TRADE_PAIRS
from pair_manager import PairManager

pair_manager = PairManager()

# ✅ Настройка логов
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


async def indicators(update: Update, context: CallbackContext) -> None:
    """Команда /indicators: анализирует RSI, MACD, SMA и возвращает таблицу"""
    try:
        result = indicator_calc.calculate_indicators()
        if not result:
            await update.message.reply_text("❌ Ошибка получения индикаторов")
            return
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"❌ Ошибка в /indicators: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def trade_pairs(update: Update, context: CallbackContext) -> None:
    """Команда /trade_pairs: изменяет список торговых пар"""
    keyboard = [[pair] for pair in TRADE_PAIRS]
    keyboard.append(["✅ Сохранить"])

    await update.message.reply_text(
        "Выберите торговые пары (нажимайте для включения/выключения):",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def button_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает кнопки меню"""
    global auto_trade_active
    text = update.message.text

    if text == "▶️ Запустить автоторговлю":
        if auto_trade_active:
            await update.message.reply_text("⚠️ Автоторговля уже запущена!")
        else:
            auto_trade_active = True
            asyncio.create_task(start_auto_trade())  # ✅ Запуск автоторговли в фоне
            await update.message.reply_text("✅ Автоторговля запущена!")

    elif text == "⏹ Остановить автоторговлю":
        if not auto_trade_active:
            await update.message.reply_text("⚠️ Автоторговля уже остановлена!")
        else:
            auto_trade_active = False
            await update.message.reply_text(stop_auto_trade())

    elif text == "📊 Баланс":
        await balance(update, context)

    elif text == "📈 Индикаторы":
        await indicators(update, context)

    elif text == "⚙️ Управление парами":
        await trade_pairs(update, context)

    elif text == "✅ Сохранить":
        await update.message.reply_text(
            f"✅ Торговые пары сохранены: {', '.join(TRADE_PAIRS)}",
            reply_markup=main_menu(),
        )


async def list_pairs(update: Update, context: CallbackContext) -> None:
    """Команда /pairs: Показывает текущие торговые пары"""
    pairs = pair_manager.get_pairs()
    await update.message.reply_text("📌 Текущие пары:\n" + "\n".join(pairs))


async def add_pair(update: Update, context: CallbackContext) -> None:
    """Команда /addpair BTCUSDT: Добавляет новую пару"""
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Использование: /addpair BTCUSDT")
        return

    pair = context.args[0].upper()
    response = pair_manager.add_pair(pair)
    await update.message.reply_text(response)


async def remove_pair(update: Update, context: CallbackContext) -> None:
    """Команда /removepair BTCUSDT: Удаляет пару"""
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Использование: /removepair BTCUSDT")
        return

    pair = context.args[0].upper()
    response = pair_manager.remove_pair(pair)
    await update.message.reply_text(response)


def main():
    """Запуск бота"""
    app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # ✅ Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("indicators", indicators))
    app.add_handler(CommandHandler("trade_pairs", trade_pairs))
    app.add_handler(CommandHandler("pairs", list_pairs))
    app.add_handler(CommandHandler("addpair", add_pair))
    app.add_handler(CommandHandler("removepair", remove_pair))

    # ✅ Обработчик текстовых сообщений (кнопки)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    loop = asyncio.get_event_loop()
    loop.create_task(send_startup_message(app))

    print("📡 Бот запущен, начинаю polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
