"""Настройки, которые можно менять из мини-аппа без передеплоя.

Хранятся в app_settings как JSONB. Если ключа нет — берётся дефолт из кода.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as env
from app.models import AppSetting
from app.services import prompts

# ключ -> дефолт
DEFAULTS: dict[str, Any] = {
    "scorer_system": prompts.SCORER_SYSTEM,
    "writer_system": prompts.WRITER_SYSTEM,
    "score_threshold": env.score_threshold,
    "score_hot": env.score_hot,
    "daily_lead_cap": env.daily_lead_cap,
    "contact_cooldown_days": env.contact_cooldown_days,
    "writer_extra": "",
    # публичный адрес мини-аппа; у бесплатного туннеля он меняется,
    # поэтому правится командой /url в боте, а не через .env
    "webapp_url": "",
}

EDITABLE = tuple(DEFAULTS)


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(AppSetting, key)
    if row is not None and row.value is not None:
        return row.value.get("v", default)
    return DEFAULTS.get(key, default)


async def get_all(session: AsyncSession) -> dict[str, Any]:
    result = dict(DEFAULTS)
    for key in EDITABLE:
        row = await session.get(AppSetting, key)
        if row is not None and row.value is not None:
            result[key] = row.value.get("v", result[key])
    return result


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    if key not in EDITABLE:
        raise KeyError(key)
    await set_internal(session, key, value)


async def set_internal(session: AsyncSession, key: str, value: Any) -> None:
    """То же хранилище, но для служебных отметок воркеров.

    Такие ключи (например, «в какой день уже предупредили про лимит») не
    показываются в настройках мини-аппа и не входят в EDITABLE.
    """
    await session.execute(
        pg_insert(AppSetting)
        .values(key=key, value={"v": value})
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": {"v": value}})
    )
