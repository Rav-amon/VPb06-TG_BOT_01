"""Долгосрочная память диалога: SQLite и отдельная таблица на пользователя."""

import os
import re
import sqlite3
from datetime import datetime, timezone

# user_<id>: в имя таблицы попадает только числовой идентификатор Telegram.
_TABLE_NAME_PATTERN = re.compile(r'^user_\d+$')
_DEFAULT_DB_PATH = 'memory.db'


def get_db_path() -> str:
    """Возвращает путь к файлу базы. Читается при каждом обращении, уже после .env."""
    return os.getenv('MEMORY_DB_PATH', _DEFAULT_DB_PATH)


def table_name_for_user(user_id: int) -> str:
    """Собирает имя таблицы user_<id> и отбрасывает любые посторонние символы."""
    name = f'user_{int(user_id)}'
    if _TABLE_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError('Некорректный идентификатор пользователя')
    return name


def init_db() -> None:
    """Создаёт файл базы при запуске, если его ещё нет."""
    with sqlite3.connect(get_db_path()) as conn:
        # WAL позволяет читать тезисы, пока другая операция их дописывает.
        conn.execute('PRAGMA journal_mode=WAL')
        conn.commit()


def load_startup_context() -> dict[str, list[str]]:
    """При запуске читает уже сохранённые тезисы всех пользователей.

    Дальше каждый ответ заново берёт тезисы конкретного человека через SQL
    и кладёт их в его системный промпт.
    """
    context: dict[str, list[str]] = {}
    with sqlite3.connect(get_db_path()) as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name LIKE 'user_%'
            """
        ).fetchall()
        for (name,) in rows:
            if _TABLE_NAME_PATTERN.fullmatch(name) is None:
                continue
            theses = conn.execute(
                f'SELECT thesis FROM "{name}" ORDER BY id ASC'
            ).fetchall()
            context[name] = [row[0] for row in theses]
    return context


def ensure_user_table(user_id: int) -> str:
    """Создаёт таблицу пользователя при первом сообщении. Повторный вызов ничего не меняет."""
    name = table_name_for_user(user_id)
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute(
            f'''
            CREATE TABLE IF NOT EXISTS "{name}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.commit()
    return name


def read_theses(user_id: int) -> list[str]:
    """Читает тезисы из базы и не создаёт таблицу, если пользователь ещё ничего не писал."""
    name = table_name_for_user(user_id)
    with sqlite3.connect(get_db_path()) as conn:
        if not _table_exists(conn, name):
            return []
        rows = conn.execute(
            f'SELECT thesis FROM "{name}" ORDER BY id ASC'
        ).fetchall()
    return [row[0] for row in rows]


def get_theses(user_id: int) -> list[str]:
    """Создаёт таблицу при первом диалоге и возвращает тезисы для системного промпта."""
    ensure_user_table(user_id)
    return read_theses(user_id)


def clear_theses(user_id: int) -> int:
    """Принудительно стирает память: удаляет таблицу пользователя и возвращает число тезисов."""
    name = table_name_for_user(user_id)
    with sqlite3.connect(get_db_path()) as conn:
        if not _table_exists(conn, name):
            return 0
        count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        conn.execute(f'DROP TABLE "{name}"')
        conn.commit()
    return int(count)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Проверяет, что таблица пользователя уже есть в sqlite_master."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def save_theses(user_id: int, theses: list[str]) -> None:
    """Пишет тезисы текущего ответа новыми строками в таблицу user_<id>."""
    cleaned = [item.strip() for item in theses if item and item.strip()]
    name = ensure_user_table(user_id)
    if not cleaned:
        return

    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(get_db_path()) as conn:
        conn.executemany(
            f'INSERT INTO "{name}" (thesis, created_at) VALUES (?, ?)',
            [(item, created_at) for item in cleaned],
        )
        conn.commit()
