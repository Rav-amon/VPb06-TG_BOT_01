import sqlite3

DB_PATH = 'tasks.db'


def init_db() -> None:
    """Создаем файл базы данных и таблицу tasks, если они не существуют."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                user TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.commit()
