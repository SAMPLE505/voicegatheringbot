
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from db.user_crud import (
    has_consent,
    get_user_survey_state,
    change_user_survey_state,
)
from services.prompts import get_random_prompts, get_random_sponatanteous

from services.recordings_processing import (
    save_voice_recording,
    DuplicateRecordingError,
)
from services.speaker_registry import (
    SpeakerRegistry,
    SpeakerSessionExpired,
    SpeakerSessionAlreadyExists,
)
from states.survey_states import SurveyStates


logger = logging.getLogger(__name__)

SURVEY_SIZE = 25
TOTAL_TASKS = SURVEY_SIZE + 1


def render_current_task(data: dict, task_number: int) -> str:
    """Формирует текст текущего задания."""

    if data["current_mode"] == "prompt":
        prompt = data["prompts"][data["prompt_index"]]

        return (
            f"🎙 Задание {task_number}/{TOTAL_TASKS}\n\n"
            "Прочитай предложение естественным голосом, "
            "в обычном темпе. Отправь запись одним голосовым сообщением.\n\n"
            f"«{prompt['text']}»"
        )

    task = data["spontaneous_task"]

    return (
        f"🎙 Задание {task_number}/{TOTAL_TASKS} — спонтанная речь\n\n"
        "Не читай готовый текст — ответь своими словами. Говори естественно, так будто рассказываешь это другу.\n\n"
        "Не называй своё имя, адрес, телефон и другие личные данные.\n\n"
        f"Задание: {task['text']}"
    )


async def send_current_task(
    message: Message,
    state: FSMContext,
    registry: SpeakerRegistry,
    user_id: int,
) -> None:
    """Выдаёт следующее задание и увеличивает счётчик."""

    data = await state.get_data()

    # Счётчик хранится в Redis вместе со speaker_id.
    task_number = await registry.increment_tasks_issued(user_id)

    task_text = render_current_task(data, task_number)

    await message.answer(task_text)


