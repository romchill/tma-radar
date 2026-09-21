"""Настройки, которые правятся прямо из мини-аппа (промпты, пороги)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TgUser, require_admin
from app.db import get_session
from app.schemas import SettingsUpdate
from app.services import settings_store

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def read_settings(
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> dict[str, Any]:
    return await settings_store.get_all(session)


@router.put("")
async def write_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> dict[str, Any]:
    unknown = set(payload.values) - set(settings_store.EDITABLE)
    if unknown:
        raise HTTPException(status_code=422, detail=f"неизвестные ключи: {sorted(unknown)}")

    for key, value in payload.values.items():
        await settings_store.set_setting(session, key, value)

    await session.commit()
    return await settings_store.get_all(session)


@router.post("/reset")
async def reset_settings(
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> dict[str, Any]:
    """Вернуть промпты и пороги к дефолтам из кода."""
    for key, value in settings_store.DEFAULTS.items():
        await settings_store.set_setting(session, key, value)
    await session.commit()
    return await settings_store.get_all(session)
