"""Порожня, але робоча конфігурація (без класів, розкладу, КТП)."""
from __future__ import annotations

import copy
from datetime import date, timedelta

BELLS = [["08:30", "09:15"], ["09:30", "10:15"], ["10:30", "11:15"], ["11:35", "12:20"],
         ["12:40", "13:25"], ["13:30", "14:15"], ["14:20", "15:05"], ["15:10", "15:55"]]


def blank_config(today: date | None = None, keep: dict | None = None) -> dict:
    today = today or date.today()
    first_year = today.year if today.month >= 7 else today.year - 1
    start = date(first_year, 9, 1)
    end = date(first_year + 1, 5, 31)
    anchor = start - timedelta(days=start.weekday())
    config = {
        "year_start": start.isoformat(), "year_end": end.isoformat(),
        "anchor_monday": anchor.isoformat(), "anchor_phase": "чисельник",
        "holidays": [], "period_times": copy.deepcopy(BELLS),
        "days": {str(day): [[None, None] for _ in BELLS] for day in range(5)},
        "course_map": {}, "classroom_course_titles": [], "google_course_ids": {},
        "video_links": {}, "ai_model": "gpt-5",
        "meal_break_after": 2, "meal_label": "ХАРЧУВАННЯ У ЇДАЛЬНІ",
        "print_bells": True, "print_meal": True, "print_numbers": True,
    }
    if keep and "ai_model" in keep:
        config["ai_model"] = keep["ai_model"]
    return config
