import asyncio
import json
import os
import aiohttp
import websockets
from dotenv import load_dotenv
from parser import parse_killmail
from discord_utils import send_kill_notification

load_dotenv()

ZKILL_WS_URL = "wss://zkillboard.com/websocket/"

def get_env_list(key):
    val = os.getenv(key, "")
    return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]

async def listen_zkill():
    config = {
        "corps": set(get_env_list("MY_CORP_IDS")),
        "systems": set(get_env_list("WATCHED_SYSTEM_IDS")),
        "constellations": set(get_env_list("WATCHED_CONSTELLATION_IDS")),
        "ships": set(get_env_list("WATCHED_SHIP_IDS")),
        "min_value": float(os.getenv("MIN_VALUE", 1000000))
    }
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    print(f"🚀 Мониторинг запущен. Ожидание событий...")

    async with aiohttp.ClientSession(headers={"User-Agent": "Bober-Bot-v3.5"}) as session:
        while True:
            try:
                async with websockets.connect(ZKILL_WS_URL, ping_interval=20, ping_timeout=20) as websocket:
                    # Подписка
                    for corp_id in config["corps"]:
                        await websocket.send(json.dumps({"action": "sub", "channel": f"corporation:{corp_id}"}))
                    for ship_id in config["ships"]:
                        await websocket.send(json.dumps({"action": "sub", "channel": f"ship:{ship_id}"}))
                    
                    print("📡 Подписки активны. Слушаю эфир...")

                    async for message in websocket:
                        data = json.loads(message)
                        k_id = data.get('killID') or data.get('killmail_id')

                        if k_id:
                            # ШАГ 1: Получаем хэш от zKill (если его нет в пакете)
                            zk_url = f"https://zkillboard.com/api/killID/{k_id}/"
                            async with session.get(zk_url) as resp:
                                zk_res = await resp.json()
                                if not zk_res: continue
                                zk_data = zk_res[0]
                                k_hash = zk_data.get('zkb', {}).get('hash')

                            # ШАГ 2: Получаем детали от ESI
                            esi_url = f"https://esi.evetech.net/latest/killmails/{k_id}/{k_hash}/?datasource=tranquility"
                            async with session.get(esi_url) as resp:
                                if resp.status == 200:
                                    esi_data = await resp.json()
                                    
                                    # ШАГ 3: Собираем полный пакет и проверяем
                                    full_killmail = {**esi_data, "zkb": zk_data.get('zkb', {})}
                                    is_ok, event = parse_killmail(full_killmail, config)

                                    if is_ok:
                                        print(f"🔥 [ID: {k_id}] Совпадение! Тип: {event}")
                                        send_kill_notification(webhook_url, full_killmail, event)

            except Exception as e:
                print(f"⚠️ Ошибка соединения: {e}. Переподключение через 10 сек...")
                await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(listen_zkill())