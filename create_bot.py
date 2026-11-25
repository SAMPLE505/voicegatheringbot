from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from datetime import timedelta
from settings import BOT_TOKEN


redis = Redis(host="redis", port=6379, db=0, decode_responses=False,)
redis_storage = RedisStorage(redis=redis, state_ttl=timedelta(hours=24), data_ttl=timedelta(hours=24),)

# инициализируем бота и диспетчера для работы с ним
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=redis_storage)