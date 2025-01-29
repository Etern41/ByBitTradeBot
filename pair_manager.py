import json
import os

PAIRS_FILE = "pairs.json"


class PairManager:
    def __init__(self):
        """Инициализация менеджера пар"""
        self.pairs = self._load_pairs()

    def _load_pairs(self):
        """Загружает пары из файла"""
        if not os.path.exists(PAIRS_FILE):
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]  # Дефолтные пары

        with open(PAIRS_FILE, "r") as file:
            return json.load(file)

    def _save_pairs(self):
        """Сохраняет пары в файл"""
        with open(PAIRS_FILE, "w") as file:
            json.dump(self.pairs, file)

    def get_pairs(self):
        """Возвращает текущий список пар"""
        return self.pairs

    def add_pair(self, pair):
        """Добавляет новую пару"""
        if pair not in self.pairs:
            self.pairs.append(pair)
            self._save_pairs()
            return f"✅ Пара {pair} добавлена!"
        return f"⚠️ Пара {pair} уже есть в списке!"

    def remove_pair(self, pair):
        """Удаляет пару"""
        if pair in self.pairs:
            self.pairs.remove(pair)
            self._save_pairs()
            return f"❌ Пара {pair} удалена!"
        return f"⚠️ Пары {pair} нет в списке!"
