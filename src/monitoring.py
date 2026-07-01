import asyncio
import logging
import os
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("⚠️ psutil не установлен. Расширенный мониторинг недоступен. Установите: pip install psutil")

@dataclass
class MonitoringStats:
    """Статистика мониторинга"""
    start_time: float = field(default_factory=time.time)
    connections_peak: int = 0
    memory_peak_mb: float = 0.0
    cpu_peak_percent: float = 0.0
    check_count: int = 0
    warnings: list = field(default_factory=list)
    last_check_time: float = field(default_factory=time.time)
    
    def update_peak(self, connections: int, memory_mb: float, cpu_percent: float):
        """Обновляет пиковые значения"""
        self.connections_peak = max(self.connections_peak, connections)
        self.memory_peak_mb = max(self.memory_peak_mb, memory_mb)
        self.cpu_peak_percent = max(self.cpu_peak_percent, cpu_percent)
        self.check_count += 1
        self.last_check_time = time.time()
    
    def add_warning(self, warning: str):
        """Добавляет предупреждение"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.warnings.append(f"[{timestamp}] {warning}")
        # Храним только последние 10 предупреждений
        if len(self.warnings) > 10:
            self.warnings.pop(0)
    
    @property
    def uptime(self) -> str:
        """Возвращает время работы в читаемом формате"""
        delta = timedelta(seconds=int(time.time() - self.start_time))
        return str(delta)

class ResourceMonitor:
    """
    Расширенный мониторинг ресурсов с контекстным менеджером
    """
    
    def __init__(self):
        # Загружаем настройки из .env
        self.check_interval = int(os.getenv("MONITORING_INTERVAL", "60"))
        self.connection_threshold = int(os.getenv("CONNECTION_WARNING_THRESHOLD", "50"))
        self.memory_threshold = float(os.getenv("MEMORY_WARNING_THRESHOLD_MB", "500"))
        self.cpu_threshold = float(os.getenv("CPU_WARNING_THRESHOLD", "80"))
        self.enabled = os.getenv("ENABLE_MONITORING", "false").lower() == "true"
        
        self.stats = MonitoringStats()
        self._monitor_task: Optional[asyncio.Task] = None
        self._process = psutil.Process() if PSUTIL_AVAILABLE else None
        self._log = logging.getLogger(__name__)
        
    async def _check_resources(self):
        """Проверяет использование ресурсов"""
        if not PSUTIL_AVAILABLE or not self._process:
            return
        
        try:
            # Получаем информацию о соединениях
            connections = self._process.connections()
            
            # В psutil 7.2.2 connections - это список namedtuple с атрибутами
            established = []
            time_wait = []
            total_tcp = 0
            
            for conn in connections:
                # Проверяем что это TCP соединение (family = AF_INET или AF_INET6)
                if hasattr(conn, 'family') and conn.family in (2, 10):  # AF_INET=2, AF_INET6=10
                    total_tcp += 1
                    if hasattr(conn, 'status'):
                        if conn.status == 'ESTABLISHED':
                            established.append(conn)
                        elif conn.status == 'TIME_WAIT':
                            time_wait.append(conn)
            
            # Получаем информацию о памяти (в МБ)
            memory_info = self._process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # Получаем информацию о CPU
            cpu_percent = self._process.cpu_percent(interval=0.1)
            
            # Обновляем статистику
            self.stats.update_peak(len(established), memory_mb, cpu_percent)
            
            # Логируем детальную информацию (debug уровень)
            self._log.debug(
                f"📊 Ресурсы: "
                f"TCP={total_tcp}, "
                f"ESTAB={len(established)}, "
                f"TIME_WAIT={len(time_wait)}, "
                f"память={memory_mb:.1f} МБ, "
                f"CPU={cpu_percent:.1f}%"
            )
            
            # Проверяем пороговые значения
            if len(established) > self.connection_threshold:
                warning = f"⚠️ Много установленных соединений: {len(established)} (порог: {self.connection_threshold})"
                self._log.warning(warning)
                self.stats.add_warning(warning)
            
            if memory_mb > self.memory_threshold:
                warning = f"⚠️ Высокое использование памяти: {memory_mb:.1f} МБ (порог: {self.memory_threshold} МБ)"
                self._log.warning(warning)
                self.stats.add_warning(warning)
            
            if cpu_percent > self.cpu_threshold:
                warning = f"⚠️ Высокая нагрузка CPU: {cpu_percent:.1f}% (порог: {self.cpu_threshold}%)"
                self._log.warning(warning)
                self.stats.add_warning(warning)
                
        except Exception as e:
            self._log.error(f"❌ Ошибка при проверке ресурсов: {e}")
    
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        self._log.info(f"📊 Мониторинг ресурсов запущен (интервал: {self.check_interval}с)")
        
        try:
            while True:
                await self._check_resources()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            self._log.info("📊 Мониторинг ресурсов остановлен")
            raise
        except Exception as e:
            self._log.error(f"❌ Ошибка в цикле мониторинга: {e}")
            raise
    
    async def start(self):
        """Запускает мониторинг"""
        if not self.enabled:
            self._log.info("📊 Мониторинг ресурсов отключен в конфигурации")
            return self
        
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
        return self
    
    async def stop(self):
        """Останавливает мониторинг"""
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self._log.error(f"❌ Ошибка при остановке мониторинга: {e}")
            finally:
                self._monitor_task = None
        
        # Логируем итоговую статистику
        if self.enabled and self.stats.check_count > 0:
            self._log.info(
                f"📊 Итоговая статистика мониторинга:\n"
                f"   • Время работы: {self.stats.uptime}\n"
                f"   • Пик соединений: {self.stats.connections_peak}\n"
                f"   • Пик памяти: {self.stats.memory_peak_mb:.1f} МБ\n"
                f"   • Пик CPU: {self.stats.cpu_peak_percent:.1f}%\n"
                f"   • Проверок выполнено: {self.stats.check_count}"
            )
            
            if self.stats.warnings:
                self._log.info("   📋 Последние предупреждения:")
                for warning in self.stats.warnings:
                    self._log.info(f"      {warning}")
    
    async def __aenter__(self):
        """Вход в контекстный менеджер"""
        return await self.start()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Выход из контекстного менеджера"""
        await self.stop()
    
    def _get_disk_usage_mb(self) -> float:
        """Возвращает размер папки проекта в МБ"""
        total = 0.0
        base = os.path.dirname(os.path.abspath(__file__))  # src/
        project_root = os.path.dirname(base)  # eve_open/
        for dirpath, dirnames, filenames in os.walk(project_root):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return round(total / 1024 / 1024, 1)

    def get_stats(self) -> Dict[str, Any]:
        """Возвращает текущую статистику в виде словаря"""
        current_memory_mb = 0.0
        current_cpu = 0.0
        if self._process:
            try:
                current_memory_mb = self._process.memory_info().rss / 1024 / 1024
                current_cpu = self._process.cpu_percent(interval=0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {
            "uptime": self.stats.uptime,
            "connections_peak": self.stats.connections_peak,
            "memory_peak_mb": round(self.stats.memory_peak_mb, 1),
            "memory_current_mb": round(current_memory_mb, 1),
            "cpu_peak_percent": round(self.stats.cpu_peak_percent, 1),
            "cpu_current_percent": round(current_cpu, 1),
            "disk_usage_mb": self._get_disk_usage_mb(),
            "check_count": self.stats.check_count,
            "warnings": self.stats.warnings.copy(),
            "enabled": self.enabled
        }


# Создаем глобальный экземпляр для использования в боте
monitor = ResourceMonitor()