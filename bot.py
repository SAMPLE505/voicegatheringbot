"""bot.py: минимальный Telegram-бот для сбора голосовых сообщений.

Что умеет:
  1. /start    показывает текст согласия с кнопками «согласен / не согласен».
  2. После согласия выдаёт задания (фразы) по одной и принимает голосовые.
  3. /revoke   отзыв согласия: удаляет записи пользователя.

Хранение пока самое простое, обычные файлы (потом заменим):
  data/users/<telegram_id>/consent.json         факт согласия
  data/users/<telegram_id>/recordings/<id>.oga  оригиналы голосовых
  data/users/<telegram_id>/recordings.jsonl     по строке на запись

Запуск:
  pip install "aiogram>=3.13"
  BOT_TOKEN=123456:ABC... python bot.py
"""
import asyncio
import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

log = logging.getLogger("bot")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MIN_VOICE_SECONDS = 2  # более короткие записи не принимаем

# --------------------------------------------------------------------------- #
# Тексты. Всё, что видит пользователь, лежит здесь: правьте под себя.
# --------------------------------------------------------------------------- #
CONSENT_VERSION = "draft-0"
CONSENT_TEXT = """\
ЧЕРНОВИК согласия (заменить текстом, согласованным с юристом)

Я собираю голосовые записи для научного исследования методов обнаружения подмены голоса.

Что будет происходить:
• вы записываете голосовые сообщения по заданиям бота;
• я сохраняю записи и технические данные (длительность, время отправки);
• записи могут использоваться для создания синтетических копий голоса (преобразование голоса) для обучения и проверки детекторов.

Согласие можно отозвать в любой момент командой /revoke: записи будут удалены.
Участвовать могут только лица старше 18 лет."""

# Заглушка: позже заменим планировщиком заданий.
PROMPTS = [
    "Сегодня хорошая погода, и я решил прогуляться по набережной.",
    "Позвони мне, пожалуйста, завтра около трёх часов дня.",
    "Рыбак поймал большую рыбу и отпустил её обратно в реку.",
    "Номер моего заказа семьсот сорок восемь, доставка во вторник.",
    "Расскажите своими словами, как вы провели прошлые выходные.",
]

router = Router()
router.message.filter(F.chat.type == "private")  # работаем только в личке


# --------------------------------------------------------------------------- #
# Хранение (обычные файлы)
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_dir(user_id: int) -> Path:
    return DATA_DIR / "users" / str(user_id)


def load_consent(user_id: int) -> dict | None:
    path = user_dir(user_id) / "consent.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_consent(user_id: int, data: dict) -> None:
    folder = user_dir(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "consent.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def has_consent(user_id: int) -> bool:
    consent = load_consent(user_id)
    return consent is not None and "revoked_at" not in consent


def save_consent(user_id: int) -> None:
    write_consent(
        user_id,
        {
            "version": CONSENT_VERSION,
            "text_sha256": hashlib.sha256(CONSENT_TEXT.encode("utf-8")).hexdigest(),
            "agreed_at": now_iso(),
        },
    )


def revoke_consent(user_id: int) -> None:
    """Отзыв: удаляем записи пользователя, в согласии ставим отметку об отзыве."""
    folder = user_dir(user_id)
    shutil.rmtree(folder / "recordings", ignore_errors=True)
    (folder / "recordings.jsonl").unlink(missing_ok=True)
    consent = load_consent(user_id) or {}
    consent["revoked_at"] = now_iso()
    write_consent(user_id, consent)


def recordings_count(user_id: int) -> int:
    path = user_dir(user_id) / "recordings.jsonl"
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def save_recording_meta(user_id: int, record: dict) -> None:
    with (user_dir(user_id) / "recordings.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Сообщения и кнопки
# --------------------------------------------------------------------------- #
def prompt_text(n: int) -> str:
    """Текст задания номер n (с нуля) или финальное сообщение."""
    if n >= len(PROMPTS):
        return "Все задания выполнены, спасибо за участие!"
    return (
        f"Задание {n + 1} из {len(PROMPTS)}. "
        f"Запишите голосовое сообщение, прочитав вслух:\n\n«{PROMPTS[n]}»"
    )


def keyboard(yes_text: str, yes_data: str, no_text: str, no_data: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=yes_text, callback_data=yes_data),
                InlineKeyboardButton(text=no_text, callback_data=no_data),
            ]
        ]
    )


