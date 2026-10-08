"""Який урок іде зараз і який ось-ось почнеться: за годинником комп'ютера й часом уроків у розкладі.

Нічого не прив'язано до конкретного розкладу: беруться «початок» і «кінець» кожного уроку, тож працює для будь-яких
дзвінків і будь-якого розкладу. Підсвічується лише поточний день.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

LEAD_MINUTES = 10                                          # дзвіночок з'являється за стільки хвилин до уроку
BELL, NOW = "bell", "now"
_TIME = re.compile(r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$")


def parse_hm(text) -> time | None:
    """«08:30», «8:30», «8.30» → time; сміття → None."""
    found = _TIME.match(str(text or ""))
    if not found:
        return None
    hours, minutes = int(found.group(1)), int(found.group(2))
    return time(hours, minutes) if hours < 24 and minutes < 60 else None


def lesson_phase(now: datetime, day: date, begin, end, lead: int = LEAD_MINUTES):
    """'bell' — за lead хвилин до початку; 'now' — урок іде; None — інакше (або це не сьогоднішній день)."""
    if now.date() != day:
        return None
    start_t, end_t = parse_hm(begin), parse_hm(end)
    if not start_t or not end_t or end_t <= start_t:
        return None
    start, finish = datetime.combine(day, start_t), datetime.combine(day, end_t)
    if start - timedelta(minutes=lead) <= now < start:
        return BELL
    if start <= now < finish:
        return NOW
    return None


def phases(rows, day: date, now: datetime, lead: int = LEAD_MINUTES) -> dict:
    """{номер рядка таблиці (рядком): 'bell' | 'now'} для рядків, що зараз мають позначку."""
    result = {}
    for k, row in enumerate(rows):
        phase = lesson_phase(now, day, getattr(row, "begin", ""), getattr(row, "end", ""), lead)
        if phase:
            result[str(k)] = phase
    return result
