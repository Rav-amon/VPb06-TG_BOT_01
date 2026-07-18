import csv
import os


def tasks_to_csv(tasks):
    """Сохраняем список задач в CSV-файл и возвращаем путь к файлу."""
    file_path = 'tasks.csv'
    try:
        with open(file_path, mode='w', encoding='utf-8', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(['id', 'text', 'user', 'created_at'])
            for task in tasks:
                writer.writerow(task)
        return file_path
    except OSError as error:
        raise RuntimeError(f'Ошибка при создании CSV-файла: {error}')
