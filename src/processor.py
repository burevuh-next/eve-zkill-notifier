import logging
import aiohttp
import os
import asyncio
from parser import parse_killmail
from discord_utils import bot
from dotenv import load_dotenv
from collections import deque

load_dotenv()

# Храним последние 1000 ID обработанных киллов
processed_kills = deque(maxlen=1000)

async def fetch_with_retry(session, url, retries=3):
    """Повторяет запрос при сетевых сбоях или DNS тайм-аутах"""
    for i in range(retries):
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    # Килла еще нет в базе ESI, подождем немного дольше
                    await asyncio.sleep(2)
        except Exception as e:
            if i == retries - 1:
                logging.warning(f"⚠️ Не удалось связаться с ESI после {retries} попыток: {e}")
                return None
            await asyncio.sleep(1) # Ждем секунду перед повтором
    return None

async def start_processor(data_queue, config):
    logging.info("⚙️ Многоканальный обработчик событий запущен...")
    all_subs = config.get("all_subs", {})
    
    async with aiohttp.ClientSession(headers={"User-Agent": os.getenv("USER_AGENT", "Bober-Bot-v4.0")}) as session:
        logging.info("🔥 [PROCESSOR] СЕССИЯ ОТКРЫТА, НАЧИНАЮ СЛУШАТЬ ОЧЕРЕДЬ...")
        while True:
            data = await data_queue.get()
            logging.info(f"📥 Процессор взял в работу KillID: {data.get('killID')}")
            
            try:
                channel_info = data.get('channel', '')
                wh_const_id = None
                wh_reg_id = None            
                
                # Логика извлечения ID локации
                if "constellation:" in channel_info:
                    try: wh_const_id = int(channel_info.split(":")[1])
                    except: pass
                if "region:" in channel_info:
                    try: wh_reg_id = int(channel_info.split(":")[1])
                    except: pass
                
                k_id = data.get('killID') or data.get('killmail_id')
                
                #Проверяем на дубликат
                if k_id in processed_kills:
                    logging.info(f"⏭️ [PROCESSOR] Пропускаю дубликат KillID: {k_id}")
                    continue
                
                if not k_id:
                    logging.warning("❓ Данные без ID")
                    continue
                
                zk_data_source = data.get('zkb', {})
                k_hash = zk_data_source.get('hash')

                # Получаем хэш, если его нет
                if not k_hash:
                #    logging.info(f"🔍 Хэша нет для {k_id}, запрашиваем zKill...")
                    zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                    zk_res = await fetch_with_retry(session, zk_url)
                    if zk_res and isinstance(zk_res, list):
                        zk_data_source = zk_res[0].get('zkb', {})
                        k_hash = zk_data_source.get('hash')

                if not k_hash:
                    logging.error(f"❌ Не удалось получить хэш для {k_id}")
                    continue

                # --- ИСПОЛЬЗУЕМ RETRY ДЛЯ ESI ---
                logging.info(f"🌐 Запрос к ESI для {k_id}...")
                esi_url = f"https://esi.evetech.net/latest/killmails/{k_id}/{k_hash}/?datasource=tranquility"
                esi_data = await fetch_with_retry(session, esi_url)
                
                if not esi_data:
                    logging.warning(f"📭 ESI не вернул данные для {k_id}")
                    continue
                
                if esi_data:
                    # Сборка пакета данных
                    full_killmail = {**esi_data, "zkb": zk_data_source}
                    if wh_const_id: full_killmail['constellation_id'] = wh_const_id
                    if wh_reg_id: full_killmail['region_id'] = wh_reg_id
                    
                    logging.info(f"⚙️ Проверка фильтров для {k_id} в {len(all_subs)} каналах...")                                     
                    # Проверка по всем каналам
                    for ch_id, ch_config in all_subs.items():
                        
                        delivery_key = f"{k_id}:{ch_id}"     
                        
                        if delivery_key in processed_kills:
                            continue 
                        
                        is_ok, event = parse_killmail(full_killmail, ch_config)
                        if is_ok:
                            logging.info(f"🔥 [ID: {k_id}] Совпадение для канала {ch_id}! Отправка...")
                            processed_kills.append(delivery_key)
                            await bot.send_kill_notification(ch_id, full_killmail, event)
                        else:
                            # Раскомментируй эту строку, если хочешь видеть, почему НЕ подошло
                            logging.info(f"⏭️ {k_id} не подошел под фильтры канала {ch_id}")
                            pass
                    processed_kills.append(k_id)
            except Exception as e:
                # Это поймает ошибки, которые мы не предусмотрели (например, баг в парсере)
                logging.error(f"💥 Критическая ошибка при обработке {k_id}: {e}", exc_info=True)
                
            finally:
                data_queue.task_done()
                logging.info(f"✅ Очередь освобождена для {k_id}")