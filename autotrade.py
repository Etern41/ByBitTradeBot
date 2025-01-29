import asyncio
import logging
from config import TRADE_PAIRS, ADMIN_CHAT_ID, TELEGRAM_API_TOKEN
from bybit_client import BybitAPI
from indicators import IndicatorCalculator
from telegram import Bot

# ✅ Настройка логов
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# ✅ Глобальная переменная для статуса автоторговли
auto_trade_active = False

# ✅ Инициализация API и индикаторов
bybit_client = BybitAPI()
indicator_calc = IndicatorCalculator()
bot = Bot(TELEGRAM_API_TOKEN)

# ✅ Храним активные ордера
active_orders = {pair: None for pair in TRADE_PAIRS}


async def start_auto_trade():
    """Асинхронный запуск автоторговли"""
    global auto_trade_active
    if auto_trade_active:
        return "⚠️ Автоторговля уже запущена!"

    auto_trade_active = True
    logging.info("✅ Автоторговля запущена!")

    while auto_trade_active:
        try:
            await trade_logic()  # ⚡ Асинхронная проверка сигналов
            await asyncio.sleep(30)  # 🔄 Ждём 30 секунд перед следующей проверкой
        except Exception as e:
            logging.error(f"❌ Ошибка в автоторговле: {e}")
            await bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибка в автоторговле: {e}")

    logging.info("⏹ Автоторговля остановлена!")


def stop_auto_trade():
    """Останавливает автоторговлю"""
    global auto_trade_active
    auto_trade_active = False
    logging.info("⏹ Автоторговля остановлена!")
    return "⏹ Автоторговля остановлена!"


async def trade_logic():
    """Основная логика принятия решений"""
    global active_orders

    # ✅ Не отправляем проверку сигналов, если автоторговля выключена
    if not auto_trade_active:
        return

    signals = indicator_calc.calculate_signals()

    # ✅ Формируем отчет о проверке сигналов
    report = "📡 *Проверка сигналов*\n"
    for pair, (signal, strength) in signals.items():
        report += f"📊 {pair}: {signal} (Сила: {strength})\n"

    # ✅ Отправляем отчет о проверке в Telegram (раз в цикл)
    if auto_trade_active:
        await bot.send_message(ADMIN_CHAT_ID, report, parse_mode="Markdown")

    for pair, (signal, strength) in signals.items():
        # ✅ Игнорируем слабые сигналы
        if strength < 1:
            continue

        # ✅ Проверяем, есть ли уже активный ордер
        if active_orders.get(pair):
            logging.info(f"⚠️ {pair}: Уже есть активный ордер, пропускаем.")
            continue

        # ✅ Получаем баланс
        balance = bybit_client.get_balance("USDT")
        if balance is None:
            logging.warning("❌ Ошибка получения баланса!")
            continue

        # ✅ Рассчитываем объем ордера
        order_size = calculate_order_size(balance, strength)
        if order_size == 0:
            logging.warning(f"⚠️ {pair}: Слишком маленький баланс для сделки")
            continue

        # ✅ Размещение ордера
        side = "Buy" if signal == "BUY" else "Sell"
        response = await bybit_client.create_order(pair, side, order_size)

        if response:
            logging.info(f"✅ {pair}: Ордер {side} на {order_size} USDT размещен!")
            active_orders[pair] = response.get("orderId")

            # ✅ Уведомление в Telegram о новом ордере
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *{pair}*: Открыт ордер `{side}` на *{order_size}* USDT",
                parse_mode="Markdown",
            )
        else:
            logging.error(f"❌ {pair}: Ошибка при размещении ордера")


def calculate_order_size(balance, strength):
    """Динамически рассчитывает объем ордера"""
    percent = 0.01 * strength  # Слабый сигнал - 1%, сильный - 2%, максимум - 5%
    order_size = balance * min(percent, 0.05)  # 🔥 Не больше 5% баланса
    return round(order_size, 2)  # Округляем до 2 знаков
