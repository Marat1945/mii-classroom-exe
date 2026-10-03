"""Розпізнає, до якого УРОКУ належить файл: «9-Б ВІ, Урок 05.10 — Тема» (назва файлу або перший рядок Word).

Клас + дата однозначно задають урок (одна й та сама тема в 8-Б, 8-В, 8-Г відрізняється саме класом).
Нічого не вгадує: якщо клас не названо, а на цю дату є кілька уроків, файл лишається нерозпізнаним.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .course_match import norm, score

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

NEW = re.compile(r"^\s*(?P<stream>.+?)\s*,\s*Урок\s*(?P<dd>\d{1,2})\.(?P<mm>\d{1,2})(?:\.\d{2,4})?"
                 r"\s*[—–\-:]\s*(?P<topic>.*?)\s*$", re.I)
OLD = re.compile(r"Урок\s*№\s*(?P<n>\d+)\s*,\s*(?P<dd>\d{1,2})\.(?P<mm>\d{1,2})\.\d{4}\s*(?P<topic>.*?)\s*$", re.I)
DATE_ONLY = re.compile(r"^\s*Урок\s*(?P<dd>\d{1,2})\.(?P<mm>\d{1,2})(?:\.\d{2,4})?\s*[—–\-:]\s*(?P<topic>.*?)\s*$", re.I)


@dataclass(frozen=True)
class Parsed:
    stream: str | None
    day: int
    month: int
    topic: str
    number: int | None = None


def kind_of(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return "word"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "other"


def clean_stem(name) -> str:
    stem = Path(str(name)).stem
    stem = re.sub(r"(?:\s*\(\d+\)|\s*-\s*копія|\s*—\s*копія)+\s*$", "", stem, flags=re.I)
    return stem.strip()


def parse_name(text) -> Parsed | None:
    value = str(text or "").strip()
    found = NEW.match(value)
    if found:
        return Parsed(found["stream"].strip(), int(found["dd"]), int(found["mm"]), found["topic"].strip(". "))
    found = OLD.search(value)
    if found:
        return Parsed(None, int(found["dd"]), int(found["mm"]), found["topic"].strip(". "), int(found["n"]))
    found = DATE_ONLY.match(value)
    if found:
        return Parsed(None, int(found["dd"]), int(found["mm"]), found["topic"].strip(". "))
    return None


def parse_file(path, first_line="") -> Parsed | None:
    """Назва файлу має перевагу; якщо вона не підходить (браузер перейменував) — перший рядок Word."""
    return parse_name(clean_stem(path)) or parse_name(first_line)


def first_line_of_docx(path) -> str:
    try:
        from docx import Document
        for paragraph in Document(path).paragraphs[:8]:
            if paragraph.text.strip():
                return paragraph.text.strip()
    except Exception:
        pass
    return ""


def _letters(text) -> str:
    """Лише букви й цифри: у назві файлу немає «?», «:», лапок, які можуть бути в темі."""
    return re.sub(r"[^0-9a-zа-яіїєґ]+", "", norm(text))[:40]


def _topic_agrees(lesson, parsed) -> bool:
    mine, theirs = _letters(lesson.topic), _letters(parsed.topic)
    return bool(mine and theirs and (mine.startswith(theirs[:24]) or theirs.startswith(mine[:24])))


def find_lesson(lessons, parsed):
    """Один урок або None. Усі уроки року передаються списком."""
    if not parsed:
        return None
    same_day = [x for x in lessons
                if int(x.day[5:7]) == parsed.month and int(x.day[8:10]) == parsed.day]
    if parsed.stream:
        pool = [x for x in same_day if norm(x.stream) == norm(parsed.stream)]
        if not pool:
            pool = [x for x in same_day if score(x.stream, parsed.stream) >= 90]
        if len(pool) > 1:                                  # подвійний урок: розрізняє тема
            pool = [x for x in pool if _topic_agrees(x, parsed)]
    else:                                                  # клас не названо — лише якщо тема однозначна
        pool = [x for x in same_day if _topic_agrees(x, parsed)]
        if parsed.number is not None:
            pool = [x for x in pool if x.lesson_number == parsed.number] or pool
    return pool[0] if len(pool) == 1 else None
