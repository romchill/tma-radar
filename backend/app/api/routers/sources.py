"""Источники: какие чаты слушаем."""

from __future__ import annotations

import re

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TgUser, require_admin
from app.db import get_session
from app.models import Lead, RawMessage, Source
from app.schemas import SourceIn, SourceOut, SourceUpdate
from app.services import tgweb, vk
from app.workers.vk_walls import vk_chat_id

router = APIRouter(prefix="/sources", tags=["sources"])

CHANNEL_KIND = "tg_channel"
VK_KIND = "vk_group"
CHANNEL_RE = re.compile(r"(?:https?://)?(?:t\.me/)?@?([A-Za-z][A-Za-z0-9_]{4,31})/?$")
# vk.com/club123, vk.com/freelance, просто freelance
VK_RE = re.compile(r"(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/([A-Za-z0-9_.]{2,64})/?$")


@router.get("", response_model=list[SourceOut])
async def list_sources(
    only_enabled: bool = False,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> list[SourceOut]:
    raw_counts = (
        select(RawMessage.source_id, func.count().label("cnt"))
        .group_by(RawMessage.source_id)
        .subquery()
    )
    lead_counts = (
        select(RawMessage.source_id, func.count(Lead.id).label("cnt"))
        .join(Lead, Lead.raw_message_id == RawMessage.id)
        .group_by(RawMessage.source_id)
        .subquery()
    )

    stmt = (
        select(
            Source,
            func.coalesce(raw_counts.c.cnt, 0),
            func.coalesce(lead_counts.c.cnt, 0),
        )
        .outerjoin(raw_counts, raw_counts.c.source_id == Source.id)
        .outerjoin(lead_counts, lead_counts.c.source_id == Source.id)
        .order_by(func.coalesce(lead_counts.c.cnt, 0).desc(), Source.title)
    )
    if only_enabled:
        stmt = stmt.where(Source.enabled.is_(True))

    result = []
    for source, raw_count, lead_count in (await session.execute(stmt)).all():
        item = SourceOut.model_validate(source)
        item.raw_count = raw_count
        item.leads_count = lead_count
        result.append(item)
    return result


async def _add_vk_group(payload: SourceIn, session: AsyncSession) -> SourceOut:
    """Добавляет группу ВК: там у постов есть авторы, а значит прямой контакт."""
    if not vk.available():
        raise HTTPException(
            status_code=422,
            detail=(
                "Не задан VK_SERVICE_TOKEN. Возьми сервисный ключ: "
                "vk.com/apps?act=manage → создать Standalone-приложение → Ключи доступа."
            ),
        )

    raw = payload.username.strip()
    match = VK_RE.match(raw)
    name = match.group(1) if match else raw.lstrip("@")

    async with aiohttp.ClientSession(timeout=vk.TIMEOUT) as http:
        posts = await vk.fetch_wall(http, name, count=10)
        title = await vk.group_title(http, name)

    if not posts:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Стену «{name}» прочитать не вышло. Так бывает, если группа "
                "закрытая, стена отключена или в адресе опечатка."
            ),
        )

    chat_id = vk_chat_id(name)
    await session.execute(
        pg_insert(Source)
        .values(
            kind=VK_KIND,
            username=name,
            title=(title or name)[:256],
            tg_chat_id=chat_id,
            url=f"https://vk.com/{name}",
            enabled=True,
        )
        .on_conflict_do_update(
            index_elements=[Source.tg_chat_id],
            set_={"enabled": True, "title": (title or name)[:256]},
        )
    )
    await session.commit()

    source = (
        await session.execute(select(Source).where(Source.tg_chat_id == chat_id))
    ).scalar_one()
    return SourceOut.model_validate(source)


@router.post("", response_model=SourceOut, status_code=201)
async def add_channel(
    payload: SourceIn,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> SourceOut:
    """Добавляет источник: телеграм-канал или группу ВК — по виду адреса."""
    raw = payload.username.strip()
    if payload.kind == VK_KIND or "vk.com" in raw or "vk.ru" in raw:
        return await _add_vk_group(payload, session)

    match = CHANNEL_RE.match(raw)
    if not match:
        raise HTTPException(
            status_code=422,
            detail="Нужно имя канала: @название или ссылка t.me/название",
        )

    username = match.group(1)

    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        posts = await tgweb.fetch_channel(http, username)

    if not posts:
        raise HTTPException(
            status_code=422,
            detail=(
                f"@{username} прочитать не вышло. Так бывает с группами "
                "(у них нет веб-версии), с закрытыми каналами и при опечатке."
            ),
        )

    await session.execute(
        pg_insert(Source)
        .values(
            kind=CHANNEL_KIND,
            username=username,
            title=username,
            tg_chat_id=tgweb.channel_chat_id(username),
            url=f"https://t.me/{username}",
            enabled=True,
        )
        .on_conflict_do_update(
            index_elements=[Source.tg_chat_id],
            set_={"enabled": True, "username": username},
        )
    )
    await session.commit()

    source = (
        await session.execute(
            select(Source).where(Source.tg_chat_id == tgweb.channel_chat_id(username))
        )
    ).scalar_one()
    return SourceOut.model_validate(source)


@router.delete("/{source_id}", status_code=204, response_class=Response)
async def remove_source(
    source_id: int,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> Response:
    await session.execute(delete(Source).where(Source.id == source_id))
    await session.commit()
    return Response(status_code=204)


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> SourceOut:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="источник не найден")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, key, value)

    await session.commit()
    await session.refresh(source)
    return SourceOut.model_validate(source)
