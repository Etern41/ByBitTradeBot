# Bybit API
BYBIT_API_KEY = "API"
BYBIT_API_SECRET = "SECRET API"
USE_TESTNET = True  # True - TESTNET, False - MAINNET

# Telegram Bot
TELEGRAM_API_TOKEN = "TG BOT TOKEN"
ADMIN_CHAT_ID = 00000  # Telegram ID


TRADE_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

TRADE_INTERVAL = "5"
ORDER_COOLDOWN = 30  # Задержка перед повторным ордером (в секундах)
PRICE_CHANGE_THRESHOLD = 0.03  # Минимальное изменение цены (3%)
STOP_LOSS_PERCENT = 0.02  # Stop-Loss 2%
TAKE_PROFIT_PERCENT = 0.05  # Take-Profit 5%
AUTO_UPDATE_PAIRS = True  # Включить автообновление списка пар
UPDATE_INTERVAL = 3600  # Интервал обновления (в секундах)
# Минимальный 24-часовой объем торгов (в USDT)
MIN_VOLUME_USDT = 10000

# Максимальная волатильность свечи (%)
MAX_VOLATILITY = 50

# Автообновление списка пар (раз в сутки)
AUTO_UPDATE_PAIRS = True
