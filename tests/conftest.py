import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import aiohttp
import tempfile
from src.image_generator_large import LargeKillImageGenerator

@pytest.fixture
def sample_killmail():
    return {
        "killmail_id": 12345,
        "solar_system_id": 30000142,
        "victim": {
            "character_id": 90000001,
            "corporation_id": 98000001,
            "ship_type_id": 670
        },
        "attackers": [{
            "character_id": 90000002,
            "corporation_id": 98000002,
            "ship_type_id": 671,
            "final_blow": True
        }],
        "zkb": {"totalValue": 150_000_000}
    }

@pytest.fixture
def temp_image_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(LargeKillImageGenerator, 'output_dir', tmpdir)
        yield tmpdir

@pytest.fixture
async def bot_session():
    async with aiohttp.ClientSession() as session:
        yield session