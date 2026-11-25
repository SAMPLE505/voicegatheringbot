from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Text, Boolean, Date, Integer
import datetime
from models.base import Base


class User(Base):
    """Реестр согласий. Содержит Telegram-ID, поэтому с записями (files) НЕ связан."""
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    consent_version: Mapped[str] = mapped_column(Text)  # версия текста согласия
    consent_sha256: Mapped[str] = mapped_column(Text)  # хэш текста: доказательство, с какой редакцией согласился
    consented_on: Mapped[datetime.date] = mapped_column(Date, default=datetime.date.today)  # только дата, без времени
    survey_started: Mapped[bool] = mapped_column(Boolean, default=False)  # True: пользователь начал опрос
    survey_finished: Mapped[bool] = mapped_column(Boolean, default=False)  # True: пользователь завершил опрос сам или он завершился по истечении TTL
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # False: заблокирован (антифрод)