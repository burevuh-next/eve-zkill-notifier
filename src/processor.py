import logging
import aiohttp
import os
from parser import parse_killmail
from discord_utils import bot
#from discord_utils import send_kill_notification
from dotenv import load_dotenv

load_dotenv()

async def start_processor(data_queue, config):
    logging.info("⚙️ Обработчик событий запущен...")
    async with aiohttp.ClientSession(headers={"User-Agent": "Bober-Bot-v3.5"}) as session:
        while True:
            # 1. Сначала забираем объект из очереди
            killmail_item = await data_queue.get()
            data = None
            
            try:
                data = killmail_item
                
                channel = data.get('channel', '')
                wh_const_id = None
                wh_reg_id = None            
                
                # Обработка каналов WebSocket (созвездия/регионы)
                if "constellation:" in channel:
                    logging.info(f"📡 [DEBUG] Сигнал созвездия: {channel}")                            
                    try: wh_const_id = int(channel.split(":")[1])
                    except: pass
                
                if "region:" in channel:
                    logging.info(f"📡 [DEBUG] Сигнал региона: {channel}")                            
                    try: wh_reg_id = int(channel.split(":")[1])
                    except: pass
                
                # В WebSocket структура может отличаться. Проверяем оба варианта ID
                k_id = data.get('killID') or data.get('killmail_id')
                
                # if k_id:
                #     logging.info(f"DEBUG: Получен сигнал ID {k_id}")
                
                if k_id:
                    # ШАГ 1: Получаем хэш от zKill (если его нет в пакете)
                    # Сначала проверяем, нет ли хэша в самом сообщении сокета
                    zk_data_source = data.get('zkb', {})
                    k_hash = zk_data_source.get('hash')
                    
                    if not k_hash:
                        zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                        async with session.get(zk_url) as resp:
                            zk_res = await resp.json()
                            if not zk_res or not isinstance(zk_res, list): 
                                continue
                            zk_data_source = zk_res[0].get('zkb', {})
                            k_hash = zk_data_source.get('hash')

                    if not k_hash:
                        continue

                    # ШАГ 2: Получаем детали от ESI
                    esi_url = f"https://esi.evetech.net/latest/killmails/{k_id}/{k_hash}/?datasource=tranquility"
    
                    async with session.get(esi_url) as resp:
                        if resp.status == 200:
                            esi_data = await resp.json()
                            
                            # ШАГ 3: Сборка пакета
                            full_killmail = {**esi_data, "zkb": zk_data_source}
                            
                            if wh_const_id:
                                full_killmail['constellation_id'] = wh_const_id
                            if wh_reg_id:
                                full_killmail['region_id'] = wh_reg_id
                                                
                            is_ok, event = parse_killmail(full_killmail, config)

                            if is_ok:
                                logging.info(f"🔥 [ID: {k_id}] Совпадение! Отправка в Discord...")
                                # Используем await, так как теперь это асинхронная функция бота
                                await bot.send_kill_notification(os.getenv("DISCORD_CHANNEL_ID"), full_killmail, event)
            
            except Exception as e:
                logging.error(f"❌ Ошибка обработки: {e}")
                # Выводим тип данных для отладки, если ошибка повторится
                logging.error(f"Тип данных: {type(data)}") 
            
            finally:
                data_queue.task_done()

async def process_killmail(raw_data):
    # Тут будет твоя логика формирования имён, ссылок и иконок
    # Возвращаем чистый словарь или объект
    return {"id": raw_data.get('killmail_id'), "status": "processed"}