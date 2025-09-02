# Базовий образ з Python
FROM python:3.11-slim

# Створюємо робочу директорію всередині контейнера
WORKDIR /app

# Копіюємо файли проекту в контейнер
COPY . /app

# Встановлюємо залежності
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Встановлюємо змінні оточення (можеш поставити свої токени або використовувати Railway secrets)
ENV TELEGRAM_TOKEN="твій_токен"
ENV DEEPSEEK_API_KEY="твій_API_ключ"

# Команда для запуску бота
CMD ["python", "main.py"]
