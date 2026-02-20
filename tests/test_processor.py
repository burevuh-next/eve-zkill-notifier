import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from src.processor import update_duplicate_tracking, processed_kills_set, processed_kills_queue

def test_update_duplicate_tracking():
    # Очищаем глобальные структуры перед тестом
    processed_kills_set.clear()
    processed_kills_queue.clear()
    
    k_id = 12345
    update_duplicate_tracking(k_id)
    
    assert k_id in processed_kills_set
    assert list(processed_kills_queue) == [k_id]
    
    # Добавляем ещё 2
    update_duplicate_tracking(12346)
    update_duplicate_tracking(12347)
    
    assert len(processed_kills_set) == 3
    assert len(processed_kills_queue) == 3

def test_update_duplicate_tracking_queue_limit():
    # Проверяем, что при превышении лимита set очищается и перестраивается
    processed_kills_set.clear()
    processed_kills_queue.clear()
    
    # Устанавливаем maxlen=1000 (как в коде), добавим 1001 элемент
    for i in range(1001):
        update_duplicate_tracking(i)
    
    # set должен содержать не более ~1100 элементов, но у нас 1001, так что всё должно быть в сете
    assert len(processed_kills_set) == 1001
    assert len(processed_kills_queue) == 1000  # deque хранит только последние 1000
    
    # Добавляем ещё 100 элементов, должно сработать условие очистки
    for i in range(1001, 1101):
        update_duplicate_tracking(i)
    
    # После очистки set должен содержать элементы из очереди (последние 1000)
    assert len(processed_kills_set) == 1000
    assert set(processed_kills_queue) == processed_kills_set
    
def test_duplicate_tracking_threshold():
    """Тестирует, что после 1100 элементов set очищается и перестраивается из deque"""
    from src.processor import update_duplicate_tracking, processed_kills_set, processed_kills_queue
    
    processed_kills_set.clear()
    processed_kills_queue.clear()
    
    # Добавляем 1100 элементов - условие очистки ещё не сработало (>1100)
    for i in range(1100):
        update_duplicate_tracking(i)
    
    # Set содержит все 1100 элементов, очередь - последние 1000
    assert len(processed_kills_set) == 1100
    assert len(processed_kills_queue) == 1000
    
    # Добавляем 1101-й элемент - теперь условие сработает (>1100)
    update_duplicate_tracking(1100)
    
    # После очистки set должен содержать только элементы из очереди (последние 1000)
    assert len(processed_kills_set) == 1000
    assert len(processed_kills_queue) == 1000
    
    # Проверяем, что первые 100 элементов удалены
    for i in range(100):
        assert i not in processed_kills_set
    
    # Проверяем, что элементы с 101 по 1100 присутствуют
    for i in range(101, 1101):
        assert i in processed_kills_set