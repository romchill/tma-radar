"""FastAPI-приложение мини-аппа.

Наружу торчит только через Caddy по пути /api/*. Все ручки требуют
подписанный Telegram initData и user id из ADMIN_IDS.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routers import config, keywords, leads, sources, stats
from app.auth import TgUser, require_admin
from app.config import settings
from app.db import engine
from app.logging_conf import setup_logging
from app.schemas import MeOut
from app.services import llm

log = setup_logging("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("api старт, домен=%s dev_mode=%s", settings.domain, settings.dev_mode)

    # На бесплатном хостинге контейнер разрешён ровно один, поэтому сбор,
    # оценка и бот живут внутри процесса api отдельной задачей. В docker
    # compose на ноутбуке это выключено: там для них есть свой контейнер.
    # На хостинге адрес мини-аппа постоянный и известен из DOMAIN, поэтому
    # он побеждает то, что когда-то прислали боту командой /url: иначе после
    # переезда кнопки вели бы на мёртвый туннель с ноутбука.
    if settings.domain and settings.domain != "localhost":
        from app.db import SessionLocal
        from app.services.settings_store import set_setting

        async with SessionLocal() as session:
            await set_setting(session, "webapp_url", f"https://{settings.domain}")
            await session.commit()
        log.info("адрес мини-аппа зафиксирован: https://%s", settings.domain)

    workers = None
    if settings.run_workers_inline:
        from app.workers.all import main as run_all

        log.info("воркеры запускаются внутри api (RUN_WORKERS_INLINE=true)")
        workers = asyncio.create_task(run_all())

    try:
        yield
    finally:
        if workers is not None:
            workers.cancel()
            with suppress(asyncio.CancelledError):
                await workers
        await engine.dispose()


app = FastAPI(
    title="TMA Lead Radar",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.dev_mode else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.dev_mode else None,
)

# В проде фронт отдаётся тем же доменом через Caddy, CORS не нужен.
# В dev-режиме фронт крутится на localhost:5173.
if settings.dev_mode:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me", response_model=MeOut, tags=["auth"])
async def me(user: TgUser = Depends(require_admin)) -> MeOut:
    return MeOut(
        id=user.id,
        username=user.username,
        title=user.title,
        ai_enabled=llm.available(),
    )


for router in (leads.router, sources.router, keywords.router, config.router, stats.router):
    app.include_router(router, prefix="/api")


# Статика мини-аппа. Монтируется последней: всё, что не совпало с /api и
# /healthz выше, отдаётся как файл. html=True возвращает index.html на "/",
# чего хватает — навигация в приложении на состоянии, своих url-путей нет.
_static = Path(settings.static_dir)
if _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="webapp")
    log.info("раздаю мини-апп из %s", _static)
else:
    log.warning(
        "нет собранного фронта в %s — собери его: cd webapp && npm run build", _static
    )
