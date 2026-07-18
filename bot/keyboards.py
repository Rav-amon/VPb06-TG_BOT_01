from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_keyboard() -> ReplyKeyboardMarkup:
    """Создаем простую клавиатуру для пользователя."""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('/start'))
    keyboard.add(KeyboardButton('/add'))
    keyboard.add(KeyboardButton('/list'))
    keyboard.add(KeyboardButton('/list_csv'))
    return keyboard
