import logging
import os
import sys
import asyncio

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.utils.token import TokenValidationError
from db.database import init_db
from bot.handlers import register_handlers

load_dotenv()

# Эта переменная нужна для токена Telegram бота.
# Перед запуском установите TELEGRAM_BOT_TOKEN в переменной окружения
# или добавьте его в файл .env
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if TOKEN:
    TOKEN = TOKEN.strip().strip('"').strip("'")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)


async def main():
    """Точка входа в приложение (async для aiogram v3)."""
    token = TOKEN
    if token:
        token = token.strip()

    if not token or ':' not in token:
        # Попробовать интерактивно попросить токен у пользователя (если терминал доступен)
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                user_input = input('TELEGRAM_BOT_TOKEN не найден. Введите токен: ').strip()
            except Exception:
                logging.error('TELEGRAM_BOT_TOKEN отсутствует и ввод недоступен. Установите токен в .env или переменных окружения.')
                sys.exit(1)

            if not user_input or ':' not in user_input:
                logging.error('Введён некорректный токен. Убедитесь, что токен имеет формат <id>:<token>')
                sys.exit(1)

            token = user_input
        else:
            logging.error('TELEGRAM_BOT_TOKEN отсутствует или имеет неверный формат. Установите корректный токен в .env или переменных окружения.')
            sys.exit(1)

    # Инициализация бота и диспетчера aiogram.
    try:
        bot = Bot(token=token)
    except TokenValidationError:
        logging.error('Неверный TELEGRAM_BOT_TOKEN. Проверьте токен в .env или в переменных окружения.')
        sys.exit(1)
    except Exception:
        logging.exception('Ошибка при инициализации бота')
        sys.exit(1)

    dp = Dispatcher()

    # Создаем базу данных, если ее еще нет.
    try:
        init_db()
    except Exception:
        logging.exception('Ошибка инициализации базы данных')
        raise

    # Регистрируем обработчики команд и сообщений.
    register_handlers(dp)

    # Запускаем бота с использованием start_polling (aiogram v3).
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception:
        logging.exception('Ошибка запуска бота')
        raise
    finally:
        # Закрываем сессию бота корректно.
        try:
            await bot.session.close()
        except Exception:
            logging.exception('Ошибка при закрытии сессии бота')


if __name__ == '__main__':
    asyncio.run(main())
