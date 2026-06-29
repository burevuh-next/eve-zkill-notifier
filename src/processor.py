import logging
import aiohttp
import os
import asyncio
import time
from parser import parse_killmail
from discord_utils import bot
from dotenv import load_dotenv
from collections import deque

load_dotenv()

SESSION_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Дедупликация
processed_kills_set = set()
processed_kills_queue = deque(maxlen=1000)

# Отложенные киллы
pending_kills = {}  # {kill_id: {"data": data, "attempts": int, "next_try": timestamp}}
PENDING_INTERVAL = 60  # секунд между попытками (было 30)
MAX_ATTEMPTS = 15      # максимальное число попыток (было 5)

stats = {
    "processed_total": 0,
    "duplicates_skipped": 0,
    "errors": 0,
    "notifications_sent": 0
}

async def fetch_with_retry(session, url, retries=3, timeout=10):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data:
                        logging.warning(f"⚠️ zKillboard вернул пустой ответ для {url}")
                    else:
                        logging.debug(f"📦 Ответ от zKillboard: {data}")
                    return data
                elif resp.status == 404:
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
                elif resp.status == 420:
                    logging.warning(f"⚠️ Rate limit от ESI. Ожидание 60с...")
                    await asyncio.sleep(60)
                else:
                    logging.warning(f"⚠️ ESI вернул статус {resp.status} для {url}")
        except asyncio.TimeoutError:
            if attempt == retries - 1:
                logging.warning(f"⚠️ Таймаут при запросе к {url} после {retries} попыток")
                return None
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            if attempt == retries - 1:
                logging.warning(f"⚠️ Ошибка при запросе к {url}: {e}")
                return None
            await asyncio.sleep(2 ** attempt)
    return None

def update_duplicate_tracking(k_id):
    processed_kills_set.add(k_id)
    processed_kills_queue.append(k_id)
    if len(processed_kills_queue) >= 1000 and len(processed_kills_set) > 1100:
        processed_kills_set.clear()
        processed_kills_set.update(processed_kills_queue)

async def process_kill_with_hash(k_id, k_hash, data, all_subs, filter_sets, session):
    """Общая функция для обработки килла после получения хэша"""
    if k_id in processed_kills_set:
        return

    logging.info(f"🌐 Запрос детальных данных для {k_id} из ESI...")
    esi_url = f"https://esi.evetech.net/latest/killmails/{k_id}/{k_hash}/?datasource=tranquility"
    esi_data = await fetch_with_retry(session, esi_url, retries=3, timeout=15)
    if not esi_data:
        logging.warning(f"📭 ESI не вернул данные для {k_id}. Пропускаем.")
        stats["errors"] += 1
        return

    zk_data_source = data.get('zkb', {})
    full_killmail = {**esi_data, "zkb": zk_data_source}

    channel_info = data.get('channel', '')
    if "constellation:" in channel_info:
        try:
            wh_const_id = int(channel_info.split(":")[1])
            full_killmail['constellation_id'] = wh_const_id
        except:
            pass
    if "region:" in channel_info:
        try:
            wh_reg_id = int(channel_info.split(":")[1])
            full_killmail['region_id'] = wh_reg_id
        except:
            pass

    logging.info(f"⚙️ Проверка фильтров {k_id} для {len(all_subs)} каналов...")
    matches_found = 0

    for ch_id, ch_config in all_subs.items():
        delivery_key = f"{k_id}:{ch_id}"
        if delivery_key in processed_kills_set:
            continue

        is_match, event_type = parse_killmail(full_killmail, ch_config, filter_sets)
        if is_match:
            matches_found += 1
            logging.info(f"🎯 [ID: {k_id}] Совпадение для канала {ch_id}! Тип: {event_type}")
            update_duplicate_tracking(delivery_key)
            try:
                await bot.send_kill_notification(ch_id, full_killmail, event_type)
                stats["notifications_sent"] += 1
                logging.info(f"✅ Уведомление отправлено в канал {ch_id}")
            except Exception as send_error:
                logging.error(f"❌ Ошибка отправки в канал {ch_id}: {send_error}")
                stats["errors"] += 1

    update_duplicate_tracking(k_id)
    stats["processed_total"] += 1
    if matches_found > 0:
        logging.info(f"✅ KillID {k_id} обработан. Совпадений: {matches_found}")
    else:
        logging.debug(f"⏭️ KillID {k_id} не подошел ни под один фильтр")

