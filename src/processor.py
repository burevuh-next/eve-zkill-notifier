import logging
import aiohttp
import os
import asyncio
from parser import parse_killmail
from discord_utils import bot
from dotenv import load_dotenv

load_dotenv()

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
        while True:
            killmail_item = await data_queue.get()
            
            try:
                data = killmail_item
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
                if not k_id:
                    continue

                zk_data_source = data.get('zkb', {})
                k_hash = zk_data_source.get('hash')
                
                # Получаем хэш, если его нет
                if not k_hash:
                    zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                    zk_res = await fetch_with_retry(session, zk_url)
                    if zk_res and isinstance(zk_res, list):
                        zk_data_source = zk_res[0].get('zkb', {})
                        k_hash = zk_data_source.get('hash')

                if not k_hash:
                    continue

                # --- ИСПОЛЬЗУЕМ RETRY ДЛЯ ESI ---
                esi_url = f"https://esi.evetech.net/latest/killmails/{k_id}/{k_hash}/?datasource=tranquility"
                esi_data = await fetch_with_retry(session, esi_url)
                
                if esi_data:
                    # Сборка пакета данных
                    full_killmail = {**esi_data, "zkb": zk_data_source}
                    if wh_const_id: full_killmail['constellation_id'] = wh_const_id
                    if wh_reg_id: full_killmail['region_id'] = wh_reg_id
                                        
                    # Проверка по всем каналам
                    for ch_id, ch_config in all_subs.items():
                        is_ok, event = parse_killmail(full_killmail, ch_config)
                        if is_ok:
                            logging.info(f"🔥 [ID: {k_id}] Совпадение для канала {ch_id}! Отправка...")
                            await bot.send_kill_notification(ch_id, full_killmail, event)
            
            except Exception as e:
                logging.error(f"❌ Ошибка обработки: {e}")
            
            finally:
                data_queue.task_done()