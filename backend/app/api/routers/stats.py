"""Аналитика: воронка, источники, ключевики."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TgUser, require_admin
from app.config import settings
from app.db import get_session
from app.models import Lead, LeadStatus, RawMessage, Source
from app.schemas import StatsOut

router = APIRouter(prefix="/stats", tags=["stats"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/overview", response_model=StatsOut)
async def overview(
    session: AsyncSession = Depends(get_session),
    _: TgUser = Depends(require_admin),
) -> StatsOut:
    by_status = {
        status: count
        for status, count in (
            await session.execute(select(Lead.status, func.count()).group_by(Lead.status))
        ).all()
    }
    raw_by_status = {
        status: count
        for status, count in (
            await session.execute(
                select(RawMessage.status, func.count()).group_by(RawMessage.status)
            )
        ).all()
    }

    day_ago = utcnow() - timedelta(days=1)
    week_ago = utcnow() - timedelta(days=7)

    leads_today = await session.scalar(
        select(func.count()).select_from(Lead).where(Lead.created_at >= day_ago)
    )
    leads_7d = await session.scalar(
        select(func.count()).select_from(Lead).where(Lead.created_at >= week_ago)
    )
    hot_open = await session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.status == LeadStatus.NEW, Lead.score >= settings.score_hot)
    )
    followups_due = await session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.next_followup_at.is_not(None), Lead.next_followup_at <= utcnow())
    )
    avg_score = await session.scalar(
        select(func.avg(Lead.score)).where(Lead.status != LeadStatus.TRASH)
    )

    top_sources_rows = (
        await session.execute(
            select(
                Source.title,
                func.count(Lead.id),
                func.count(Lead.id).filter(Lead.status == LeadStatus.DEAL),
            )
            .join(RawMessage, RawMessage.source_id == Source.id)
            .join(Lead, Lead.raw_message_id == RawMessage.id)
            .where(Lead.status != LeadStatus.TRASH)
            .group_by(Source.title)
            .order_by(func.count(Lead.id).desc())
            .limit(10)
        )
    ).all()

    # какие ключевики реально приносят лидов
    top_keywords_rows = (
        await session.execute(
            text(
                """
                SELECT kw.value AS pattern, count(*) AS leads
                FROM raw_messages r
                JOIN leads l ON l.raw_message_id = r.id
                CROSS JOIN LATERAL jsonb_array_elements_text(r.matched) AS kw(value)
                WHERE l.status <> 'trash' AND r.matched IS NOT NULL
                GROUP BY kw.value
                ORDER BY count(*) DESC
                LIMIT 10
                """
            )
        )
    ).all()

    return StatsOut(
        by_status=by_status,
        leads_today=leads_today or 0,
        leads_7d=leads_7d or 0,
        raw_by_status=raw_by_status,
        hot_open=hot_open or 0,
        followups_due=followups_due or 0,
        avg_score=round(float(avg_score or 0), 1),
        top_sources=[
            {"title": title or "?", "leads": leads, "deals": deals}
            for title, leads, deals in top_sources_rows
        ],
        top_keywords=[{"pattern": pattern, "leads": leads} for pattern, leads in top_keywords_rows],
    )
