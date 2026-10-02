"""Розумне зіставлення класів і предметів: «10 ІУ» = 10 клас, Історія України.

Класи в Classroom і в розкладі часто записані по-різному: інша велика/мала літера,
латинська «I» замість української «І», довге тире, «Право + ГО» в одному курсі,
«5-Г історія» проти «5-Г ІУ». Тут усе приводиться до змісту: клас, літера, предмет,
рівень. Невпевнені збіги НЕ приймаються (повертається None), щоб не переплутати класи.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ACCEPT = 60

_HOMOGLYPHS = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "I": "І", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "i": "і", "k": "к", "m": "м",
    "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
})
PHRASES = (("історія україни", "IU"), ("всесвітня історія", "VI"),
           ("громадянська освіта", "GO"), ("основи правознавства", "LAW"),
           ("правознавство", "LAW"), ("громадянська", "GO"))
TOKENS = {"іу": "IU", "ві": "VI", "го": "GO", "право": "LAW", "історія": "HIST", "історії": "HIST"}
SUBJECT_NAMES = {"IU": "Історія України", "VI": "Всесвітня історія",
                 "GO": "Громадянська освіта", "LAW": "Правознавство", "HIST": "Історія"}


def norm(text) -> str:
    """Порівнювана форма: без регістру, латинських двійників, довгих тире й зайвих пробілів."""
    value = unicodedata.normalize("NFKC", str(text or "")).replace("’", "'").replace("ʼ", "'")
    value = value.translate(_HOMOGLYPHS)
    value = re.sub(r"[‐‑‒–—―−]", "-", value).casefold()
    value = re.sub(r"\s*([-+/,])\s*", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class Parsed:
    grade: int
    letter: str | None
    level: str | None
    subjects: frozenset


def parse(text) -> Parsed | None:
    value = norm(text)
    found = re.match(r"^(\d{1,2})(?:-([а-яіїєґ])(?![а-яіїєґ]))?\s*(.*)$", value)
    if not found:
        return None
    grade, letter, rest = int(found.group(1)), found.group(2), found.group(3)
    level = ("profile" if "профіл" in rest else "standard" if "стандарт" in rest else None)
    subjects = set()
    for phrase, code in PHRASES:
        if phrase in rest:
            subjects.add(code)
            rest = rest.replace(phrase, " ")
    for token in re.split(r"[+/,\s]+", rest):
        if token in TOKENS:
            subjects.add(TOKENS[token])
    return Parsed(grade, letter, level, frozenset(subjects))


def _expand(subjects):
    return (set(subjects) - {"HIST"}) | ({"IU", "VI"} if "HIST" in subjects else set())


def score(a, b) -> int:
    """0…100: наскільки назви означають той самий клас і предмет."""
    if not norm(a) or not norm(b):
        return 0
    if norm(a) == norm(b):
        return 100
    first, second = parse(a), parse(b)
    if not first or not second or first.grade != second.grade:
        return 0
    if first.letter and second.letter and first.letter != second.letter:
        return 0
    if first.level and second.level and first.level != second.level:
        return 0
    if not first.subjects or not second.subjects:
        return 0
    if first.subjects == second.subjects:
        value = 90
    elif first.subjects <= second.subjects:
        value = 80                    # «9-Б ГО» належить об'єднаному курсові «9-Б Право + ГО»
    elif _expand(first.subjects) & _expand(second.subjects) and "HIST" in first.subjects | second.subjects:
        value = 70                    # «5-Г історія» ≈ «5-Г ІУ»
    elif second.subjects <= first.subjects:
        value = 50
    else:
        return 0
    if bool(first.letter) != bool(second.letter):
        value -= 10
    if bool(first.level) != bool(second.level):
        value -= 10
    return max(0, value)


def best_match(name, candidates):
    """Єдиний найкращий кандидат (рядок) або None, якщо збігу немає чи він неоднозначний."""
    ranked = sorted(((score(name, c), c) for c in candidates), key=lambda x: -x[0])
    if not ranked or ranked[0][0] < ACCEPT:
        return None
    if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
        return None
    return ranked[0][1]


def assign_streams(streams: dict, courses) -> dict:
    """{потік: назва_курсу_Classroom | None}. streams: потік → налаштована назва курсу."""
    courses = list(courses)
    result = {}
    for stream, title in streams.items():
        best_by_name = best_match(stream, courses)
        best_by_title = best_match(title, courses) if title else None
        exact_title = next((c for c in courses if title and norm(c) == norm(title)), None)
        result[stream] = exact_title or best_by_title or best_by_name
    return result


def match_titles(titles, courses) -> dict:
    """{назва_курсу_в_налаштуваннях: курс_Classroom(dict з id, name)} — лише однозначні."""
    by_name = {}
    for course in courses:
        by_name.setdefault(course["name"], []).append(course)
    found = {}
    for title in titles:
        hit = best_match(title, list(by_name))
        if hit is not None and len(by_name[hit]) == 1:
            found[title] = by_name[hit][0]
    return found


def describe(name) -> str:
    parsed = parse(name)
    if not parsed:
        return str(name)
    subjects = ", ".join(SUBJECT_NAMES[s] for s in sorted(parsed.subjects)) or "?"
    return f"{parsed.grade} клас, {subjects}"
