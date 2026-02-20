import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.parser import parse_killmail

def test_parse_killmail_priority_overrides_others():
    """Проверяет, что приоритетные цели (ping_sys/ping_ship) имеют высший приоритет"""
    
    killmail = {
        "solar_system_id": 30000142,  # Jita
        "victim": {"ship_type_id": 670, "corporation_id": 98000001, "character_id": 90000001},
        "zkb": {"totalValue": 50_000_000},
        "attackers": []
    }
    
    channel_config = {
        "min_value": 10_000_000,
        "systems": [30000142],  # система в обычном вотче
        "ships": [670],  # корабль в обычном вотче
        "corps": [98000001],  # корпорация в обычном вотче
        "ping_sys": [30000142]  # И ТА ЖЕ система как приоритетная
    }
    
    filter_sets = {
        "systems": {30000142},
        "ships": {670},
        "corps": {98000001},
        "ping_sys": {30000142},
        "ping_ship": set(),
        "chars": set(),
        "regions": set(),
        "consts": set()
    }
    
    is_match, event_type = parse_killmail(killmail, channel_config, filter_sets)
    
    assert is_match is True
    assert event_type == "PRIORITY_TARGET", "Приоритетная система должна переопределять обычный вотч"

def test_parse_killmail_ship_and_location_match():
    """Проверяет, что корабль и система определяются правильно при одновременном совпадении"""
    
    killmail = {
        "solar_system_id": 30000142,
        "victim": {"ship_type_id": 670},
        "zkb": {"totalValue": 50_000_000},
        "attackers": []
    }
    
    channel_config = {
        "min_value": 10_000_000,
        "systems": [30000142],
        "ships": [670],
        "ping_sys": [],
        "ping_ship": []
    }
    
    filter_sets = {
        "systems": {30000142},
        "ships": {670},
        "ping_sys": set(),
        "ping_ship": set(),
        "corps": set(),
        "chars": set(),
        "regions": set(),
        "consts": set()
    }
    
    is_match, event_type = parse_killmail(killmail, channel_config, filter_sets)
    
    assert is_match is True
    # Может быть SHIP_WATCH или LOCATION_WATCH в зависимости от порядка проверки
    assert event_type in ["SHIP_WATCH", "LOCATION_WATCH"]

def test_parse_killmail_attacker_and_victim_match():
    """Проверяет, что совпадение по атакующему и жертве обрабатывается корректно"""
    
    killmail = {
        "solar_system_id": 30000142,
        "victim": {
            "ship_type_id": 670,
            "corporation_id": 98000001,
            "character_id": 90000001
        },
        "attackers": [{
            "corporation_id": 98000002,
            "character_id": 90000002,
            "ship_type_id": 671,
            "final_blow": True
        }],
        "zkb": {"totalValue": 50_000_000}
    }
    
    channel_config = {
        "min_value": 10_000_000,
        "corps": [98000001, 98000002],  # обе корпорации в вотче
        "chars": [90000001, 90000002],  # оба персонажа в вотче
        "systems": [],
        "ships": []
    }
    
    filter_sets = {
        "corps": {98000001, 98000002},
        "chars": {90000001, 90000002},
        "systems": set(),
        "ships": set(),
        "ping_sys": set(),
        "ping_ship": set(),
        "regions": set(),
        "consts": set()
    }
    
    is_match, event_type = parse_killmail(killmail, channel_config, filter_sets)
    
    assert is_match is True
    # Должен определить как TARGET_KILL (атакующий в вотче) или TARGET_LOSS (жертва в вотче)
    assert event_type in ["TARGET_KILL", "TARGET_LOSS"]

