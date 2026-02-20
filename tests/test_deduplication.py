import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.processor import start_processor, processed_kills_set, processed_kills_queue, stats, update_duplicate_tracking

@pytest.fixture(autouse=True)
def reset_globals():
    """Сбрасывает глобальные переменные перед каждым тестом"""
    processed_kills_set.clear()
    processed_kills_queue.clear()
    stats["duplicates_skipped"] = 0
    stats["processed_total"] = 0
    stats["errors"] = 0
    stats["notifications_sent"] = 0
    yield

@pytest.mark.asyncio
async def test_duplicate_skip():
    """Проверяет, что дубликаты пропускаются"""
    # Создаём тестовую очередь
    queue = asyncio.Queue()
    
    # Добавляем два одинаковых kill_id
    kill_data = {"killID": 12345, "zkb": {"hash": "testhash"}}
    await queue.put(kill_data)
    await queue.put(kill_data)  # дубликат
    
    # Мокаем функции
    with patch('src.processor.fetch_with_retry', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"killmail_id": 12345, "victim": {}}
        
        with patch('src.processor.bot.send_kill_notification', new_callable=AsyncMock):
            
            # Создаём простую конфигурацию
            config = {
                "all_subs": {},
                "filter_sets": {}
            }
            
            # Запускаем процессор в отдельной задаче
            processor_task = asyncio.create_task(start_processor(queue, config))
            
            # Даём время обработать сообщения
            await asyncio.sleep(0.2)
            
            # Останавливаем процессор
            processor_task.cancel()
            
            # Ждём завершения с игнорированием CancelledError
            try:
                await processor_task
            except asyncio.CancelledError:
                pass
            
            # Проверяем статистику
            assert stats["duplicates_skipped"] == 1, "Должен быть пропущен один дубликат"
            assert stats["processed_total"] == 1, "Должен быть обработан только один уникальный kill"

@pytest.mark.asyncio
async def test_delivery_key_duplicates():
    """Тестирует, что дубликаты по каналам (delivery_key) тоже пропускаются"""
    from src.processor import start_processor, processed_kills_set, processed_kills_queue, stats
    import asyncio
    from unittest.mock import AsyncMock, patch
    
    # Очищаем глобальные структуры
    processed_kills_set.clear()
    processed_kills_queue.clear()
    stats["duplicates_skipped"] = 0
    stats["processed_total"] = 0
    stats["notifications_sent"] = 0
    
    queue = asyncio.Queue()
    
    # Один kill_id
    kill_data = {"killID": 12345, "zkb": {"hash": "testhash"}}
    await queue.put(kill_data)
    
    # Мокаем
    with patch('src.processor.fetch_with_retry', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"killmail_id": 12345, "victim": {}}
        
        with patch('src.processor.bot.send_kill_notification', new_callable=AsyncMock) as mock_send:
            
            # Создаём конфигурацию с двумя каналами
            config = {
                "all_subs": {
                    "channel1": {"min_value": 0},
                    "channel2": {"min_value": 0}
                },
                "filter_sets": {}
            }
            
            # ВАЖНО: мокаем parse_killmail ТАМ, ГДЕ ОН ИСПОЛЬЗУЕТСЯ - в processor.py
            with patch('src.processor.parse_killmail', return_value=(True, "TEST")) as mock_parse:
                processor_task = asyncio.create_task(start_processor(queue, config))
                
                await asyncio.sleep(0.3)
                
                processor_task.cancel()
                try:
                    await processor_task
                except asyncio.CancelledError:
                    pass
                
                # Проверяем, что parse_killmail вызывался для каждого канала
                assert mock_parse.call_count == 2, f"parse_killmail вызван {mock_parse.call_count} раз, ожидалось 2"
                
                # Проверяем, что отправлено два уведомления
                assert mock_send.call_count == 2, f"Отправлено {mock_send.call_count} уведомлений, ожидалось 2"
                assert stats["notifications_sent"] == 2
                assert stats["processed_total"] == 1

def test_update_duplicate_tracking_basic():
    """Тестирует базовую работу функции отслеживания дубликатов"""
    k_id = 99999
    update_duplicate_tracking(k_id)
    
    assert k_id in processed_kills_set
    assert list(processed_kills_queue) == [k_id]
    assert len(processed_kills_set) == 1
    assert len(processed_kills_queue) == 1

def test_update_duplicate_tracking_multiple():
    """Тестирует добавление нескольких уникальных ID"""
    for i in range(10):
        update_duplicate_tracking(i)
    
    assert len(processed_kills_set) == 10
    assert len(processed_kills_queue) == 10
    assert all(i in processed_kills_set for i in range(10))

def test_update_duplicate_tracking_queue_limit():
    """Тестирует, что при превышении лимита set очищается и перестраивается"""
    # Добавляем 1001 элемент (maxlen=1000)
    for i in range(1001):
        update_duplicate_tracking(i)
    
    # После первого превышения лимита set содержит все элементы (нет очистки)
    assert len(processed_kills_set) == 1001
    assert len(processed_kills_queue) == 1000  # deque хранит только последние 1000
    
    # Добавляем ещё 100 элементов, чтобы превысить порог очистки set (>1100)
    for i in range(1001, 1101):
        update_duplicate_tracking(i)
    
    # После очистки set должен содержать только элементы из очереди (последние 1000)
    assert len(processed_kills_set) == 1000
    assert set(processed_kills_queue) == processed_kills_set
    
    # Проверяем граничные значения
    # Последние 1000 элементов - это ID от 101 до 1100
    assert 101 in processed_kills_set  # первый элемент после очистки
    assert 1000 in processed_kills_set  # последний элемент первой партии, попавший в очередь
    assert 1100 in processed_kills_set  # последний добавленный
    assert 100 not in processed_kills_set  # должен быть удалён

def test_duplicate_detection_after_cleanup():
    """Тестирует, что система продолжает определять дубликаты после очистки set"""
    # Добавляем 1100 элементов (0-1099)
    for i in range(1100):
        update_duplicate_tracking(i)
    
    # Set всё ещё содержит 1100 элементов, потому что условие очистки >1100
    assert len(processed_kills_set) == 1100
    assert len(processed_kills_queue) == 1000  # очередь хранит только последние 1000
    
    # Добавляем 1101-й элемент - теперь условие сработает
    update_duplicate_tracking(1100)
    
    # После очистки set должен содержать только элементы из очереди (последние 1000)
    assert len(processed_kills_set) == 1000
    assert len(processed_kills_queue) == 1000
    assert set(processed_kills_queue) == processed_kills_set
    
    # Проверяем, что старые ID (0-100) удалены
    for i in range(101):
        assert i not in processed_kills_set, f"ID {i} должен быть удалён"
    
    # Проверяем, что ID из очереди (101-1100) присутствуют
    for i in range(101, 1101):
        assert i in processed_kills_set, f"ID {i} должен быть в сете"