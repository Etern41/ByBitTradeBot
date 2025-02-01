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
    TRADE_INTERVAL,
    TRAILING_STOP_PERCENT,
    TRAILING_TAKE_PROFIT_PERCENT,
    MIN_ORDER_USDT,
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
active_orders = {}

pair_manager = PairManager()
first_signal_check = True
active_orders = {}  # Ключ: торговая пара, значение: словарь с данными ордера

# Порог проверки для обновления trailing (интервал в секундах для мониторинга)
TRAILING_CHECK_INTERVAL = 10


async def monitor_position(pair, order_info):
    """
    Мониторинг открытой позиции с динамическим трейлинг стоп‑лосс и тейк‑профитом.
    """

    entry_price = order_info["entry_price"]
    side = order_info["side"]
    order_size = order_info["order_size"]
    max_price = entry_price  # для позиции BUY
    # Для реинтри входа зададим cooldown и порог, например:
    REENTRY_TRIGGER_PERCENT = 0.03  # при росте на 3% от entry_price
    REENTRY_COOLDOWN = 300  # 5 минут
    last_reentry_time = 0

    while pair in active_orders:
        # Получаем текущую цену из последней свечи:
        kline = bybit_client.get_kline(pair, interval=TRADE_INTERVAL, limit=1)
        if kline and "result" in kline and kline["result"]["list"]:
            current_price = float(kline["result"]["list"][-1][4])
        else:
            await asyncio.sleep(5)
            continue

        if side == "Buy":
            if current_price > max_price:
                max_price = current_price
            trailing_stop = max_price * (1 - TRAILING_STOP_PERCENT)
            take_profit = entry_price * (1 + TRAILING_TAKE_PROFIT_PERCENT)
            # Если цена падает ниже трейлинг стоп или достигает тейк‑профита — закрыть позицию
            if current_price <= trailing_stop or current_price >= take_profit:
                close_response = await asyncio.to_thread(
                    bybit_client.close_position, pair, side, order_size
                )
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    f"📉 *{pair}*: Позиция закрыта по динамическому условию.\n"
                    f"Цена: {current_price:.2f} | Trailing Stop: {trailing_stop:.2f} | Take Profit: {take_profit:.2f}",
                    parse_mode="Markdown",
                )
                active_orders.pop(pair, None)
                break

            # Логика для повторного входа (реинтри) при сильном росте
            if current_price >= entry_price * (1 + REENTRY_TRIGGER_PERCENT):
                now = time.time()
                if now - last_reentry_time > REENTRY_COOLDOWN:
                    additional_order_size = calculate_order_size(
                        entry_price, 3
                    )  # или другая логика для дополнительного объёма
                    response = await asyncio.to_thread(
                        bybit_client.create_order, pair, side, additional_order_size
                    )
                    if response:
                        last_reentry_time = now
                        order_info["order_size"] += additional_order_size
                        await bot.send_message(
                            ADMIN_CHAT_ID,
                            f"✅ *{pair}*: Дополнительный вход выполнен при сильном росте.\n"
                            f"Дополнительный объём: {additional_order_size} USDT",
                            parse_mode="Markdown",
                        )
            elif side == "Sell":
                # Инициализируем min_price один раз, если еще не задано
                if "min_price" not in order_info:
                    order_info["min_price"] = entry_price
                if current_price < order_info["min_price"]:
                    order_info["min_price"] = current_price
                trailing_stop = order_info["min_price"] * (1 + TRAILING_STOP_PERCENT)
                take_profit = entry_price * (1 - TRAILING_TAKE_PROFIT_PERCENT)
                # Если цена начинает расти от минимума или достигает целевого уровня, закрываем позицию
                if current_price >= trailing_stop or current_price <= take_profit:
                    await asyncio.to_thread(bybit_client.close_position, pair, side, order_size)
                    await bot.send_message(
                        ADMIN_CHAT_ID,
                        f"📉 *{pair}*: Позиция закрыта.\nЦена: {current_price:.2f} | Trailing Stop: {trailing_stop:.2f} | Take Profit: {take_profit:.2f}",
                        parse_mode="Markdown",
                    )
                    active_orders.pop(pair, None)
                    break
                # Реинтри для SELL – если цена продолжает снижаться значительно
                REENTRY_TRIGGER_PERCENT = 0.03  # 3% снижение от entry_price
                REENTRY_COOLDOWN = 300  # 5 минут
                now = time.time()
                if current_price <= entry_price * (1 - REENTRY_TRIGGER_PERCENT):
                    # Дополнительный вход только, если прошло достаточно времени
                    if "last_reentry_time" not in order_info or now - order_info["last_reentry_time"] > REENTRY_COOLDOWN:
                        additional_order_size = calculate_order_size(entry_price, 3)
                        response = await asyncio.to_thread(bybit_client.create_order, pair, side, additional_order_size)
                        if response:
                            order_info["order_size"] += additional_order_size
                            order_info["last_reentry_time"] = now
                            await bot.send_message(
                                ADMIN_CHAT_ID,
                                f"✅ *{pair}*: Дополнительный вход (SELL) выполнен при сильном снижении.\nДоп. объём: {additional_order_size} USDT",
                                parse_mode="Markdown",
                            )

        await asyncio.sleep(5)


def extract_balance_from_text(balance_text):
    """Извлекает числовое значение USDT из текста баланса"""
    match = re.search(r"💳 \*Общий баланс:\* ([\d,]+\.?\d*) USDT", balance_text)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0  # Если не найдено, считаем, что баланса нет


