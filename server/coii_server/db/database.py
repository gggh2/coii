from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from coii_server.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    from coii_server.models import orm  # noqa: F401 - registers all models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed built-in pricing
    from coii_server.db.seed import seed_pricing
    async with AsyncSessionLocal() as session:
        await seed_pricing(session)
        await session.commit()
