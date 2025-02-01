import pandas as pd
import ta
from bybit_client import BybitAPI
from config import TRADE_PAIRS, TRADE_INTERVAL


class IndicatorCalculator:
    def __init__(self):
        self.client = BybitAPI()

    def get_historical_data(self, symbol):
        """Получает исторические данные OHLCV для пары"""
        try:
            response = self.client.get_kline(symbol, interval=TRADE_INTERVAL)
            if (
                not response
                or "result" not in response
                or "list" not in response["result"]
            ):
                print(f"❌ Ошибка API для {symbol}: некорректный ответ")
                return None

            raw_data = response["result"]["list"]
            columns = ["timestamp", "open", "high", "low", "close", "volume"]
            if len(raw_data[0]) == 7:
                columns.append("turnover")
            df = pd.DataFrame(raw_data, columns=columns)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            return df

        except Exception as e:
            print(f"❌ Ошибка загрузки данных для {symbol}: {e}")
            return None

    def calculate_indicators(self, trade_pairs=None):
        """Анализирует все пары и возвращает индикаторы с эмоджи"""
        if trade_pairs is None:
            trade_pairs = TRADE_PAIRS
        report = f"📊 *Анализ индикаторов (интервал: {TRADE_INTERVAL} мин)*\n\n"
        for pair in trade_pairs:
            df = self.get_historical_data(pair)
            if df is None:
                report += f"❌ {pair}: Ошибка загрузки данных\n"
                continue

            df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            macd = ta.trend.MACD(df["close"])
            df["macd"] = macd.macd()
            df["macd_signal"] = macd.macd_signal()
            df["sma_50"] = ta.trend.SMAIndicator(df["close"], window=50).sma_indicator()
            df["sma_200"] = ta.trend.SMAIndicator(
                df["close"], window=200
            ).sma_indicator()
            bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
            df["bb_high"] = bb.bollinger_hband()
            df["bb_low"] = bb.bollinger_lband()
            atr = ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            )
            df["atr"] = atr.average_true_range()
            last_row = df.iloc[-1]
            signal, strength = self.generate_trade_signal(last_row)
            composite = signal
            if strength >= 3:
                composite += " 💪"

            report += (
                f"📊 *{pair}* {get_signal_emoji(signal)}\n"
                f"{get_rsi_emoji(last_row['rsi'])} RSI: {last_row['rsi']:.2f} (Цель: 30/70)\n"
                f"{get_macd_emoji(last_row['macd'], last_row['macd_signal'])} MACD: {last_row['macd']:.2f} (Signal: {last_row['macd_signal']:.2f})\n"
                f"{get_sma_emoji(last_row['sma_50'], last_row['sma_200'], last_row['close'])} SMA 50/200: {last_row['sma_50']:.2f} / {last_row['sma_200']:.2f}\n"
                f"{get_bb_emoji(last_row['close'], last_row['bb_low'], last_row['bb_high'])} BB High/Low: {last_row['bb_high']:.2f} / {last_row['bb_low']:.2f}\n"
                f"{get_atr_emoji(last_row['atr'])} ATR: {last_row['atr']:.2f}\n"
                f"📢 Сигнал: {composite} Сила: {strength}\n\n"
            )

        return report


    def generate_trade_signal(self, last_row):
        """
        Генерация сигнала с использованием связок индикаторов.
        Для BUY требуются:
        - RSI < 30
        - MACD > MACD_Signal
        - Цена не более чем на 2% выше нижней границы Bollinger
        - ATR ниже порога (например, < 10)
        - Цена выше SMA50
        Для SELL – зеркальное условие.
        Если выполнено хотя бы 3 условия, возвращается сигнал с силой равной количеству выполненных условий.
        """
        signal = "HOLD"
        strength = 0
        price = last_row["close"]

        # BUY условия
        buy_conditions = 0
        if last_row["rsi"] < 30:
            buy_conditions += 1
        if last_row["macd"] > last_row["macd_signal"]:
            buy_conditions += 1
        # Допустим, разрешаем 2% отклонение от нижней границы
        if price <= last_row["bb_low"] * 1.02:
            buy_conditions += 1
        if last_row["atr"] < 10:  # порог ATR (настраивается эмпирически)
            buy_conditions += 1
        if price > last_row["sma_50"]:
            buy_conditions += 1

        # SELL условия
        sell_conditions = 0
        if last_row["rsi"] > 70:
            sell_conditions += 1
        if last_row["macd"] < last_row["macd_signal"]:
            sell_conditions += 1
        if price >= last_row["bb_high"] * 0.98:
            sell_conditions += 1
        if last_row["atr"] < 10:
            sell_conditions += 1
        if price < last_row["sma_50"]:
            sell_conditions += 1

        if buy_conditions >= 3:
            signal = "BUY"
            strength = buy_conditions
        elif sell_conditions >= 3:
            signal = "SELL"
            strength = sell_conditions

        return signal, strength

    def calculate_signals(self, trade_pairs=None):
        """Анализирует все пары и возвращает сигналы с рассчитанными индикаторами"""
        if trade_pairs is None:
            trade_pairs = TRADE_PAIRS
        signals = {}

        for pair in trade_pairs:
            df = self.get_historical_data(pair)
            if df is None or df.empty:
                signals[pair] = ("HOLD", 0)
                continue

            try:
                # Рассчитываем индикаторы для вычисления торгового сигнала
                df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
                macd = ta.trend.MACD(df["close"])
                df["macd"] = macd.macd()
                df["macd_signal"] = macd.macd_signal()
                df["sma_50"] = ta.trend.SMAIndicator(
                    df["close"], window=50
                ).sma_indicator()
                df["sma_200"] = ta.trend.SMAIndicator(
                    df["close"], window=200
                ).sma_indicator()
                bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
                df["bb_high"] = bb.bollinger_hband()
                df["bb_low"] = bb.bollinger_lband()
                atr = ta.volatility.AverageTrueRange(
                    df["high"], df["low"], df["close"], window=14
                )
                df["atr"] = atr.average_true_range()
            except Exception as e:
                print(f"Ошибка при расчете индикаторов для {pair}: {e}")
                signals[pair] = ("HOLD", 0)
                continue

            last_row = df.iloc[-1]
            try:
                signal, strength = self.generate_trade_signal(last_row)
            except Exception as e:
                print(f"Ошибка при генерации сигнала для {pair}: {e}")
                signal, strength = ("HOLD", 0)

            signals[pair] = (signal, strength)
        return signals


