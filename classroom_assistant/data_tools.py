"""Копія, очищення («порожня програма») та відновлення даних учителя.

Нічого не видаляється без повної копії у ZIP, яку вчитель зберігає сам.
Паролі, токени й OAuth-файли Google ніколи не копіюються й не стираються.
"""
from __future__ import annotations

import copy
import json
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

from .engine import DATA, ROOT

SKIP_DIRS = {".git", ".github", "classroom_assistant", "tests", "__pycache__", "build", "dist",
             "venv", ".venv", ".pytest_cache"}
SECRET_NAMES = {"google_credentials.json", "credentials.json", "token.json"}
# Що вважається «даними вчителя» і очищується разом із розкладом та КТП.
WIPE_DIRS = ("Готові Word", "Вкладення Classroom", "Бібліотека уроків")
RESTORE_DIRS = WIPE_DIRS + ("data", "Архів навчальних даних", "КТП джерела")
BELLS = [["08:30", "09:15"], ["09:30", "10:15"], ["10:30", "11:15"], ["11:35", "12:20"],
         ["12:40", "13:25"], ["13:30", "14:15"], ["14:20", "15:05"], ["15:10", "15:55"]]


def is_secret(path: Path) -> bool:
    name = path.name.casefold()
    return name in SECRET_NAMES or "token" in name or name.endswith((".pem", ".key", ".env"))


def data_files(root: Path = ROOT):
    """Усі робочі дані програми (КТП, розклад, Word, вкладення), без паролів і токенів."""
    for item in sorted(root.iterdir()):
        if item.name in SKIP_DIRS or item.name.startswith("."):
            continue
        if item.is_dir():
            for path in sorted(item.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and not is_secret(path):
                    yield path
        elif item.is_file() and item.suffix.casefold() in (".json", ".docx", ".txt", ".md") \
                and not is_secret(item):
            yield item


def export_all_data(destination, root: Path = ROOT) -> int:
    count = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in data_files(root):
            archive.write(path, path.relative_to(root).as_posix())
            count += 1
    return count


def blank_config(today: date | None = None, keep: dict | None = None) -> dict:
    """Порожня, але робоча конфігурація: без класів, розкладу, канікул і КТП."""
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
    for name in ("ai_model",):
        if keep and name in keep:
            config[name] = keep[name]
    return config


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_to_blank(backup_zip, root: Path = ROOT, data_dir: Path | None = None) -> int:
    """Спершу повна копія у ZIP; потім порожні розклад, КТП, стан, Word і вкладення."""
    data_dir = data_dir or (root / "data")
    count = export_all_data(backup_zip, root)
    try:
        old = json.loads((data_dir / "Налаштування.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    _write_json(data_dir / "Налаштування.json", blank_config(keep=old))
    _write_json(data_dir / "Календарні плани.json", {})
    state = data_dir / "Стан.json"
    if state.exists():
        state.unlink()
    for name in WIPE_DIRS:
        folder = root / name
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    return count


def restore_from_zip(zip_path, safety_zip, root: Path = ROOT) -> int:
    """Відновлення з копії. Перед цим поточні дані автоматично зберігаються в safety_zip."""
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if "data/Налаштування.json" not in names or "data/Календарні плани.json" not in names:
            raise ValueError("Це не копія даних програми: у ZIP немає розкладу й календарних планів.")
        base = root.resolve()
        planned = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = (root / info.filename).resolve()
            top = Path(info.filename).parts[0] if Path(info.filename).parts else ""
            if base not in target.parents or top not in RESTORE_DIRS \
                    or is_secret(Path(info.filename)):
                continue
            planned.append((info, target))
        if not planned:
            raise ValueError("У ZIP немає даних для відновлення.")
        export_all_data(safety_zip, root)
        for info, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
    return len(planned)
