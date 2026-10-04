"""Іконка програми у вікні (заголовок, панель завдань, Alt+Tab) і мітка програми для панелі завдань Windows.

Іконка в Провіднику (на самому .exe) вбудовується під час збірки: PyInstaller --icon app_icon.ico.
Тут — лише іконка запущеного вікна: логотип вбудовано в код, окремий файл поруч з .exe не потрібен.
"""
from __future__ import annotations

import io
import sys
import tkinter as tk

APP_ID = "Pasichnyk.PomichnykUchytelia.Classroom"
WINDOW_SIZES = (16, 24, 32, 48, 64, 256)


def set_app_id() -> bool:
    """Щоб Windows показувала на панелі завдань іконку програми, а не загальну іконку Python (лише Windows)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return True
    except Exception:
        return False


def photos(master) -> list:
    """Логотип у кількох розмірах як PhotoImage (Tk сам вибере підходящий для заголовка, панелі завдань, Alt+Tab)."""
    from PIL import Image
    from . import retro_assets
    from .app_icon_data import png_bytes
    base = Image.open(io.BytesIO(png_bytes())).convert("RGBA")
    return [retro_assets.photo(base.resize((s, s), Image.LANCZOS), master) for s in WINDOW_SIZES]


def apply(window) -> bool:
    """Поставити логотип іконкою вікна й усіх наступних вікон програми. Збій не заважає роботі."""
    try:
        images = photos(window)
        window.iconphoto(True, *images)
        window._icon_images = images                      # без посилання Tk «забуває» зображення
        return True
    except (tk.TclError, ImportError, OSError, ValueError):
        return False
