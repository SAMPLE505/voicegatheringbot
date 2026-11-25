from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


# сделать команду 


def sys_admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
        KeyboardButton(text="/status"),
        KeyboardButton(text="/delete_admin"),
        ],
            [
        KeyboardButton(text="/send_all"),
        KeyboardButton(text="/send_schedule")
        ],
            [
        KeyboardButton(text="/cancel"),
        ]
        ], 
        resize_keyboard=True,
        input_field_placeholder="Выбери команду"
    )


def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
        KeyboardButton(text="/send_all"),
        KeyboardButton(text="/send_schedule")
        ],
            [
        KeyboardButton(text="/status"),
        ],
            [
            KeyboardButton(text="/cancel"),
        ]],
        resize_keyboard=True,
        input_field_placeholder="Выбери команду"
    )


def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да ✅", callback_data="confirm_yes"),
            InlineKeyboardButton(text="Нет ❌", callback_data="confirm_no")
        ]
    ])

def confirm_new_admin(user_id: int, username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да ✅", callback_data=f"confirm_admin:{user_id}:{username}"),
            InlineKeyboardButton(text="Нет ❌", callback_data=f"deny_admin:{user_id}:{username}")
        ]
    ])