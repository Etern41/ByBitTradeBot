import logging
import time
from pybit.unified_trading import HTTP
from config import BYBIT_API_KEY, BYBIT_API_SECRET, USE_TESTNET, TRADE_INTERVAL


class BybitAPI:
    def __init__(self):
        """Инициализирует сессию для Unified API v5 через pybit.unified_trading."""
        self.session = HTTP(
            testnet=USE_TESTNET,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET,
        )

    def create_order(self, symbol, side, order_size, price=None, order_link_id=None):
        """Создает ордер на Bybit Spot через Unified API v5 c использованием pybit."""
        params = {
            "category": "spot",
            "symbol": symbol,
            "side": side,
        }
        if price is None:
            params["orderType"] = "Market"
            if side == "Buy":
                # Получаем текущую цену, чтобы рассчитать количество токена, которое соответствует order_size (USDT)
                kline = self.get_kline(symbol, interval=TRADE_INTERVAL, limit=1)
                if kline and "result" in kline and kline["result"]["list"]:
                    current_price = float(kline["result"]["list"][-1][4])
                    # Рассчитываем количество токена с округлением (например, до 8 знаков)
                    token_qty = round(order_size / current_price, 8)
                    params["qty"] = str(token_qty)
                else:
                    return None
            else:
                params["qty"] = str(order_size)
        else:
            params["orderType"] = "Limit"
            params["price"] = str(price)
            params["qty"] = str(order_size)
            params["timeInForce"] = "GTC"
            if order_link_id is not None:
                params["orderLinkId"] = order_link_id

        try:
            response = self.session.place_order(**params)
            logging.info(f"Ответ API при создании ордера: {response}")
            return response
        except Exception as e:
            logging.error(f"Ошибка создания ордера: {e}")
            return None

    def get_usdt_balance(self):
        try:
            response = self.session.get_wallet_balance(accountType="UNIFIED")
        except Exception as e:
            logging.error(f"Ошибка получения баланса: {e}")
            return 0.0
        coins = response["result"]["list"][0]["coin"]
        for coin in coins:
            if coin["coin"] == "USDT":
                return float(coin["walletBalance"])
        return 0.0

    def close_position(self, symbol, current_side, order_size):
        """
        Закрывает позицию на Bybit Spot.
        Если позиция Buy, закрытие происходит ордером Sell, и наоборот.
        """
        opposite_side = "Sell" if current_side == "Buy" else "Buy"
        return self.create_order(symbol, opposite_side, order_size)

    def get_open_orders(self):
        """
        Получает открытые ордера по спотовой торговле через Unified API v5.
        Здесь предполагается, что метод get_order_list существует и принимает параметр orderStatus.
        """
        try:
            response = self.session.get_order_list(category="spot", orderStatus="New")
            logging.info(f"Получены открытые ордера: {response}")
            return response
        except Exception as e:
            logging.error(f"Ошибка получения открытых ордеров: {e}")
            return None

    def get_wallet_balance(self, as_report=False):
        """
        Получает баланс Unified Trading через Unified API v5.
        Если as_report=True, возвращается форматированный отчёт,
        иначе возвращается числовое значение общего баланса (USDT).
        """
        try:
            response = self.session.get_wallet_balance(accountType="UNIFIED")
        except Exception as e:
            logging.error(f"Ошибка получения баланса: {e}")
            return None

        coins = response["result"]["list"][0]["coin"]
        total_balance = sum(float(coin["usdValue"]) for coin in coins)

        if as_report:
            report = "💰 *Баланс Bybit*\n"
            for coin in coins:
                report += f"{coin['coin']}: {coin['walletBalance']} USDT\n"
            report += "━━━━━━━━━━━━━━━━━━━━━\n"
            report += f"💳 *Общий баланс:* {total_balance:,.2f} USDT"
            return report
        else:
            return total_balance

    def get_kline(self, symbol, interval=TRADE_INTERVAL, limit=1000):
        """
        Получает исторические данные свечей через Unified API v5.
        """
        try:
            response = self.session.get_kline(
                category="spot", symbol=symbol, interval=interval, limit=str(limit)
            )
            return response
        except Exception as e:
            logging.error(f"Ошибка получения свечей для {symbol}: {e}")
            return None

    def get_trading_pairs(self, min_volume=100000):
        """
        Получает список торговых пар с Bybit Spot через Unified API v5.
        Фильтрует пары по объему и исключает пары со стейблкоинами.
        """
        try:
            response = self.session.get_tickers(category="spot")
        except Exception as e:
            logging.error(f"Ошибка получения тикеров: {e}")
            return []
        stablecoins = {"USDC", "BUSD", "DAI", "TUSD", "FDUSD", "EURS"}
        pairs = []
        for ticker in response["result"]["list"]:
            symbol = ticker["symbol"]
            volume = float(ticker["turnover24h"])
            if "USDT" in symbol and not any(stable in symbol for stable in stablecoins):
                if volume >= min_volume:
                    pairs.append(symbol)
        logging.info(f"✅ Найдено {len(pairs)} ликвидных пар")
        return pairs

    def get_available_pairs(self):
        """
        Получает список всех доступных торговых пар на Bybit Spot через Unified API v5.
        """
        try:
            response = self.session.get_instruments(category="spot")
            pairs = [item["symbol"] for item in response["result"]["list"]]
            return pairs
        except Exception as e:
            logging.error(f"Ошибка получения доступных пар: {e}")
            return []

    def get_spot_pairs(self):
        """
        Получает все доступные пары на Bybit Spot через Unified API v5 (тикеры).
        """
        try:
            response = self.session.get_tickers(category="spot")
            return response["result"]["list"]
        except Exception as e:
            logging.error(f"Ошибка получения тикеров: {e}")
            return []

    def get_asset_balance(self, asset):
        """
        Возвращает баланс конкретного актива (например, BTC) из счета Unified Trading.
        """
        try:
            response = self.session.get_wallet_balance(accountType="UNIFIED")
            coins = response["result"]["list"][0]["coin"]
            for coin in coins:
                if coin["coin"] == asset:
                    return float(coin["walletBalance"])
            return 0.0
        except Exception as e:
            logging.error(f"Ошибка получения баланса для {asset}: {e}")
            return 0.0
