# 🎨 ПРОДВИНУТЫЙ ГЕНЕРАТОР ИЗОБРАЖЕНИЙ - Полное руководство

## 🌟 Новые возможности

### 1. **Портреты персонажей** 👤
- Автоматическая загрузка портретов с ESI
- Портреты жертвы и убийцы на изображении
- Красивые рамки вокруг портретов

### 2. **Анимированные GIF** 🎬
- Автоматически для киллов дороже 1B ISK
- Пульсирующие эффекты
- 10 кадров анимации

### 3. **Множество стилей** 🎨
- **Default** - классический темный стиль
- **Cyberpunk** - неоновые цвета и свечение
- **Space** - космическая тема со звездами
- **Minimal** - светлый минималистичный
- **Neon** - яркий неоновый стиль

### 4. **Статистика пилотов** 📊
- K/D ratio (Kill/Death)
- Общее количество киллов
- Количество потерь
- Solo kills для убийцы
- Данные с zKillboard API

### 5. **Логотипы корпораций** 🏢
- На фоне изображения
- Полупрозрачные для эстетики
- Автоматическая загрузка с ESI

### 6. **Эффекты взрыва** 💥
- Для приоритетных целей
- Многослойная анимация
- Градиентные цвета

### 7. **Умное свечение** ✨
- Для дорогих киллов (100M+)
- Вокруг кораблей
- Для киберпанк темы

## 📦 Установка

### Шаг 1: Установите зависимости
```bash
pip install Pillow>=10.0.0
```

### Шаг 2: Скопируйте файлы
```bash
# Основной генератор
cp image_generator_advanced.py /path/to/bot/

# Конфигурация
cp image_config.py /path/to/bot/

# Обновленный discord_utils
# (замените метод send_kill_notification из discord_notification_advanced.py)
```

### Шаг 3: Создайте директории
```bash
mkdir -p image_cache/portraits
mkdir -p image_cache/corp_logos
mkdir -p killmail_images
```

### Шаг 4: Обновите импорт
В `discord_utils.py` замените:
```python
# Было:
from image_generator import get_generator

# Стало:
from image_generator_advanced import get_generator
```

## 🎯 Использование

### Автоматический выбор стиля

Бот автоматически выбирает стиль:
- **Приоритетные цели** → Cyberpunk (яркий, привлекает внимание)
- **Дорогие киллы (100M+)** → Space (космический)
- **Обычные киллы** → Default (стандартный)

### Ручной выбор стиля

В `discord_notification_advanced.py`:
```python
# Всегда использовать киберпанк
generator = get_generator(style='cyberpunk')

# Или space
generator = get_generator(style='space')
```

### Настройка через конфиг

Отредактируйте `image_config.py`:

```python
# Отключить автовыбор стиля
AUTO_STYLE_SELECTION = False

# Использовать только один стиль
DEFAULT_STYLE = 'cyberpunk'

# Изменить порог для GIF
GIF_THRESHOLD = 500_000_000  # 500M вместо 1B

# Отключить портреты (быстрее генерация)
ENABLE_CHARACTER_PORTRAITS = False

# Отключить статистику (быстрее генерация)
ENABLE_PILOT_STATS = False
```

## 🎨 Кастомизация стилей

### Создание своей темы

В `image_config.py` добавьте в `THEMES`:

```python
'my_custom_theme': {
    'name': 'Моя Тема',
    'colors': {
        'background': (30, 30, 40),      # RGB цвет фона
        'card_bg': (40, 40, 50),         # Цвет карточек
        'accent': (255, 100, 50),        # Акцент для loss
        'accent_green': (50, 255, 100),  # Акцент для kill
        'accent_gold': (255, 200, 0),    # Приоритеты
        'text_primary': (255, 255, 255), # Основной текст
        'text_secondary': (200, 200, 200), # Вторичный
        'border': (70, 70, 80),          # Границы
    },
    'glow': True,    # Включить свечение
    'stars': False,  # Звездный фон
}
```

