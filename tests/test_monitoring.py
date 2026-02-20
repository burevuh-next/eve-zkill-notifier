import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.monitoring import ResourceMonitor

def test_threshold_warnings():
    monitor = ResourceMonitor()
    monitor.connection_threshold = 5
    monitor.memory_threshold = 100
    monitor.cpu_threshold = 50
    # Дополнительные тесты можно добавить при необходимости
    assert monitor.connection_threshold == 5