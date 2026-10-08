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


# Розмір вікон-діалогів: частка екрана, мінімум (ширина, висота).
SIZE_PRESETS={"small":(0.46,0.58,720,500),
              "normal":(0.64,0.76,980,660),
              "large":(0.82,0.86,1100,700)}


def fit_work_window(window,kind="normal",minimum=None):
    """Зручне вікно: не на весь екран, але й без обрізаного вмісту.

    Розмір = частка екрана, але не менший за те, що просить вміст (reqsize),
    і не більший за екран. Вікно по центру; мінімальний розмір не дає
    стиснути його так, що кнопки зникнуть.
    """
    ratio_w,ratio_h,min_w,min_h=SIZE_PRESETS[kind]
    if minimum:min_w,min_h=minimum
    try:
        from .theme import add_rivets, add_title_plate
        add_title_plate(window)                          # металева табличка з назвою угорі
        add_rivets(window)                               # іржава рамка й заклепки в кутах
    except Exception:
        pass

    def apply():
        try:
            if not window.winfo_exists():return
            window.update_idletasks()
            sw,sh=window.winfo_screenwidth(),window.winfo_screenheight()
            max_w,max_h=int(sw*0.96),int(sh*0.92)
            floor_w,floor_h=min(min_w,max_w),min(min_h,max_h)
            w=min(max(int(sw*ratio_w),window.winfo_reqwidth(),floor_w),max_w)
            h=min(max(int(sh*ratio_h),window.winfo_reqheight(),floor_h),max_h)
            x=max(0,(sw-w)//2)
            y=max(0,(sh-h)//2-int(sh*0.02))
            window.minsize(floor_w,floor_h)
            window.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass
    window.after_idle(apply)
    return window


def reuse_window(owner, key):
    """Вікно з таким ключем уже відкрите? Тоді виносимо його наперед і повертаємо (нового не створюємо)."""
    window = getattr(owner, "_single_windows", {}).get(key)
    if window is None:
        return None
    try:
        if not window.winfo_exists():
            return None
        window.deiconify()
        window.lift()
        window.focus_force()
        return window
    except tk.TclError:
        return None


def remember_window(owner, key, window):
    """Запам'ятати відкрите вікно, щоб повторний клац не відкривав друге таке саме."""
    if not hasattr(owner, "_single_windows"):
        owner._single_windows = {}
    owner._single_windows[key] = window
    return window
