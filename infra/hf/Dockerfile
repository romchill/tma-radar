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
EXPOSE 7860

CMD ["/start.sh"]
