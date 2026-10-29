from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.settings import settings

Base = declarative_base()


def create_engine_and_session(database_url: str = settings.DATABASE_URL) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    # WAL mode for SQLite to handle concurrent reads
    engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
    )

    session_maker = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return engine, session_maker


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # Enable WAL mode and foreign keys on SQLite
        if "sqlite" in str(engine.url):
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
            await conn.execute(text("PRAGMA foreign_keys=ON;"))
            await conn.execute(text("PRAGMA busy_timeout=5000;"))
        await conn.run_sync(Base.metadata.create_all)


# Shared default engine and session maker singleton for the application
default_engine, default_session_maker = create_engine_and_session()
