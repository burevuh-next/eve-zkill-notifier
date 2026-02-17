# 🚀 EVE Online KillBot для Discord

Discord-бот для мониторинга killmail'ов в реальном времени из EVE Online через zKillboard WebSocket API.

## ✨ Возможности

- 📡 **Мониторинг в реальном времени** через WebSocket
- 🎯 **Гибкая фильтрация** по системам, регионам, корпорациям, персонажам, кораблям
- 🚨 **Приоритетные уведомления** с ping для критичных целей
- 📊 **Мульти-канальность** - каждый Discord канал имеет свои фильтры
- ⚡ **Высокая производительность** с асинхронной обработкой
- 🔄 **Graceful restart** при изменении конфигурации
- 📈 **Статистика и мониторинг** работы бота

## 📋 Требования

- Python 3.9+
- Discord Bot Token
- Зависимости из `requirements.txt`

## 🔧 Установка

### 1. Клонируйте репозиторий
```bash
git clone https://github.com/yourusername/eve-killbot.git
cd eve-killbot
```

### 2. Установите зависимости
```bash
pip install -r requirements.txt
```

### 3. Настройте окружение
```bash
cp .env.example .env
nano .env
```

Заполните `.env` файл:
```env
DISCORD_BOT_TOKEN=your_token_here
USER_AGENT=EVE-KillBot/5.0 (your@email.com)
MIN_VALUE=1000000
```

### 4. Создайте Discord бота

