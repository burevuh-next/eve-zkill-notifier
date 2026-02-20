import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from src.parser import parse_killmail

def test_priority_system_match():
    killmail = {
        "solar_system_id": 30000142,
        "victim": {"ship_type_id": 670},
        "zkb": {"totalValue": 1000},
        "attackers": []
    }
    channel_config = {
        "min_value": 1_000_000,
        "systems": [],
        "ping_sys": [30000142]
    }
    is_match, event_type = parse_killmail(killmail, channel_config, {})
    assert is_match is True
    assert event_type == "PRIORITY_TARGET"

def test_value_filter():
    killmail = {
        "solar_system_id": 30000142,
        "victim": {"ship_type_id": 670},
        "zkb": {"totalValue": 500_000},
        "attackers": []
    }
    channel_config = {
        "min_value": 1_000_000,
        "systems": [30000142],
        "ships": [],
        "corps": [],
        "chars": []
    }
    is_match, _ = parse_killmail(killmail, channel_config, {})
    assert is_match is False