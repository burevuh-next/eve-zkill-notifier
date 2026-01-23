import asyncio
import logging
import os
from dotenv import load_dotenv


# Импортируем функции из твоих новых файлов
from listener import start_listener
from processor import start_processor

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

load_dotenv()
async def main():
    def get_list(key):
        val = os.getenv(key, "")
        # Очищаем от пробелов и пустых значений, переводим в int
        return {int(x.strip()) for x in val.split(",") if x.strip().isdigit()}
    
    config = {
        "corps": get_list("MY_CORP_IDS"),
        "systems": get_list("WATCHED_SYSTEM_IDS"),
        "regions": get_list("WATCHED_REGIONS_IDS"),
        "constellations": get_list("WATCHED_CONSTELLATION_IDS"),
        "ships": get_list("WATCHED_SHIP_IDS"),
        "min_value": float(os.getenv("MIN_VALUE", 1000000))
    }
    
    print("="*30)
    print("⚙️  КОНФИГУРАЦИЯ ЗАГРУЖЕНА:")
    print(f"🏢  Корпорации:    {len(config['corps'])} шт.")
    print(f"🌌  Системы:       {len(config['systems'])} шт.")
    print(f"🛰  Регионы:       {len(config['regions'])} шт.")
    print(f"🛰  Созвездия:     {len(config['constellations'])} шт.")
    print(f"🚀  Типы кораблей: {len(config['ships'])} шт.")
    print(f"💰  Мин. цена:     {config['min_value']:,.0f} ISK")
    print("="*30)

    
    shared_queue = asyncio.Queue(maxsize=100)

    # Теперь функции будут найдены
    await asyncio.gather(
        start_listener(shared_queue,config),
        start_processor(shared_queue,config)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass