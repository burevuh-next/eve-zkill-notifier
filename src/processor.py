import logging
import asyncio
import aiohttp
import json
import time
from parser import parse_killmail
from discord_utils import bot
from collections import deque

zkb_log = logging.getLogger('zkb_debug')

processed_kills_set = set()
processed_kills_queue = deque(maxlen=1000)

pending_kills = {}
PENDING_INTERVAL = 1800

stats = {
    "processed_total": 0,
    "duplicates_skipped": 0,
    "errors": 0,
    "notifications_sent": 0,
}

def update_duplicate_tracking(k_id):
    processed_kills_set.add(k_id)
    processed_kills_queue.append(k_id)
    if len(processed_kills_queue) >= 1000 and len(processed_kills_set) > 1100:
        processed_kills_set.clear()
        processed_kills_set.update(processed_kills_queue)

def extract_channel_info(data):
    channel_info = data.get('channel', '')
    result = {}
    if "constellation:" in channel_info:
        try:
            result['constellation_id'] = int(channel_info.split(":")[1])
        except:
            pass
    if "region:" in channel_info:
        try:
            result['region_id'] = int(channel_info.split(":")[1])
        except:
            pass
    return result

async def process_kill(k_id, killmail_data, ws_data, all_subs, filter_sets):
    if k_id in processed_kills_set:
        return

    zkb_log.debug(f"[PROCESS] KillID={k_id} data_keys={list(killmail_data.keys())}")

    channel_extra = extract_channel_info(ws_data)
    if channel_extra:
        killmail_data.update(channel_extra)

    logging.info(f"⚙️ Проверка фильтров {k_id} для {len(all_subs)} каналов...")
    matches_found = 0

    for ch_id, ch_config in all_subs.items():
        delivery_key = f"{k_id}:{ch_id}"
        if delivery_key in processed_kills_set:
            continue

        is_match, event_type = parse_killmail(killmail_data, ch_config, filter_sets)
        if is_match:
            matches_found += 1
            logging.info(f"🎯 [ID: {k_id}] Совпадение для канала {ch_id}! Тип: {event_type}")
            update_duplicate_tracking(delivery_key)
            try:
                await bot.send_kill_notification(ch_id, killmail_data, event_type)
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

async def process_pending_kills(all_subs, filter_sets):
    while True:
        await asyncio.sleep(30)
        now = time.time()
        to_remove = []

        for k_id, info in list(pending_kills.items()):
            if now >= info["next_try"]:
                attempt = info["attempts"] + 1
                logging.info(f"🔄 Pending retry для KillID {k_id} (попытка {attempt})")
                try:
                    async with aiohttp.ClientSession() as session:
                        url = f"https://zkillboard.com/api/killID/{k_id}/"
                        async with session.get(url, headers={"User-Agent": "EVE-KillBot/5.0"}) as resp:
                            if resp.status == 200:
                                body = await resp.read()
                                if len(body) > 10:
                                    data = json.loads(body)
                                    if isinstance(data, list) and len(data) > 0:
                                        killmail_data = data[0]
                                        ws_data = info.get("data", {})
                                        await process_kill(k_id, killmail_data, ws_data, all_subs, filter_sets)
                                        to_remove.append(k_id)
                                        continue
                except Exception as e:
                    logging.warning(f"⚠️ Pending error {k_id}: {e}")

                info["attempts"] += 1
                backoff = min(PENDING_INTERVAL * (1 + info["attempts"] // 5), 7200)
                info["next_try"] = now + backoff
                zkb_log.debug(f"[PENDING] KillID={k_id} retry={attempt} next={time.ctime(info['next_try'])}")

        for k_id in to_remove:
            pending_kills.pop(k_id, None)

async def start_processor(data_queue, config):
    logging.info("⚙️ Обработчик событий запущен...")
    all_subs = config.get("all_subs", {})
    filter_sets = config.get("filter_sets", {})

    pending_task = asyncio.create_task(process_pending_kills(all_subs, filter_sets))

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

            if k_id in processed_kills_set:
                stats["duplicates_skipped"] += 1
                logging.info(f"⏭️ [PROCESSOR] Пропускаю дубликат KillID: {k_id}")
                data_queue.task_done()
                continue

            channel = data.get('channel', 'unknown')
            logging.info(f"📥 [PROCESSOR] KillID={k_id} channel={channel}")

            if not data.get('zkb'):
                logging.warning(f"⚠️ KillID {k_id}: нет zkb, добавляю в pending")
                pending_kills[k_id] = {"data": data, "attempts": 0, "next_try": time.time() + 60}
                data_queue.task_done()
                continue

            await process_kill(k_id, data, data, all_subs, filter_sets)
            data_queue.task_done()

            if stats["processed_total"] % 25 == 0 and stats["processed_total"] > 0:
                logging.info(
                    f"📊 Статистика: Обработано={stats['processed_total']}, "
                    f"Уведомлений={stats['notifications_sent']}, "
                    f"Дубликатов={stats['duplicates_skipped']}, "
                    f"Ошибок={stats['errors']}"
                )
    finally:
        pending_task.cancel()
        try:
            await pending_task
        except asyncio.CancelledError:
            pass

def get_processor_stats():
    return stats.copy()
