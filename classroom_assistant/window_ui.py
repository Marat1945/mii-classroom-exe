"""Єдиний повнорозмірний інтерфейс робочих вікон Windows.

Використовується лише для великих діалогів програми; системні
підтвердження Yes/No і вікна файлового вибору залишаються компактними.
"""
from __future__ import annotations
import tkinter as tk


def maximize_work_window(window):
    """Розгорнути вікно на екран Windows, з коректним резервним шляхом."""
    def apply():
        try:
            if not window.winfo_exists():return
            # MainApp.state — словник навчальних даних, а не tkinter-метод.
            # Виклик wm_state уникає конфлікту назв у головному вікні.
            window.wm_state("zoomed")
            return
        except (tk.TclError,ValueError):
            pass
        try:
            # Для середовищ X11: 95% екрану; користувач може довільно змінити розмір.
            w=max(820,int(window.winfo_screenwidth()*0.95))
            h=max(560,int(window.winfo_screenheight()*0.91))
            window.geometry(f"{w}x{h}+0+0")
        except tk.TclError:pass
    window.after_idle(apply)
    return window