1. Перейдите на [Discord Developer Portal](https://discord.com/developers/applications)
2. Создайте новое приложение
3. Во вкладке "Bot" создайте бота и скопируйте токен
4. Включите все **Privileged Gateway Intents** (особенно Message Content Intent)
5. Сгенерируйте invite ссылку с правами:
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Mention Everyone (для priority alerts)

### 5. Запустите бота
```bash
python main.py
```

## 📖 Использование

### Базовые команды

#### Инициализация канала
```
!init
```
Настраивает текущий Discord канал для получения уведомлений.

#### Статус канала
```
!status
```
Показывает текущие фильтры и настройки канала.

#### Установка порога ISK
```
!min 500
```
Устанавливает минимальную стоимость киллов в миллионах ISK (500M в примере).

### Управление фильтрами

#### Добавление фильтров
```
!add <тип> <ID>
```

Доступные типы:
- `system` - Солнечная система
- `region` - Регион
- `const` - Констелляция
- `ship` - Тип корабля
- `corp` - Корпорация
- `char` - Персонаж
- `ping_sys` - Приоритетная система (игнорирует порог ISK, пингует @everyone)
- `ping_ship` - Приоритетный корабль (игнорирует порог ISK, пингует @everyone)

**Примеры:**
```
!add system 30000142    # Jita
!add ship 670           # Capsule
!add corp 98569524      # Моя корпорация
!add ping_sys 30045349  # Wormhole система с алертом
```

#### Удаление фильтров
```
!remove <тип> <ID>
```

**Пример:**
```
!remove system 30000142
```

#### Массовое добавление
```
!addmulti <тип> <ID1> <ID2> <ID3> ...
```

**Пример:**
```
!addmulti system 30000142 30002187 30045349
```

### Утилиты

#### Поиск ID
```
!search <название>
```
Ищет ID систем, персонажей, корпораций по названию.

**Пример:**
```
!search Jita
!search Goonswarm
```

#### Проверка ID
```
!check <ID>
```
Показывает название объекта по его ID.

**Пример:**
```
!check 30000142
```

#### Статистика бота
```
!stats
```
Показывает статистику работы бота: обработанные киллы, размер очереди, ошибки.

#### Экспорт конфигурации
```
!export
```
Сохраняет конфигурацию канала в JSON файл.

#### Импорт конфигурации
```
!import
```
Загружает конфигурацию из JSON файла (прикрепите файл к команде).

#### Очистка кэша
```
!clearcache
```
Очищает кэш имен ESI (требуется при проблемах с отображением имен).

#### Проверка связи
```
!ping
```
Проверяет, отвечает ли бот.

#### Справка
```
!help
```
Показывает список всех команд.

## 📊 Типы событий

Бот различает несколько типов событий:

- **PRIORITY_TARGET** 🚨 - Приоритетная цель (ping_sys/ping_ship)
  - Игнорирует порог ISK
  - Отправляет @everyone уведомление
  
- **SHIP_WATCH** 🚀 - Отслеживаемый корабль
  - Килл/потеря интересующего корабля
  
- **LOCATION_WATCH** 🌌 - Отслеживаемая локация
  - Событие в системе/регионе/констелляции
  
- **TARGET_LOSS** ☠️ - Потеря цели
  - Отслеживаемая корпорация/персонаж погиб
  
- **TARGET_KILL** ⚔️ - Килл цели
  - Отслеживаемая корпорация/персонаж совершил килл

## 🏗️ Архитектура

```
┌─────────────────┐
│  Discord Bot    │ ← Команды пользователей
│ (discord_utils) │
└────────┬────────┘
         │
         ├──────────┐
         │          │
┌────────▼────┐  ┌──▼──────────┐
│  Listener   │  │  Processor  │
│ (WebSocket) │  │  (Killmails)│
└─────────────┘  └─────────────┘
     │                 │
     │  Async Queue    │
     └────────┬────────┘
              │
         ┌────▼────┐
         │  Parser │
         │(Filters)│
         └─────────┘
```

### Компоненты

- **main.py** - Точка входа, управление lifecycle
- **discord_utils.py** - Discord бот и команды
- **listener.py** - WebSocket подключение к zKillboard
- **processor.py** - Обработка killmail'ов и отправка уведомлений
- **parser.py** - Логика фильтрации событий

## ⚙️ Настройка для production

### Systemd service (Linux)

Создайте `/etc/systemd/system/eve-killbot.service`:

```ini
[Unit]
Description=EVE Online KillBot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/eve-killbot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Запуск:
```bash
sudo systemctl enable eve-killbot
sudo systemctl start eve-killbot
sudo systemctl status eve-killbot
```

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

```bash
docker build -t eve-killbot .
docker run -d --name killbot --env-file .env eve-killbot
```

## 🔍 Мониторинг

### Логи
Бот пишет логи в файл `killbot.log` с автоматической ротацией (макс 10MB, 5 файлов).

### Команда статистики
```
!stats
```
Показывает:
- Размер очереди обработки
- Количество обработанных киллов
- Отправленные уведомления
- Пропущенные дубликаты
- Количество ошибок
- Размер кэша
- Количество активных каналов

### Healthcheck endpoint (опционально)
Можно добавить HTTP endpoint для мониторинга (см. документацию по улучшениям).

## 🐛 Troubleshooting

### Бот не получает киллы

1. Проверьте WebSocket подключение в логах
2. Убедитесь, что фильтры настроены (`!status`)
3. Проверьте, что порог ISK не слишком высокий

### Дублирующиеся уведомления

Это нормально при рестарте бота. Система дедупликации хранит последние 1000 киллов.

### Высокая задержка

1. Проверьте размер очереди (`!stats`)
2. Увеличьте `QUEUE_MAX_SIZE` в .env
3. Убедитесь, что сервер не перегружен

### Бот не отвечает на команды

1. Проверьте, что бот онлайн в Discord
2. Убедитесь, что у бота есть права на чтение и отправку сообщений
3. Проверьте логи на ошибки

## 📝 Лицензия

MIT License

## 🤝 Вклад

Pull requests приветствуются! Для значительных изменений сначала откройте issue.

## 📧 Контакты

- EVE Online: [Ваш персонаж]
- Discord: [Ваш Discord]
- Email: [Ваш email]

---

**o7 Fly Safe!**