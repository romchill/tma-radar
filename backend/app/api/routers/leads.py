"""Лента лидов, карточка, воронка, генерация первого сообщения."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TgUser, require_admin
from app.db import get_session
from app.models import Lead, LeadEvent, LeadStatus, RawMessage
from app.schemas import (
    DraftOut,
    DraftRequest,
    EventOut,
    LeadOut,
    LeadPage,
    LeadUpdate,
)
from app.services import llm, templates
from app.services.settings_store import get_setting

router = APIRouter(prefix="/leads", tags=["leads"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _get_lead(session: AsyncSession, lead_id: int) -> Lead:
    lead = (
        await session.execute(select(Lead).where(Lead.id == lead_id))
    ).unique().scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="лид не найден")
    return lead


@router.get("", response_model=LeadPage)
async def list_leads(
    status: str | None = Query(default=None, description="new/contacted/dialog/offer/deal/lost/trash"),
    min_score: int = Query(default=0, ge=0, le=100),
    q: str | None = Query(default=None, description="поиск по тексту, нише и чату"),
    with_contact: bool = Query(
        default=False,
        description="только те, кому можно написать напрямую в телеграм",
    ),
    source_id: int | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> LeadPage:
    stmt = select(Lead).join(RawMessage, Lead.raw_message_id == RawMessage.id)

    if status:
        if status not in LeadStatus.ALL:
            raise HTTPException(status_code=422, detail="неизвестный статус")
        stmt = stmt.where(Lead.status == status)
    else:
        stmt = stmt.where(Lead.status != LeadStatus.TRASH)

    if min_score:
        stmt = stmt.where(Lead.score >= min_score)
    if source_id:
        stmt = stmt.where(RawMessage.source_id == source_id)
    if with_contact:
        # у перепечаток с бирж контакта нет: писать можно только автору
        # сообщения из чата или тому, кто оставил @username в тексте
        stmt = stmt.where(RawMessage.contact_url.is_not(None))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                RawMessage.text.ilike(pattern),
                RawMessage.chat_title.ilike(pattern),
                Lead.niche.ilike(pattern),
                Lead.summary.ilike(pattern),
            )
        )

    total = await session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )

    rows = (
        (
            await session.execute(
                # при равных баллах сверху свежий: на бирже решают часы
                stmt.order_by(
                    Lead.score.desc(),
                    RawMessage.posted_at.desc().nullslast(),
                    Lead.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        .unique()
        .scalars()
        .all()
    )

    return LeadPage(
        items=[LeadOut.from_lead(x) for x in rows],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> LeadOut:
    return LeadOut.from_lead(await _get_lead(session, lead_id))


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    session: AsyncSession = Depends(get_session),
    user: TgUser = Depends(require_admin),
) -> LeadOut:
    lead = await _get_lead(session, lead_id)
    data = payload.model_dump(exclude_unset=True)

    if "status" in data:
        if data["status"] not in LeadStatus.ALL:
            raise HTTPException(status_code=422, detail="неизвестный статус")
        if data["status"] != lead.status:
            session.add(
                LeadEvent(
                    lead_id=lead.id,
                    kind="status",
                    payload={"from": lead.status, "to": data["status"]},
                    actor_id=user.id,
                )
            )
        if data["status"] == LeadStatus.CONTACTED and lead.contacted_at is None:
            lead.contacted_at = utcnow()

    for key, value in data.items():
        setattr(lead, key, value)

    await session.commit()
    await session.refresh(lead)
    return LeadOut.from_lead(lead)


@router.post("/{lead_id}/draft", response_model=DraftOut)
async def make_draft(
    lead_id: int,
    payload: DraftRequest,
    session: AsyncSession = Depends(get_session),
    user: TgUser = Depends(require_admin),
) -> DraftOut:
    """Генерирует первое сообщение в ЛС. Отправляешь его ты, руками."""
    lead = await _get_lead(session, lead_id)

    if lead.draft_message and not payload.regenerate:
        return DraftOut(draft_message=lead.draft_message)

    extra = payload.extra or await get_setting(session, "writer_extra", "") or None

    if llm.available():
        system = await get_setting(session, "writer_system", None)
        try:
            text = await llm.write_outreach(
                text=lead.raw.text,
                niche=lead.niche,
                pain=lead.pain,
                chat_title=lead.raw.chat_title,
                author_name=lead.raw.author_name,
                extra=extra,
                system=system,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"модель недоступна: {exc}") from exc
    else:
        # без ключа пишем по шаблону: хуже, чем модель, но лучше пустого поля
        text = templates.build_draft(lead.raw.text, extra=extra)

    lead.draft_message = text
    session.add(LeadEvent(lead_id=lead.id, kind="draft", actor_id=user.id))
    await session.commit()
    return DraftOut(draft_message=text)


@router.get("/{lead_id}/events", response_model=list[EventOut])
async def lead_events(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> list[EventOut]:
    rows = (
        await session.execute(
            select(LeadEvent).where(LeadEvent.lead_id == lead_id).order_by(LeadEvent.id.desc())
        )
    ).scalars().all()
    return [EventOut.model_validate(x) for x in rows]
