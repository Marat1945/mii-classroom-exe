"""Контекстні меню в стилі програми: пергамент, металевий кант, мідні роздільники, кольорові значки, підменю.

Дані меню (пункти, команди, стани) лишаються звичайним tk.Menu, тож уся логіка програми й тести працюють без змін.
Підмінено лише ПОКАЗ: Menu.tk_popup малює власне вікно замість стандартного меню Windows.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

PARCH, PARCH_HOVER, INK, MUTED = "#F4ECD6", "#E4D3A4", "#2A2118", "#9A8F78"
EDGE, BRASS, METAL = "#3A3127", "#B08A3E", "#4A5448"
FONT_FAMILY = "Segoe UI"
ROW_HEIGHT = 30
_open = []                                            # ланцюжок відкритих вікон меню: головне й підменю
_original_tk_popup = tk.Menu.tk_popup

ICONS = (                                              # ключове слово в підписі → (символ, колір фону значка)
    ("чернетк", "✎", "#2F6DB5"), ("опублікув", "✔", "#2E8B57"), ("word", "W", "#2B5797"), ("перегляну", "◉", "#7A6A9A"),
    ("копіюв", "⧉", "#8A7A52"), ("готов", "✔", "#2E8B57"), ("властив", "⚙", "#6B6B6B"), ("скасув", "✖", "#C4342C"),
    ("видал", "✖", "#C4342C"), ("очист", "✖", "#C4342C"), ("вирізат", "✂", "#8A7A52"), ("встав", "⎘", "#8A7A52"),
    ("вибра", "☑", "#2F6DB5"), ("зняти", "☐", "#6B6B6B"), ("відкрит", "↗", "#2F6DB5"), ("зберег", "⬇", "#2E8B57"),
    ("клас", "▣", "#2E8B57"), ("дії", "▸", "#8A7A52"),
)


def icon_for(label: str):
    low = label.casefold()
    for key, glyph, color in ICONS:
        if key in low:
            return glyph, color
    return "•", "#B08A3E"


def close_all(*_):
    while _open:
        window = _open.pop()
        try:
            window.grab_release()
        except tk.TclError:
            pass
        try:
            window.destroy()
        except tk.TclError:
            pass


def _inside(window, x_root, y_root) -> bool:
    try:
        return (window.winfo_rootx() <= x_root < window.winfo_rootx() + window.winfo_width()
                and window.winfo_rooty() <= y_root < window.winfo_rooty() + window.winfo_height())
    except tk.TclError:
        return False


def _entries(menu):
    end = menu.index("end")
    if end is None:
        return []
    items = []
    for i in range(end + 1):
        kind = menu.type(i)
        if kind == "tearoff":
            continue
        item = {"index": i, "type": kind}
        if kind != "separator":
            item["label"] = str(menu.entrycget(i, "label"))
            item["state"] = str(menu.entrycget(i, "state"))
            try:
                item["accel"] = str(menu.entrycget(i, "accelerator"))
            except tk.TclError:
                item["accel"] = ""
        if kind == "cascade":
            try:
                item["submenu"] = menu.nametowidget(str(menu.entrycget(i, "menu")))
            except (KeyError, tk.TclError):
                item["submenu"] = None
        items.append(item)
    return items


def build_window(menu, x, y, parent=None):
    """Одне вікно меню (головне чи підменю) зі списком пунктів; повертає Toplevel."""
    window = tk.Toplevel(parent or menu.master)
    window.withdraw()
    window.overrideredirect(True)
    try:
        window.attributes("-topmost", True)
    except tk.TclError:
        pass
    window.configure(bg=METAL, bd=0)
    window.menu = menu
    window.rows = []
    window.child = None
    frame = tk.Frame(window, bg=PARCH, bd=0, highlightthickness=2, highlightbackground=BRASS)
    frame.pack(padx=3, pady=3)
    font = tkfont.Font(family=FONT_FAMILY, size=10)
    for item in _entries(menu):
        if item["type"] == "separator":
            tk.Frame(frame, bg=BRASS, height=2).pack(fill="x", padx=8, pady=3)
            continue
        disabled = item["state"] == "disabled"
        row = tk.Frame(frame, bg=PARCH)
        row.pack(fill="x")
        glyph, color = icon_for(item["label"])
        chip = tk.Label(row, text=glyph, width=2, bg=color if not disabled else "#BDB6A2", fg="white",
                        font=tkfont.Font(family="Segoe UI Symbol", size=9, weight="bold"))
        chip.pack(side="left", padx=(8, 8), pady=4)
        text = tk.Label(row, text=item["label"], bg=PARCH, fg=INK if not disabled else MUTED, font=font, anchor="w",
                        pady=7)
        text.pack(side="left", fill="x", expand=True)
        tail = "▸" if item["type"] == "cascade" else item.get("accel", "")
        mark = tk.Label(row, text=tail, bg=PARCH, fg=MUTED if disabled else INK, font=font)
        mark.pack(side="right", padx=(18, 10))
        widgets = (row, text, mark)
        entry = {"item": item, "row": row, "widgets": widgets, "disabled": disabled}
        window.rows.append(entry)
        for widget in widgets + (chip,):
            widget.bind("<Enter>", lambda _e, w=window, en=entry: _hover(w, en))
            widget.bind("<ButtonRelease-1>", lambda _e, w=window, en=entry: _activate(w, en))
            widget.bind("<Button-1>", lambda _e, w=window, en=entry: _activate(w, en) if en["item"]["type"] == "cascade" else None)
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = max(0, min(x, window.winfo_screenwidth() - width - 2))
    y = max(0, min(y, window.winfo_screenheight() - height - 2))
    window.geometry(f"+{x}+{y}")
    window.deiconify()
    window.lift()
    _open.append(window)
    return window


def _paint(entry, active):
    bg = PARCH_HOVER if active and not entry["disabled"] else PARCH
    for widget in entry["widgets"]:
        widget.configure(bg=bg)


def _hover(window, entry):
    for other in window.rows:
        _paint(other, other is entry)
    if window.child is not None:                                  # відкрите підменю закриваємо, коли курсор пішов на інший пункт
        if window.child_owner is not entry:
            _close_child(window)
    item = entry["item"]
    if item["type"] == "cascade" and not entry["disabled"] and window.child is None and item.get("submenu"):
        row = entry["row"]
        child = build_window(item["submenu"], row.winfo_rootx() + row.winfo_width() - 4, row.winfo_rooty() - 4, parent=window)
        window.child, window.child_owner = child, entry


def _close_child(window):
    child = window.child
    window.child = None
    window.child_owner = None
    if child is None:
        return
    _close_child(child)
    if child in _open:
        _open.remove(child)
    try:
        child.destroy()
    except tk.TclError:
        pass


def _activate(window, entry):
    item = entry["item"]
    if entry["disabled"]:
        return
    if item["type"] == "cascade":
        _hover(window, entry)
        return
    menu, index = window.menu, item["index"]
    close_all()
    menu.after(10, lambda: menu.invoke(index))                  # команда виконується вже ПІСЛЯ закриття меню


def popup(menu, x, y, entry=""):
    """Показати меню біля курсора (замість стандартного tk_popup)."""
    close_all()
    if menu.index("end") is None:
        return
    window = build_window(menu, int(x), int(y))
    window.child_owner = None
    root = menu.winfo_toplevel()
    if not getattr(root, "_menu_escape", False):                  # Esc закриває меню навіть коли фокус лишився в головному вікні
        root.bind_all("<Escape>", lambda _e: close_all() if _open else None, add="+")
        root._menu_escape = True
    try:
        window.grab_set()
    except tk.TclError:
        pass
    window.focus_set()
    window.bind("<Escape>", close_all)
    for sequence in ("<ButtonPress-1>", "<ButtonPress-2>", "<ButtonPress-3>"):
        window.bind(sequence, lambda e: close_all() if not any(_inside(w, e.x_root, e.y_root) for w in _open) else None, add="+")


def install():
    """Усі tk.Menu програми показуються у стилі програми. Чужу підміну tk_popup (наприклад, у тестах) не затираємо."""
    if getattr(tk.Menu.tk_popup, "__module__", None) in ("tkinter", __name__):
        tk.Menu.tk_popup = popup


def uninstall():
    tk.Menu.tk_popup = _original_tk_popup
