import pytest
import asyncio
import random
from unittest.mock import AsyncMock, patch, MagicMock
from collections import Counter
from src.processor import start_processor, processed_kills_set, processed_kills_queue, stats, update_duplicate_tracking

# Убираем autouse=True, чтобы контролировать сброс вручную
@pytest.fixture
def reset_globals():
    """Сбрасывает глобальные переменные перед каждым тестом"""
    processed_kills_set.clear()
    processed_kills_queue.clear()
    stats["duplicates_skipped"] = 0
    stats["processed_total"] = 0
    stats["errors"] = 0
    stats["notifications_sent"] = 0
    yield
    # После теста тоже можно очистить
    processed_kills_set.clear()
    processed_kills_queue.clear()

@pytest.mark.asyncio
async def test_queue_50_scenarios(reset_globals):
    """Тестирует 50 различных сценариев работы с очередью"""
    
    # Генерируем 50 различных сценариев
    scenarios = []
    
    for i in range(50):
        scenario = {
            "name": f"scenario_{i}",
            "kill_ids": [],
            "channels": [],
            "expected_unique_kills": 0,
            "expected_notifications": 0,
            "expected_duplicates": 0,
            "description": ""
        }
        
        # Разные типы сценариев
        scenario_type = i % 10
        
        if scenario_type == 0:
            scenario["kill_ids"] = [10000 + i]
            scenario["channels"] = ["channel1"]
            scenario["expected_unique_kills"] = 1
            scenario["expected_notifications"] = 1
            scenario["expected_duplicates"] = 0
            scenario["description"] = "Один kill, один канал"
            
        elif scenario_type == 1:
            scenario["kill_ids"] = [20000 + i]
            scenario["channels"] = ["channel1", "channel2", "channel3"]
            scenario["expected_unique_kills"] = 1
            scenario["expected_notifications"] = 3
            scenario["expected_duplicates"] = 0
            scenario["description"] = "Один kill, 3 канала"
            
        elif scenario_type == 2:
            kill_id = 30000 + i
            scenario["kill_ids"] = [kill_id, kill_id, kill_id]
            scenario["channels"] = ["channel1"]
            scenario["expected_unique_kills"] = 1
            scenario["expected_notifications"] = 1
            scenario["expected_duplicates"] = 2
            scenario["description"] = "Три одинаковых kill_id в очереди"
            
        elif scenario_type == 3:
            scenario["kill_ids"] = [40000 + i, 40001 + i, 40002 + i]
            scenario["channels"] = ["channel1"]
            scenario["expected_unique_kills"] = 3
            scenario["expected_notifications"] = 3
            scenario["expected_duplicates"] = 0
            scenario["description"] = "Три разных kill_id для одного канала"
            
        elif scenario_type == 4:
            scenario["kill_ids"] = [50000 + i, 50001 + i, 50002 + i]
            scenario["channels"] = ["channel1", "channel2"]
            scenario["expected_unique_kills"] = 3
            scenario["expected_notifications"] = 6
            scenario["expected_duplicates"] = 0
            scenario["description"] = "3 разных kill_id для 2 каналов"
            
        elif scenario_type == 5:
            kill_id = 60000 + i
            scenario["kill_ids"] = [kill_id]
            scenario["channels"] = ["channel1", "channel2"]
            scenario["expected_unique_kills"] = 1
            scenario["expected_notifications"] = 2
            scenario["expected_duplicates"] = 0
            scenario["description"] = "Проверка delivery_key - один kill для двух каналов"
            
        elif scenario_type == 6:
            base = 70000 + i * 10
            scenario["kill_ids"] = [base, base, base + 1, base + 1, base + 2]
            scenario["channels"] = ["channel1"]
            scenario["expected_unique_kills"] = 3
            scenario["expected_notifications"] = 3
            scenario["expected_duplicates"] = 2
            scenario["description"] = "Частичные дубликаты (2 дубликата из 5)"
            
        elif scenario_type == 7:
            kill_id = 80000 + i
            scenario["kill_ids"] = [kill_id, kill_id]
            scenario["channels"] = ["channel1", "channel2", "channel3", "channel4", "channel5"]
            scenario["expected_unique_kills"] = 1
            scenario["expected_notifications"] = 5
            scenario["expected_duplicates"] = 1
            scenario["description"] = "Один kill_id для 5 каналов + дубликат"
            
        elif scenario_type == 8:
            scenario["kill_ids"] = [90000 + i]
            scenario["channels"] = []
            scenario["expected_unique_kills"] = 1
            scenario["expected_notifications"] = 0
            scenario["expected_duplicates"] = 0
            scenario["description"] = "Kill без подписанных каналов"
            
        elif scenario_type == 9:
            scenario["kill_ids"] = [100000 + i + j for j in range(5)]
            scenario["channels"] = ["channel1"]
            scenario["expected_unique_kills"] = 5
            scenario["expected_notifications"] = 5
            scenario["expected_duplicates"] = 0
            scenario["description"] = "5 разных kill_id подряд"
        
        scenarios.append(scenario)
    
    # Запускаем все сценарии последовательно
    for idx, scenario in enumerate(scenarios):
        print(f"\n--- Сценарий {idx}: {scenario['description']} ---")
        
        # Сбрасываем статистику для каждого сценария
        processed_kills_set.clear()
        processed_kills_queue.clear()
        stats["duplicates_skipped"] = 0
        stats["processed_total"] = 0
        stats["errors"] = 0
        stats["notifications_sent"] = 0
        
        # Создаём очередь
        queue = asyncio.Queue()
        
        # Наполняем очередь данными согласно сценарию
        for kill_id in scenario["kill_ids"]:
            kill_data = {
                "killID": kill_id,
                "zkb": {"hash": f"hash_{kill_id}"},
                "solar_system_id": 30000142
            }
            await queue.put(kill_data)
        
        # Создаём конфигурацию
        all_subs = {}
        filter_sets = {
            "systems": set(), "ships": set(), "corps": set(), "chars": set(),
            "ping_sys": set(), "ping_ship": set(), "regions": set(), "consts": set()
        }
        
        for channel in scenario["channels"]:
            all_subs[channel] = {"min_value": 0}
        
        config = {
            "all_subs": all_subs,
            "filter_sets": filter_sets
        }
        
        # Мокаем все внешние вызовы
        with patch('src.processor.fetch_with_retry', new_callable=AsyncMock) as mock_fetch:
            # Исправленная функция с правильной обработкой аргументов
            def fetch_side_effect(session, url, *args, **kwargs):
                # Проверяем, что url - это строка
                if not isinstance(url, str):
                    url = str(url)
                
                # Пытаемся извлечь kill_id из URL
                import re
                match = re.search(r'killmails/(\d+)/', url)
                if match:
                    kill_id = int(match.group(1))
                else:
                    # Пробуем другой паттерн
                    match = re.search(r'killID/(\d+)/', url)
                    if match:
                        kill_id = int(match.group(1))
                    else:
                        kill_id = 12345
                
                return {
                    "killmail_id": kill_id,
                    "victim": {"ship_type_id": 670, "corporation_id": 98000001},
                    "attackers": [],
                    "solar_system_id": 30000142
                }
            
            mock_fetch.side_effect = fetch_side_effect
            
            with patch('src.processor.bot.send_kill_notification', new_callable=AsyncMock) as mock_send:
                with patch('src.processor.parse_killmail', return_value=(True, "TEST")):
                    
                    # Запускаем процессор
                    processor_task = asyncio.create_task(start_processor(queue, config))
                    
                    # Ждём обработки
                    timeout = 1.0 + (len(scenario["kill_ids"]) * 0.2)
                    await asyncio.sleep(timeout)
                    
                    # Останавливаем процессор
                    processor_task.cancel()
                    try:
                        await processor_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Проверяем результаты
                    expected_notifications = scenario["expected_notifications"]
                    actual_notifications = mock_send.call_count
                    
                    print(f"  Ожидаемые уведомления: {expected_notifications}")
                    print(f"  Фактические уведомления: {actual_notifications}")
                    print(f"  Уникальных kill обработано: {stats['processed_total']}")
                    print(f"  Дубликатов пропущено: {stats['duplicates_skipped']}")
                    print(f"  Ошибок: {stats['errors']}")
                    
                    # Проверяем статистику
                    assert stats["processed_total"] == scenario["expected_unique_kills"], \
                        f"Сценарий {idx}: Ожидалось {scenario['expected_unique_kills']} уникальных kill, получено {stats['processed_total']}"
                    
                    assert stats["duplicates_skipped"] == scenario["expected_duplicates"], \
                        f"Сценарий {idx}: Ожидалось {scenario['expected_duplicates']} дубликатов, пропущено {stats['duplicates_skipped']}"
                    
                    assert actual_notifications == scenario["expected_notifications"], \
                        f"Сценарий {idx}: Ожидалось {scenario['expected_notifications']} уведомлений, отправлено {actual_notifications}"
                    
                    assert stats["errors"] == 0, f"Сценарий {idx}: Не должно быть ошибок, получено {stats['errors']}"