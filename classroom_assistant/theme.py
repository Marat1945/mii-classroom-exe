"""Єдине оформлення програми: кольори, шрифти, таблиці, вкладки, шапка.

Тільки стандартні засоби Tk/ttk (тема «clam»), без додаткових бібліотек,
тож це не ускладнює збірку EXE. Якщо щось піде не так — програма
працює зі звичайним виглядом.
"""
from __future__ import annotations
import sys
import tkinter as tk
from tkinter import ttk

BG = "#EEF3F8"
CARD = "#FFFFFF"
INK = "#1B2A3A"
MUTED = "#4B5F73"
BORDER = "#C3D2E0"
BUTTON = "#DCE8F5"
BUTTON_HOVER = "#C6DAF0"
BUTTON_PRESSED = "#B1CCE8"
ACCENT = "#1F6FB2"
ACCENT_DARK = "#164F82"
SELECT = "#2E7BC4"
HEADING = "#D3E2F1"
BANNER_FROM = (31, 78, 121)
BANNER_TO = (46, 123, 196)

FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"


def apply_theme(root):
    """Застосувати кольори до всієї програми (один раз, на головному вікні)."""
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=(FONT, 10),
                        bordercolor=BORDER, lightcolor=BG, darkcolor=BG, troughcolor=BORDER)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("TCheckbutton", background=BG, foreground=INK)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TLabelframe", background=BG, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT_DARK,
                        font=(FONT, 10, "bold"))
        style.configure("TButton", background=BUTTON, foreground=INK, padding=(11, 5),
                        borderwidth=1, relief="flat", focusthickness=1, focuscolor=ACCENT)
        style.map("TButton",
                  background=[("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER),
                              ("disabled", "#E6ECF2")],
                  foreground=[("disabled", "#8A99A8")],
                  bordercolor=[("active", ACCENT)])
        style.configure("TEntry", fieldbackground=CARD, padding=4, bordercolor=BORDER)
        style.configure("TCombobox", fieldbackground=CARD, background=BUTTON, padding=4,
                        arrowsize=15, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)],
                  selectbackground=[("readonly", CARD)], selectforeground=[("readonly", INK)])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 6, 2, 0))
        style.configure("TNotebook.Tab", background=BUTTON, foreground=INK, padding=(16, 7),
                        font=(FONT, 10, "bold"), borderwidth=1)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD), ("active", BUTTON_HOVER)],
                  foreground=[("selected", ACCENT_DARK)])
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK,
                        rowheight=27, borderwidth=1, bordercolor=BORDER)
        style.map("Treeview", background=[("selected", SELECT)],
                  foreground=[("selected", "white")])
        style.configure("Treeview.Heading", background=HEADING, foreground=ACCENT_DARK,
                        font=(FONT, 10, "bold"), padding=(6, 6), relief="flat",
                        borderwidth=1, bordercolor=BORDER)
        style.map("Treeview.Heading", background=[("active", BUTTON_HOVER)])
        style.configure("TScrollbar", background=BUTTON, troughcolor=BG, bordercolor=BG,
                        arrowcolor=ACCENT_DARK)
        style.configure("TPanedwindow", background=BG)
        style.configure("Sash", background=BORDER)
    except tk.TclError:
        return False
    # Звичайні (не ttk) віджети: вікна, поля тексту, списки.
    try:
        root.configure(background=BG)
        root.option_add("*Toplevel.background", BG)
        root.option_add("*Text.background", CARD)
        root.option_add("*Text.foreground", INK)
        root.option_add("*Text.selectBackground", SELECT)
        root.option_add("*Text.selectForeground", "white")
        root.option_add("*Text.relief", "solid")
        root.option_add("*Text.borderWidth", 1)
        root.option_add("*Text.highlightThickness", 1)
        root.option_add("*Text.highlightBackground", BORDER)
        root.option_add("*Text.highlightColor", ACCENT)
        root.option_add("*Listbox.background", CARD)
        root.option_add("*Listbox.foreground", INK)
        root.option_add("*Listbox.relief", "solid")
        root.option_add("*Listbox.borderWidth", 1)
        root.option_add("*Listbox.highlightThickness", 0)
        root.option_add("*Menu.background", CARD)
        root.option_add("*Menu.foreground", INK)
        root.option_add("*Menu.activeBackground", SELECT)
        root.option_add("*Menu.activeForeground", "white")
        root.option_add("*Menu.relief", "flat")
        root.option_add("*Menu.borderWidth", 1)
        root.option_add("*Canvas.background", BG)
        root.option_add("*TCombobox*Listbox.background", CARD)
        root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
        root.option_add("*TCombobox*Listbox.selectForeground", "white")
    except tk.TclError:
        pass
    return True


def make_banner(parent, title, subtitle=""):
    """Шапка з плавним градієнтом і назвою програми."""
    height = 52
    canvas = tk.Canvas(parent, height=height, highlightthickness=0, bd=0)

    def draw(_event=None):
        width = max(canvas.winfo_width(), 400)
        canvas.delete("all")
        steps = 64
        for i in range(steps):
            ratio = i / (steps - 1)
            color = "#%02x%02x%02x" % tuple(
                int(a + (b - a) * ratio) for a, b in zip(BANNER_FROM, BANNER_TO))
            canvas.create_rectangle(width * i / steps, 0, width * (i + 1) / steps + 1, height,
                                    fill=color, outline=color)
        canvas.create_text(20, 19, anchor="w", text=title, fill="white",
                           font=(FONT, 16, "bold"))
        if subtitle:
            canvas.create_text(22, 39, anchor="w", text=subtitle, fill="#D6E7F7",
                               font=(FONT, 9))
        canvas.create_line(0, height - 1, width, height - 1, fill=ACCENT_DARK)

    canvas.bind("<Configure>", draw)
    return canvas
