import asyncio
from config import TRADE_PAIRS
from indicators import IndicatorCalculator
from bybit_client import BybitAPI
import numpy as np

indicator_calc = IndicatorCalculator()
bybit_client = BybitAPI()

auto_trade_active = False
auto_trade_task = None  # Фоновая задача


def calculate_trade_size(balance, signal_strength, atr):
    """Динамический расчет размера ордера с учетом силы сигнала и ATR"""
    risk_percent = {1: 2, 2: 5, 3: 10}  # % от баланса в зависимости от силы сигнала
    atr_multiplier = np.clip(
        atr / 10, 0.5, 2
    )  # Усиление от ATR (если волатильность высокая)

    percent = risk_percent.get(signal_strength, 0) * atr_multiplier
    trade_size = (balance * percent) / 100

    return round(trade_size, 4)


def calculate_sl_tp(last_price, signal, strength, atr):
    """Динамический расчет стоп-лосса (SL) и тейк-профита (TP)"""
    atr_factor = {1: 0.5, 2: 1, 3: 1.5}  # SL/TP множитель от ATR
    factor = atr_factor.get(strength, 0.5) * atr

    sl = last_price - factor if signal == "BUY" else last_price + factor
    tp = last_price + (factor * 2) if signal == "BUY" else last_price - (factor * 2)

    return round(sl, 2), round(tp, 2)


async def auto_trade():
    """Основной цикл автоторговли"""
    global auto_trade_active
    while auto_trade_active:
        balance = bybit_client.get_wallet_balance()
        if not balance:
            print("❌ Ошибка получения баланса!")
            await asyncio.sleep(60)
            continue

        balance_value = float(
            balance.split("*Общий баланс:* ")[1].split(" ")[0].replace(",", "")
        )

        for pair in TRADE_PAIRS:
            df = indicator_calc.get_historical_data(pair)
            if df is None:
                print(f"❌ Ошибка данных {pair}")
                continue

            signal, strength = indicator_calc.calculate_signal_strength(df)
            if strength == 0:
                continue  # Пропускаем нейтральные сигналы

            # Фильтрация ложных сигналов
            valid_signal, reason = indicator_calc.filter_fake_signals(df)
            if not valid_signal:
                print(f"🚫 Пропущен сигнал для {pair} ({reason})")
                continue

            atr = indicator_calc.calculate_atr(df)  # Новый расчет ATR
            trade_size = calculate_trade_size(balance_value, strength, atr)
            last_price = df.iloc[-1]["close"]
            sl, tp = calculate_sl_tp(last_price, signal, strength, atr)

            print(
                f"📊 {pair}: {signal} (Сила: {strength}) | Объем: {trade_size} | SL: {sl} | TP: {tp}"
            )

            # Отправляем ордер
            side = "Buy" if signal == "🟢 Покупка" else "Sell"
            order = bybit_client.create_order(
                pair, side, trade_size, price=None, order_type="Market"
            )
            print(f"✅ Ордер: {order}")

        await asyncio.sleep(60)  # Интервал анализа


def start_auto_trade():
    """Запускает автоторговлю"""
    global auto_trade_active, auto_trade_task
    if auto_trade_active:
        return "⚙️ Автоторговля уже запущена!"
    auto_trade_active = True
    auto_trade_task = asyncio.create_task(auto_trade())
    return "⚙️ Автоторговля запущена!"


def stop_auto_trade():
    """Останавливает автоторговлю"""
    global auto_trade_active, auto_trade_task
    if not auto_trade_active:
        return "⏹ Автоторговля уже остановлена!"
    auto_trade_active = False
    if auto_trade_task:
        auto_trade_task.cancel()
    return "⏹ Автоторговля остановлена!"
