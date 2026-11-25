
from __future__ import annotations

from uuid import uuid4

from redis.asyncio import Redis

from database import has_files_for_speaker


class SpeakerSessionExpired(RuntimeError):
    """Временная связь с Telegram-аккаунтом отсутствует или истекла."""


class SpeakerIdentityMismatch(RuntimeError):
    """UUID диктора не совпадает с идентификатором активной сессии."""


class SpeakerSessionAlreadyExists(RuntimeError):
    """Для Telegram-аккаунта уже существует активная Redis-сессия."""


class SpeakerRegistry:
    """Временная связь Telegram ID -> анонимный speaker_id.

    В одной Redis hash-записи хранятся:
      - speaker_id: UUID диктора;
      - tasks_issued: количество выданных заданий.

    TTL устанавливается при создании сессии и не продлевается.
    FSM-состояния отдельно хранятся в RedisStorage aiogram.
    """

    def __init__(
        self,
        redis: Redis,
        ttl_seconds: int = 24 * 60 * 60,
        key_prefix: str = "survey:session",
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds должен быть положительным")
        if not key_prefix:
            raise ValueError("key_prefix не должен быть пустым")

        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix

    def _key(self, telegram_user_id: int) -> str:
        return f"{self.key_prefix}:{telegram_user_id}"

    @staticmethod
    def _as_text(value: str | bytes | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    async def create_new(self, telegram_user_id: int) -> str:
        """Создаёт UUID диктора и временную сессию на 24 часа."""
        key = self._key(telegram_user_id)

        async with self.redis.lock(
            f"{key}:create-lock",
            timeout=30,
            blocking_timeout=10,
        ):
            if await self.redis.exists(key):
                raise SpeakerSessionAlreadyExists(
                    "Для этого Telegram-аккаунта уже есть активная сессия."
                )

            while True:
                speaker_id = str(uuid4())
                if not await has_files_for_speaker(speaker_id):
                    break

            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.hset(
                    key,
                    mapping={
                        "speaker_id": speaker_id,
                        "tasks_issued": 0,
                    },
                )
                pipe.expire(key, self.ttl_seconds)
                await pipe.execute()

            return speaker_id

    async def get_speaker_id(self, telegram_user_id: int) -> str:
        """Возвращает UUID диктора или сообщает об истечении сессии."""
        value = self._as_text(
            await self.redis.hget(
                self._key(telegram_user_id),
                "speaker_id",
            )
        )

        if value is None:
            raise SpeakerSessionExpired(
                "Сессия истекла или была удалена."
            )

        return value

    async def ensure_active(
        self,
        telegram_user_id: int,
        expected_speaker_id: str,
    ) -> str:
        """Проверяет существование сессии и совпадение UUID."""
        actual_speaker_id = await self.get_speaker_id(
            telegram_user_id
        )

        if actual_speaker_id != expected_speaker_id:
            raise SpeakerIdentityMismatch(
                "UUID диктора не совпадает с активной сессией."
            )

        return actual_speaker_id

    async def get_tasks_issued(self, telegram_user_id: int) -> int:
        """Возвращает число выданных заданий."""
        key = self._key(telegram_user_id)
        value = await self.redis.hget(key, "tasks_issued")

        if value is None:
            if not await self.redis.exists(key):
                raise SpeakerSessionExpired(
                    "Сессия истекла или была удалена."
                )

            raise RuntimeError(
                "В Redis-сессии отсутствует счётчик tasks_issued."
            )

        return int(value)

    async def increment_tasks_issued(
        self,
        telegram_user_id: int,
    ) -> int:
        """Атомарно увеличивает счётчик, не создавая новую сессию."""
        key = self._key(telegram_user_id)

        result = await self.redis.eval(
            """
            if redis.call('EXISTS', KEYS[1]) == 0 then
                return -1
            end

            if redis.call('HEXISTS', KEYS[1], 'speaker_id') == 0 then
                return -2
            end

            return redis.call('HINCRBY', KEYS[1], 'tasks_issued', 1)
            """,
            1,
            key,
        )

        result = int(result)

        if result == -1:
            raise SpeakerSessionExpired(
                "Сессия истекла или была удалена."
            )

        if result == -2:
            raise RuntimeError(
                "В Redis-сессии отсутствует speaker_id."
            )

        return result

    async def delete(self, telegram_user_id: int) -> None:
        """Удаляет временную связь и счётчик заданий."""
        await self.redis.delete(
            self._key(telegram_user_id)
        )
