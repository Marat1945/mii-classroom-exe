"""Вікно «Куди зберігати файли від GPT»: прямий запис браузера в папку програми (одноразове налаштування)."""
from __future__ import annotations

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk

from . import browser_downloads as bd
from . import lecture_inbox
from .engine import ROOT
from .toast import show_toast
from .window_ui import fit_work_window, remember_window, reuse_window

INTRO = (
    "Куди браузер зберігає завантажене, вирішує сам браузер: сайт і програма цього змінити не можуть. Тому один раз "
    "налаштуйте його, і далі файли від ChatGPT потраплятимуть ПРЯМО в папку програми. Програма сама розкладе їх по "
    "уроках (Word і зображення), позначить зеленим у таблиці дня готові уроки й перенесе оброблене в підпапку "
    "«Оброблено». Вам лишиться лише натиснути «Створити чернетку».")

STEPS = (
    "1. Натисніть «Копіювати шлях» (шлях до папки програми потрапить у буфер обміну).\n"
    "2. Натисніть «Відкрити налаштування» біля свого браузера: відкриється сторінка «Завантаження».\n"
    "3. Біля пункту «Розташування» натисніть «Змінити», вставте шлях (Ctrl+V) і підтвердьте вибір папки.\n"
    "4. Якщо ввімкнено «Запитувати, куди зберегти кожен файл» — вимкніть, інакше браузер щоразу питатиме.\n"
    "5. Поверніться сюди й натисніть «Перевірити ще раз»: біля браузера має з'явитися ✓.")

NOTE = (
    "Це змінює папку завантажень браузера для ВСІХ файлів. Стороннє програма не чіпає: вона бере лише файли з назвою "
    "«клас, Урок дд.мм — …» та архіви дня. Не хочете змінювати — нічого не робіть: програма й далі стежить за "
    "«Завантаженнями» та за папкою, яку вибрав браузер.")


def status_text(kind: str) -> tuple:
    if kind == "direct":
        return "✓ Файли від GPT потрапляють прямо в програму", "#1E6B46"
    if kind == "other":
        return ("⚠ Інша папка: програма стежить і за нею, але бере лише файли з назвою «клас, Урок дд.мм — …»",
                "#7A5200")
    return ("Звичайні «Завантаження»: програма їх бачить, але бере лише файли з назвою уроку. "
            "Щоб було прямо в програму — змініть папку (кроки нижче)", "#5E5039")


def summary_line(found, inbox, downloads) -> tuple:
    """Короткий рядок стану для вікна «Лекції на весь день»: (текст, колір)."""
    if bd.any_direct(found, inbox, downloads):
        return "✓ Автоприйом: браузер зберігає прямо в програму — файли з'являться тут самі", "#1E6B46"
    return ("Файли з браузера підхоплюються із «Завантажень» (щоб зберігалось прямо в програму — "
            "кнопка «Куди зберігати файли…»)", "#5E5039")


def open_folder(folder) -> None:
    if sys.platform == "win32":
        os.startfile(str(folder))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])


def show_download_setup(app):
    existing = reuse_window(app, "download_setup")
    if existing:                                       # повторний клац не відкриває друге таке саме вікно
        return existing
    win = tk.Toplevel(app)
    remember_window(app, "download_setup", win)
    win.title("Куди зберігати файли від GPT")
    fit_work_window(win, "normal")
    win.transient(app)
    win.escape_closes = True
    inbox = lecture_inbox.inbox_dir(ROOT)
    outer = ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text=INTRO, wraplength=820, justify="left").pack(anchor="w")

    box = ttk.LabelFrame(outer, text=" Папка програми для файлів від GPT ", padding=10)
    box.pack(fill="x", pady=(12, 8))
    path_var = tk.StringVar(master=win, value=str(inbox))
    win.path_var = path_var                      # без посилання Tkinter «забуває» змінну, і поле лишається порожнім
    path_entry = ttk.Entry(box, textvariable=path_var, state="readonly")
    path_entry.pack(fill="x")
    win.path_entry = path_entry
    bar = ttk.Frame(box)
    bar.pack(fill="x", pady=(8, 0))

    def copy_path():
        win.clipboard_clear()
        win.clipboard_append(str(inbox))
        show_toast(app, "✓ Шлях скопійовано · вставте його (Ctrl+V) у налаштуваннях браузера", 2800)
    ttk.Button(bar, text="Копіювати шлях", command=copy_path).pack(side="left")
    ttk.Button(bar, text="Відкрити папку", command=lambda: open_folder(inbox)).pack(side="left", padx=8)

    browsers = ttk.LabelFrame(outer, text=" Що зараз налаштовано у вашому браузері ", padding=10)
    browsers.pack(fill="x", pady=(0, 8))
    win.browsers_frame = browsers

    def refresh():
        for child in browsers.winfo_children():
            child.destroy()
        downloads = lecture_inbox.downloads_dir()
        found = bd.detect()
        win.found = found
        if not found:
            ttk.Label(browsers, wraplength=800, justify="left",
                      text="Chrome, Edge чи Brave не знайдено (можливо, у вас Firefox). Нічого страшного: змініть папку "
                           "завантажень у своєму браузері вручну — вставте шлях із буфера обміну.").pack(anchor="w")
            return
        shown = set()
        for item in found:
            if item.browser in shown:                                   # профілів може бути кілька; показуємо за браузером
                continue
            shown.add(item.browser)
            kind = bd.classify(item, inbox, downloads)
            text, color = status_text(kind)
            row = ttk.Frame(browsers)
            row.pack(fill="x", pady=3)
            where = str(item.folder) if item.folder else f"{downloads} (за замовчуванням)"
            ttk.Label(row, text=f"{item.browser}: зберігає в {where}", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            line = ttk.Frame(row)
            line.pack(fill="x")
            ttk.Label(line, text=text, foreground=color, wraplength=640, justify="left").pack(side="left")
            ttk.Button(line, text=f"Відкрити налаштування {item.browser}",
                       command=lambda name=item.browser: _open(name)).pack(side="right")

    def _open(name):
        if not bd.open_settings(name):
            show_toast(app, f"Не вдалося відкрити {name}: відкрийте {bd.settings_url(name)} вручну", 4000, "warn")
        else:
            show_toast(app, f"Відкриваю налаштування {name}… далі кроки 3–5", 2600)

    refresh()
    ttk.Label(outer, text=STEPS, justify="left", wraplength=820).pack(anchor="w", pady=(0, 8))
    ttk.Label(outer, text=NOTE, justify="left", wraplength=820, foreground="#5E5039").pack(anchor="w")
    buttons = ttk.Frame(outer)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="Перевірити ще раз", command=lambda: (refresh(), app.__dict__.pop("_bf_ts", None))).pack(side="left")
    ttk.Button(buttons, text="Закрити", command=win.destroy).pack(side="right")
    win.refresh = refresh
    return win
