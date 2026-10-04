"""Автоматичне підхоплення готових файлів від GPT: ZIP-архів дня та стеження за папками.

Безпека: з архіву беруться ЛИШЕ Word і зображення (без підпапок і виконуваних файлів); у «Завантаженнях»
чіпаються лише файли з назвою «<клас>, Урок дд.мм — …» або архів «дд.мм.рр.zip». Нічого не видаляється.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

from .file_match import IMAGE_SUFFIXES, clean_stem, parse_name

SUPPORTED = {".docx"} | IMAGE_SUFFIXES
INBOX_NAME = "Вхідні файли GPT"
DONE_NAME = "Оброблено"
ZIP_NAME = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}$")
ZIP_DATE = re.compile(r"\d{2}[.\-_]\d{2}[.\-_]\d{2,4}")                # дата будь-де в назві: «Лекції 05.10.26.zip»
MAX_LOOSE_ZIP = 100 * 1024 * 1024                                      # у власній папці великі чужі архіви не чіпаємо
TEMP_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")
MAX_FILES = 300
MAX_TOTAL = 500 * 1024 * 1024
MAX_ONE = 200 * 1024 * 1024


def inbox_dir(root: Path) -> Path:
    folder = Path(root) / INBOX_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def downloads_dir() -> Path:
    """Справжня папка «Завантаження» (Windows може перенаправляти її)."""
    if sys.platform == "win32":
        try:
            import ctypes
            guid = (ctypes.c_ubyte * 16)(0x90, 0xE2, 0x4D, 0x37, 0x3F, 0x12, 0x65, 0x45,
                                         0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B)
            pointer = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) == 0 \
                    and pointer.value:
                path = Path(pointer.value)
                ctypes.windll.ole32.CoTaskMemFree(pointer)
                return path
        except Exception:
            pass
    return Path.home() / "Downloads"


def is_zip_for_day(path) -> bool:
    """Архів дня: у назві є дата («05.10.26.zip», «Лекції 05.10.26.zip» — ChatGPT інколи додає слова)."""
    return Path(path).suffix.lower() == ".zip" and bool(ZIP_DATE.search(clean_stem(path)))


def extract_archive(zip_path, folder, limit_files=MAX_FILES) -> list:
    """Розпаковує лише Word і зображення (плоско, без підпапок). Повертає шляхи."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    extracted, total = [], 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        return []
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename.replace("\\", "/")).name
            if not name or Path(name).suffix.lower() not in SUPPORTED:
                continue
            if info.file_size > MAX_ONE or total + info.file_size > MAX_TOTAL or len(extracted) >= limit_files:
                continue
            target = folder / name
            number = 2
            while target.exists():
                target = folder / f"{Path(name).stem} ({number}){Path(name).suffix}"
                number += 1
            try:
                with archive.open(info) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
            except (zipfile.BadZipFile, OSError, RuntimeError):
                continue
            total += info.file_size
            extracted.append(target)
    return extracted


def expand_archives(paths, folder):
    """(список файлів без архівів, {розпакований: архів}). Архіви замінюються їхнім вмістом."""
    result, origin = [], {}
    for path in paths:
        path = Path(path)
        if path.suffix.lower() == ".zip":
            for inner in extract_archive(path, Path(folder) / clean_stem(path)):
                result.append(inner)
                origin[inner] = path
        else:
            result.append(path)
    return result, origin


def is_candidate(path, strict: bool) -> bool:
    """strict=True («Завантаження»): лише файли з назвою уроку чи архів дня; інакше — будь-який Word/зображення/ZIP."""
    path = Path(path)
    name = path.name
    suffix = path.suffix.lower()
    if name.startswith(("~$", ".")) or name.endswith(TEMP_SUFFIXES):
        return False
    if suffix == ".zip":
        if strict or is_zip_for_day(path):
            return is_zip_for_day(path)
        try:                                                          # власна папка: будь-який НЕВЕЛИКИЙ архів
            return path.stat().st_size <= MAX_LOOSE_ZIP
        except OSError:
            return False
    if suffix not in SUPPORTED:
        return False
    return parse_name(clean_stem(path)) is not None if strict else True


def signature(path: Path) -> tuple:
    stat = path.stat()
    return (path.name, stat.st_size, stat.st_mtime_ns)


class InboxWatcher:
    """Каже, які нові файли вже повністю записані (розмір не змінювався між двома опитуваннями)."""

    def __init__(self, done=None):
        self.done = set(tuple(x) for x in (done or ()))
        self.pending = {}

    def poll(self, sources, since_ns=None):
        """sources — [(папка, strict)]. Повертає [(шлях, strict)], готові до обробки."""
        ready = []
        for folder, strict in sources:
            try:
                entries = list(Path(folder).iterdir())
            except OSError:
                continue
            for path in entries:
                try:
                    if not path.is_file() or not is_candidate(path, strict):
                        continue
                    sig = signature(path)
                except OSError:
                    continue
                if sig in self.done:
                    continue
                if strict and since_ns is not None and sig[2] < since_ns:
                    continue
                if self.pending.get(path) == sig:
                    ready.append((path, strict))
                else:
                    self.pending[path] = sig
        return ready

    def mark_done(self, path):
        try:
            sig = signature(Path(path))
        except OSError:
            return
        self.done.add(sig)
        self.pending.pop(Path(path), None)

    def export(self, limit=400):
        return [list(x) for x in list(self.done)[-limit:]]


def move_to_done(path: Path) -> Path | None:
    """Оброблений файл із власної папки програми переносимо в «Оброблено» (нічого не видаляємо)."""
    try:
        folder = Path(path).parent / DONE_NAME
        folder.mkdir(exist_ok=True)
        target = folder / Path(path).name
        number = 2
        while target.exists():
            target = folder / f"{Path(path).stem} ({number}){Path(path).suffix}"
            number += 1
        shutil.move(str(path), str(target))
        return target
    except OSError:
        return None
