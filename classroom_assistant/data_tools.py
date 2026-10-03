"""Копія, очищення («порожня програма») та відновлення даних учителя.

Нічого не видаляється без повної копії у ZIP, яку вчитель зберігає сам.
Паролі, токени й OAuth-файли Google ніколи не копіюються й не стираються.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from .blank_data import BELLS, blank_config  # noqa: F401
from .engine import DATA, ROOT

SKIP_DIRS = {".git", ".github", "classroom_assistant", "tests", "__pycache__", "build", "dist",
             "venv", ".venv", ".pytest_cache", "Резервні копії"}
SECRET_NAMES = {"google_credentials.json", "credentials.json", "token.json", "install_state.json"}
# Що вважається «даними вчителя» і очищується разом із розкладом та КТП.
WIPE_DIRS = ("Готові Word", "Вкладення Classroom", "Бібліотека уроків")
RESTORE_DIRS = WIPE_DIRS + ("data", "Архів навчальних даних", "КТП джерела")
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
    kept = {}
    if state.exists():
        try:
            previous = json.loads(state.read_text(encoding="utf-8"))
            kept = {k: previous[k] for k in KEEP_STATE_KEYS if isinstance(previous, dict) and k in previous}
        except (OSError, ValueError):
            kept = {}
        state.unlink()
    if kept:                                    # налаштування вікна й GPT не губляться при «Скинути все»
        _write_json(state, kept)
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
        # Відновлення = стан РІВНО як у копії: папки з даними замінюються, а не доповнюються
        # (поточний стан щойно збережено в safety_zip). Вхід у Google (токени) не чіпаємо.
        for name in WIPE_DIRS:
            shutil.rmtree(root / name, ignore_errors=True)
        state_file = root / "data" / "Стан.json"
        if "data/Стан.json" not in names and state_file.exists():
            state_file.unlink()
        for info, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
    return len(planned)


INSTALL_FILE = "install_state.json"
CLEAN_START_RELEASE = "4.3"            # випуск, у якому один раз виконується «чистий старт»
KEEP_STATE_KEYS = ("chatgpt_url", "autopaste", "autosend", "autopaste_delay", "column_order",
                   "watch_downloads", "watch_inbox", "inbox_done")


def read_install(data_dir: Path | None = None) -> dict:
    """Службова мітка встановлення: не копіюється й не відновлюється з архівів (тож чистий старт не повторюється)."""
    path = (data_dir or DATA) / INSTALL_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_install(values: dict, data_dir: Path | None = None) -> None:
    folder = data_dir or DATA
    folder.mkdir(parents=True, exist_ok=True)
    current = read_install(folder)
    current.update(values)
    (folder / INSTALL_FILE).write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


BACKUP_FOLDER = "Резервні копії"
RESET_PREFIX = "Копія перед скиданням"


def backup_dir(root: Path = ROOT) -> Path:
    return root / BACKUP_FOLDER


def auto_backup_path(prefix: str, root: Path = ROOT) -> Path:
    folder = backup_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{prefix} {datetime.now():%Y-%m-%d %H-%M-%S}.zip"


def latest_backup(root: Path = ROOT, prefix: str | None = RESET_PREFIX):
    """Остання автоматична копія (за замовчуванням — створена перед скиданням) або None."""
    folder = backup_dir(root)
    if not folder.is_dir():
        return None
    files = [p for p in folder.glob("*.zip") if p.is_file()]
    chosen = [p for p in files if prefix and p.name.startswith(prefix)] or files
    return max(chosen, key=lambda p: p.stat().st_mtime, default=None)
