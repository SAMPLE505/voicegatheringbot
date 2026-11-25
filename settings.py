from dotenv import load_dotenv
from pathlib import Path
import os

# Определение пути к корню проекта
BASE_DIR = Path(__file__)


# Подгрузка основного .env
load_dotenv()


# Импорт переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
SYS_ADMIN = int(os.getenv("SYS_ADMIN"))
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT")