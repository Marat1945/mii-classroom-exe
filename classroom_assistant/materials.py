"""Навчальні матеріали: довідники, вшиті в програму, і власні файли вчителя (завжди під рукою).

• Вбудовані довідники лежать у збірці (папка «КТП джерела/Навчальні матеріали») і доступні завжди.
• Власні матеріали вчитель додає сам: вони зберігаються в «Документи → Помічник учителя Classroom → Навчальні матеріали».
• Будь-який файл можна одним клацом зберегти в «Завантаження».
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

FOLDER = "Навчальні матеріали"
BUNDLED_SECTION = "Довідники"
USER_SECTION = "Мої матеріали"

TITLES = {
    "Рятівник - ВІ 6-7": "«Рятівник» — Всесвітня історія, 6–7 класи",
    "Рятівник - ВІ 8-9": "«Рятівник» — Всесвітня історія, 8–9 класи",
    "Рятівник - ВІ 10-11": "«Рятівник» — Всесвітня історія, 10–11 класи",
    "Рятівник - ІУ 7-9": "«Рятівник» — Історія України, 7–9 класи",
    "Рятівник - ІУ 10-11": "«Рятівник» — Історія України, 10–11 класи",
    "ІУ - 5 в схемах і таблицях": "Історія України, 5 клас — у схемах і таблицях",
}
ORDER = list(TITLES)


@dataclass
class Item:
    title: str
    path: Path
    section: str
    builtin: bool

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @property
    def name(self) -> str:
        return self.path.name


def bundled_dir() -> Path:
    """Де лежать вбудовані довідники: у зібраній програмі — у її збірці, інакше — у папці проєкту."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "КТП джерела" / FOLDER


def user_dir(root) -> Path:
    return Path(root) / FOLDER


def title_for(path: Path) -> str:
    return TITLES.get(path.stem, path.stem)


def human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} МБ"
    return f"{max(1, round(size / 1024))} КБ"


def catalog(root) -> list:
    """Усі матеріали: спершу вбудовані довідники (за порядком), потім власні вчителя (за розділами й іменами)."""
    items, known = [], set()
    bundled = bundled_dir()
    if bundled.is_dir():
        files = sorted((p for p in bundled.iterdir() if p.is_file() and not p.name.startswith(".")),
                       key=lambda p: (ORDER.index(p.stem) if p.stem in ORDER else len(ORDER), p.name))
        for path in files:
            items.append(Item(title_for(path), path, BUNDLED_SECTION, True))
            known.add(path.name)
    folder = user_dir(root)
    if folder.is_dir():
        for path in sorted((p for p in folder.rglob("*") if p.is_file() and not p.name.startswith(".")),
                           key=lambda p: (str(p.parent), p.name.casefold())):
            relative = path.relative_to(folder)
            section = relative.parts[0] if len(relative.parts) > 1 else USER_SECTION
            if section == BUNDLED_SECTION and path.name in known:               # копія вбудованого: не дублюємо
                continue
            items.append(Item(path.stem, path, section, False))
    return items


def unique_target(folder: Path, name: str) -> Path:
    """Файл із таким іменем уже є? Додаємо « (1)», « (2)»…: нічого не перезаписуємо."""
    target = Path(folder) / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    k = 1
    while (Path(folder) / f"{stem} ({k}){suffix}").exists():
        k += 1
    return Path(folder) / f"{stem} ({k}){suffix}"


def local_copy(item: Item, root) -> Path:
    """Звичайний файл на диску. Вбудований довідник спершу розпаковується у папку вчителя: тимчасова папка збірки
    зникає після закриття програми, а відкритий PDF має лишатись доступним."""
    if not item.builtin:
        return item.path
    target = user_dir(root) / BUNDLED_SECTION / item.path.name
    if not target.exists() or target.stat().st_size != item.size:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.path, target)
    return target


def add_files(root, paths, section: str = USER_SECTION) -> list:
    """Додати власні файли до розділу (копіюються у папку вчителя). Повертає шляхи копій."""
    section = (section or USER_SECTION).strip().strip("/\\") or USER_SECTION
    for bad in '<>:"|?*':
        section = section.replace(bad, "")
    folder = user_dir(root) if section == USER_SECTION else user_dir(root) / section
    folder.mkdir(parents=True, exist_ok=True)
    copies = []
    for source in paths:
        source = Path(source)
        if source.is_file():
            target = unique_target(folder, source.name)
            shutil.copy2(source, target)
            copies.append(target)
    return copies


def remove(item: Item) -> bool:
    """Видалити власний матеріал. Вбудовані довідники видалити не можна."""
    if item.builtin:
        return False
    try:
        item.path.unlink()
        return True
    except OSError:
        return False


def save_to_downloads(item: Item, root, downloads) -> Path:
    """Зберегти копію у «Завантаження» (під унікальним іменем)."""
    source = local_copy(item, root)
    downloads = Path(downloads)
    downloads.mkdir(parents=True, exist_ok=True)
    target = unique_target(downloads, source.name)
    shutil.copy2(source, target)
    return target


def open_file(path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal(path) -> None:
    """Показати файл у Провіднику (виділеним)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_file(Path(path).parent)
