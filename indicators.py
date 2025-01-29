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

            # Определяем количество колонок
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
        table = ""

        for pair in TRADE_PAIRS:
            df = self.get_historical_data(pair)
            if df is None:
                table += f"📊 {pair}\n❌ Ошибка загрузки данных\n\n"
                continue

            # RSI и его целевые уровни
            rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            rsi_last = rsi.iloc[-1]
            rsi_signal = "Цель: 30 (Покупка) / 70 (Продажа)"

            # MACD и сигнал
            macd = ta.trend.MACD(df["close"])
            macd_last = macd.macd().iloc[-1]
            macd_signal = macd.macd_signal().iloc[-1]

            # SMA 50 и SMA 200
            sma_50 = ta.trend.SMAIndicator(df["close"], window=50).sma_indicator()
            sma_200 = ta.trend.SMAIndicator(df["close"], window=200).sma_indicator()
            sma_50_last = round(sma_50.iloc[-1], 2)
            sma_200_last = round(sma_200.iloc[-1], 2)

            # Bollinger Bands
            bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
            bb_high = bb.bollinger_hband().iloc[-1]
            bb_low = bb.bollinger_lband().iloc[-1]
            bb_signal = f"{bb_low:.2f} / {bb_high:.2f}"

            # ATR (Средний истинный диапазон)
            atr = ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            ).average_true_range()
            atr_last = atr.iloc[-1]
            atr_avg = atr.mean()

            # Генерация торгового сигнала
            signal = self.generate_trade_signal(rsi_last, macd_last, macd_signal)

            # Формируем текст
            table += (
                f"📊 {pair}\n"
                f"🔹 RSI: {rsi_last:.2f} ({rsi_signal})\n"
                f"🔹 MACD: {macd_last:.2f} (Signal: {macd_signal:.2f})\n"
                f"🔹 SMA 50/200: {sma_50_last} / {sma_200_last}\n"
                f"🔹 BB High/Low: {bb_signal}\n"
                f"🔹 ATR: {atr_last:.2f} (Средний: {atr_avg:.2f})\n"
                f"📢 Сигнал: {signal}\n\n"
            )

        return table

    def generate_trade_signal(self, rsi, macd, macd_signal):
        """Определяет торговый сигнал"""
        signal = "⚪ Нейтральный (Сила: 0)"

        if rsi < 30 and macd > macd_signal:
            signal = "🟢 Покупка (Сильный)" if rsi < 20 else "🟢 Покупка (Слабый)"
        elif rsi > 70 and macd < macd_signal:
            signal = "🔴 Продажа (Сильный)" if rsi > 80 else "🔴 Продажа (Слабый)"

        return signal
