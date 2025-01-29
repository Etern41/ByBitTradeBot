import time
import json
import asyncio
import logging
import re
from config import (
    TRADE_PAIRS,
    ADMIN_CHAT_ID,
    TELEGRAM_API_TOKEN,
    AUTO_UPDATE_PAIRS,
    UPDATE_INTERVAL,
    MIN_VOLUME_USDT,
    MAX_VOLATILITY,
)
from telegram import Bot
from bybit_client import BybitAPI
from indicators import IndicatorCalculator
from pair_manager import PairManager

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

pair_manager = PairManager()
first_signal_check = True


def extract_balance_from_text(balance_text):
    """Извлекает числовое значение USDT из текста баланса"""
    match = re.search(r"💳 \*Общий баланс:\* ([\d,]+\.?\d*) USDT", balance_text)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0  # Если не найдено, считаем, что баланса нет


async def start_auto_trade():
    """Асинхронный запуск автоторговли (не запускается при 0 балансе)"""
    global auto_trade_active
    if auto_trade_active:
        return "⚠️ Автоторговля уже запущена!"

    # ✅ Проверяем баланс перед запуском
    balance = bybit_client.get_wallet_balance()

    try:
        balance = float(balance)  # 🔥 Преобразуем строку в число
    except (TypeError, ValueError):
        balance = 0  # ❗ Если ошибка, считаем баланс 0

    if balance <= 0:
        await bot.send_message(
            ADMIN_CHAT_ID,
            "⚠️ Недостаточно средств для торговли! Автоторговля не запущена.",
        )
        logging.warning("⛔ Недостаточно средств. Автоторговля НЕ запущена!")
        return  # ❌ НЕ включаем `auto_trade_active`

    auto_trade_active = True
    logging.info("✅ Автоторговля запущена!")
    await bot.send_message(ADMIN_CHAT_ID, "✅ Автоторговля запущена!")

    while auto_trade_active:
        try:
            await trade_logic()
            await asyncio.sleep(30)
        except Exception as e:
            logging.error(f"❌ Ошибка в автоторговле: {e}")
            await bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибка в автоторговле: {e}")

    logging.info("⏹ Автоторговля остановлена!")
    await bot.send_message(ADMIN_CHAT_ID, "⏹ Автоторговля остановлена!")


def stop_auto_trade():
    """Останавливает автоторговлю"""
    global auto_trade_active
    auto_trade_active = False
    logging.info("⏹ Автоторговля остановлена!")
    return "⏹ Автоторговля остановлена!"


async def trade_logic():
    """Основная логика принятия решений"""
    global active_orders, first_signal_check
    trading_pairs = pair_manager.get_active_pairs()
    signals = indicator_calc.calculate_signals(trading_pairs)

    # ✅ Получаем баланс перед торговлей
    balance_text = bybit_client.get_wallet_balance()
    balance = extract_balance_from_text(balance_text)

    if balance == 0:
        await bot.send_message(ADMIN_CHAT_ID, "⚠️ Недостаточно средств для торговли!")
        logging.warning("⚠️ Недостаточно средств для торговли!")
        return  # ❌ Выходим, если денег нет

    # ✅ Проверяем, нужно ли отправлять отчет
    send_report = first_signal_check  # Отправить, если первый запуск
    report = "📡 *Проверка сигналов*\n"

    for pair, (signal, strength) in signals.items():
        report += f"📊 {pair}: {signal} (Сила: {strength})\n"

    if send_report:
        await bot.send_message(ADMIN_CHAT_ID, report, parse_mode="Markdown")
        first_signal_check = False  # ❗ После первого раза больше не отправляем

    for pair, (signal, strength) in signals.items():
        if strength < 1:
            continue

        if active_orders.get(pair):
            logging.info(f"⚠️ {pair}: Уже есть активный ордер, пропускаем.")
            continue

        order_size = calculate_order_size(balance, strength)
        if order_size == 0:
            logging.warning(f"⚠️ {pair}: Слишком маленький баланс для сделки")
            continue

        side = "Buy" if signal == "BUY" else "Sell"
        response = await bybit_client.create_order(pair, side, order_size)

        if response:
            logging.info(f"✅ {pair}: Ордер {side} на {order_size} USDT размещен!")
            active_orders[pair] = response.get("orderId")

            # ✅ После ордера отправляем `📡 Проверка сигналов` ещё раз
            await bot.send_message(ADMIN_CHAT_ID, report, parse_mode="Markdown")

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


async def update_trade_pairs():
    """Автообновление списка торговых пар (ТОП-15 по объему, исключая стейблкоины, кроме USDT)"""
    print("📡 Обновление списка торговых пар...")
    all_pairs = bybit_client.get_spot_pairs()

    if not all_pairs:
        print("❌ Ошибка получения пар!")
        return

    stablecoins = {"USDC", "BUSD", "DAI", "TUSD", "FDUSD", "EURS"}
    pair_volumes = []

    for pair in all_pairs:
        symbol = pair["symbol"]
        volume = float(pair.get("turnover24h", 0))  # Объем торгов за 24ч

        # ✅ Оставляем только пары с USDT и без стейблкоинов
        if "USDT" in symbol and not any(stable in symbol for stable in stablecoins):
            pair_volumes.append((symbol, volume))

    # ✅ Сортируем пары по объему и берем ТОП-15
    pair_volumes.sort(key=lambda x: x[1], reverse=True)
    top_pairs = [pair[0] for pair in pair_volumes[:15]]

    global TRADE_PAIRS
    TRADE_PAIRS = top_pairs

    with open("config.json", "w") as file:
        json.dump({"TRADE_PAIRS": top_pairs}, file, indent=4)

    msg = (
        f"✅ Обновлено {len(top_pairs)} пар!\n📊 Торговые пары: {', '.join(top_pairs)}"
    )
    print(msg)
    await bot.send_message(ADMIN_CHAT_ID, msg)


def start_background_tasks():
    """Запускает фоновые задачи в основном event loop"""
    loop = asyncio.get_event_loop()
    loop.create_task(update_trade_pairs())


if AUTO_UPDATE_PAIRS:
    start_background_tasks()
