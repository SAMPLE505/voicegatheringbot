from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, exists
from models.base import Base
from models.file import File
import os

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def has_files_for_speaker(speaker_id: str) -> bool:
    """Возвращает True, если в таблице files есть записи этого диктора."""
    async with SessionLocal() as session:
        result = await session.scalar(
            select(exists().where(File.speaker_id == speaker_id))
        )
        return bool(result)