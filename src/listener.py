import asyncio
import json
import logging
import aiohttp
import os

SESSION_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)

async def start_listener(data_queue, config):
    uri = "wss://zkillboard.com/websocket/"
    reconnect_delay = 5
    max_delay = 300

    # Заголовки для WebSocket (имитируем браузер)
    ws_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://zkillboard.com",
        "Referer": "https://zkillboard.com/"
    }

    logging.info("🔗 Подключение к WebSocket zKillboard...")

    async with aiohttp.ClientSession(
        timeout=SESSION_TIMEOUT,
        headers={"User-Agent": os.getenv("USER_AGENT", "EVE-KillBot/5.0 (Discord Bot)")}
    ) as session:

        while True:
            try:
                async with session.ws_connect(uri, headers=ws_headers) as websocket:
                    reconnect_delay = 5
                    logging.info("✅ Успешное подключение к zKillboard WebSocket")

                    # Получаем сеты фильтров из оптимизированного конфига
                    filter_sets = config.get("filter_sets", {})

                    # Собираем все каналы для подписки
                    channels = []
                    for sys_id in filter_sets.get("ping_sys", []):
                        channels.append(f"system:{sys_id}")
                    for ship_id in filter_sets.get("ping_ship", []):
                        channels.append(f"ship:{ship_id}")
                    for corp_id in filter_sets.get("corps", []):
                        channels.append(f"corporation:{corp_id}")
                    for ship_id in filter_sets.get("ships", []):
                        channels.append(f"ship:{ship_id}")
                    for sys_id in filter_sets.get("systems", []):
                        channels.append(f"system:{sys_id}")
                    for reg_id in filter_sets.get("regions", []):
                        channels.append(f"region:{reg_id}")
                    for const_id in filter_sets.get("consts", []):
                        channels.append(f"constellation:{const_id}")
                    for char_id in filter_sets.get("chars", []):
                        channels.append(f"character:{char_id}")

                    # Убираем дубликаты
                    channels = list(set([c for c in channels if ":" in c]))
                    if "killstream" not in channels:
                        channels.insert(0, "killstream")

                    logging.info(f"📡 Всего каналов для подписки: {len(channels)}")

                    # Подписываемся на killstream первым
                    await websocket.send_json({"action": "sub", "channel": "killstream"})
                    await asyncio.sleep(0.5)
                    logging.info("✅ Подписка на killstream установлена")

                    subscribed = 0
                    errors = 0
                    for channel in channels:
                        if channel == "killstream":
                            continue
                        try:
                            await websocket.send_json({"action": "sub", "channel": channel})
                            subscribed += 1
                            if subscribed % 20 == 0:
                                logging.info(f"📡 Прогресс: {subscribed}/{len(channels)-1} каналов")
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            errors += 1
                            logging.warning(f"⚠️ Не удалось подписаться на {channel}: {e}")

                    logging.info(f"✅ Подписки завершены: {subscribed} успешно, {errors} ошибок")

                    # Основной цикл обработки сообщений
                    async for msg in websocket:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
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
                                if 'channel' in data and data['channel'] == 'public' and 'kills' in data:
                                    logging.info(f"📊 Статистика zKillboard: {data.get('kills', 0)} убийств за последний час")
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logging.warning("WebSocket закрыт со стороны сервера")
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logging.error(f"Ошибка WebSocket: {websocket.exception()}")
                            break

            except aiohttp.ClientError as e:
                logging.warning(f"⚠️ Ошибка соединения: {e}. Переподключение через {reconnect_delay} сек...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

            except asyncio.CancelledError:
                logging.info("🛑 Listener получил сигнал остановки")
                raise

            except Exception as e:
                logging.error(f"❌ Неожиданная ошибка в Listener: {e}", exc_info=True)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)