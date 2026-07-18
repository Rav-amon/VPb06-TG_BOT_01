import logging

from aiogram import types
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile
from db.tasks import add_task, get_tasks
from bot.keyboards import main_keyboard
from utils.csv_export import tasks_to_csv

logger = logging.getLogger(__name__)

router = Router()

def text_equals(value: str):
    def _filter(message: types.Message) -> bool:
        return (message.text or '').strip() == value

    return _filter


def register_handlers(dp):
    """Регистрируем роутер с обработчиками в диспетчере."""
    dp.include_router(router)


@router.message(Command('start'))
async def start_command(message: types.Message):
    """Команда /start приветствует пользователя."""
    text = (
        'Привет! Я бот для командной работы.\n'
        'Используй /add для добавления задачи,\n'
        '/list для просмотра списка задач и\n'
        '/list_csv для получения файла CSV.'
    )
    await message.answer(text, reply_markup=main_keyboard())


@router.message(Command('add'))
async def add_command(message: types.Message):
    """Команда /add добавляет задачу в базу данных."""
    text = (message.text or '').strip()
    task_text = ''
    if text.startswith('/add'):
        task_text = text[4:].strip()

    if not task_text:
        await message.answer(
            'Пожалуйста, отправь /add и текст задачи, например:\n'
            '/add купить продукты'
        )
        return

    user_name = message.from_user.full_name if message.from_user else 'Unknown'
    try:
        add_task(text=task_text, user=user_name)
        await message.answer(f'Задача добавлена: {task_text}')
    except Exception:
        logger.exception('Ошибка при добавлении задачи')
        await message.answer('Произошла ошибка при добавлении задачи. Попробуйте позже.')


@router.message(Command('list'))
async def list_command(message: types.Message):
    """Команда /list показывает все задачи из базы данных."""
    try:
        tasks = get_tasks()
    except Exception:
        logger.exception('Ошибка при получении списка задач')
        await message.answer('Не удалось получить список задач. Попробуйте позже.')
        return

    if not tasks:
        await message.answer('Список задач пуст. Добавьте первую задачу через /add.')
        return

    lines = [f'{task[0]}. {task[1]} — {task[2]} ({task[3]})' for task in tasks]
    await message.answer('\n'.join(lines))


@router.message(Command('list_csv'))
async def list_csv_command(message: types.Message):
    """Команда /list_csv отправляет CSV-файл со списком задач."""
    try:
        tasks = get_tasks()
    except Exception:
        logger.exception('Ошибка при получении списка задач для CSV')
        await message.answer('Не удалось получить задачи для экспорта. Попробуйте позже.')
        return

    if not tasks:
        await message.answer('Список задач пуст. Нечего экспортировать.')
        return

    try:
        file_path = tasks_to_csv(tasks)
        await message.answer_document(FSInputFile(file_path, filename='tasks.csv'))
    except Exception:
        logger.exception('Ошибка при создании CSV-файла')
        await message.answer('Не удалось создать CSV-файл. Попробуйте позже.')


# Также регистрируем обработчики на обычный текст (ReplyKeyboard отправляет текст без entity)
router.message(text_equals('/start'))(start_command)
router.message(text_equals('/add'))(add_command)
router.message(text_equals('/list'))(list_command)
router.message(text_equals('/list_csv'))(list_csv_command)