async def process_pending_kills(session, all_subs, filter_sets):
    """Фоновая задача для повторных попыток"""
    while True:
        await asyncio.sleep(10)
        now = time.time()
        to_remove = []
        for k_id, info in list(pending_kills.items()):
            if now >= info["next_try"]:
                data = info["data"]
                zk_data_source = data.get('zkb', {})
                k_hash = zk_data_source.get('hash')
                if not k_hash:
                    attempt = info["attempts"] + 1
                    logging.info(f"🔄 Повторный запрос хэша для KillID {k_id} (попытка {attempt}/{MAX_ATTEMPTS})")
                    zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                    zk_res = await fetch_with_retry(session, zk_url, retries=1, timeout=10)
                    if zk_res and isinstance(zk_res, list) and len(zk_res) > 0:
                        zk_data_source = zk_res[0].get('zkb', {})
                        k_hash = zk_data_source.get('hash')
                        if k_hash:
                            logging.info(f"✅ Получен хэш для KillID {k_id} после {attempt} попыток")
                if k_hash:
                    await process_kill_with_hash(k_id, k_hash, data, all_subs, filter_sets, session)
                    to_remove.append(k_id)
                else:
                    info["attempts"] += 1
                    if info["attempts"] >= MAX_ATTEMPTS:
                        logging.error(f"❌ Превышено количество попыток для KillID {k_id}. Пропускаем.")
                        to_remove.append(k_id)
                    else:
                        next_try = now + PENDING_INTERVAL
                        info["next_try"] = next_try
                        # ЯВНО ВЫВОДИМ ВРЕМЯ СЛЕДУЮЩЕЙ ПОПЫТКИ
                        logging.info(f"⏳ Следующая попытка для KillID {k_id} в {time.ctime(next_try)} (через {PENDING_INTERVAL}с)")
        for k_id in to_remove:
            pending_kills.pop(k_id, None)

async def start_processor(data_queue, config):
    logging.info("⚙️ Многоканальный обработчик событий запущен...")
    all_subs = config.get("all_subs", {})
    filter_sets = config.get("filter_sets", {})

    headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://zkillboard.com",
        "Referer": "https://zkillboard.com/",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }
    async with aiohttp.ClientSession(
        headers=headers,
        timeout=SESSION_TIMEOUT,
        connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    ) as session:
        logging.info("🔥 [PROCESSOR] СЕССИЯ ОТКРЫТА, НАЧИНАЮ ОБРАБОТКУ...")
        pending_task = asyncio.create_task(process_pending_kills(session, all_subs, filter_sets))

        try:
            while True:
                try:
                    data = await data_queue.get()
                except asyncio.CancelledError:
                    logging.info("🛑 Processor получил сигнал остановки")
                    raise
                except Exception as e:
                    logging.error(f"❌ Ошибка получения из очереди: {e}")
                    continue

                k_id = data.get('killID') or data.get('killmail_id')
                if not k_id:
                    logging.warning("❓ Получены данные без KillID")
                    data_queue.task_done()
                    continue

                logging.info(f"📥 [PROCESSOR] Начинаю обработку KillID: {k_id}")

                # Логируем содержимое WebSocket сообщения (для отладки)
                logging.debug(f"📨 WebSocket данные: {data}")

                if k_id in processed_kills_set:
                    stats["duplicates_skipped"] += 1
                    logging.info(f"⏭️ [PROCESSOR] Пропускаю дубликат KillID: {k_id}")
                    data_queue.task_done()
                    continue

                zk_data_source = data.get('zkb', {})
                k_hash = zk_data_source.get('hash')
                if not k_hash:
                    logging.info(f"🔍 Запрос хэша для {k_id} у zKillboard...")
                    zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                    zk_res = await fetch_with_retry(session, zk_url, retries=2, timeout=10)
                    if zk_res and isinstance(zk_res, list) and len(zk_res) > 0:
                        zk_data_source = zk_res[0].get('zkb', {})
                        k_hash = zk_data_source.get('hash')
                        if k_hash:
                            logging.info(f"✅ Хэш для {k_id} получен сразу")

                if k_hash:
                    await process_kill_with_hash(k_id, k_hash, data, all_subs, filter_sets, session)
                    data_queue.task_done()
                else:
                    next_try_time = time.time() + PENDING_INTERVAL
                    logging.info(f"⏳ KillID {k_id} временно отсутствует, добавляем в отложенные. Следующая попытка в {time.ctime(next_try_time)}")
                    pending_kills[k_id] = {
                        "data": data,
                        "attempts": 0,
                        "next_try": next_try_time
                    }
                    data_queue.task_done()
                if stats["processed_total"] % 100 == 0 and stats["processed_total"] > 0:
                    logging.info(
                        f"📊 Статистика: Обработано: {stats['processed_total']}, "
                        f"Уведомлений: {stats['notifications_sent']}, "
                        f"Дубликатов: {stats['duplicates_skipped']}, "
                        f"Ошибок: {stats['errors']}"
                    )
        finally:
            pending_task.cancel()
            try:
                await pending_task
            except asyncio.CancelledError:
                pass

def get_processor_stats():
    return stats.copy()