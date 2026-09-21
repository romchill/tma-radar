from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.dburl import normalize


class Base(DeclarativeBase):
    pass


_url, _connect_args = normalize(settings.database_url)

engine = create_async_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
