"""Ключевые слова предфильтра + песочница для их проверки."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TgUser, require_admin
from app.db import get_session
from app.models import Keyword
from app.schemas import KeywordIn, KeywordOut, KeywordTest, KeywordTestOut, KeywordUpdate
from app.services.matcher import matcher

router = APIRouter(prefix="/keywords", tags=["keywords"])


def _validate_regex(pattern: str, is_regex: bool) -> None:
    if not is_regex:
        return
    try:
        re.compile(pattern)
    except re.error as exc:
        raise HTTPException(status_code=422, detail=f"битый regex: {exc}") from exc


@router.get("", response_model=list[KeywordOut])
async def list_keywords(
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> list[KeywordOut]:
    rows = (
        await session.execute(select(Keyword).order_by(Keyword.weight.desc(), Keyword.id))
    ).scalars().all()
    return [KeywordOut.model_validate(x) for x in rows]


@router.post("", response_model=KeywordOut, status_code=201)
async def create_keyword(
    payload: KeywordIn,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> KeywordOut:
    _validate_regex(payload.pattern, payload.is_regex)
    keyword = Keyword(**payload.model_dump())
    session.add(keyword)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="такой ключевик уже есть") from exc
    await session.refresh(keyword)
    await matcher.refresh(force=True)
    return KeywordOut.model_validate(keyword)


@router.patch("/{keyword_id}", response_model=KeywordOut)
async def update_keyword(
    keyword_id: int,
    payload: KeywordUpdate,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> KeywordOut:
    keyword = await session.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(status_code=404, detail="ключевик не найден")

    data = payload.model_dump(exclude_unset=True)
    _validate_regex(
        data.get("pattern", keyword.pattern),
        data.get("is_regex", keyword.is_regex),
    )
    for key, value in data.items():
        setattr(keyword, key, value)

    await session.commit()
    await session.refresh(keyword)
    await matcher.refresh(force=True)
    return KeywordOut.model_validate(keyword)


@router.delete("/{keyword_id}", status_code=204, response_class=Response)
async def delete_keyword(
    keyword_id: int,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> Response:
    await session.execute(delete(Keyword).where(Keyword.id == keyword_id))
    await session.commit()
    await matcher.refresh(force=True)
    return Response(status_code=204)


@router.post("/test", response_model=KeywordTestOut)
async def test_keywords(
    payload: KeywordTest,
    _: TgUser = Depends(require_admin),
) -> KeywordTestOut:
    """Прогнать произвольный текст через текущий набор ключевиков."""
    await matcher.refresh(force=True)
    blocked = await matcher.stop_hit(payload.text)
    return KeywordTestOut(
        matched=await matcher.match(payload.text),
        weight=await matcher.weight(payload.text),
        blocked_by=blocked,
    )
