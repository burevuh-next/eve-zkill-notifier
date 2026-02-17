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
    
    # Создаем сессию один раз для всего цикла переподключений
    async with aiohttp.ClientSession(
        timeout=SESSION_TIMEOUT,
        headers={"User-Agent": os.getenv("USER_AGENT", "EVE-KillBot/5.0 (Discord Bot)")}
    ) as session:
        
        while True:
            try:
                async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as websocket:
                    # Сбрасываем задержку при успешном подключении
                    reconnect_delay = 5
                    logging.info("✅ Успешное подключение к zKillboard WebSocket")
                    
                    # Получаем сеты фильтров из оптимизированного конфига
                    filter_sets = config.get("filter_sets", {})
                    
                    # Собираем список каналов
                    channels = []
                    
                    # Базовые подписки
                    for corp_id in filter_sets.get("corps", []): 
                        channels.append(f"corporation:{corp_id}")
                    for ship_id in filter_sets.get("ships", []): 
                        channels.append(f"item:{ship_id}")
                    for sys_id in filter_sets.get("systems", []): 
                        channels.append(f"system:{sys_id}")
                    for reg_id in filter_sets.get("regions", []): 
                        channels.append(f"region:{reg_id}")
                    for const_id in filter_sets.get("consts", []): 
                        channels.append(f"constellation:{const_id}")
                    for char_id in filter_sets.get("chars", []): 
                        channels.append(f"character:{char_id}")
                    
                    # ПИНГ-каналы (приоритетные)
                    for p_ship in filter_sets.get("ping_ship", []): 
                        channels.append(f"item:{p_ship}")
                    for p_sys in filter_sets.get("ping_sys", []): 
                        channels.append(f"system:{p_sys}")

                    # Очистка от дубликатов
                    channels = list(set([c for c in channels if ":" in c]))

                    logging.info(f"📡 Подготовка подписок на {len(channels)} каналов...")
                    
                    # КРИТИЧНО: Сначала подписываемся на основной поток killstream
                    await websocket.send(json.dumps({"action": "sub", "channel": "killstream"}))
                    await asyncio.sleep(0.5)
                    logging.info("✅ Подписка на killstream установлена")
                    
                    # Затем подписываемся на все фильтры
                    for channel in channels:
                        try:
                            await websocket.send(json.dumps({"action": "sub", "channel": channel}))
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            logging.warning(f"⚠️ Не удалось подписаться на {channel}: {e}")
                    
                    logging.info(f"✅ Все подписки ({len(channels)}) отправлены zKillboard")
                    
                    # Основной цикл обработки сообщений
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError as e:
                            logging.error(f"❌ Ошибка парсинга JSON: {e}")
                            continue

                        k_id = data.get('killID') or data.get('killmail_id')
                        
                        if k_id:
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
                            logging.debug(f"⚙️ [LISTENER] Техническое сообщение: {data}")
                    
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