import asyncio
import websockets
import json
import logging

async def start_listener(data_queue, config):
    uri = "wss://zkillboard.com/websocket/"
    logging.info("🔗 Подключение к WebSocket zKillboard...")
    
    async for websocket in websockets.connect(uri):
        try:
            # Собираем список каналов
            channels = []
            
            # Базовые подписки
            for corp_id in config.get("corps", []): channels.append(f"corporation:{corp_id}")
            for ship_id in config.get("ships", []): channels.append(f"item:{ship_id}")
            for sys_id in config.get("systems", []): channels.append(f"system:{sys_id}")
            for reg_id in config.get("regions", []): channels.append(f"region:{reg_id}")
            for const_id in config.get("consts", []): channels.append(f"constellation:{const_id}")
            for char_id in config.get("chars", []): channels.append(f"character:{char_id}")
            
            # ПИНГ-каналы (ключи из вашего main.py: ping_sys и ping_ship)
            for p_ship in config.get("ping_ship", []): channels.append(f"item:{p_ship}")
            for p_sys in config.get("ping_sys", []): channels.append(f"system:{p_sys}")

            # Очистка
            channels = list(set([c for c in channels if ":" in c]))

            logging.info(f"📡 Отправка подписок на {len(channels)} каналов...")
            
            # Сначала ОБЯЗАТЕЛЬНО подписываемся на поток киллов
            #await websocket.send(json.dumps({"action": "sub", "channel": "killstream"}))
            
            # Затем на все фильтры
            for channel in channels:
                await websocket.send(json.dumps({"action": "sub", "channel": channel}))
            
            logging.info("✅ Все подписки приняты zKillboard.")
            # ВАЖНО: Этот цикл держит соединение открытым!
            async for message in websocket:
                try:
                    data = json.loads(message)
                except Exception as e:
                    logging.error(f"❌ Ошибка парсинга JSON: {e}")
                    continue

                k_id = data.get('killID')
                
                # Если это не техническое сообщение о подписке, а реальный килл
                if k_id:
                    logging.info(f"📡 [LISTENER] Пытаюсь положить в очередь KillID: {k_id}")
                    await data_queue.put(data)
                    logging.info(f"✅ [LISTENER] KillID {k_id} успешно добавлен в очередь. Размер: {data_queue.qsize()}")
                else:
                    # Это техническое сообщение (подписка и т.д.)
                    logging.debug(f"⚙️ [LISTENER] Техническое сообщение: {data}")
                
        except websockets.ConnectionClosed:
            logging.warning("⚠️ Соединение с zKillboard разорвано. Переподключение через 5 сек...")
            await asyncio.sleep(5)
            continue
        except Exception as e:
            logging.error(f"❌ Ошибка в Listener: {e}")
            await asyncio.sleep(5)