def get_rsi_emoji(rsi):
    if rsi < 30:
        return "🟢"
    elif rsi > 70:
        return "🔴"
    else:
        return "🔵"


def get_macd_emoji(macd, macd_signal):
    if macd > macd_signal:
        return "🟢"
    elif macd < macd_signal:
        return "🔴"
    else:
        return "🔵"


def get_sma_emoji(sma50, sma200, price):
    # Если цена выше SMA50 и SMA50 выше SMA200 – бычье состояние (зелёный)
    if price > sma50 and sma50 > sma200:
        return "🟢"
    # Если цена ниже SMA50 и SMA50 ниже SMA200 – медвежье (красный)
    elif price < sma50 and sma50 < sma200:
        return "🔴"
    else:
        return "🔵"


def get_bb_emoji(price, bb_low, bb_high):
    # Если цена близка к нижней границе – сигнал на покупку (зелёный),
    # если к верхней – сигнал на продажу (красный), иначе нейтральный (оранжевый)
    if price <= bb_low:
        return "🟢"
    elif price >= bb_high:
        return "🔴"
    else:
        return "🔵"


def get_atr_emoji(atr):
    # Здесь можно задать произвольные пороги; для примера:
    if atr < 1:
        return "🟢"
    elif atr > 50:
        return "🔴"
    else:
        return "🔵"


def get_signal_emoji(signal):
    # Композитный эмоджи определяется только по типу сигнала
    if signal == "BUY":
        return "🟢"
    elif signal == "SELL":
        return "🔴"
    else:
        return "🔵"
