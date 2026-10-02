"""Де зберігаються дані вчителя: папка «Помічник учителя Classroom» у «Документах»."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_FOLDER = "Помічник учителя Classroom"
LEGACY_FOLDER = "PomichnykUchyteliaClassroom"
MARKER = "ДАНІ ПЕРЕНЕСЕНО В ДОКУМЕНТИ.txt"


def documents_dir() -> Path:
    """Справжня «Документи» (Windows може перенаправляти її на інший диск чи OneDrive)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            guid = ctypes.c_byte * 16
            folder_documents = (ctypes.c_ubyte * 16)(0xD0, 0x9A, 0xD3, 0xFD, 0x8F, 0x23, 0xAF, 0x46,
                                                     0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7)
            pointer = ctypes.c_wchar_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folder_documents), 0, None, ctypes.byref(pointer))
            if result == 0 and pointer.value:
                path = Path(pointer.value)
                ctypes.windll.ole32.CoTaskMemFree(pointer)
                return path
        except Exception:
            pass
    return Path.home() / "Documents"


def legacy_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / LEGACY_FOLDER


def resolve_root(documents: Path, legacy: Path):
    """(папка, звідки): existing | migrated | new | legacy. Дані не видаляються ніколи."""
    new = Path(documents) / APP_FOLDER
    settings = Path("data") / "Налаштування.json"
    if (new / settings).exists():
        return new, "existing"
    if (Path(legacy) / settings).exists():
        try:
            shutil.copytree(legacy, new, dirs_exist_ok=True)
            if not (new / settings).exists():
                raise OSError("копія неповна")
            try:
                (Path(legacy) / MARKER).write_text(
                    f"Ваші дані скопійовано в «{new}».\nНадалі програма працює з тією папкою. "
                    "Цю стару папку можна видалити після того, як переконаєтесь, що все на місці.",
                    encoding="utf-8")
            except OSError:
                pass
            return new, "migrated"
        except Exception:
            return Path(legacy), "legacy"
    try:
        new.mkdir(parents=True, exist_ok=True)
        return new, "new"
    except OSError:
        return Path(legacy), "legacy"
