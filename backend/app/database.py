"""
Database connections: SQLAlchemy (PostgreSQL or SQLite), MongoDB (optional), Redis (optional).
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# SQLAlchemy (Async)
is_sqlite = "sqlite" in settings.DATABASE_URL

engine_kwargs = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
}
if not is_sqlite:
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_postgres():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# MongoDB (optional)
mongo_client = None
mongo_db = None


async def init_mongodb():
    global mongo_client, mongo_db
    if not settings.USE_MONGODB:
        print("   [SKIP] MongoDB disabled")
        return
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=3000)
        await mongo_client.admin.command('ping')
        mongo_db = mongo_client[settings.MONGODB_DB_NAME]
        await mongo_db.challenges.create_index([("type", 1), ("difficulty", 1)])
        await mongo_db.challenges.create_index([("tags", 1)])
    except Exception as e:
        print(f"   [WARN] MongoDB unavailable: {e}")
        mongo_client = None
        mongo_db = None


def get_mongodb():
    return mongo_db


async def close_mongodb():
    global mongo_client
    if mongo_client:
        mongo_client.close()


# Redis (optional)
redis_client = None


async def init_redis():
    global redis_client
    if not settings.USE_REDIS:
        print("   [SKIP] Redis disabled")
        return
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
    except Exception as e:
        print(f"   [WARN] Redis unavailable: {e}")
        redis_client = None


def get_redis():
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
