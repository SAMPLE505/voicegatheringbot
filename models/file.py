from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Date, Integer, Uuid
import datetime
import uuid
from models.base import Base


class File(Base):
    """Обезличенная голосовая запись. Ссылок на users нет и быть не должно."""
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)  # случайный, не порядковый
    speaker_id: Mapped[str] = mapped_column(Text, index=True)  # HMAC(секрет, tg_id): объединяет записи одного человека
    file_path: Mapped[str] = mapped_column(Text)  # путь к .oga; в имени файла нет tg-данных
    sha256: Mapped[str] = mapped_column(Text, index=True)  # поиск дубликатов, контроль целостности
    duration_s: Mapped[int] = mapped_column(Integer)
    file_size: Mapped[int] = mapped_column(Integer)  # байты
    prompt_id: Mapped[int | None] = mapped_column(Integer)  # номер задания в банке; None для свободной речи
    prompt_text: Mapped[str | None] = mapped_column(Text)  # что именно читали (банк может измениться)
    prompt_type: Mapped[str | None] = mapped_column(Text)  # тип промпта (тип предложения или спонтанная речь)