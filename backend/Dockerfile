FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && apt-get purge -y gcc libc6-dev && apt-get autoremove -y

COPY . .

RUN mkdir -p /app/sessions

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
