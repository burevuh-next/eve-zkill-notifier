import asyncio
import logging
import os
import json
from dotenv import load_dotenv

# Импортируем листенер, процессор и объект бота
from listener import start_listener
from processor import start_processor
from discord_utils import bot  

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

load_dotenv()

def get_current_config():
    """Функция для динамической сборки конфига из окружения"""
    def get_list(key):
        val = os.getenv(key, "")
        return {int(x.strip()) for x in val.split(",") if x.strip().isdigit()}
    
    return {
        "corps": get_list("MY_CORP_IDS"),
        "systems": get_list("WATCHED_SYSTEM_IDS"),
        "regions": get_list("WATCHED_REGIONS_IDS"),
        "constellations": get_list("WATCHED_CONSTELLATION_IDS"),
        "ships": get_list("WATCHED_SHIP_IDS"),
        "ping_sys": get_list("PING_SYSTEM_IDS"),
        "ping_ship": get_list("PING_SHIP_IDS"),
        "min_value": float(os.getenv("MIN_VALUE", 1000000))
    }

async def run_zkill_tasks(shared_queue):
    """Управляет жизненным циклом листенера и процессора"""
    while True:
        config = get_current_config()
        
        print("\n" + "="*30)
        print("🔄 ПРИМЕНЕНИЕ КОНФИГУРАЦИИ:")
        print(f"🌌 Системы: {len(config['systems'])} | 🏢 Корпы: {len(config['corps'])}")
        print("="*30)

        # Создаем задачи для прослушивания и обработки
        listener_task = asyncio.create_task(start_listener(shared_queue, config))
        processor_task = asyncio.create_task(start_processor(shared_queue, config))
        
        # Сбрасываем флаг, так как мы только что применили конфиг
        bot.config_updated = False

        # Ждем, пока либо задачи упадут сами, либо флаг в боте изменится
        while not bot.config_updated:
            # Проверяем не упали ли задачи (на всякий случай)
            if listener_task.done() or processor_task.done():
                logging.warning("⚠️ Одна из задач завершилась. Перезапуск...")
                break
            await asyncio.sleep(1) # Короткая пауза для проверки флага

        # Если мы вышли из цикла, значит флаг config_updated стал True
        logging.info("⚙️ Конфигурация изменилась. Перезапуск потоков zKill...")
        
        # Отменяем текущие задачи
        listener_task.cancel()
        processor_task.cancel()
        
        # Ждем завершения отмены
        await asyncio.gather(listener_task, processor_task, return_exceptions=True)
        logging.info("✅ Старые потоки остановлены. Запуск новых...")

async def main():
    shared_queue = asyncio.Queue(maxsize=100)
    token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not token:
        logging.critical("❌ DISCORD_BOT_TOKEN не найден!")
        return

    # Запускаем Discord бота и менеджер задач zKill одновременно
    try:
        await asyncio.gather(
            bot.start(token),
            run_zkill_tasks(shared_queue)
        )
    except Exception as e:
        logging.error(f"💥 Критическая ошибка: {e}")
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен.")