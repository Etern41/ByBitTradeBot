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
    MIN_ORDER_USDT,
)
from telegram import Bot, ReplyKeyboardMarkup
from bybit_client import BybitAPI
from indicators import IndicatorCalculator
from pair_manager import PairManager
from order_storage import load_active_orders, save_active_orders

# Настройка логов
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Глобальные переменные
auto_trade_active = False
trade_task = None

# Инициализация API, индикаторов и Telegram-бота
bybit_client = BybitAPI()
indicator_calc = IndicatorCalculator()
bot = Bot(TELEGRAM_API_TOKEN)

# Загрузка активных ордеров из файла
active_orders = load_active_orders()

pair_manager = PairManager()
first_signal_check = True

# Порог проверки для трейлинга (секунды)
TRAILING_CHECK_INTERVAL = 10


# --- Функция мониторинга позиции ---
async def monitor_position(pair, order_info):
    """
    Мониторит открытую позицию с динамическим трейлинг-стопом и тейк-профитом.
    При закрытии ордера удаляет его из active_orders и сохраняет обновлённое состояние.
    """
    entry_price = order_info["entry_price"]
    side = order_info["side"]
    order_size = order_info["order_size"]
    max_price = entry_price
    REENTRY_TRIGGER_PERCENT = 0.03
    REENTRY_COOLDOWN = 300
    last_reentry_time = 0

    while pair in active_orders and auto_trade_active:
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
            take_profit = entry_price * (1 + TRAILING_STOP_PERCENT)
            if current_price <= trailing_stop or current_price >= take_profit:
                await asyncio.to_thread(
                    bybit_client.close_position, pair, side, order_size
                )
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    f"📉 *{pair}*: Позиция закрыта.\nЦена: {current_price:.2f} | TS: {trailing_stop:.2f} | TP: {take_profit:.2f}",
                    parse_mode="Markdown",
                )
                active_orders.pop(pair, None)
                save_active_orders(active_orders)
                break

            if current_price >= entry_price * (1 + REENTRY_TRIGGER_PERCENT):
                now = time.time()
                if now - last_reentry_time > REENTRY_COOLDOWN:
                    additional_order_size = calculate_order_size(entry_price, 3)
                    response = await asyncio.to_thread(
                        bybit_client.create_order, pair, side, additional_order_size
                    )
                    if response:
                        last_reentry_time = now
                        order_info["order_size"] += additional_order_size
                        await bot.send_message(
                            ADMIN_CHAT_ID,
                            f"✅ *{pair}*: Дополнительный вход при росте.\nДоп. объём: {additional_order_size} USDT",
                            parse_mode="Markdown",
                        )
                        save_active_orders(active_orders)
        elif side == "Sell":
            if "min_price" not in order_info:
                order_info["min_price"] = entry_price
            if current_price < order_info["min_price"]:
                order_info["min_price"] = current_price
            trailing_stop = order_info["min_price"] * (1 + TRAILING_STOP_PERCENT)
            take_profit = entry_price * (1 - TRAILING_STOP_PERCENT)
            if current_price >= trailing_stop or current_price <= take_profit:
                await asyncio.to_thread(
                    bybit_client.close_position, pair, side, order_size
                )
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    f"📉 *{pair}*: Позиция закрыта.\nЦена: {current_price:.2f} | TS: {trailing_stop:.2f} | TP: {take_profit:.2f}",
                    parse_mode="Markdown",
                )
                active_orders.pop(pair, None)
                save_active_orders(active_orders)
                break
            now = time.time()
            if current_price <= entry_price * (1 - 0.03):
                if (
                    "last_reentry_time" not in order_info
                    or now - order_info["last_reentry_time"] > REENTRY_COOLDOWN
                ):
                    additional_order_size = calculate_order_size(entry_price, 3)
                    response = await asyncio.to_thread(
                        bybit_client.create_order, pair, side, additional_order_size
                    )
                    if response:
                        order_info["order_size"] += additional_order_size
                        order_info["last_reentry_time"] = now
                        await bot.send_message(
                            ADMIN_CHAT_ID,
                            f"✅ *{pair}*: Дополнительный вход (SELL) при снижении.\nДоп. объём: {additional_order_size} USDT",
                            parse_mode="Markdown",
                        )
                        save_active_orders(active_orders)
        await asyncio.sleep(5)


# --- Основной торговый цикл ---
async def trade_logic():
    global active_orders, first_signal_check, auto_trade_active
    if not auto_trade_active:
        return []
    trading_pairs = pair_manager.get_active_pairs()
    signals = indicator_calc.calculate_signals(trading_pairs)
    orders_placed = []

    usdt_balance = bybit_client.get_usdt_balance()
    if usdt_balance == 0:
        await bot.send_message(ADMIN_CHAT_ID, "⚠️ Недостаточно USDT для торговли!")
        logging.warning("⚠️ Недостаточно USDT для торговли!")
        return orders_placed
    if usdt_balance < MIN_ORDER_USDT:
        logging.warning(
            f"Баланс USDT ({usdt_balance} USDT) меньше минимального ордера ({MIN_ORDER_USDT} USDT)."
        )
        return orders_placed

    if first_signal_check:
        report = "📡 *Проверка сигналов*\n"
        for pair, (signal, strength) in signals.items():
            report += f"📊 {pair}: {signal} (Сила: {strength})\n"
        await bot.send_message(ADMIN_CHAT_ID, report, parse_mode="Markdown")
        first_signal_check = False

    for pair, (signal, strength) in signals.items():
        if not auto_trade_active:
            break
        if signal not in ("BUY", "SELL"):
            continue
        if strength < 2:
            continue
        if pair in active_orders:
            continue
        if signal == "SELL":
            asset = pair.replace("USDT", "")
            asset_balance = bybit_client.get_asset_balance(asset)
            if asset_balance <= 0:
                continue

        current_usdt_balance = bybit_client.get_usdt_balance()
        if current_usdt_balance < MIN_ORDER_USDT:
            logging.warning(
                f"Текущий баланс USDT ({current_usdt_balance} USDT) меньше минимального ордера ({MIN_ORDER_USDT} USDT)."
            )
            break

        order_size = calculate_order_size(current_usdt_balance, strength)
        if order_size < MIN_ORDER_USDT:
            logging.warning(
                f"⚠️ {pair}: Расчетный объём ({order_size} USDT) меньше минимального ордера ({MIN_ORDER_USDT} USDT)."
            )
            continue

        side = "Buy" if signal == "BUY" else "Sell"
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
            save_active_orders(active_orders)
            asyncio.create_task(monitor_position(pair, active_orders[pair]))
        else:
            logging.error(f"❌ {pair}: Ошибка при размещении ордера")
    return orders_placed


def calculate_order_size(balance, strength):
    percent = 0.01 * strength  # 1% для слабого сигнала, 2% для сильного, максимум 5%
    order_size = balance * min(percent, 0.05)
    order_size = round(order_size, 2)
    if order_size < MIN_ORDER_USDT:
        if balance >= MIN_ORDER_USDT:
            order_size = MIN_ORDER_USDT
        else:
            order_size = 0
    return order_size


# --- Функция обновления списка торговых пар ---
async def update_trade_pairs():
    print("📡 Обновление списка торговых пар...")
    all_pairs = bybit_client.get_spot_pairs()
    if not all_pairs:
        print("❌ Ошибка получения пар!")
        return
    stablecoins = {"USDC", "BUSD", "DAI", "TUSD", "FDUSD", "EURS"}
    pair_volumes = []
    for pair in all_pairs:
        symbol = pair["symbol"]
        volume = float(pair.get("turnover24h", 0))
        if "USDT" in symbol and not any(stable in symbol for stable in stablecoins):
            pair_volumes.append((symbol, volume))
    pair_volumes.sort(key=lambda x: x[1], reverse=True)
    top_pairs = [pair[0] for pair in pair_volumes[:15]]
    global TRADE_PAIRS
    TRADE_PAIRS = top_pairs
    with open("trade_pairs.json", "w") as file:
        json.dump({"TRADE_PAIRS": top_pairs}, file, indent=4)
    msg = (
        f"✅ Обновлено {len(top_pairs)} пар!\n📊 Торговые пары: {', '.join(top_pairs)}"
    )
    print(msg)
    await bot.send_message(ADMIN_CHAT_ID, msg)


# --- Ежедневное обновление списка торговых пар ---
async def daily_update_trade_pairs():
    while True:
        await update_trade_pairs()
        await asyncio.sleep(86400)


def start_background_tasks():
    loop = asyncio.get_event_loop()
    loop.create_task(daily_update_trade_pairs())


if AUTO_UPDATE_PAIRS:
    start_background_tasks()


# --- Основной торговый цикл ---
async def main_trade_loop():
    while auto_trade_active:
        try:
            await trade_logic()
            await asyncio.sleep(30)
        except Exception as e:
            logging.error(f"❌ Ошибка в автоторговле: {e}")
            await bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибка в автоторговле: {e}")
    logging.info("⏹ Автоторговля остановлена!")


async def restore_active_orders():
    """
    Восстанавливает открытые ордера с биржи и запускает для них мониторинг.
    Если биржа возвращает список открытых ордеров, обновляем active_orders и сохраняем их в файл.
    """
    response = await asyncio.to_thread(bybit_client.get_open_orders)
    if response and response.get("retCode") == 0:
        orders = response["result"]["list"]
        for order in orders:
            symbol = order["symbol"]
            order_info = {
                "order_id": order.get("orderId"),
                "side": order.get("side"),
                "entry_price": float(order.get("price", 0)),
                "order_size": float(order.get("qty", 0)),
            }
            active_orders[symbol] = order_info
            asyncio.create_task(monitor_position(symbol, order_info))
        save_active_orders(active_orders)
        logging.info("Восстановлены открытые ордера с биржи.")
    else:
        logging.info("Открытых ордеров для восстановления не найдено.")


# --- Функции старта и остановки автоторговли ---
async def start_auto_trade():
    global auto_trade_active, trade_task
    if auto_trade_active:
        return "⚠️ Автоторговля уже запущена!"

    balance = bybit_client.get_wallet_balance(as_report=False)
    try:
        balance = float(balance)
    except (TypeError, ValueError):
        balance = 0

    if balance < MIN_ORDER_USDT:
        logging.warning(
            f"Баланс ({balance} USDT) меньше минимального ордера ({MIN_ORDER_USDT} USDT)."
        )
        return

    await restore_active_orders()

    auto_trade_active = True
    logging.info("✅ Автоторговля запущена!")
    await bot.send_message(ADMIN_CHAT_ID, "✅ Автоторговля запущена!")
    trade_task = asyncio.create_task(main_trade_loop())


def stop_auto_trade():
    global auto_trade_active, trade_task, active_orders
    auto_trade_active = False
    if trade_task:
        trade_task.cancel()
    save_active_orders(active_orders)
    logging.info("⏹ Автоторговля остановлена!")
    return "⏹ Автоторговля остановлена!"
