"""Коліщатко миші скрізь, де потрібна прокрутка чи вибір.

Tk сам прокручує списки, таблиці й тексти; тут — те, чого немає «з коробки»: прокручувані області
на Canvas (діалоги з довгими списками) і поле дати.
"""
from __future__ import annotations

import tkinter as tk

NATIVE = ("Text", "Listbox", "Treeview", "TCombobox", "TSpinbox", "Spinbox", "Entry", "TEntry")


def direction(event) -> int:
    """-1 = коліщатко вгору (прокрутка вгору), +1 = униз; 0 — подія без напрямку."""
    num = getattr(event, "num", None)
    if num == 4:
        return -1
    if num == 5:
        return 1
    delta = getattr(event, "delta", 0) or 0
    if delta == 0:
        return 0
    return -1 if delta > 0 else 1


def notches(event) -> int:
    delta = abs(getattr(event, "delta", 0) or 0)
    return max(1, delta // 120) if delta else 1


def scroll_target(widget):
    """Найближчий Canvas із вертикальною прокруткою; None — якщо прокручує сам Tk або нема що."""
    current = widget
    while current is not None:
        try:
            cls = current.winfo_class()
            if cls in NATIVE:
                return None
            if cls == "Canvas" and current.cget("yscrollcommand"):
                return current
            current = current.master
        except (tk.TclError, AttributeError):
            return None
    return None


def on_wheel(event):
    sign = direction(event)
    if not sign:
        return None
    try:
        target = event.widget.winfo_containing(event.x_root, event.y_root) or event.widget
    except (tk.TclError, AttributeError, KeyError):
        target = event.widget
    canvas = scroll_target(target)
    if canvas is None:
        return None
    try:
        first, last = canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return None                                  # усе вміщається — прокручувати нічого
        canvas.yview_scroll(sign * 3 * notches(event), "units")
    except tk.TclError:
        return None
    return "break"


def install(root):
    root.bind_all("<MouseWheel>", on_wheel, add="+")
    root.bind_all("<Button-4>", on_wheel, add="+")      # X11 / Linux
    root.bind_all("<Button-5>", on_wheel, add="+")


def bind_steps(widget, callback):
    """Коліщатко над віджетом викликає callback(+1 | -1, big): вниз = +1 (пізніше/далі), вгору = −1.

    Shift або Ctrl разом із коліщатком дають «великий крок» (big=True): тиждень, рік.
    """
    def handler(event):
        sign = direction(event)
        if not sign:
            return None
        big = bool(getattr(event, "state", 0) & 0x0005)      # Shift або Ctrl
        callback(sign, big)                                   # вниз = далі, як гортання сторінки
        return "break"
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        widget.bind(sequence, handler)
