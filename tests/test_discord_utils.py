import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
import aiohttp
from aioresponses import aioresponses
from src.discord_utils import EveBot

@pytest.mark.asyncio
async def test_get_eve_names():
    bot = EveBot()
    bot.session = aiohttp.ClientSession()
    
    with aioresponses() as m:
        m.post(
            "https://esi.evetech.net/latest/universe/names/",
            payload=[{"id": 30000142, "name": "Jita"}],
            status=200
        )
        names = await bot.get_eve_names([30000142])
        assert names[30000142] == "Jita"
        # Проверка кеша
        names2 = await bot.get_eve_names([30000142])
        assert names2[30000142] == "Jita"
        assert len(m.requests) == 1
    await bot.session.close()