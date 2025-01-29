import requests
import time
import hmac
import hashlib
import json
import uuid
import logging
import pandas as pd
from config import BYBIT_API_KEY, BYBIT_API_SECRET, USE_TESTNET, TRADE_INTERVAL


class BybitAPI:
    def __init__(self):
        """Инициализация API Bybit"""
        self.api_key = BYBIT_API_KEY
        self.secret_key = BYBIT_API_SECRET
        self.recv_window = "5000"
        self.base_url = (
            "https://api-testnet.bybit.com" if USE_TESTNET else "https://api.bybit.com"
        )
        self.http_client = requests.Session()

    def _generate_signature(self, payload: dict, timestamp: str) -> str:
        """Генерирует HMAC SHA256 подпись для Bybit API V5"""
        sorted_payload = "&".join(
            f"{key}={value}" for key, value in sorted(payload.items())
        )
        param_str = f"{timestamp}{self.api_key}{self.recv_window}{sorted_payload}"

        return hmac.new(
            self.secret_key.encode("utf-8"), param_str.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _make_request(self, endpoint, method, payload, description):
        """Отправляет запрос с аутентификацией"""
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(payload, timestamp)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-SIGN-TYPE": "2",
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = self.base_url + endpoint
        response = self.http_client.request(
            method, url, headers=headers, params=payload
        )

        if response.status_code != 200:
            logging.error(
                f"❌ Ошибка запроса {description}: {response.status_code} | {response.text}"
            )
            return None

        return response.json()

    def get_wallet_balance(self):
        """Получает баланс (Bybit API V5) в компактном формате"""
        endpoint = "/v5/account/wallet-balance"
        payload = {"accountType": "UNIFIED"}
        response = self._make_request(endpoint, "GET", payload, "Получение баланса")

        if not response or response.get("retCode") != 0:
            return f"❌ Ошибка API: {response.get('retMsg', 'Неизвестная ошибка')}"

        coins = response["result"]["list"][0]["coin"]
        total_balance = sum(float(coin["usdValue"]) for coin in coins)

        # 🔹 Формируем текстовый отчет
        report = "💰 *Баланс Bybit*\n"
        for coin in coins:
            name = coin["coin"]
            amount = f"{float(coin['walletBalance']):,.4f}".rstrip("0").rstrip(".")
            usd_value = f"{float(coin.get('usdValue', 0)):.2f}"
            report += f"{name}: {amount} ({usd_value} USDT)\n"

        report += "━━━━━━━━━━━━━━━━━━━━━\n"
        report += f"💳 *Общий баланс:* {total_balance:,.2f} USDT"

        return report


    def get_trading_pairs(self, min_volume=100000):
        """Получает список ликвидных USDT-пар с Bybit, исключая стейблкоины (кроме USDT)"""
        endpoint = "/v5/market/tickers"
        payload = {"category": "spot"}
        response = self._make_request(endpoint, "GET", payload, "Получение списка пар")

        if not response or response.get("retCode") != 0:
            logging.error(f"❌ Ошибка API: {response.get('retMsg', 'Неизвестная ошибка')}")
            return []

        stablecoins = {"USDC", "BUSD", "DAI", "TUSD", "FDUSD", "EURS"}
        pairs = []

        for ticker in response["result"]["list"]:
            symbol = ticker["symbol"]
            volume = float(ticker["turnover24h"])

            # Фильтрация: оставляем только USDT и исключаем пары со стейблкоинами
            if "USDT" in symbol and not any(stable in symbol for stable in stablecoins):
                if volume >= min_volume:
                    pairs.append(symbol)

        logging.info(f"✅ Найдено {len(pairs)} ликвидных пар")
        return pairs

    def get_kline(self, symbol, interval=TRADE_INTERVAL, limit=1000):
        """Получает исторические данные свечей"""
        endpoint = "/v5/market/kline"
        payload = {
            "category": "spot",
            "symbol": symbol,
            "interval": str(interval),
            "limit": str(limit),
        }
        return self._make_request(endpoint, "GET", payload, "Получение исторических данных")

    def filter_pairs_by_volatility(self, pairs, min_atr=0.005):
        """Фильтрует пары по волатильности (ATR)"""
        filtered_pairs = []
        for pair in pairs:
            kline_data = self.get_kline(pair)
            if not kline_data or "result" not in kline_data:
                continue

            df = pd.DataFrame(
                kline_data["result"]["list"],
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["close"] = df["close"].astype(float)

            # Рассчитываем ATR через стандартное отклонение цены закрытия
            atr = df["close"].rolling(50).std().mean()
            if atr > min_atr:
                filtered_pairs.append(pair)

        logging.info(f"✅ Отфильтровано {len(filtered_pairs)} волатильных пар")
        return filtered_pairs

    def get_available_pairs(self):
        """Получает список всех доступных торговых пар на Bybit (SPOT)"""
        endpoint = "/v5/market/instruments-info"
        payload = {"category": "spot"}
        response = self._make_request(endpoint, "GET", payload, "Получение списка пар")

        if not response or response.get("retCode") != 0:
            return []

        pairs = [item["symbol"] for item in response["result"]["list"]]
        return pairs

    def get_spot_pairs(self):
        """Получает все доступные пары на Bybit Spot"""
        endpoint = "/v5/market/tickers"
        payload = {"category": "spot"}
        response = self._make_request(endpoint, "GET", payload, "Получение всех пар")

        if not response or response.get("retCode") != 0:
            print(f"❌ Ошибка API: {response.get('retMsg', 'Неизвестная ошибка')}")
            return []

        return response["result"]["list"]
