import asyncio
import logging
import os
import signal
import logging.handlers
import re

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
def setup_logging():
    """Настройка логирования - вызывается до всех импортов"""
    log_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_handler = logging.handlers.RotatingFileHandler(
        'killbot.log',
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    if not root_logger.handlers:
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
    
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)

setup_logging()

# === ИМПОРТЫ ===
from dotenv import load_dotenv
load_dotenv()
from image_generator_large import get_generator, start_cleanup, stop_cleanup
from listener import start_listener
from processor import start_processor, get_processor_stats
from discord_utils import bot, load_subs
from monitoring import monitor

shutdown_event = asyncio.Event()

def get_current_config():
    """Загружает и оптимизирует конфигурацию"""
    try:
        subs = load_subs()
        if not subs:
            logging.warning("subscriptions.json is empty or not found!")
            return None
        
        # Оптимизация: сразу создаем сеты для быстрой проверки в парсере
        global_ids = {
            "corps": set(), "systems": set(), "regions": set(),
            "ships": set(), "ping_sys": set(), "ping_ship": set(),
            "chars": set(), "consts": set()
        }
        
        for ch_id, ch_data in subs.items():
            for key in global_ids.keys():
                if key in ch_data and isinstance(ch_data[key], list):
                    # Конвертируем в int и добавляем в сет
                    global_ids[key].update(int(x) for x in ch_data[key] if str(x).isdigit())
        
        # Создаем оптимизированный конфиг с сетами для парсера
        config = {
            "filter_sets": global_ids,  # Готовые сеты для быстрой проверки
            "all_subs": subs,
            "min_value": float(os.getenv("MIN_VALUE", 1_000_000))
        }
        
        total_filters = sum(len(v) for v in global_ids.values())
        logging.info(f"📊 Конфиг загружен: {total_filters} фильтров, {len(subs)} каналов")
        return config
        
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки конфига: {e}", exc_info=True)
        return None

async def run_zkill_tasks(shared_queue):
    logging.info("--- MONITORING SYSTEM STARTING ---")

    while not bot.is_ready():
        if shutdown_event.is_set():
            return
        await asyncio.sleep(1)

    logging.info("✅ Discord bot ready")
    
    # Запускаем очистку изображений
    await start_cleanup()
    
    # Используем контекстный менеджер для мониторинга
    async with monitor:
        while not shutdown_event.is_set():
            config = get_current_config()
            
            if not config:
                logging.warning("⚠️ Config unavailable. Retry in 10s...")
                await asyncio.sleep(10)
                continue

            logging.info(f"🚀 Starting workers for {len(config['all_subs'])} channels")

            listener_task = asyncio.create_task(start_listener(shared_queue, config))
            processor_task = asyncio.create_task(start_processor(shared_queue, config))
            
            bot.config_updated = False

            while not bot.config_updated and not shutdown_event.is_set():
                if listener_task.done():
                    try:
                        listener_task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logging.error(f"💥 Listener crashed: {e}")
                    break
                    
                if processor_task.done():
                    try:
                        processor_task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logging.error(f"💥 Processor crashed: {e}")
                    break
                    
                await asyncio.sleep(2)

            logging.info("🛑 Stopping workers...")
            
            listener_task.cancel()
            processor_task.cancel()
            await asyncio.gather(listener_task, processor_task, return_exceptions=True)
            
            if not shutdown_event.is_set() and shared_queue.qsize() > 0:
                logging.info(f"⏳ Processing {shared_queue.qsize()} remaining kills...")
                try:
                    await asyncio.wait_for(shared_queue.join(), timeout=30.0)
                except asyncio.TimeoutError:
                    logging.warning("⚠️ Timeout waiting for queue to clear")
            
            while not shared_queue.empty():
                try:
                    shared_queue.get_nowait()
                    shared_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            
            if not shutdown_event.is_set():
                await asyncio.sleep(2)
    await stop_cleanup()
    logging.info("📊 Monitoring system stopped")


async def main():
    queue_size = int(os.getenv("QUEUE_MAX_SIZE", 200))
    shared_queue = asyncio.Queue(maxsize=queue_size)
    
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logging.critical("❌ DISCORD_BOT_TOKEN missing!")
        return

    def signal_handler():
        logging.info("🛑 Shutdown signal received")
        shutdown_event.set()
    
    # Настройка обработчиков сигналов
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        logging.info("🚀 Starting EVE KillBot...")
        
        bot_task = asyncio.create_task(bot.start(token))
        zkill_task = asyncio.create_task(run_zkill_tasks(shared_queue))
        
        done, pending = await asyncio.wait(
            [bot_task, zkill_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
    except KeyboardInterrupt:
        pass
    finally:
        logging.info("🔌 Closing connections...")
        
        if not bot.is_closed():
            await bot.close()
        
        if hasattr(bot, 'session') and bot.session and not bot.session.closed:
            await bot.session.close()
        
        await asyncio.sleep(0.5)
        logging.info("👋 EVE KillBot stopped. o7")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass