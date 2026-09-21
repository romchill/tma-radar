#!/bin/sh
# Запуск радара на Hugging Face Spaces.
#
# Миграции гоняются при каждом старте: контейнер Space пересоздаётся на
# любом обновлении кода, а база живёт снаружи (Neon), так что схему нужно
# подтягивать самому. Alembic на уже применённых версиях ничего не делает.
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
	echo "НЕТ DATABASE_URL — задай его в секретах Space (строка подключения к Neon)" >&2
	exit 1
fi

echo "применяю миграции..."
alembic upgrade head

echo "старт радара на порту ${PORT:-7860}"
exec uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-7860}" --proxy-headers
