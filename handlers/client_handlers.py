
from pathlib import Path
import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from redis.asyncio import Redis

from db.user_crud import (
    has_consent,
    save_consent,
    get_user_survey_state,
)
from keyboards.client_keyboards import (
    consent_keyboard,
    start_survey_keyboard,
)
from services.speaker_registry import (
    SpeakerRegistry,
    SpeakerSessionExpired,
)
from states.survey_states import SurveyStates


# Корневая папка проекта
BASE_DIR = Path(__file__).resolve().parent.parent
TEXTS_DIR = BASE_DIR / "texts"

CONSENT_TEXT = (
    TEXTS_DIR / "CONSENT_TEXT.txt"
).read_text(encoding="utf-8")

INTRODUCTION_TEXT = (
    TEXTS_DIR / "INTRODUCTION_TEXT.txt"
).read_text(encoding="utf-8")

logger = logging.getLogger(__name__)


def create_client_router(redis: Redis) -> Router:
    router = Router(name="client")

    registry = SpeakerRegistry(
        redis=redis,
        ttl_seconds=24 * 60 * 60,
    )

    # --------------------------------------------------
    # Команда /start
    # --------------------------------------------------

    @router.message(CommandStart())
    async def start_command(
        message: Message,
        state: FSMContext,
    ) -> None:

        if message.from_user is None:
            return

        user_id = message.from_user.id

        # 1. Проверяем согласие.
        if not await has_consent(user_id):
            await message.answer(
                CONSENT_TEXT,
                reply_markup=consent_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # 2. Проверяем, начинал ли пользователь опрос.
        survey_started = await get_user_survey_state(user_id)

        if survey_started is None:
            await message.answer(
                "Не удалось найти информацию о пользователе в базе данных."
            )
            return

        # 3. Пользователь дал согласие, но ещё не начинал опрос.
        if not survey_started:
            await message.answer(
                INTRODUCTION_TEXT,
                reply_markup=start_survey_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # 4. Пользователь уже начинал опрос.
        # Проверяем, сохранилась ли его временная Redis-сессия.
        try:
            await registry.get_speaker_id(user_id)

        except SpeakerSessionExpired:
            await state.clear()

            await message.answer(
                "Ты уже прошёл опрос или время на его прохождение истекло. Повторное прохождение невозможно."
            )
            return

        # 5. Redis-сессия существует.
        # Дополнительно убеждаемся, что FSM действительно активна.
        current_state = await state.get_state()

        active_states = {
            SurveyStates.waiting_for_prompt_answer.state,
            SurveyStates.waiting_for_spontaneous_answer.state,
        }

        if current_state in active_states:
            await message.answer(
                "🎙 Опрос уже запущен.\n\n"
                "Продолжай с последнего выданного задания, отправив голосовое сообщение."
            )
            return

        # Redis-сессия осталась, но состояние опроса отсутствует.
        # Это не позволяет создать новую попытку или принять запись
        # без корректного состояния FSM.
        await state.clear()

        try:
            await registry.delete(user_id)
        except Exception:
            logger.exception(
                "Не удалось удалить неактивную Redis-сессию пользователя %s",
                user_id,
            )

        await message.answer(
            "Ты уже прошёл опрос или время на его прохождение истекло. Повторное прохождение невозможно."
        )

    # --------------------------------------------------
    # Отказ от согласия
    # --------------------------------------------------

    @router.callback_query(F.data == "consent:no")
    async def consent_no(cb: CallbackQuery) -> None:
        await cb.answer()

        if cb.message is not None:
            await cb.message.edit_text(
                "Хорошо, без согласия я ничего не записываю. "
                "Если передумаешь, нажми /start."
            )

    # --------------------------------------------------
    # Согласие на участие
    # --------------------------------------------------

    @router.callback_query(F.data == "consent:yes")
    async def consent_yes(cb: CallbackQuery) -> None:

        if cb.from_user is None:
            await cb.answer()
            return

        user_id = cb.from_user.id
        await cb.answer()

        if not await has_consent(user_id):
            await save_consent(
                user_id,
                "1.0",
                CONSENT_TEXT,
            )

            logger.info("consent granted: user %s", user_id)

        if cb.message is not None:
            await cb.message.edit_text(
                "Спасибо за предоставленное согласие!"
            )

        # Показываем вступление только тем, кто ещё не начинал опрос.
        survey_started = await get_user_survey_state(user_id)

        if survey_started is False:
            await cb.bot.send_message(
                user_id,
                INTRODUCTION_TEXT,
                reply_markup=start_survey_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await cb.bot.send_message(
                user_id,
                "Ты уже прошёл опрос или время на его прохождение истекло. Повторное прохождение невозможно.",
            )

    return router
