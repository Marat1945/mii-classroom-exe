"""Виділення рядків таблиці утримуванням лівої кнопки миші (у всіх таблицях програми)."""
from __future__ import annotations

import tkinter as tk

SHIFT, CONTROL = 0x0001, 0x0004


def _press(event):
    tree = event.widget
    tree._drag_select = None
    try:
        if str(tree.cget("selectmode")) != "extended":
            return
        if event.state & (SHIFT | CONTROL):
            return                          # Shift/Ctrl+клац — стандартна поведінка
        if tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return
        row = tree.identify_row(event.y)
        if row:
            tree._drag_select = {"anchor": row, "last": None}
    except tk.TclError:
        pass


def _motion(event):
    tree = event.widget
    state = getattr(tree, "_drag_select", None)
    if not state:
        return
    try:
        height = tree.winfo_height()
        if event.y < 0:
            tree.yview_scroll(-1, "units")
        elif event.y > height:
            tree.yview_scroll(1, "units")
        row = tree.identify_row(min(max(event.y, 2), max(height - 2, 3)))
        if not row:
            return
        rows = tree.get_children("")
        first, second = rows.index(state["anchor"]), rows.index(row)
        low, high = min(first, second), max(first, second)
        if (low, high) == state["last"]:
            return
        state["last"] = (low, high)
        tree.selection_set(rows[low:high + 1])
    except (tk.TclError, ValueError):
        pass


def install(root):
    root.bind_class("Treeview", "<ButtonPress-1>", _press, add="+")
    root.bind_class("Treeview", "<B1-Motion>", _motion, add="+")
