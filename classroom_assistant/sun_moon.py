"""Схід і захід сонця та довгота дня: чисті обчислення без інтернету (для листочка календаря)."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

J2000 = 2451545.0


def _utc(jd: float) -> datetime:
    return datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=jd - J2000)


def sun_times(day: date, lat: float, lon: float):
    """Схід і захід у UTC та довгота дня (за алгоритмом «sunrise equation»). Полярний день/ніч — None."""
    n = math.ceil(day.toordinal() + 1721425.0 - J2000 + 0.0008)
    j_star = n - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = J2000 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    decl = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(decl)) / (math.cos(phi) * math.cos(decl))
    if abs(cos_w) > 1:
        return None
    w = math.degrees(math.acos(cos_w))
    rise, sunset = _utc(transit - w / 360.0), _utc(transit + w / 360.0)
    return rise, sunset, sunset - rise


def _last_sunday(year: int, month: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def ukraine_offset(moment_utc: datetime) -> timedelta:
    """Київ: UTC+2 узимку, UTC+3 від останньої неділі березня до останньої неділі жовтня (о 01:00 UTC)."""
    year = moment_utc.year
    start = datetime.combine(_last_sunday(year, 3), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(year, 10), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1)
    return timedelta(hours=3) if start <= moment_utc < end else timedelta(hours=2)


def local_text(moment_utc: datetime) -> str:
    local = moment_utc + ukraine_offset(moment_utc)
    return f"{local.hour:02d}:{local.minute:02d}"


def day_length_text(length: timedelta) -> str:
    minutes = int(round(length.total_seconds() / 60))
    return f"{minutes // 60}:{minutes % 60:02d}"


def sun_summary(day: date, lat: float, lon: float):
    """(схід, захід, довгота дня) як «07:14», «18:51», «11:37» за київським часом; None — полярний день/ніч."""
    times = sun_times(day, lat, lon)
    if not times:
        return None
    rise, sunset, length = times
    return local_text(rise), local_text(sunset), day_length_text(length)


def hm(moment_utc) -> str:
    """Час за київським часом у «календарному» записі: 7.12, 17.38 (без нуля попереду годин)."""
    if moment_utc is None:
        return "—"
    local = moment_utc + ukraine_offset(moment_utc)
    return f"{local.hour}.{local.minute:02d}"


def duration_parts(length: timedelta):
    """Тривалість як (години, хвилини)."""
    minutes = int(round(length.total_seconds() / 60))
    return minutes // 60, minutes % 60


def sun_card(day: date, lat: float, lon: float):
    """Дані про Сонце для листочка: схід, захід («7.12», «17.38»), години й хвилини дня. None — полярний день чи ніч."""
    times = sun_times(day, lat, lon)
    if not times:
        return None
    rise, sunset, length = times
    hours, mins = duration_parts(length)
    return {"sunrise": hm(rise), "sunset": hm(sunset), "hours": f"{hours} год.", "minutes": f"{mins:02d} хв."}
