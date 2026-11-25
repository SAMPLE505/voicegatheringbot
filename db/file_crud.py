from sqlalchemy import select

from database import SessionLocal
from models.file import File


async def save_file(
    id: int,
    speaker_id: str,
    file_path: str,
    sha256: str,
    duration_s: int,
    file_size: int,
    prompt_id: int | None = None,
    prompt_text: str | None = None,
    prompt_type: str | None = None
) -> File:
    """
    Сохраняет запись об обезличенной голосовой записи.

    speaker_id берётся из speaker_session.get_speaker_id().
    user_id сюда не передаётся: связи записи с пользователем быть не должно.
    """
    async with SessionLocal() as session:
        file = File(
            id=id,
            speaker_id=speaker_id,
            file_path=file_path,
            sha256=sha256,
            duration_s=duration_s,
            file_size=file_size,
            prompt_id=prompt_id,
            prompt_text=prompt_text,
            prompt_type=prompt_type
        )
        session.add(file)

        await session.commit()
        await session.refresh(file)

        return file


async def file_exists(sha256: str) -> bool:
    """Проверяет, есть ли уже запись с таким хешем (поиск дубликата)."""
    async with SessionLocal() as session:
        result = await session.scalar(
            select(File.id).where(File.sha256 == sha256).limit(1)
        )
        return result is not None