def create_survey_router(redis: Redis) -> Router:
    router = Router(name="survey")

    registry = SpeakerRegistry(
        redis=redis,
        ttl_seconds=24 * 60 * 60,
    )

    # ---------------------------------------------------------
    # Запуск опроса
    # ---------------------------------------------------------

    @router.callback_query(F.data == "start_survey")
    async def start_survey(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:

        await callback.answer()

        if callback.from_user is None:
            return

        user_id = callback.from_user.id

        if callback.message is None or not isinstance(
            callback.message, Message
        ):
            return

        if callback.message.chat.type != ChatType.PRIVATE:
            await callback.message.answer(
                "Опрос можно пройти только в личном чате с ботом."
            )
            return

        if not await has_consent(user_id):
            await callback.message.answer(
                "Сначала необходимо дать согласие через команду /start."
            )
            return

        # Защита от двойного нажатия кнопки и параллельного запуска.
        async with redis.lock(
            f"survey:lock:start:{user_id}",
            timeout=30,
            blocking_timeout=10,
        ):
            survey_started = await get_user_survey_state(user_id)

            if survey_started is None:
                await callback.message.answer(
                    "Не удалось найти пользователя в базе данных."
                )
                return

            if survey_started:
                await callback.message.answer(
                    "Ты уже начинал опрос. Повторное прохождение невозможно."
                )
                return

            selected_prompts = get_random_prompts(SURVEY_SIZE)
            spontaneous_task = get_random_sponatanteous()

            # Создаём временную связь Telegram ID -> speaker_id.
            try:
                await registry.create_new(user_id)
            except SpeakerSessionAlreadyExists:
                await callback.message.answer(
                    "Для этого аккаунта уже существует активная сессия."
                )
                return

            # Фиксируем факт начала в PostgreSQL.
            if not await change_user_survey_state(user_id):
                await registry.delete(user_id)
                await callback.message.answer(
                    "Не удалось зарегистрировать начало опроса."
                )
                return

            try:
                await state.set_data(
                    {
                        "survey_active": True,
                        "prompts": selected_prompts,
                        "prompt_index": 0,
                        "spontaneous_task": spontaneous_task,
                        "current_mode": "prompt",
                    }
                )

                await state.set_state(
                    SurveyStates.waiting_for_prompt_answer
                )

            except Exception:
                logger.exception("Не удалось инициализировать FSM")
                await registry.delete(user_id)
                await state.clear()
                raise

        try:
            await callback.message.edit_text(
                "✅ Опрос начат. Отправляй голосовые сообщения по очереди, ожидая следующего задания."
            )
        except TelegramBadRequest:
            pass

        await send_current_task(
            callback.message,
            state,
            registry,
            user_id,
        )

    # ---------------------------------------------------------
    # Приём голосовых сообщений
    # ---------------------------------------------------------

    @router.message(
        SurveyStates.waiting_for_prompt_answer,
        F.voice,
    )
    @router.message(
        SurveyStates.waiting_for_spontaneous_answer,
        F.voice,
    )
    async def handle_voice_message(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:

        if message.from_user is None or message.voice is None:
            return

        user_id = message.from_user.id

        # Защита от одновременной обработки двух записей участника.
        async with redis.lock(
            f"survey:lock:record:{user_id}",
            timeout=120,
            blocking_timeout=10,
        ):
            current_state = await state.get_state()
            data = await state.get_data()

            if not data.get("survey_active"):
                await state.clear()
                await message.answer(
                    "Активная сессия опроса не найдена."
                )
                return

            # Проверяем, существует ли временная связь в Redis.
            try:
                speaker_id = await registry.get_speaker_id(user_id)

            except SpeakerSessionExpired:
                await state.clear()
                await message.answer(
                    "⏰ Время на прохождение опроса истекло. Повторное прохождение невозможно."
                )
                return

            # Определяем текущее задание.
            if current_state == SurveyStates.waiting_for_prompt_answer.state:
                mode = "prompt"

                index = int(data["prompt_index"])
                prompts = data["prompts"]

                if not 0 <= index < len(prompts):
                    await message.answer(
                        "Не удалось определить текущее задание."
                    )
                    return

                prompt = prompts[index]

            elif (
                current_state
                == SurveyStates.waiting_for_spontaneous_answer.state
            ):
                mode = "spontaneous"
                prompt = data["spontaneous_task"]

            else:
                await message.answer(
                    "Сейчас бот не ожидает голосовую запись."
                )
                return

            # Скачиваем аудио, проверяем SHA-256 и сохраняем его.
            try:
                await save_voice_recording(
                    bot=bot,
                    voice=message.voice,
                    speaker_id=speaker_id,
                    prompt=prompt,
                )

            except DuplicateRecordingError:
                await message.answer(
                    "Эта запись уже присутствует в датасете. "
                    "Пожалуйста, запиши задание ещё раз."
                )
                return

            except Exception:
                logger.exception(
                    "Ошибка сохранения аудиозаписи участника"
                )
                await message.answer(
                    "Не удалось сохранить запись. Текущее задание не изменилось. Попробуй отправить голосовое сообщение ещё раз."
                )
                return

            # Переходим к следующему текстовому заданию.
            if mode == "prompt":
                next_index = index + 1

                if next_index < len(data["prompts"]):
                    await state.update_data(
                        prompt_index=next_index
                    )

                    await send_current_task(
                        message,
                        state,
                        registry,
                        user_id,
                    )
                    return

                # Все 25 предложений прочитаны.
                await state.update_data(
                    current_mode="spontaneous"
                )

                await state.set_state(
                    SurveyStates.waiting_for_spontaneous_answer
                )

                await send_current_task(
                    message,
                    state,
                    registry,
                    user_id,
                )
                return

            # Последнее задание — спонтанная речь.
            try:
                await registry.delete(user_id)
            except Exception:
                logger.exception(
                    "Не удалось немедленно удалить сессию Redis"
                )
            finally:
                await state.clear()

            await message.answer(
                "✅ Спасибо за участие в опросе! Все записи сохранены. Повторное прохождение невозможно."
            )

    # ---------------------------------------------------------
    # Отклонение сообщений, не являющихся голосовыми
    # ---------------------------------------------------------

    @router.message(
        SurveyStates.waiting_for_prompt_answer,
        ~F.voice,
    )
    @router.message(
        SurveyStates.waiting_for_spontaneous_answer,
        ~F.voice,
    )
    async def reject_non_voice(message: Message) -> None:
        await message.answer(
            "Для текущего задания необходимо отправить именно голосовое сообщение, записанное в Telegram."
        )

    # ---------------------------------------------------------
    # Голосовое сообщение вне активного опроса
    # ---------------------------------------------------------

    @router.message(F.voice)
    async def voice_without_survey(
        message: Message,
        state: FSMContext,
    ) -> None:

        if message.from_user is None:
            return

        user_id = message.from_user.id

        survey_started = await get_user_survey_state(user_id)

        if survey_started is True:
            await message.answer(
                "Я не могу обработать твоё голосовое сообщение. Возможно, срок прохождения опроса истёк или ты завершил его, ответив на все задания. Повторное прохождение невозможно."
            )
        else:
            await message.answer(
                "Чтобы принять участие в исследовании, сначала дай согласие и нажми кнопку «Начать опрос»."
            )

    return router
