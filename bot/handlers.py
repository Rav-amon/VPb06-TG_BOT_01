"""Обработчики Telegram: диалог с нейросетью и запись тезисов в SQLite."""

import asyncio
import json
import logging

from aiogram import Bot, F, Router, types
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import BotCommand

from bot.neural import NeuralApiError, generate_reply
from db.database import clear_theses, get_theses, read_theses, save_theses

logger = logging.getLogger(__name__)

router = Router()

# Лимит одного сообщения Telegram. Более длинный ответ уходит несколькими частями.
TELEGRAM_MESSAGE_LIMIT = 4096


def register_handlers(dp) -> None:
    """Подключает роутер с обработчиками к диспетчеру."""
    dp.include_router(router)


async def setup_bot_commands(bot: Bot) -> None:
    """Показывает слэш-команды в меню Telegram."""
    commands = [
        BotCommand(command='start', description='Подсказка по боту'),
        BotCommand(command='theses', description='Тезисы из базы данных'),
        BotCommand(command='reset', description='Очистить память диалога'),
    ]
    await bot.set_my_commands(commands)


def split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Делит длинный ответ на части, не изменяя исходную строку."""
    if len(text) <= limit:
        return [text]
    return [text[index:index + limit] for index in range(0, len(text), limit)]


def format_theses(theses: list[str]) -> str:
    """Собирает текст списка тезисов для чата. Исходный список не меняет."""
    if not theses:
        return 'В базе данных тезисов пока нет.'
    lines = [f'{index}. {item}' for index, item in enumerate(theses, start=1)]
    return 'Тезисы из базы данных:\n' + '\n'.join(lines)


@router.message(Command('start'))
async def start_command(message: types.Message) -> None:
    """Команда /start объясняет, что диалог переживает перезапуск бота."""
    text = (
        'Привет! Я бот с долгосрочной памятью.\n'
        'Напишите сообщение — я отвечу и сохраню тезисы диалога.\n'
        '/theses — показать тезисы из базы данных\n'
        '/reset — стереть память и начать разговор заново\n'
        'После перезапуска сохранённые тезисы снова попадут в системный промпт.'
    )
    await message.answer(text)


@router.message(Command('theses'))
async def theses_command(message: types.Message) -> None:
    """Показывает тезисы этого пользователя прямо из SQLite."""
    user = message.from_user
    if user is None:
        await message.answer('Не удалось определить пользователя.')
        return

    try:
        theses = await asyncio.to_thread(read_theses, user.id)
    except Exception:
        logger.exception('Ошибка чтения тезисов')
        await message.answer('Не удалось прочитать тезисы из базы. Попробуйте ещё раз.')
        return

    await _send_text(message, format_theses(theses))


@router.message(Command('reset'))
async def reset_command(message: types.Message) -> None:
    """Удаляет таблицу пользователя и обнуляет контекст для следующих ответов."""
    user = message.from_user
    if user is None:
        await message.answer('Не удалось определить пользователя.')
        return

    try:
        removed = await asyncio.to_thread(clear_theses, user.id)
    except Exception:
        logger.exception('Ошибка очистки памяти')
        await message.answer('Не удалось очистить память. Попробуйте ещё раз.')
        return

    if removed == 0:
        await message.answer('Память уже пуста. Контекст сброшен.')
        return

    await message.answer(
        f'Память очищена. Удалено тезисов: {removed}. '
        'Следующий ответ пойдёт без прошлого контекста.'
    )


@router.message(F.text)
async def dialogue_message(message: types.Message) -> None:
    """Берёт тезисы пользователя из базы, отвечает и дописывает новые тезисы."""
    user = message.from_user
    if user is None:
        await message.answer('Не удалось определить пользователя.')
        return

    user_text = (message.text or '').strip()
    if not user_text:
        return
    if user_text.startswith('/'):
        await message.answer(
            'Напишите сообщение обычным текстом. '
            'Команды: /start, /theses и /reset.'
        )
        return

    user_id = user.id
    try:
        # На первом сообщении здесь же создаётся таблица user_<id>.
        saved_theses = await asyncio.to_thread(get_theses, user_id)
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        theses, answer = await generate_reply(saved_theses, user_text)
    except NeuralApiError as error:
        logger.error('Ошибка API нейросети: %s', error)
        if error.status == 401:
            await message.answer(
                'Ключ OPENAI_API_KEY отклонён сервисом. '
                'Вставьте действующий ключ в .env и перезапустите бота.'
            )
            return
        await message.answer('Нейросеть вернула ошибку. Подробности есть в консоли.')
        return
    except Exception:
        logger.exception('Ошибка при генерации ответа')
        await message.answer(
            'Не получилось получить ответ. Проверьте OPENAI_API_KEY и попробуйте ещё раз.'
        )
        return

    # В чат уходит только message. Список тезисов остаётся в консоли.
    logger.info('Тезисы: %s', json.dumps(theses, ensure_ascii=False))

    try:
        await asyncio.to_thread(save_theses, user_id, theses)
    except Exception:
        logger.exception('Ошибка записи тезисов в базу')
        await _send_text(message, answer)
        await message.answer(
            'Ответ отправлен, но тезисы этого хода не удалось записать в базу.'
        )
        return

    await _send_text(message, answer)


@router.message()
async def unsupported_message(message: types.Message) -> None:
    """Говорит, что стикеры, фото и прочие вложения бот не разбирает."""
    await message.answer('Я понимаю только текстовые сообщения.')


async def _send_text(message: types.Message, text: str) -> None:
    """Отправляет текст ответа частями, если он длиннее лимита Telegram."""
    for chunk in split_for_telegram(text):
        await message.answer(chunk)