@pytest.mark.asyncio
async def test_processor_multiple_matches_single_channel():
    """Проверяет, что при множественных совпадениях для одного канала отправляется только одно уведомление"""
    
    from src.processor import start_processor, processed_kills_set, processed_kills_queue, stats
    import asyncio
    from unittest.mock import AsyncMock, patch, MagicMock
    
    # Очищаем глобальные структуры
    processed_kills_set.clear()
    processed_kills_queue.clear()
    stats["duplicates_skipped"] = 0
    stats["processed_total"] = 0
    stats["notifications_sent"] = 0
    
    queue = asyncio.Queue()
    
    # Killmail, который соответствует нескольким фильтрам
    kill_data = {
        "killID": 12345,
        "zkb": {"hash": "testhash"},
        "solar_system_id": 30000142
    }
    await queue.put(kill_data)
    
    # Мокаем fetch_with_retry для возврата ESI данных
    with patch('src.processor.fetch_with_retry', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "killmail_id": 12345,
            "victim": {"ship_type_id": 670, "corporation_id": 98000001},
            "attackers": [],
            "solar_system_id": 30000142
        }
        
        # Мокаем отправку уведомлений
        with patch('src.processor.bot.send_kill_notification', new_callable=AsyncMock) as mock_send:
            
            # Конфигурация с одним каналом
            config = {
                "all_subs": {
                    "channel1": {
                        "min_value": 0,
                        "systems": [30000142],
                        "ships": [670],
                        "corps": [98000001]
                    }
                },
                "filter_sets": {
                    "systems": {30000142},
                    "ships": {670},
                    "corps": {98000001},
                    "chars": set(),
                    "ping_sys": set(),
                    "ping_ship": set(),
                    "regions": set(),
                    "consts": set()
                }
            }
            
            # ВАЖНО: мокаем parse_killmail в том месте, где он используется - в processor.py
            with patch('src.processor.parse_killmail') as mock_parse:
                # Настраиваем мок на возврат совпадения
                mock_parse.return_value = (True, "SHIP_WATCH")
                
                # Запускаем процессор
                processor_task = asyncio.create_task(start_processor(queue, config))
                
                # Даём время на обработку
                await asyncio.sleep(0.3)
                
                # Останавливаем процессор
                processor_task.cancel()
                try:
                    await processor_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Error: {e}")
                
                # Проверяем, что parse_killmail был вызван
                assert mock_parse.call_count > 0, "parse_killmail должен быть вызван"
                
                # Проверяем, что отправлено только одно уведомление
                assert mock_send.call_count == 1, f"Ожидался 1 вызов send, получено {mock_send.call_count}"
                assert stats["notifications_sent"] == 1
                assert stats["processed_total"] == 1

def test_parse_killmail_order_of_checks():
    """Проверяет порядок проверки фильтров и что приоритеты работают правильно"""
    
    # Тестовые случаи в порядке приоритета
    test_cases = [
        {
            "name": "Приоритетная система",
            "killmail": {
                "solar_system_id": 30000142,
                "victim": {"ship_type_id": 670},
                "zkb": {"totalValue": 1_000_000},
                "attackers": []
            },
            "channel_config": {
                "min_value": 10_000_000,  # стоимость ниже порога, но приоритет должен игнорировать
                "systems": [30000142],
                "ping_sys": [30000142]
            },
            "filter_sets": {
                "systems": {30000142},
                "ping_sys": {30000142},
                "ships": set(),
                "corps": set()
            },
            "expected_match": True,
            "expected_type": "PRIORITY_TARGET"
        },
        {
            "name": "Приоритетный корабль игнорирует стоимость",
            "killmail": {
                "solar_system_id": 30000142,
                "victim": {"ship_type_id": 670},
                "zkb": {"totalValue": 500_000},  # ниже порога
                "attackers": []
            },
            "channel_config": {
                "min_value": 10_000_000,
                "ping_ship": [670]
            },
            "filter_sets": {
                "ping_ship": {670},
                "ships": set(),
                "systems": set()
            },
            "expected_match": True,
            "expected_type": "PRIORITY_TARGET"
        },
        {
            "name": "Атакующий в вотче (TARGET_KILL) имеет приоритет над обычными фильтрами",
            "killmail": {
                "solar_system_id": 30000142,
                "victim": {"ship_type_id": 670},
                "attackers": [{
                    "corporation_id": 98000002,
                    "final_blow": True
                }],
                "zkb": {"totalValue": 50_000_000}
            },
            "channel_config": {
                "min_value": 10_000_000,
                "systems": [30000142],  # тоже совпадает, но менее приоритетно
                "corps": [98000002]  # корпорация атакующего
            },
            "filter_sets": {
                "systems": {30000142},
                "corps": {98000002},
                "ships": set(),
                "ping_sys": set()
            },
            "expected_match": True,
            "expected_type": "TARGET_KILL"  # Должен быть TARGET_KILL, не LOCATION_WATCH
        }
    ]
    
    for case in test_cases:
        is_match, event_type = parse_killmail(
            case["killmail"], 
            case["channel_config"], 
            case["filter_sets"]
        )
        
        assert is_match == case["expected_match"], f"Ошибка в случае: {case['name']}"
        assert event_type == case["expected_type"], f"Ошибка типа в случае: {case['name']}"