# 🚀 Быстрый старт - Пошаговая инструкция

## Шаг 1: Установка Docker (если не установлен)

```bash
# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Установка Docker Compose V2 (обычно идет с Docker)
sudo apt-get update
sudo apt-get install docker-compose-plugin
```

## Шаг 2: Запуск проекта

```bash
# Перейти в директорию проекта
cd /root/se-toolkit-hackathon

# Собрать и запустить все сервисы
docker compose up --build

# Или в фоновом режиме
docker compose up --build -d
```

## Шаг 3: Доступ к приложению

После запуска откройте в браузере:

- **Фронтенд**: http://localhost:3000
- **Бэкенд API**: http://localhost:8000
- **API Документация (Swagger)**: http://localhost:8000/docs
- **База данных**: localhost:5432

## Шаг 4: Тестирование

### Через веб-интерфейс:
1. Откройте http://localhost:3000
2. Введите handles: `tourist, petr`
3. Нажмите "Compare"

### Через curl:
```bash
# Проверить здоровье API
curl http://localhost:8000/health

# Сравнить пользователей
curl "http://localhost:8000/compare?handles=tourist,petr"

# Получить сохраненные сравнения
curl "http://localhost:8000/comparisons?limit=5"
```

## Шаг 5: Остановка

```bash
# Остановить все сервисы
docker compose down

# Остановить и удалить volumes (удалит данные БД)
docker compose down -v
```

## Логи сервисов

```bash
# Все логи
docker compose logs

# Только бэкенд
docker compose logs backend

# Только база данных
docker compose logs db

# Только фронтенд
docker compose logs frontend
```

## Альтернатива: Локальный запуск без Docker

### 1. База данных
```bash
# Установите PostgreSQL
sudo apt-get install postgresql

# Создайте пользователя и базу
sudo -u postgres psql -c "CREATE USER cfuser WITH PASSWORD 'cfpassword';"
sudo -u postgres psql -c "CREATE DATABASE cfcompare OWNER cfuser;"
sudo -u postgres psql -d cfcompare -f docker/init-db.sql
```

### 2. Бэкенд
```bash
cd backend

# Виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Зависимости
pip install -r requirements.txt

# Запуск
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Фронтенд
```bash
# Простой HTTP сервер
cd frontend
python3 -m http.server 3000

# Или просто откройте index.html в браузере
```
