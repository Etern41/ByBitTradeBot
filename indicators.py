import pandas as pd
import ta
from bybit_client import BybitAPI
from config import TRADE_PAIRS


class IndicatorCalculator:
    def __init__(self):
        self.client = BybitAPI()

    def get_historical_data(self, symbol):
        """Получает исторические данные OHLCV для пары"""
        try:
            response = self.client.get_kline(symbol)
            if (
                not response
                or "result" not in response
                or "list" not in response["result"]
            ):
                print(f"❌ Ошибка API для {symbol}: некорректный ответ")
                return None

            raw_data = response["result"]["list"]

            # 🛠 Определяем колонки автоматически (6 или 7)
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

    def calculate_indicators(self):
        """Анализирует все пары в TRADE_PAIRS и возвращает индикаторы"""
        report = ""

        for pair in TRADE_PAIRS:
            df = self.get_historical_data(pair)
            if df is None:
                report += f"❌ {pair}: Ошибка загрузки данных\n"
                continue

            # ✅ Рассчитываем RSI
            df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

            # ✅ Рассчитываем MACD
            macd = ta.trend.MACD(df["close"])
            df["macd"] = macd.macd()
            df["macd_signal"] = macd.macd_signal()

            # ✅ Рассчитываем SMA (50 и 200)
            df["sma_50"] = ta.trend.SMAIndicator(df["close"], window=50).sma_indicator()
            df["sma_200"] = ta.trend.SMAIndicator(
                df["close"], window=200
            ).sma_indicator()

            # ✅ Рассчитываем Bollinger Bands
            bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
            df["bb_high"] = bb.bollinger_hband()
            df["bb_low"] = bb.bollinger_lband()

            # ✅ Рассчитываем ATR (14)
            atr = ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            )
            df["atr"] = atr.average_true_range()

            # ✅ Последняя строка
            last_row = df.iloc[-1]

            # ✅ Генерируем сигнал
            signal, strength = self.generate_trade_signal(last_row)

            # ✅ Добавляем данные в отчет
            report += (
                f"📊 *{pair}*\n"
                f"🔹 RSI: {last_row['rsi']:.2f} (Цель: 30 (Покупка) / 70 (Продажа))\n"
                f"🔹 MACD: {last_row['macd']:.2f} (Signal: {last_row['macd_signal']:.2f})\n"
                f"🔹 SMA 50/200: {last_row['sma_50']:.2f} / {last_row['sma_200']:.2f}\n"
                f"🔹 BB High/Low: {last_row['bb_high']:.2f} / {last_row['bb_low']:.2f}\n"
                f"🔹 ATR: {last_row['atr']:.2f} (Средний: {df['atr'].mean():.2f})\n"
                f"📢 Сигнал: {signal}\n\n"
            )

        return report


    def generate_trade_signal(self, last_row):
        """Генерация сигнала на основе RSI, MACD, SMA"""
        required_columns = ["rsi", "macd", "macd_signal", "sma"]

        # ✅ Проверяем, есть ли все необходимые столбцы
        for col in required_columns:
            if col not in last_row:
                
                return "HOLD", 0  # ✅ Если нет данных, не торгуем

        signal = "HOLD"
        strength = 0

        # 🔥 Покупка (Слабый сигнал: RSI < 30, сильный сигнал: RSI < 20)
        if last_row["rsi"] < 30 and last_row["macd"] > last_row["macd_signal"]:
            signal = "BUY"
            strength = 1 if last_row["rsi"] > 20 else 2  # Чем ниже RSI, тем сильнее сигнал

        # 🔥 Продажа (Слабый сигнал: RSI > 70, сильный сигнал: RSI > 80)
        elif last_row["rsi"] > 70 and last_row["macd"] < last_row["macd_signal"]:
            signal = "SELL"
            strength = 1 if last_row["rsi"] < 80 else 2  # Чем выше RSI, тем сильнее сигнал

        return signal, strength

    def calculate_signals(self):
        """Анализирует все пары и возвращает сигналы в корректном формате"""
        signals = {}

        for pair in TRADE_PAIRS:
            df = self.get_historical_data(pair)
            if df is None:
                signals[pair] = ("HOLD", 0)
                continue

            last_row = df.iloc[-1]
            signal, strength = self.generate_trade_signal(last_row)

            # ✅ Записываем результат в правильном формате
            signals[pair] = (signal, strength)

        return signals
