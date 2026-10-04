"""Єдине оформлення програми: «старий прилад» — металева рамка, пергаментні поля, латунні кнопки.

Усе робиться стандартними засобами Tk/ttk і Pillow (текстури малюються в пам'яті), тож збірка EXE не ускладнюється.
Якщо Pillow недоступний — програма працює з простим плоским виглядом тих самих кольорів.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from . import retro_assets as assets

# --- палітра (знята зі зразка-макета) ---
METAL = "#566258"
METAL_DARK = "#2F3631"
METAL_LIGHT = "#8A9585"
PARCH = "#E9DDBF"
PARCH_LIGHT = "#F4ECD6"
PARCH_DARK = "#CDBE9A"
BRASS = "#D4C497"
EDGE = "#3A3127"
INK = "#2A2118"
MUTED = "#5E5039"
NAVY = "#1D4A7D"
NAVY_HOVER = "#2A62A0"
GREEN = "#1E6B46"
GREEN_HOVER = "#2A865A"
SELECT = "#3E7DBA"
CREAM = "#F2E9CC"

# --- сумісні назви (їх очікують інші модулі) ---
BG = PARCH
CARD = PARCH_LIGHT
BORDER = EDGE
BUTTON = BRASS
BUTTON_HOVER = "#E2D5AB"
BUTTON_PRESSED = "#B7A57A"
ACCENT = NAVY
ACCENT_DARK = "#143A63"
HEADING = "#D2C196"
BANNER_FROM = (47, 54, 49)
BANNER_TO = (86, 98, 88)

FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
TITLE_FONT = "Georgia" if sys.platform == "win32" else "DejaVu Serif"
BORDER_WIDTH = 12

_KEEP = []                                           # посилання на зображення: без них Tk їх «забуває»


def _image_buttons(style):
    states = {s: assets.photo(assets.button_image(s)) for s in ("normal", "hover", "pressed", "disabled")}
    _KEEP.extend(states.values())
    style.element_create("Retro.Button.plate", "image", states["normal"],
                         ("disabled", states["disabled"]), ("pressed", states["pressed"]),
                         ("active", states["hover"]), border=(10, 10, 10, 10), sticky="nswe")
    style.layout("TButton", [("Retro.Button.plate", {"sticky": "nswe", "children": [
        ("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})]})])


def apply_theme(root):
    """Застосувати вигляд до всієї програми (один раз, на головному вікні)."""
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=PARCH, foreground=INK, font=(FONT, 10), bordercolor=EDGE,
                        lightcolor=PARCH_LIGHT, darkcolor=PARCH_DARK, troughcolor=PARCH_DARK)
        style.configure("TFrame", background=PARCH)
        style.configure("TLabel", background=PARCH, foreground=INK)
        style.configure("TCheckbutton", background=PARCH, foreground=INK)
        style.map("TCheckbutton", background=[("active", PARCH)])
        style.configure("TRadiobutton", background=PARCH, foreground=INK)
        style.configure("TLabelframe", background=PARCH, bordercolor=EDGE)
        style.configure("TLabelframe.Label", background=PARCH, foreground=NAVY, font=(FONT, 10, "bold"))
        style.configure("TButton", background=BRASS, foreground=INK, padding=(6, 3), borderwidth=0,
                        relief="flat", font=(FONT, 10, "bold"), focusthickness=0)
        style.map("TButton", foreground=[("disabled", "#8E8566"), ("pressed", INK)])
        if assets.available():
            try:
                _image_buttons(style)
            except tk.TclError:
                style.map("TButton", background=[("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)])
        else:
            style.map("TButton", background=[("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)])
        style.configure("TEntry", fieldbackground=PARCH_LIGHT, foreground=INK, padding=4, bordercolor=EDGE)
        style.map("TEntry", fieldbackground=[("readonly", PARCH_DARK), ("disabled", PARCH_DARK)],
                  foreground=[("readonly", INK), ("disabled", MUTED)])
        style.configure("TSpinbox", fieldbackground=PARCH_LIGHT, foreground=INK, padding=3, bordercolor=EDGE)
        style.configure("TCombobox", fieldbackground=PARCH_LIGHT, background=BRASS, foreground=INK, padding=4,
                        arrowsize=15, bordercolor=EDGE)
        style.map("TCombobox", fieldbackground=[("readonly", PARCH_LIGHT)],
                  selectbackground=[("readonly", PARCH_LIGHT)], selectforeground=[("readonly", INK)])
        style.configure("TNotebook", background=PARCH, borderwidth=0, tabmargins=(2, 6, 2, 0))
        style.configure("TNotebook.Tab", background=PARCH_DARK, foreground=INK, padding=(16, 7),
                        font=(FONT, 10, "bold"), borderwidth=1, bordercolor=EDGE)
        style.map("TNotebook.Tab", background=[("selected", PARCH_LIGHT), ("active", BRASS)],
                  foreground=[("selected", NAVY)])
        style.configure("Treeview", background=PARCH_LIGHT, fieldbackground=PARCH_LIGHT, foreground=INK,
                        rowheight=27, borderwidth=2, bordercolor=EDGE)
        style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", "white")])
        style.configure("Treeview.Heading", background=HEADING, foreground=INK, font=(FONT, 10, "bold"),
                        padding=(6, 6), relief="raised", borderwidth=1, bordercolor=EDGE,
                        lightcolor="#EBDFB8", darkcolor="#9C8A5E")
        style.map("Treeview.Heading", background=[("active", BRASS)])
        style.configure("TScrollbar", background=BRASS, troughcolor=PARCH_DARK, bordercolor=EDGE, arrowcolor=INK)
        style.configure("TPanedwindow", background=PARCH)
        style.configure("Sash", background=EDGE)
    except tk.TclError:
        return False
    # Звичайні (не ttk) віджети: вікна з металевою рамкою, пергаментні поля тексту, списки, меню.
    try:
        root.configure(background=METAL, bd=BORDER_WIDTH, relief="ridge")
        root.option_add("*Toplevel.background", METAL)
        root.option_add("*Toplevel.borderWidth", BORDER_WIDTH)
        root.option_add("*Toplevel.relief", "ridge")
        root.option_add("*Text.background", PARCH_LIGHT)
        root.option_add("*Text.foreground", INK)
        root.option_add("*Text.selectBackground", SELECT)
        root.option_add("*Text.selectForeground", "white")
        root.option_add("*Text.relief", "solid")
        root.option_add("*Text.borderWidth", 1)
        root.option_add("*Text.highlightThickness", 1)
        root.option_add("*Text.highlightBackground", EDGE)
        root.option_add("*Text.highlightColor", NAVY)
        root.option_add("*Listbox.background", PARCH_LIGHT)
        root.option_add("*Listbox.foreground", INK)
        root.option_add("*Listbox.selectBackground", SELECT)
        root.option_add("*Listbox.selectForeground", "white")
        root.option_add("*Listbox.relief", "solid")
        root.option_add("*Listbox.borderWidth", 1)
        root.option_add("*Listbox.highlightThickness", 0)
        root.option_add("*Menu.background", PARCH)
        root.option_add("*Menu.foreground", INK)
        root.option_add("*Menu.activeBackground", SELECT)
        root.option_add("*Menu.activeForeground", "white")
        root.option_add("*Menu.relief", "raised")
        root.option_add("*Menu.borderWidth", 2)
        root.option_add("*Canvas.background", PARCH)
        root.option_add("*TCombobox*Listbox.background", PARCH_LIGHT)
        root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
        root.option_add("*TCombobox*Listbox.selectForeground", "white")
    except tk.TclError:
        pass
    return True


def add_rivets(window):
    """Чотири заклепки в кутах металевої рамки вікна (place: не заважає розкладці вмісту)."""
    if not assets.available() or getattr(window, "_rivets", None):
        return
    try:
        image = assets.photo(assets.rivet_image(BORDER_WIDTH), window)
        labels = []
        for relx, rely, anchor in ((0, 0, "nw"), (1, 0, "ne"), (0, 1, "sw"), (1, 1, "se")):
            label = tk.Label(window, image=image, bd=0, highlightthickness=0, bg=METAL)
            label.place(relx=relx, rely=rely, anchor=anchor)
            labels.append(label)
        window._rivets = (image, labels)
    except tk.TclError:
        pass


def make_banner(parent, title, subtitle="", author="", animate=True):
    """Шапка-прилад: циферблат, лампочка зв'язку, назва, що переливається, табличка автора."""
    from .retro_header import InstrumentHeader
    return InstrumentHeader(parent, title, subtitle, author, animate=animate)
