"""Автоматичне читання файлу КТП та визначення, чи це КТП, чи розклад (без вікон і запитань)."""
from __future__ import annotations

from pathlib import Path

from .course_match import norm
from .editor_core import csv_rows, docx_table_rows, extract_lessons, guess_columns, import_source_dates

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
TABLE_SUFFIXES = {".docx", ".doc", ".csv", ".xlsx"}


def classify_file(path) -> str:
    """'ktp' | 'schedule' | 'image' | 'unsupported'. Зміст має перевагу над назвою."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix not in TABLE_SUFFIXES:
        return "unsupported"
    name = norm(path.stem)
    if suffix != ".doc":                           # .doc читається через Word — повільно, тому лише за назвою
        try:
            from .schedule_io import table_rows
            for row in table_rows(path)[:6]:
                low = " ".join(str(cell) for cell in row).casefold()
                if "понеділок" in low and "вівторок" in low:
                    return "schedule"
        except Exception:
            pass
    if "навантаження" in name or ("розклад" in name and "календар" not in name):
        return "schedule"
    return "schedule" if suffix == ".xlsx" else "ktp"


def load_ktp(path, academic_start: int) -> list:
    """Рядки таблиці → уроки з датами за класами. ValueError — якщо таблиці немає."""
    path = Path(path)
    rows = docx_table_rows(path) if path.suffix.lower() in (".docx", ".doc") else csv_rows(path)
    if max((len(row) for row in rows), default=0) < 2:
        raise ValueError("не знайдено таблицю зі стовпцями тем і домашніх завдань")
    sample = next((r for r in rows[:8]
                   if any("тема" in c.casefold() or "зміст" in c.casefold() for c in r)), rows[0])
    topic, homework, number = guess_columns(sample)
    lessons = extract_lessons(rows, topic, homework, number, True)
    lessons = import_source_dates(rows, lessons, topic, number, academic_start=academic_start)
    for index, row in enumerate(lessons, 1):
        row["index"] = index
    return lessons
