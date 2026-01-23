# Инструкции для сборки образа
# Используем стабильную и легкую версию Python
FROM python:3.10-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Устанавливаем системные зависимости (если понадобятся для сборки некоторых библиотек)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь исходный код (папку src и main.py)
COPY . .

# Указываем переменную окружения, чтобы логи выводились сразу (без буферизации)
ENV PYTHONUNBUFFERED=1

# Команда для запуска бота
CMD ["python", "src/main.py"]