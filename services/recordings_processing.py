import hashlib
import logging
import os
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import Voice

from database import SessionLocal
from db.file_crud import save_file, file_exists
from models.file import File


logger = logging.getLogger(__name__)


class DuplicateRecordingError(Exception):
    """Аудиозапись с таким SHA-256 уже существует."""


# Корневая папка проекта
BASE_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = BASE_DIR / "recordings"

async def save_voice_recording(
    bot: Bot,
    voice: Voice,
    speaker_id: str,
    prompt: dict,
) -> Path:
    """Скачивает голосовое и сохраняет файл + метаданные в таблицу File.
    Telegram user_id, username и Telegram file_id в БД не записываются.
    """

    speaker_dir = RECORDINGS_DIR / speaker_id
    speaker_dir.mkdir(parents=True, exist_ok=True)

    telegram_file = await bot.get_file(voice.file_id)
    extension = Path(telegram_file.file_path or "").suffix or ".ogg"
    # Файл называется случайным UUID; в пути нет Telegram ID или username.
    file_id = uuid4().hex
    temp_path = speaker_dir / f".{file_id}.part"
    audio_path = speaker_dir / f"{file_id}{extension}"
    
    try:
        # Сначала загружаем аудио во временный файл.
        await bot.download_file(
            telegram_file.file_path,
            destination=temp_path,
        )

        # Вычисляем SHA-256 по частям.
        digest = hashlib.sha256()

        with temp_path.open("rb") as audio_file:
            for chunk in iter(
                lambda: audio_file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        sha256 = digest.hexdigest()

        # Проверяем дубликат до помещения в постоянное хранилище.
        if await file_exists(sha256):
            raise DuplicateRecordingError(
                "Аудиозапись с таким SHA-256 уже существует."
            )

        # Только уникальную запись помещаем в постоянное хранилище.
        temp_path.replace(audio_path)

        record_values = {
            "id": file_id,
            "speaker_id": speaker_id,
            "file_path": str(audio_path),
            "sha256": sha256,
            "duration_s": int(voice.duration),
            "file_size": audio_path.stat().st_size,
            "prompt_id": prompt["id"],
            "prompt_text": prompt["text"],
            "prompt_type": prompt["type"],
        }

        await save_file(**record_values)

        return audio_path

    except Exception:
        # Удаляем временный файл или аудио,
        # если метаданные не удалось сохранить.
        for path in (temp_path, audio_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Не удалось удалить файл: %s",
                    path,
                )

        raise