async def start_auto_trade():
    global auto_trade_active
    if auto_trade_active:
        return "⚠️ Автоторговля уже запущена!"

    balance = bybit_client.get_wallet_balance(as_report=False)
    try:
        balance = float(balance)
    except (TypeError, ValueError):
        balance = 0

    if balance <= 0:
        await bot.send_message(
            ADMIN_CHAT_ID,
            "⚠️ Недостаточно средств для торговли! Автоторговля не запущена.",
        )
        logging.warning("⛔ Недостаточно средств. Автоторговля НЕ запущена!")
        return

    auto_trade_active = True
    logging.info("✅ Автоторговля запущена!")
    await bot.send_message(ADMIN_CHAT_ID, "✅ Автоторговля запущена!")
    cycle_count = 0
    while auto_trade_active:
        try:
            orders_placed = await trade_logic()
            cycle_count += 1
            if orders_placed:
                for pair in orders_placed:
                    await bot.send_message(
                        ADMIN_CHAT_ID,
                        f"✅ *{pair}*: Сделка выставлена.",
                        parse_mode="Markdown",
                    )
            elif cycle_count % 60 == 0:
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    "🔄 Автоторговля активна – проверка сигналов выполнена.",
                )
                cycle_count = 0
            await asyncio.sleep(30)
        except Exception as e:
            logging.error(f"❌ Ошибка в автоторговле: {e}")
            await bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибка в автоторговле: {e}")

    logging.info("⏹ Автоторговля остановлена!")


def stop_auto_trade():
    """Останавливает автоторговлю и завершает мониторинг всех позиций"""
    global auto_trade_active, active_orders
    auto_trade_active = False
    active_orders.clear()
    logging.info("⏹ Автоторговля остановлена!")
    return "⏹ Автоторговля остановлена!"


async def trade_logic():
    """Основная логика принятия торговых решений.
    Возвращает список пар, для которых были выставлены ордера.
    """
    global active_orders, first_signal_check
    trading_pairs = pair_manager.get_active_pairs()
    signals = indicator_calc.calculate_signals(trading_pairs)
    orders_placed = []

    # Получаем числовой баланс Unified Trading (USDT)
    balance = bybit_client.get_wallet_balance(as_report=False)
    if balance == 0:
        await bot.send_message(ADMIN_CHAT_ID, "⚠️ Недостаточно средств для торговли!")
        logging.warning("⚠️ Недостаточно средств для торговли!")
        return orders_placed

    # При первом запуске отправляем полный отчёт по сигналам
    if first_signal_check:
        report = "📡 *Проверка сигналов*\n"
        for pair, (signal, strength) in signals.items():
            report += f"📊 {pair}: {signal} (Сила: {strength})\n"
        await bot.send_message(ADMIN_CHAT_ID, report, parse_mode="Markdown")
        first_signal_check = False

    for pair, (signal, strength) in signals.items():
        # Выставляем ордер только если сигнал явно BUY или SELL
        if signal not in ("BUY", "SELL"):
            continue

        # Требуем минимальный порог силы сигнала, например ≥2
        if strength < 2:
            continue

        if pair in active_orders:
            # logging.info(f"⚠️ {pair}: Уже есть активная позиция, пропускаем.")
            continue

        # Если сигнал SELL, проверяем баланс базового актива
        if signal == "SELL":
            asset = pair.replace("USDT", "")
            asset_balance = bybit_client.get_asset_balance(asset)
            if asset_balance <= 0:
                # logging.info(
                #     f"⚠️ {pair}: Недостаточно {asset} для продажи. Пропускаем ордер."
                # )
                continue

        order_size = calculate_order_size(balance, strength)
        if order_size == 0:
            logging.warning(f"⚠️ {pair}: Слишком маленький баланс для сделки (расчётный объём меньше минимального {MIN_ORDER_USDT} USDT)")
            continue

        side = "Buy" if signal == "BUY" else "Sell"
        # Вызываем синхронный метод создания ордера через asyncio.to_thread
        response = await asyncio.to_thread(
            bybit_client.create_order, pair, side, order_size
        )
        if response:
            kline = bybit_client.get_kline(pair, interval=TRADE_INTERVAL, limit=1)
            entry_price = float(kline["result"]["list"][-1][4]) if kline else 0

            active_orders[pair] = {
                "order_id": response.get("orderId"),
                "side": side,
                "entry_price": entry_price,
                "order_size": order_size,
            }
            orders_placed.append(pair)
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *{pair}*: Открыта позиция `{side}` на {order_size} USDT по цене {entry_price:.2f}",
                parse_mode="Markdown",
            )
            # Запускаем фоновый мониторинг трейлинга для этой позиции
            asyncio.create_task(monitor_position(pair, active_orders[pair]))
        else:
            logging.error(f"❌ {pair}: Ошибка при размещении ордера")
    return orders_placed


def calculate_order_size(balance, strength):
    """Динамически рассчитывает объём ордера с корректировкой до минимально допустимого уровня.

    Если рассчитанный объём меньше MIN_ORDER_USDT и баланс позволяет, устанавливаем MIN_ORDER_USDT.
    Если баланс меньше MIN_ORDER_USDT, возвращаем 0.
    """
    percent = 0.01 * strength  # Слабый сигнал – 1%, сильный – 2%, максимум – 5%
    order_size = balance * min(percent, 0.05)
    order_size = round(order_size, 2)
    if order_size < MIN_ORDER_USDT:
        if balance >= MIN_ORDER_USDT:
            order_size = MIN_ORDER_USDT
        else:
            order_size = 0
    return order_size


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
