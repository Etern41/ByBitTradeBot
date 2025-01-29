import requests
import time
import hmac
import hashlib
import json
import uuid
from config import BYBIT_API_KEY, BYBIT_API_SECRET, USE_TESTNET


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
            print(
                f"❌ Ошибка запроса {description}: HTTP {response.status_code} | {response.text}"
            )

        return response.json() if response.status_code == 200 else None

    def get_wallet_balance(self):
        """Получает баланс (Bybit API V5)"""
        endpoint = "/v5/account/wallet-balance"
        payload = {"accountType": "UNIFIED"}
        response = self._make_request(endpoint, "GET", payload, "Получение баланса")

        if not response or response.get("retCode") != 0:
            return f"❌ Ошибка API: {response.get('retMsg', 'Неизвестная ошибка')}"

        coins = response["result"]["list"][0]["coin"]
        total_balance = sum(float(coin["usdValue"]) for coin in coins)

        table = "💰 *Баланс аккаунта Bybit:*\n━━━━━━━━━━━━━━━━━━━━━\n"
        table += "🪙 *Токен*  | 💰 *Кол-во*  | 💲 *В USDT*\n━━━━━━━━━━━━━━━━━━━━━\n"

        for coin in coins:
            name = f"🔹 {coin['coin']}"
            amount = f"{float(coin['walletBalance']):,.4f}"
            usd_value = f"{float(coin.get('usdValue', 0)):.2f}"
            table += (
                f"{name.ljust(8)} | {amount.rjust(10)} | {usd_value.rjust(10)} USDT\n"
            )

        table += f"━━━━━━━━━━━━━━━━━━━━━\n💳 *Общий баланс:* {total_balance:,.2f} USDT"
        return table

    def get_kline(self, symbol, interval="60", limit=200):
        """Получает исторические данные свечей"""
        endpoint = "/v5/market/kline"
        payload = {
            "category": "spot",  # Для фьючерсов заменить на "linear"
            "symbol": symbol,
            "interval": interval,
            "limit": str(limit),
        }
        return self._make_request(
            endpoint, "GET", payload, "Получение исторических данных"
        )
