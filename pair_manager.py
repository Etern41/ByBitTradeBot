import json
from config import TRADE_PAIRS


class PairManager:
    """Менеджер торговых пар: загружает, обновляет и хранит пары"""

    def __init__(self):
        self.pairs_file = "trade_pairs.json"
        self.active_pairs = self.load_pairs()

    def load_pairs(self):
        """Загружает торговые пары из JSON или берёт из trade_pairs.py"""
        try:
            with open(self.pairs_file, "r") as file:
                data = json.load(file)
                return data.get("TRADE_PAIRS", TRADE_PAIRS)
        except (FileNotFoundError, json.JSONDecodeError):
            return TRADE_PAIRS

    def save_pairs(self, pairs):
        """Сохраняет новые пары в trade_pairs.json"""
        self.active_pairs = pairs
        with open(self.pairs_file, "w") as file:
            json.dump({"TRADE_PAIRS": pairs}, file, indent=4)

    def get_active_pairs(self):
        """Возвращает актуальный список пар"""
        return self.active_pairs
