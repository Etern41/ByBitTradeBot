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
        """
        Генерирует HMAC SHA256 подпись для Bybit API V5.
        Строка для подписи формируется как отсортированная строка параметров без добавления префиксов.
        """
        sorted_keys = sorted(payload.keys())
        # Собираем строку параметров в виде "key1=value1&key2=value2..."
        query_string = "&".join(f"{key}={payload[key]}" for key in sorted_keys)
        # Используем только query_string для подписи
        signature = hmac.new(
            self.secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return signature

    def _make_request(self, endpoint, method, payload, description):
        """
        Отправляет запрос с аутентификацией.
        Добавляем в payload api_key, timestamp и recv_window, затем вычисляем подпись.
        """
        timestamp = str(int(time.time() * 1000))
        if "api_key" not in payload:
            payload["api_key"] = self.api_key
        if "timestamp" not in payload:
            payload["timestamp"] = timestamp
        if "recv_window" not in payload:
            payload["recv_window"] = self.recv_window

        signature = self._generate_signature(payload, timestamp)
        payload["sign"] = signature

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = self.base_url + endpoint
        if method.upper() == "GET":
            response = self.http_client.request(
                method, url, headers=headers, params=payload
            )
        else:
            response = self.http_client.request(
                method, url, headers=headers, data=json.dumps(payload)
            )

        if response.status_code != 200:
            logging.error(
                f"❌ Ошибка запроса {description}: {response.status_code} | {response.text}"
            )
            return None
        return response.json()

    def get_wallet_balance(self, as_report=False):
        """Получает баланс Unified Trading.
        Если as_report=True, возвращается форматированный отчёт со списком токенов.
        Если as_report=False, возвращается числовое значение общего баланса (USDT).
        """
        endpoint = "/v5/account/wallet-balance"
        payload = {"accountType": "UNIFIED"}
        payload["api_key"] = self.api_key
        payload["timestamp"] = str(int(time.time() * 1000))
        payload["recv_window"] = self.recv_window
        response = self._make_request(endpoint, "GET", payload, "Получение баланса")
        if not response or response.get("retCode") != 0:
            return (
                None
                if not as_report
                else f"❌ Ошибка API: {response.get('retMsg', 'Неизвестная ошибка')}"
            )

        unified_account = None
        for account in response["result"]["list"]:
            if account.get("accountType") == "UNIFIED":
                unified_account = account
                break
        if not unified_account:
            return None if not as_report else "❌ Ошибка: Unified Trading счет не найден!"

        coins = unified_account["coin"]
        total_balance = sum(float(coin["usdValue"]) for coin in coins)

        if as_report:
            report = "💰 *Баланс Bybit*\n"
            for coin in coins:
                name = coin["coin"]
                amount = f"{float(coin['walletBalance']):,.4f}".rstrip("0").rstrip(".")
                usd_value = f"{float(coin.get('usdValue', 0)):.2f}"
                report += f"{name}: {amount} ({usd_value} USDT)\n"
            report += "━━━━━━━━━━━━━━━━━━━━━\n"
            report += f"💳 *Общий баланс:* {total_balance:,.2f} USDT"
            return report
        else:
            return total_balance

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


    def create_order(self, symbol, side, order_size, price=None, order_link_id=None):
        """
        Создает ордер на Bybit Spot через Unified API v5.

        Если price не указан (None), ордер считается рыночным:
        - Для Buy: используется параметр "quoteQty" (сумма в USDT).
        - Для Sell: используется параметр "qty" (количество базового актива).

        Если price указан, создается лимитный ордер с параметрами "price", "qty" и "timeInForce" = "PostOnly".

        Для устранения ошибки unknown parameter добавляем:
        slTriggerBy = "LastPrice"
        slOrderType = "Market"
        """
        endpoint = "/v5/order/create"
        payload = {
            "category": "spot",
            "symbol": symbol,
            "side": side,
            "slTriggerBy": "LastPrice",
            "slOrderType": "Market",
            "isLeverage": 0,
            "orderFilter": "Order",
        }
        if price is None:
            payload["orderType"] = "Market"
            if side == "Buy":
                payload["quoteQty"] = str(order_size)
            else:
                payload["qty"] = str(order_size)
        else:
            payload["orderType"] = "Limit"
            payload["price"] = str(price)
            payload["qty"] = str(order_size)
            payload["timeInForce"] = "PostOnly"
            if order_link_id is not None:
                payload["orderLinkId"] = order_link_id

        response = self._make_request(endpoint, "POST", payload, "Создание ордера")
        logging.info(f"Ответ API при создании ордера: {response}")
        return response

    def close_position(self, symbol, current_side, order_size):
        """Закрытие позиции на Bybit Spot.
        Если позиция Buy, закрытие происходит ордером Sell, и наоборот.
        """
        opposite_side = "Sell" if current_side == "Buy" else "Buy"
        return self.create_order(symbol, opposite_side, order_size)

    def get_asset_balance(self, asset):
        """Возвращает баланс конкретного актива (например, BTC) из счета Unified Trading"""
        endpoint = "/v5/account/wallet-balance"
        payload = {"accountType": "UNIFIED"}
        response = self._make_request(endpoint, "GET", payload, "Получение баланса")
        if not response or response.get("retCode") != 0:
            return 0.0
        unified_account = None
        for account in response["result"]["list"]:
            if account.get("accountType") == "UNIFIED":
                unified_account = account
                break
        if not unified_account:
            return 0.0
        for coin in unified_account["coin"]:
            if coin["coin"] == asset:
                return float(coin["walletBalance"])
        return 0.0
