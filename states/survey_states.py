from aiogram.fsm.state import State, StatesGroup


class SurveyStates(StatesGroup):
    """Состояния опроса. Сами значения хранятся через RedisStorage aiogram."""
    waiting_for_prompt_answer = State()
    waiting_for_spontaneous_answer = State()