Затем используйте:
```python
generator = get_generator(style='my_custom_theme')
```

### Изменение размеров

В `image_config.py`:
```python
# Больше изображение (детальнее, но медленнее)
IMAGE_WIDTH = 1200
IMAGE_HEIGHT = 600

# Компактнее (быстрая загрузка)
IMAGE_WIDTH = 600
IMAGE_HEIGHT = 300
```

### Добавление логотипа альянса

1. Положите файл `alliance_logo.png` в корень проекта
2. В `image_config.py`:
```python
ALLIANCE_LOGO_PATH = "alliance_logo.png"
ALLIANCE_LOGO_SIZE = (80, 80)
ALLIANCE_LOGO_POSITION = (10, 10)  # Верхний левый угол
ALLIANCE_LOGO_ALPHA = 150  # Прозрачность
```

## 📊 Производительность

### Время генерации

| Тип | Первый раз | С кэшем |
|-----|-----------|---------|
| Обычное изображение | 3-4 сек | 0.8-1.2 сек |
| С портретами | 4-5 сек | 1.0-1.5 сек |
| С статистикой | 5-6 сек | 1.2-1.8 сек |
| GIF анимация | 8-12 сек | 3-5 сек |

### Оптимизация

**Отключите ненужное:**
```python
# В image_config.py
ENABLE_CHARACTER_PORTRAITS = False  # -30% времени
ENABLE_PILOT_STATS = False          # -20% времени
ENABLE_CORP_LOGOS = False           # -10% времени
```

**Уменьшите размер:**
```python
IMAGE_WIDTH = 600   # Вместо 800
IMAGE_HEIGHT = 300  # Вместо 400
```

**Отключите GIF:**
```python
ENABLE_GIF_FOR_EXPENSIVE = False
```

## 🎬 Примеры результатов

### Обычный килл (Default стиль)
```
┌────────────────────────────────────────┐
│ [Портрет]    ☠️ LOSS                  │
│              Rifter                    │
│ [Корабль]    📍 Jita                  │
│                                        │
│              💤 ЖЕРТВА                 │
│              Player Name               │
│              Corp Name                 │
│              📊 K/D: 1.2 | 45/38      │
│                                        │
│              ⚔️ УБИЙЦА                │
│              Killer Name               │
│              Corp | 🚀 Dramiel        │
│              📊 K/D: 3.5 | Solo: 120  │
│                                        │
│              💰 45.2M ISK              │
│              👥 5 атакующих            │
└────────────────────────────────────────┘
```

### Приоритет (Cyberpunk стиль)
```
┌────────────────────────────────────────┐
│  💥💥💥                                │
│ [Эффект     🚨 ПРИОРИТЕТ              │
│  взрыва]    [НЕОНОВЫЕ ЦВЕТА]          │
│  💥💥💥     Titan                     │
│                                        │
│ [Все в ярких неоновых цветах]         │
│ [Пурпурный + Циан]                     │
│ [Эффект свечения]                      │
│                                        │
│              💰 15.5B ISK              │
└────────────────────────────────────────┘
```

### Дорогой килл (Space стиль + GIF)
```
┌────────────────────────────────────────┐
│ ✨✨✨ Звездный фон ✨✨✨            │
│                                        │
│ [Анимация: пульсирующее свечение]     │
│ [10 кадров, плавная анимация]         │
│                                        │
│              💎 1.2B ISK               │
│ [Космическая атмосфера]                │
└────────────────────────────────────────┘
```

## 🔧 Troubleshooting

### Медленная генерация

**Проблема:** Первые изображения генерируются долго

**Решение:**
1. Это нормально - загружаются портреты, корабли, логотипы
2. После кэширования будет быстро
3. Можно отключить портреты/статистику

### Ошибка загрузки портретов

**Проблема:** `Failed to download portrait`

**Решение:**
- ESI API может быть недоступен
- Проверьте интернет
- Бот автоматически продолжит без портрета

### GIF не создается

**Проблема:** Вместо GIF обычное изображение

**Решение:**
```python
# Проверьте порог
GIF_THRESHOLD = 1_000_000_000  # 1B

# Проверьте включение
ENABLE_GIF_FOR_EXPENSIVE = True

# Проверьте логи
tail -f killbot.log | grep "GIF"
```

### Статистика не отображается

**Проблема:** Нет K/D и количества киллов

**Решение:**
- zKillboard API может быть медленным
- Увеличьте таймаут: `STATS_TIMEOUT = 10`
- Или отключите: `ENABLE_PILOT_STATS = False`

### Плохое качество текста

**Проблема:** Шрифты выглядят размыто

**Решение:**
```bash
# Установите хорошие шрифты
sudo apt-get install fonts-dejavu-core fonts-dejavu-extra

# Или укажите путь в image_config.py
FONT_PATH_BOLD = "/path/to/font-bold.ttf"
FONT_PATH_REGULAR = "/path/to/font-regular.ttf"
```

## 💡 Продвинутые фичи

### Условные стили по корпорации

В `discord_notification_advanced.py`:

```python
# Специальный стиль для вашей корпорации
v_corp_id = victim.get('corporation_id')
if v_corp_id == 98569524:  # ID вашей корпы
    style = 'cyberpunk'  # Всегда яркий стиль
elif event_type == "PRIORITY_TARGET":
    style = 'cyberpunk'
else:
    style = 'default'
```

### Различные GIF для разных порогов

```python
if value >= 10_000_000_000:  # 10B+
    # Очень длинная анимация
    image_path = await generator.generate_animated_gif(...)
elif value >= 1_000_000_000:  # 1B+
    # Обычная анимация
    image_path = await generator.generate_animated_gif(...)
else:
    # Статичное изображение
    image_path = await generator.generate_killmail_image(...)
```

### Кастомный watermark

В `image_generator_advanced.py` найдите строку:
```python
draw.text((20, height - 40), "EVE KillBot", ...)
```

Замените на:
```python
draw.text((20, height - 40), "Your Alliance Name o7", ...)
```

## 🎯 Рекомендуемые настройки

### Для производительности
```python
ENABLE_CHARACTER_PORTRAITS = False
ENABLE_PILOT_STATS = False
ENABLE_GIF_FOR_EXPENSIVE = False
IMAGE_WIDTH = 600
IMAGE_HEIGHT = 300
```

### Для максимального качества
```python
ENABLE_CHARACTER_PORTRAITS = True
ENABLE_PILOT_STATS = True
ENABLE_CORP_LOGOS = True
ENABLE_GIF_FOR_EXPENSIVE = True
IMAGE_WIDTH = 1200
IMAGE_HEIGHT = 600
IMAGE_QUALITY = 95
```

### Сбалансированные (рекомендуется)
```python
ENABLE_CHARACTER_PORTRAITS = True
ENABLE_PILOT_STATS = True
ENABLE_CORP_LOGOS = False  # Не всегда нужны
ENABLE_GIF_FOR_EXPENSIVE = True
GIF_THRESHOLD = 1_000_000_000
IMAGE_WIDTH = 800
IMAGE_HEIGHT = 400
```

## 📝 Changelog

### v2.0 (Advanced)
- ✅ Портреты персонажей
- ✅ Анимированные GIF
- ✅ 5 стилей оформления
- ✅ Статистика пилотов
- ✅ Логотипы корпораций
- ✅ Эффекты взрыва
- ✅ Компактный размер (800x400)

### v1.0 (Basic)
- Базовая генерация изображений
- Один стиль
- Рендер кораблей

---

**Готово!** Теперь у вас самый крутой бот для EVE Online! 🚀
