import sqlite3
from datetime import datetime

from db.database import DB_PATH


def add_task(text: str, user: str) -> None:
    """Добавляем новую задачу в таблицу tasks."""
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO tasks (text, user, created_at) VALUES (?, ?, ?)',
                (text, user, created_at)
            )
            conn.commit()
    except sqlite3.Error as error:
        raise RuntimeError(f'Ошибка при сохранении задачи: {error}')


def get_tasks():
    """Получаем все задачи из таблицы tasks."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, text, user, created_at FROM tasks ORDER BY id')
            return cursor.fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f'Ошибка при чтении задач: {error}')
