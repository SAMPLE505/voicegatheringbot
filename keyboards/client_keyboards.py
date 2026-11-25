from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def consent_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Не согласен(на)", callback_data="consent:no"),
            InlineKeyboardButton(text="✅ Согласен(на)", callback_data="consent:yes")
        ]
    ])

def start_survey_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Начать опрос", callback_data="start_survey"),
        ]
    ])