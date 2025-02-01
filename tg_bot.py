import json
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

from autotrade import (
    start_auto_trade,
    stop_auto_trade,
    update_trade_pairs,
    auto_trade_active,
    active_orders
)
from bybit_client import BybitAPI
from indicators import IndicatorCalculator
from config import TELEGRAM_API_TOKEN, ADMIN_CHAT_ID, TRADE_PAIRS
from pair_manager import PairManager

pair_manager = PairManager()


# ✅ Настройка логов
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

print("✅ Бот запущен и готов к работе!")

bot = Bot(token=TELEGRAM_API_TOKEN)
bybit_client = BybitAPI()
indicator_calc = IndicatorCalculator()


def load_trade_pairs():
    try:
        with open("config.json", "r") as file:
            config_data = json.load(file)
            return config_data.get("TRADE_PAIRS", [])  # ✅ Загружаем пары
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main_menu():
    """Возвращает клавиатуру главного меню"""
    return ReplyKeyboardMarkup(
        [
            ["▶️ Запустить автоторговлю", "⏹ Остановить автоторговлю"],
            ["📊 Баланс", "📈 Индикаторы"],
            ["🔄 Обновить торговые пары", "📉 Позиции"],
        ],
        resize_keyboard=True,
    )


async def positions(update: Update, context: CallbackContext) -> None:
    """Команда /positions: показывает активные позиции с данными трейлинга"""
    if not active_orders:
        await update.message.reply_text("Нет активных позиций.")
        return
    msg = "📉 *Активные позиции:*\n"
    for pair, info in active_orders.items():
        if info:
            msg += (
                f"• {pair}: Ордер {info.get('order_id')}, "
                f"Сторона: {info.get('side')}, Вход: {info.get('entry_price'):.2f}, "
                f"Размер: {info.get('order_size')} USDT\n"
            )
    await update.message.reply_text(msg, parse_mode="Markdown")


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
        "Привет! Я трейд-бот для Bybit.", reply_markup=main_menu()
    )


async def balance(update: Update, context: CallbackContext) -> None:
    """Команда /balance: показывает баланс аккаунта"""
    try:
        result = bybit_client.get_wallet_balance(as_report=True)
        if not result:
            await update.message.reply_text("❌ Ошибка получения баланса")
            return
        # Экранируем нижние подчеркивания, чтобы Markdown правильно их обработал.
        result = result.replace("_", r"\_")
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"❌ Ошибка в /balance: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def indicators(update: Update, context: CallbackContext) -> None:
    """Команда /indicators: анализирует RSI, MACD, SMA и возвращает таблицу"""
    try:
        updated_pairs = load_trade_pairs()
        result = indicator_calc.calculate_indicators(updated_pairs)
        if not result:
            await update.message.reply_text("❌ Ошибка получения индикаторов")
            return
        await update.message.reply_text(result, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"❌ Ошибка в /indicators: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def update_pairs(update: Update, context: CallbackContext):
    """Команда 'Обновить торговые пары'"""
    await update.message.reply_text("📡 Обновление списка торговых пар...")
    await update_trade_pairs()
    await update.message.reply_text("✅ Торговые пары обновлены!")


async def button_handler(update: Update, context: CallbackContext) -> None:
    global auto_trade_active
    text = update.message.text

    if text == "▶️ Запустить автоторговлю":
        if auto_trade_active:
            await update.message.reply_text("⚠️ Автоторговля уже запущена!")
        else:
            auto_trade_active = True
            asyncio.create_task(start_auto_trade())
    elif text == "⏹ Остановить автоторговлю":
        if not auto_trade_active:
            await update.message.reply_text("⚠️ Автоторговля уже остановлена!")
        else:
            auto_trade_active = False
            await update.message.reply_text("⏹ Автоторговля остановлена!")
    elif text == "📊 Баланс":
        await balance(update, context)
    elif text == "📈 Индикаторы":
        await indicators(update, context)
    elif text == "🔄 Обновить торговые пары":
        await update_pairs(update, context)
        await update.message.reply_text(
            f"✅ Торговые пары сохранены: {', '.join(TRADE_PAIRS)}",
            reply_markup=main_menu(),
        )
    elif text == "📉 Позиции":
        await positions(update, context)


def main():
    app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("indicators", indicators))
    app.add_handler(CommandHandler("update_pairs", update_pairs))
    app.add_handler(CommandHandler("positions", positions))  # Новый обработчик

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    loop = asyncio.get_event_loop()
    loop.create_task(send_startup_message(app))

    print("📡 Бот запущен, начинаю polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
