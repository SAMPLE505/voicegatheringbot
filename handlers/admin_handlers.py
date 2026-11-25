from aiogram import Bot, Router
from aiogram.filters import BaseFilter
from aiogram.types import Message
from settings import SYS_ADMIN

import csv
import logging
import tempfile
import zipfile

from datetime import date, datetime
from pathlib import Path
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SessionLocal
from models.file import File
from models.user import User


router = Router()


class IsAdmin(BaseFilter):
    """
    Фильтр для проверки, является ли пользователь администратором.

    Returns:
        False: Юзер не админ.
        True: Юзер админ.
    """
    def __init__(self):
        # user_id системного администратора
        self.sys_admin = SYS_ADMIN

    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        return user.id == self.sys_admin


router = Router(name="admin")
logger = logging.getLogger(__name__)


# --------------------------------------------------
# Вспомогательное форматирование
# --------------------------------------------------

def format_bytes(size: int) -> str:
    value = float(size)

    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"

        value /= 1024

    return f"{value:.2f} ТБ"


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours} ч {minutes} мин"

    if minutes:
        return f"{minutes} мин {seconds} с"

    return f"{seconds} с"


# --------------------------------------------------
# Главное меню
# --------------------------------------------------

@router.message(Command("admin"), IsAdmin())
async def admin_panel(message: Message) -> None:

    await message.answer(
        "🛠 Админ-панель\n\n"
        "/stats — статистика бота\n"
        "/export_db — выгрузить users и files в ZIP\n"
        "/export_users — выгрузить пользователей в CSV\n"
        "/export_files — выгрузить аудиозаписи в CSV"
    )


# --------------------------------------------------
# Статистика
# --------------------------------------------------

@router.message(Command("stats"), IsAdmin())
async def show_stats(message: Message) -> None:

    try:
        async with SessionLocal() as session:
            # Пользователи
            users_total = await session.scalar(
                select(func.count()).select_from(User)
            ) or 0

            users_active = await session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.active.is_(True))
            ) or 0

            users_blocked = await session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.active.is_(False))
            ) or 0

            # Аудиозаписи
            files_total = await session.scalar(
                select(func.count()).select_from(File)
            ) or 0

            total_size = await session.scalar(
                select(func.coalesce(func.sum(File.file_size), 0))
            ) or 0

            total_duration = await session.scalar(
                select(func.coalesce(func.sum(File.duration_s), 0))
            ) or 0

            # Счётчик выдачи заданий
            recordings_sent = await session.scalar(
                select(func.count()).select_from(File)
            ) or 0

        text = (
            "📊 СТАТИСТИКА БОТА\n"
            "\n"
            f"👥 Пользователи: {users_total}\n"
            f"✅ Активные: {users_active}\n"
            f"🚫 Заблокированные: {users_blocked}\n"
            "\n"
            f"🎙 Аудиозаписи: {files_total}\n"
            f"💾 Общий объём: {format_bytes(total_size)}\n"
            f"⏱ Суммарная длительность: "
            f"{format_duration(total_duration)}\n"
            "\n"
            f"📤 Счётчик выданных заданий: {recordings_sent}"
        )

        await message.answer(text)

    except Exception:
        logger.exception("Ошибка получения статистики")
        await message.answer(
            "❌ Не удалось получить статистику. "
            "Подробности доступны в логах бота."
        )


# --------------------------------------------------
# Запросы для экспорта
# --------------------------------------------------

def users_export_query():
    return select(
        User.user_id,
        User.consent_version,
        User.consent_sha256,
        User.consented_on,
        User.survey_started,
        User.survey_finished,
        User.active,
    ).order_by(User.user_id)


def files_export_query():
    return select(
        File.id,
        File.speaker_id,
        File.file_path,
        File.sha256,
        File.duration_s,
        File.file_size,
        File.prompt_id,
        File.prompt_text,
        File.prompt_type
    ).order_by(File.speaker_id, File.id)


def csv_value(value) -> str:
    if value is None:
        return ""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, bool):
        return str(value).lower()

    return str(value)


async def write_query_to_csv(
    session: AsyncSession,
    query,
    output_path: Path,
) -> None:
    """Выгружает результат SQL-запроса в CSV потоком."""
    result = await session.stream(query)

    try:
        with output_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(list(result.keys()))

            async for row in result:
                writer.writerow([csv_value(value) for value in row])

    finally:
        await result.close()


# --------------------------------------------------
# Экспорт одной таблицы
# --------------------------------------------------

async def send_table_export(
    message: Message,
    query,
    filename: str,
) -> None:
    await message.answer("⏳ Готовлю выгрузку...")

    try:
        with tempfile.TemporaryDirectory(prefix="bot_export_") as temp_dir:
            path = Path(temp_dir) / filename

            async with SessionLocal() as session:
                await write_query_to_csv(session, query, path)

            await message.answer_document(
                document=FSInputFile(path, filename=filename),
                caption=f"✅ Экспорт завершён: {filename}",
            )

    except Exception:
        logger.exception("Ошибка экспорта %s", filename)
        await message.answer(
            "❌ Не удалось выполнить экспорт. "
            "Подробности доступны в логах бота."
        )


@router.message(Command("export_users"), IsAdmin())
async def export_users(message: Message) -> None:

    await send_table_export(
        message,
        users_export_query(),
        "users.csv",
    )


@router.message(Command("export_files"), IsAdmin())
async def export_files(message: Message) -> None:

    await send_table_export(
        message,
        files_export_query(),
        "files.csv",
    )


# --------------------------------------------------
# Полная выгрузка: users.csv + files.csv -> ZIP
# --------------------------------------------------

@router.message(Command("export_db"), IsAdmin())
async def export_database(message: Message) -> None:

    await message.answer("⏳ Формирую архив базы данных...")

    try:
        with tempfile.TemporaryDirectory(prefix="bot_export_") as temp_dir:
            directory = Path(temp_dir)

            users_csv = directory / "users.csv"
            files_csv = directory / "files.csv"
            archive_path = directory / "database_export.zip"

            async with SessionLocal() as session:
                await write_query_to_csv(
                    session,
                    users_export_query(),
                    users_csv,
                )

                await write_query_to_csv(
                    session,
                    files_export_query(),
                    files_csv,
                )

            with zipfile.ZipFile(
                archive_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.write(users_csv, arcname="users.csv")
                archive.write(files_csv, arcname="files.csv")

            await message.answer_document(
                document=FSInputFile(
                    archive_path,
                    filename="database_export.zip",
                ),
                caption=(
                    "✅ Выгрузка базы данных готова.\n\n"
                    "В архиве:\n"
                    "• users.csv — реестр согласий;\n"
                    "• files.csv — метаданные аудиозаписей."
                ),
            )

    except Exception:
        logger.exception("Ошибка экспорта базы данных")
        await message.answer(
            "❌ Не удалось сформировать архив. "
            "Подробности доступны в логах бота."
        )