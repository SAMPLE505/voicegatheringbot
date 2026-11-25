import hashlib
from datetime import date

from sqlalchemy import select, func

from database import SessionLocal
from models.user import User


async def has_consent(user_id: int) -> bool:
    """Проверяет, есть ли в БД запись о согласии пользователя."""
    async with SessionLocal() as session:
        result = await session.scalar(
            select(User.user_id).where(User.user_id == user_id)
        )
        return result is not None


async def get_user(user_id: int) -> User | None:
    """Возвращает пользователя по Telegram ID."""
    async with SessionLocal() as session:
        return await session.get(User, user_id)


async def add_or_update_user(
    user_id: int,
    consent_version: str,
    consent_sha256: str,
) -> User:
    """
    Сохраняет факт согласия.

    Если пользователь уже есть в БД, возвращает False
    """
    async with SessionLocal() as session:
        user = await session.get(User, user_id)

        if user is None:
            user = User(
                user_id=user_id,
                consent_version=consent_version,
                consent_sha256=consent_sha256,
                consented_on=date.today(),
                survey_started = False,
                active=True,
            )
            session.add(user)
        else:
            return False

        await session.commit()
        await session.refresh(user)

        return user


async def save_consent(
    user_id: int,
    consent_version: str,
    consent_text: str,
) -> User:
    """Вычисляет SHA-256 текста согласия и сохраняет согласие."""
    consent_sha256 = hashlib.sha256(
        consent_text.encode("utf-8")
    ).hexdigest()

    return await add_or_update_user(
        user_id=user_id,
        consent_version=consent_version,
        consent_sha256=consent_sha256,
    )


async def set_user_active(user_id: int, active: bool) -> bool:
    """
    Изменяет статус пользователя.
    Возвращает False, если пользователь не найден.
    """
    async with SessionLocal() as session:
        user = await session.get(User, user_id)

        if user is None:
            return False

        user.active = active

        await session.commit()
        return True

async def get_user_survey_state(
    user_id: int,
) -> bool| None:
    """
    Возвращает survey_started.
    Возвращает None, если пользователь не найден.
    """
    async with SessionLocal() as session:
        user = await session.get(User, user_id)

        if user is None:
            return False

        return bool(user.survey_started)


async def change_user_survey_state(
    user_id: int,
) -> bool | None:
    """
    Меняет survey_started на True, показывая, что пользователь уже начинал опрос.
    Возвращает None, если пользователь не найден.
    """
    async with SessionLocal() as session:
        user = await session.get(User, user_id)

        if user is None:
            return False

        user.survey_started = True

        await session.commit()
        return True


async def count_users() -> int:
    """Возвращает общее количество пользователей с записью в БД."""
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(User)
        ) or 0


async def get_users(
    limit: int = 100,
    offset: int = 0,
) -> list[User]:
    """Возвращает пользователей постранично."""
    if limit < 1 or offset < 0:
        raise ValueError("limit должен быть положительным, offset — неотрицательным")

    async with SessionLocal() as session:
        result = await session.scalars(
            select(User)
            .order_by(User.consented_on.desc(), User.user_id)
            .limit(limit)
            .offset(offset)
        )

        return list(result.all())