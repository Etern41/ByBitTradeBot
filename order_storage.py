import json
import os

ORDERS_FILE = "active_orders.json"


def load_active_orders():
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, "r") as file:
                return json.load(file)
        except Exception as e:
            print(f"Ошибка загрузки активных ордеров: {e}")
            return {}
    return {}


def save_active_orders(active_orders):
    try:
        with open(ORDERS_FILE, "w") as file:
            json.dump(active_orders, file, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения активных ордеров: {e}")
