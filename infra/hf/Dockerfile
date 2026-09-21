# Образ для Hugging Face Spaces: весь радар в одном контейнере.
#
# Бесплатный Space даёт ровно один контейнер и постоянный адрес
# https://<аккаунт>-<space>.hf.space. Поэтому здесь и api, и сбор, и бот
# живут в одном процессе (RUN_WORKERS_INLINE=true), а база данных вынесена
# наружу — в бесплатный Postgres на Neon, потому что диск Space сбрасывается
# при каждом перезапуске.

# ---------- сборка мини-аппа ----------
FROM node:20-alpine AS webapp

WORKDIR /build
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

# ---------- рабочий образ ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY --from=webapp /build/dist ./static
COPY infra/hf/start.sh /start.sh
RUN chmod +x /start.sh

# HF Spaces пускает трафик только на 7860 и запускает контейнер
# от пользователя без прав на запись в /app
ENV PORT=7860 \
    STATIC_DIR=/app/static \
    RUN_WORKERS_INLINE=true \
    DEV_MODE=false \
    HOME=/tmp

# Ритм под бесплатную базу. Она засыпает после 5 минут покоя и считает только
# время бодрствования: 100 CU-hours в месяц при 0.25 CU — это около 400 часов.
# Обход раз в 15 минут держит её включённой примерно 5.5 минуты за цикл, то
# есть ~66 CU-hours в месяц. При обходе раз в 3 минуты она не засыпала бы
# никогда и лимит кончился бы к середине месяца.
#
# Скорер и напоминалка по таймеру почти не ходят: их будит сам цикл сбора,
# поэтому заказ оценивается сразу, а не ждёт своего интервала.
ENV CHANNEL_POLL_INTERVAL_SEC=900 \
    VK_POLL_INTERVAL_SEC=900 \
    SCORER_INTERVAL_SEC=900 \
    FOLLOWUP_INTERVAL_SEC=3600
EXPOSE 7860

CMD ["/start.sh"]
