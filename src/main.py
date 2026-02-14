import asyncio
import logging
import os
from dotenv import load_dotenv

# Импортируем всё необходимое из твоих файлов
from listener import start_listener
from processor import start_processor
# Важно: убедись, что в discord_utils есть функция load_subs и объект bot
from discord_utils import bot, load_subs 

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s | %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

load_dotenv()

def get_current_config():
    """Собирает агрегированный конфиг для WebSocket и детальный для каналов"""
    try:
        subs = load_subs()
        if not subs:
            logging.warning("⚠️ Файл subscriptions.json пуст или не найден!")
        
        global_ids = {
            "corps": set(), "systems": set(), "regions": set(),
            "ships": set(), "ping_sys": set(), "ping_ship": set(),
            "chars": set(), "consts": set()
        }
        
        for ch_id, ch_data in subs.items():
            for key in global_ids.keys():
                if key in ch_data:
                    global_ids[key].update(ch_data[key])
        
        config = {k: list(v) for k, v in global_ids.items()}
        config["all_subs"] = subs 
        config["min_value"] = float(os.getenv("MIN_VALUE", 1))
        return config
    except Exception as e:
        logging.error(f"❌ Ошибка в get_current_config: {e}")
        return None

async def run_zkill_tasks(shared_queue):
    logging.info("--- ⚙️ СИСТЕМА МОНИТОРИНГА ГОТОВИТСЯ К СТАРТУ ---")

    # Ждем, пока Discord бот загрузится (Shard ID станет не None)
    while not bot.is_ready():
        await asyncio.sleep(1)

    while True:
        config = get_current_config()
        if not config:
            await asyncio.sleep(10)
            continue

        logging.info(f"🔄 Конфигурация обновлена. Активных каналов: {len(config['all_subs'])}")

        listener_task = asyncio.create_task(start_listener(shared_queue, config))
        processor_task = asyncio.create_task(start_processor(shared_queue, config))
        
        bot.config_updated = False

        while not bot.config_updated:
            if listener_task.done() or processor_task.done():
                logging.error("🚨 Один из воркеров упал! Перезапуск через 5 сек...")
                break
            await asyncio.sleep(2)

        logging.warning("🔄 Остановка воркеров для обновления конфигурации...")
        listener_task.cancel()
        processor_task.cancel()
        await asyncio.gather(listener_task, processor_task, return_exceptions=True)
        
        # ОЧИЩАЕМ ОЧЕРЕДЬ принудительно, чтобы старые киллы не мешали     
        while not shared_queue.empty():
            try:
                shared_queue.get_nowait()
                shared_queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        logging.info("♻️ Очередь очищена. Рестарт...")
        await asyncio.sleep(2)

async def main():
    shared_queue = asyncio.Queue(maxsize=200)
    token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not token:
        logging.critical("❌ DISCORD_BOT_TOKEN отсутствует в .env!")
        return

    try:
        # Запускаем две основные задачи параллельно
        await asyncio.gather(
            bot.start(token),
            run_zkill_tasks(shared_queue)
        )
    except Exception as e:
        logging.error(f"💥 Критическая ошибка запуска: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass