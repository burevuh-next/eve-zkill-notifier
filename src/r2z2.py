import asyncio
import logging
import random
import aiohttp

logger = logging.getLogger('r2z2')

SEQUENCE_URL = "https://r2z2.zkillboard.com/ephemeral/sequence.json"
KILL_URL_T = "https://r2z2.zkillboard.com/ephemeral/{}.json"
POLL_INTERVAL = 10
RATE_LIMIT_SLEEP = 0.2

async def get_sequence(session):
    async with session.get(SEQUENCE_URL) as resp:
        data = await resp.json()
        return data["sequence"]

async def fetch_kill(session, seq):
    url = KILL_URL_T.format(seq)
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data
        return None

def jitter_sleep(base):
    return asyncio.sleep(base * random.uniform(0.75, 1.25))

def matches_filters(kill_data, filter_sets):
    esi = kill_data.get("esi") or {}
    victim = esi.get("victim") or {}
    ship_id = victim.get("ship_type_id")
    corp_id = victim.get("corporation_id")
    char_id = victim.get("character_id")
    alliance_id = victim.get("alliance_id")

    if ship_id and ship_id in filter_sets.get("ships", set()):
        return True, "ship"
    if ship_id and ship_id in filter_sets.get("ping_ship", set()):
        return True, "ping_ship"
    if corp_id and corp_id in filter_sets.get("corps", set()):
        return True, "corp"
    if char_id and char_id in filter_sets.get("chars", set()):
        return True, "char"
    if alliance_id and alliance_id in filter_sets.get("alliances", set()):
        return True, "alliance"

    system_id = esi.get("solar_system_id")
    if system_id and system_id in filter_sets.get("systems", set()):
        return True, "system"
    if system_id and system_id in filter_sets.get("ping_sys", set()):
        return True, "ping_sys"

    return False, None

async def r2z2_loop(data_queue, config):
    filter_sets = config.get("filter_sets", {})
    logger.info("R2Z2 loop started")

    headers = {
        "User-Agent": "EVE-KillBot/5.0 (Discord Bot)",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        seq = await get_sequence(session)
        logger.info(f"R2Z2 starting from sequence {seq}")

        while True:
            try:
                kill_data = await fetch_kill(session, seq)
                if kill_data:
                    km_id = kill_data.get("killmail_id")
                    esi = kill_data.get("esi") or {}
                    victim = esi.get("victim") or {}
                    ship_id = victim.get("ship_type_id")

                    is_match, match_type = matches_filters(kill_data, filter_sets)
                    if is_match:
                        esi_hash = kill_data.get("hash", "")
                        logger.info(f"R2Z2 killID={km_id} ship={ship_id} match={match_type}")
                        await data_queue.put({
                            "killID": km_id,
                            "killmail_id": km_id,
                            "zkb": kill_data.get("zkb", {}),
                            "victim": victim,
                            "attackers": esi.get("attackers", []),
                            "killmail_time": esi.get("killmail_time", ""),
                            "solar_system_id": esi.get("solar_system_id"),
                            "hash": esi_hash,
                            "channel": "r2z2",
                        })

                    seq += 1
                    await jitter_sleep(RATE_LIMIT_SLEEP)
                else:
                    await jitter_sleep(POLL_INTERVAL)

                if seq % 1000 == 0:
                    logger.debug(f"R2Z2 at sequence {seq}")

            except asyncio.CancelledError:
                logger.info("R2Z2 loop cancelled")
                raise
            except Exception as e:
                logger.error(f"R2Z2 error: {e}", exc_info=True)
                await jitter_sleep(POLL_INTERVAL)
