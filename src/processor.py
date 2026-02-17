import logging
import aiohttp
import os
import asyncio
from parser import parse_killmail
from discord_utils import bot
from dotenv import load_dotenv
from collections import deque

load_dotenv()

# Константы для сессии
SESSION_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)
USER_AGENT = os.getenv("USER_AGENT", "EVE-KillBot/5.0 (Discord Bot)")

# Оптимизированная дедупликация: set для быстрой проверки + deque для лимита
processed_kills_set = set()
processed_kills_queue = deque(maxlen=1000)

# Статистика для мониторинга
stats = {
    "processed_total": 0,
    "duplicates_skipped": 0,
    "errors": 0,
    "notifications_sent": 0
}

async def fetch_with_retry(session, url, retries=3, timeout=10):
    """Повторяет запрос при сетевых сбоях с экспоненциальной задержкой"""
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
                elif resp.status == 420:  # Rate limit
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
    """Обновляет систему отслеживания дубликатов"""
    processed_kills_set.add(k_id)
    processed_kills_queue.append(k_id)
    
    if len(processed_kills_queue) >= 1000:
        if len(processed_kills_set) > 1100:
            processed_kills_set.clear()
            processed_kills_set.update(processed_kills_queue)

async def start_processor(data_queue, config):
    logging.info("⚙️ Многоканальный обработчик событий запущен...")
    all_subs = config.get("all_subs", {})
    filter_sets = config.get("filter_sets", {})  # Получаем оптимизированные сеты
    
    # Создаем сессию один раз для всего процессора
    async with aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT},
        timeout=SESSION_TIMEOUT,
        connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    ) as session:
        
        logging.info("🔥 [PROCESSOR] СЕССИЯ ОТКРЫТА, НАЧИНАЮ ОБРАБОТКУ...")
        
        while True:
            try:
                data = await data_queue.get()
                k_id = data.get('killID') or data.get('killmail_id')
                
                if not k_id:
                    logging.warning("❓ Получены данные без KillID")
                    data_queue.task_done()
                    continue
                
                logging.info(f"📥 [PROCESSOR] Начинаю обработку KillID: {k_id}")
                
                if k_id in processed_kills_set:
                    stats["duplicates_skipped"] += 1
                    logging.info(f"⏭️ [PROCESSOR] Пропускаю дубликат KillID: {k_id}")
                    data_queue.task_done()
                    continue
                
                try:
                    channel_info = data.get('channel', '')
                    wh_const_id = None
                    wh_reg_id = None
                    
                    if "constellation:" in channel_info:
                        try:
                            wh_const_id = int(channel_info.split(":")[1])
                        except (IndexError, ValueError):
                            pass
                            
                    if "region:" in channel_info:
                        try:
                            wh_reg_id = int(channel_info.split(":")[1])
                        except (IndexError, ValueError):
                            pass
                    
                    zk_data_source = data.get('zkb', {})
                    k_hash = zk_data_source.get('hash')

                    if not k_hash:
                        logging.info(f"🔍 Запрос хэша для {k_id} у zKillboard...")
                        zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                        zk_res = await fetch_with_retry(session, zk_url, retries=2, timeout=10)
                        
                        if zk_res and isinstance(zk_res, list) and len(zk_res) > 0:
                            zk_data_source = zk_res[0].get('zkb', {})
                            k_hash = zk_data_source.get('hash')

                    if not k_hash:
                        logging.error(f"❌ Не удалось получить хэш для {k_id}. Пропускаю.")
                        stats["errors"] += 1
                        data_queue.task_done()
                        continue

                    logging.info(f"🌐 Запрос детальных данных для {k_id} из ESI...")
                    esi_url = f"https://esi.evetech.net/latest/killmails/{k_id}/{k_hash}/?datasource=tranquility"
                    esi_data = await fetch_with_retry(session, esi_url, retries=3, timeout=15)
                    
                    if not esi_data:
                        logging.warning(f"📭 ESI не вернул данные для {k_id}. Пропускаю.")
                        stats["errors"] += 1
                        data_queue.task_done()
                        continue
                    
                    full_killmail = {**esi_data, "zkb": zk_data_source}
                    
                    if wh_const_id:
                        full_killmail['constellation_id'] = wh_const_id
                    if wh_reg_id:
                        full_killmail['region_id'] = wh_reg_id
                    
                    logging.info(f"⚙️ Проверка фильтров {k_id} для {len(all_subs)} каналов...")
                    
                    matches_found = 0
                    
                    for ch_id, ch_config in all_subs.items():
                        delivery_key = f"{k_id}:{ch_id}"
                        
                        if delivery_key in processed_kills_set:
                            continue
                        
                        # Передаем в парсер готовые сеты фильтров
                        is_match, event_type = parse_killmail(
                            full_killmail, 
                            ch_config,
                            filter_sets  # Передаем оптимизированные сеты
                        )
                        
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
                
                except Exception as e:
                    logging.error(f"💥 Ошибка при обработке {k_id}: {e}", exc_info=True)
                    stats["errors"] += 1
                    
            except asyncio.CancelledError:
                logging.info("🛑 Processor получил сигнал остановки")
                raise
                
            except Exception as e:
                logging.error(f"💥 Критическая ошибка в processor loop: {e}", exc_info=True)
                
            finally:
                data_queue.task_done()
                
                if stats["processed_total"] % 100 == 0 and stats["processed_total"] > 0:
                    logging.info(
                        f"📊 Статистика: Обработано: {stats['processed_total']}, "
                        f"Уведомлений: {stats['notifications_sent']}, "
                        f"Дубликатов: {stats['duplicates_skipped']}, "
                        f"Ошибок: {stats['errors']}"
                    )

def get_processor_stats():
    """Возвращает текущую статистику процессора"""
    return stats.copy()