async def remove_keyboard(cb: CallbackQuery) -> None:
    """Убирает кнопки под сообщением, чтобы на них не жали повторно."""
    if isinstance(cb.message, Message):
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #
@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id
    if has_consent(user_id):
        await message.answer("Вы уже дали согласие, продолжаем.")
        await message.answer(prompt_text(recordings_count(user_id)))
        return
    await message.answer(
        CONSENT_TEXT,
        reply_markup=keyboard(
            "✅ Мне есть 18 лет, я согласен(на)", "consent:yes",
            "❌ Не согласен(на)", "consent:no",
        ),
    )


# --------------------------------------------------------------------------- #
# Нажатия кнопок
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "consent:yes")
async def consent_yes(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    await cb.answer()
    await remove_keyboard(cb)
    if not has_consent(user_id):
        save_consent(user_id)
        log.info("consent granted: user %s", user_id)
    await cb.bot.send_message(user_id, "Спасибо! Начинаем.")
    await cb.bot.send_message(user_id, prompt_text(recordings_count(user_id)))


@router.callback_query(F.data == "consent:no")
async def consent_no(cb: CallbackQuery) -> None:
    await cb.answer()
    await remove_keyboard(cb)
    await cb.bot.send_message(
        cb.from_user.id,
        "Хорошо, без согласия я ничего не записываю. Если передумаете, нажмите /start.",
    )



# --------------------------------------------------------------------------- #
# Приём голосовых сообщений
# --------------------------------------------------------------------------- #
@router.message(F.voice)
async def on_voice(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id

    if not has_consent(user_id):
        await message.answer("Сначала нужно ваше согласие: нажмите /start.")
        return
    if message.forward_origin is not None:
        await message.answer("Пересланные сообщения не подходят. Запишите голосовое сами.")
        return

    voice = message.voice
    if voice.duration < MIN_VOICE_SECONDS:
        await message.answer("Слишком короткая запись, попробуйте ещё раз.")
        return

    n = recordings_count(user_id)
    if n >= len(PROMPTS):
        await message.answer(prompt_text(n))
        return

    folder = user_dir(user_id) / "recordings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{message.message_id}.oga"  # оригинал сохраняем как есть
    try:
        await bot.download(voice, destination=path)
    except Exception:
        log.exception("download failed: user %s, message %s", user_id, message.message_id)
        await message.answer("Не удалось сохранить запись, попробуйте ещё раз.")
        return

    save_recording_meta(
        user_id,
        {
            "file": path.name,
            "prompt_index": n,
            "prompt_text": PROMPTS[n],
            "tg_message_id": message.message_id,
            "tg_date": message.date.isoformat(),
            "received_at": now_iso(),
            "duration_s": voice.duration,
            "file_size": voice.file_size,
            "mime_type": voice.mime_type,
            "file_unique_id": voice.file_unique_id,
        },
    )
    await message.answer("Записал, спасибо!")
    await message.answer(prompt_text(n + 1))


# --------------------------------------------------------------------------- #
# Всё остальное (текст, файлы, кружки...). Должен быть последним обработчиком.
# --------------------------------------------------------------------------- #
@router.message()
async def on_other(message: Message) -> None:
    user_id = message.from_user.id
    if not has_consent(user_id):
        await message.answer("Чтобы начать, нажмите /start.")
        return
    await message.answer(
        "Мне нужно голосовое сообщение: зажмите значок микрофона в Telegram. "
        "Аудиофайлы и видеокружки не подходят."
    )
    await message.answer(prompt_text(recordings_count(user_id)))


async def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Задайте переменную окружения BOT_TOKEN")
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())