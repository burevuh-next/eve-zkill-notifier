FROM python:3.10-slim
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements.txt
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY src/ ./src/
COPY subscriptions.json .

# Создаем необходимые директории
RUN mkdir -p /app/image_cache/renders \
             /app/image_cache/portraits \
             /app/image_cache/corp_logos \
             /app/killmail_images

# Проверяем наличие файлов генератора
WORKDIR /app
CMD ["python", "src/main.py"]
