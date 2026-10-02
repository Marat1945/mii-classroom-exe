"""Визначає за файлом КТП, для якого він класу й предмета: назва файлу, шапка, класи в датах.

Мета — щоб вчитель не мусив вручну «підбирати» КТП: програма сама бачить, що файл
«Календарне_ВІ_9-Б_9-Г…» — це Всесвітня історія для 9-Б та 9-Г, і не дасть вкласти його в «9-Б ІУ».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .course_match import SUBJECT_NAMES, _expand, norm, parse

PHRASES = (("історія україни", "IU"), ("всесвітня історія", "VI"), ("громадянська освіта", "GO"),
           ("основи правознавства", "LAW"), ("правознавство", "LAW"), ("громадянська", "GO"))
TOKENS = {"іу": "IU", "ві": "VI", "го": "GO", "право": "LAW"}


@dataclass(frozen=True)
class Detection:
    grade: int | None = None
    subjects: frozenset = frozenset()
    level: str | None = None
    classes: frozenset = frozenset()        # {"9-б", "9-г"}

    @property
    def known(self) -> bool:
        return self.grade is not None and bool(self.subjects)

    def describe(self) -> str:
        if self.grade is None:
            return "клас не визначено"
        parts = [f"{self.grade} клас"]
        if self.subjects:
            parts.append(", ".join(SUBJECT_NAMES[s] for s in sorted(self.subjects)))
        if self.level:
            parts.append("профільний рівень" if self.level == "profile" else "стандартний рівень")
        if self.classes:
            parts.append("класи " + ", ".join(sorted(c.upper() for c in self.classes)))
        return "; ".join(parts)


def _find_grade(text):
    found = re.search(r"(?<![\d.,])(\d{1,2})\s*[-_ ]?\s*клас", text)
    if found and 5 <= int(found.group(1)) <= 11:
        return int(found.group(1))
    for token in re.finditer(r"(?<![\d.,])(\d{1,2})(?!\d)", text):
        if 5 <= int(token.group(1)) <= 11:
            return int(token.group(1))
    return None


def _find_subjects(text):
    found, rest = set(), text
    for phrase, code in PHRASES:
        if phrase in rest:
            found.add(code)
            rest = rest.replace(phrase, " ")
    tokens = re.split(r"[^а-яіїєґa-z0-9]+", rest)
    for token in tokens:
        if token in TOKENS:
            found.add(TOKENS[token])
    if not found and "історія" in tokens:
        found.add("HIST")
    return found


def _find_level(text):
    if "профіл" in text:
        return "profile"
    if "стандарт" in text:
        return "standard"
    if re.search(r"(?<![\d.,])3\s*год", text):
        return "profile"
    if re.search(r"1[,.]5\s*год", text):
        return "standard"
    return None


def header_text(path) -> str:
    """Перші абзаци Word-файлу (назва документа), якщо вони є."""
    path = Path(path)
    if path.suffix.lower() != ".docx":
        return ""
    try:
        from docx import Document
        return " ".join(p.text for p in Document(path).paragraphs[:12] if p.text.strip())
    except Exception:
        return ""


def detect(filename, header="", entries=None) -> Detection:
    name = norm(Path(str(filename)).stem)
    head = norm(header)
    grade = _find_grade(name) or _find_grade(head)
    subjects = _find_subjects(name) or _find_subjects(head)
    level = _find_level(name) or _find_level(head)
    classes = set()
    for text in (name, head):
        for token in re.finditer(r"(?<![\d.,])(\d{1,2})\s*-\s*([а-яіїєґ])(?![а-яіїєґ])", text):
            if 5 <= int(token.group(1)) <= 11:
                classes.add(f"{int(token.group(1))}-{token.group(2)}")
    for row in entries or []:
        for key in (row.get("source_dates") or {}):
            parsed = re.match(r"^(\d{1,2})\s*-\s*([а-яіїєґ])$", norm(key))
            if parsed:
                classes.add(f"{int(parsed.group(1))}-{parsed.group(2)}")
    if grade is None and classes:
        grade = int(sorted(classes)[0].split("-")[0])
    return Detection(grade, frozenset(subjects), level, frozenset(classes))


def targets(detection: Detection, streams) -> list:
    """Потоки програми, яким підходить цей файл (клас + предмет + рівень + літери класів у датах)."""
    if detection.grade is None:
        return []
    wanted = _expand(detection.subjects) if detection.subjects else set()
    result = []
    for stream in streams:
        parsed = parse(stream)
        if not parsed or parsed.grade != detection.grade:
            continue
        if wanted and not (_expand(parsed.subjects) & wanted):
            continue
        if detection.level and parsed.level and detection.level != parsed.level:
            continue
        if detection.classes and parsed.letter and f"{parsed.grade}-{parsed.letter}" not in detection.classes:
            continue
        result.append(stream)
    if not detection.subjects and len({frozenset(parse(s).subjects) for s in result}) > 1:
        return []
    return sorted(result)


def level_conflict(streams) -> bool:
    """Серед кандидатів і профільні, і стандартні — файл сам не скаже, який саме."""
    return len({parse(s).level for s in streams} - {None}) > 1
