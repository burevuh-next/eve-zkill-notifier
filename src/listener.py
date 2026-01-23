import asyncio
import websockets
import json
import logging
import os

async def start_listener(data_queue,config):
    uri = "wss://zkillboard.com/websocket/"
    logging.info("🔗 Подключение к WebSocket zKillboard...")
 

    
    async for websocket in websockets.connect(uri):
        try:
            # Подписываемся на все киллы (или конкретную систему/корпорацию)
            for corp_id in config["corps"]:
                await websocket.send(json.dumps({"action": "sub", "channel": f"corporation:{corp_id}"}))
            for ship_id in config["ships"]:
                await websocket.send(json.dumps({"action": "sub", "channel": f"ship:{ship_id}"}))
            for const_id in config["constellations"]:
                await websocket.send(json.dumps({"action": "sub", "channel": f"constellation:{const_id}"}))
            for reg_id in config["regions"]:
                await websocket.send(json.dumps({"action": "sub", "channel": f"region:{reg_id}"}))
                    
            logging.info("✅ Подписка оформлена. Ожидание данных...")

            async for message in websocket:
                data = json.loads(message)
                # Кладем сырые данные в очередь для обработки
                await data_queue.put(data)
                
        except websockets.ConnectionClosed:
            logging.warning("⚠️ Соединение разорвано. Переподключение...")
            continue
        except Exception as e:
            logging.error(f"❌ Ошибка в Listener: {e}")
            await asyncio.sleep(5)