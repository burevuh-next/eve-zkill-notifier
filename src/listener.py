import asyncio
import websockets
import json
import logging
import aiohttp
import os

SESSION_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)

async def start_listener(data_queue, config):
    uri = "wss://zkillboard.com/websocket/"
    reconnect_delay = 5
    max_delay = 300
    
    logging.info("🔗 Подключение к WebSocket zKillboard...")
    
    async with aiohttp.ClientSession(
        timeout=SESSION_TIMEOUT,
        headers={"User-Agent": os.getenv("USER_AGENT", "EVE-KillBot/5.0 (Discord Bot)")}
    ) as session:
        
        while True:
            try:
                async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as websocket:
                    reconnect_delay = 5
                    logging.info("✅ Успешное подключение к zKillboard WebSocket")
                    
                    # Получаем сеты фильтров из оптимизированного конфига
                    filter_sets = config.get("filter_sets", {})
                    
                    # --- ИСПРАВЛЕНИЕ: собираем ВСЕ каналы для подписки ---
                    channels = []
                    
                    # 1. Приоритетные системы (ping_sys)
                    for sys_id in filter_sets.get("ping_sys", []):
                        channels.append(f"system:{sys_id}")
                        logging.debug(f"Добавлен приоритетный канал системы: {sys_id}")
                    
                    # 2. Приоритетные корабли (ping_ship)
                    for ship_id in filter_sets.get("ping_ship", []):
                        channels.append(f"ship:{ship_id}")
                        logging.debug(f"Добавлен приоритетный канал корабля: {ship_id}")
                    
                    # 3. Обычные корпорации
                    for corp_id in filter_sets.get("corps", []):
                        channels.append(f"corporation:{corp_id}")
                        logging.debug(f"Добавлен канал корпорации: {corp_id}")
                    
                    # 4. Обычные корабли
                    for ship_id in filter_sets.get("ships", []):
                        channels.append(f"ship:{ship_id}")
                        logging.debug(f"Добавлен канал корабля: {ship_id}")
                    
                    # 5. Обычные системы
                    for sys_id in filter_sets.get("systems", []):
                        channels.append(f"system:{sys_id}")
                        logging.debug(f"Добавлен канал системы: {sys_id}")
                    
                    # 6. Регионы
                    for reg_id in filter_sets.get("regions", []):
                        channels.append(f"region:{reg_id}")
                        logging.debug(f"Добавлен канал региона: {reg_id}")
                    
                    # 7. Созвездия
                    for const_id in filter_sets.get("consts", []):
                        channels.append(f"constellation:{const_id}")
                        logging.debug(f"Добавлен канал созвездия: {const_id}")
                    
                    # 8. Персонажи
                    for char_id in filter_sets.get("chars", []):
                        channels.append(f"character:{char_id}")
                        logging.debug(f"Добавлен канал персонажа: {char_id}")
                    
                    # Убираем дубликаты (если один ID есть и в обычных, и в приоритетных)
                    channels = list(set([c for c in channels if ":" in c]))
                    
                    # Обязательно подписываемся на killstream
                    if "killstream" not in channels:
                        channels.insert(0, "killstream")

                    logging.info(f"📡 Всего каналов для подписки: {len(channels)}")
                    
                    # Подписываемся на killstream первым (критично важно)
                    await websocket.send(json.dumps({"action": "sub", "channel": "killstream"}))
                    await asyncio.sleep(0.5)
                    logging.info("✅ Подписка на killstream установлена")
                    
                    # Подписываемся на остальные каналы
                    subscribed = 0
                    errors = 0
                    
                    for channel in channels:
                        if channel == "killstream":
                            continue  # уже подписались
                        
                        try:
                            await websocket.send(json.dumps({"action": "sub", "channel": channel}))
                            subscribed += 1
                            if subscribed % 20 == 0:  # Логируем каждые 20 подписок
                                logging.info(f"📡 Прогресс: {subscribed}/{len(channels)-1} каналов")
                            await asyncio.sleep(0.05)  # Небольшая задержка между подписками
                        except Exception as e:
                            errors += 1
                            logging.warning(f"⚠️ Не удалось подписаться на {channel}: {e}")
                    
                    logging.info(f"✅ Подписки завершены: {subscribed} успешно, {errors} ошибок")
                    
                    # Основной цикл обработки сообщений
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError as e:
                            logging.error(f"❌ Ошибка парсинга JSON: {e}")
                            continue

                        k_id = data.get('killID') or data.get('killmail_id')
                        
                        if k_id:
                            # Проверка переполнения очереди
                            if data_queue.qsize() >= data_queue.maxsize:
                                logging.warning(f"⚠️ Очередь переполнена ({data_queue.qsize()}). Пропускаю KillID: {k_id}")
                                continue
                            
                            logging.info(f"📡 [LISTENER] Получен KillID: {k_id}. Добавляю в очередь...")
                            try:
                                await asyncio.wait_for(data_queue.put(data), timeout=5.0)
                                logging.info(f"✅ [LISTENER] KillID {k_id} добавлен. Размер очереди: {data_queue.qsize()}")
                            except asyncio.TimeoutError:
                                logging.error(f"❌ Таймаут при добавлении {k_id} в очередь")
                        else:
                            # Техническое сообщение (пинг и т.д.)
                            if 'channel' in data and data['channel'] == 'public':
                                if 'kills' in data:
                                    logging.info(f"📊 Статистика zKillboard: {data.get('kills', 0)} убийств за последний час")
                    
            except websockets.ConnectionClosed as e:
                logging.warning(f"⚠️ WebSocket соединение закрыто: {e}. Переподключение через {reconnect_delay} сек...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)
                
            except asyncio.CancelledError:
                logging.info("🛑 Listener получил сигнал остановки")
                raise
                
            except Exception as e:
                logging.error(f"❌ Неожиданная ошибка в Listener: {e}", exc_info=True)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)