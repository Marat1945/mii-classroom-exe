"""Панель повітряної тривоги (малюнок) та вікно вибору місця й джерела даних."""
from __future__ import annotations

import threading
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import ttk

from . import air_alerts as aa
from . import retro_assets as assets
from .toast import show_toast
from .window_ui import fit_work_window

WIDTH, HEIGHT, PLATE_HEIGHT = 250, 268, 208
LEVEL_COLORS = {aa.RED: (255, 111, 94), aa.YELLOW: (246, 196, 49)}
CAPTION = "Натисніть на малюнок: можна вибрати будь-який населений пункт України. Зараз обрано: {place}"
SUBTITLES = {
    aa.RED: "Терміново пройдіть до найближчого укриття.",
    aa.YELLOW: "Будьте готові перейти до укриття.",
    aa.NONE: "",
    aa.UNKNOWN: "Підключіть джерело даних: натисніть на малюнок.",
}
TITLES = {aa.RED: "Повітряна тривога", aa.YELLOW: "Жовтий рівень", aa.NONE: "Тривоги немає",
          aa.UNKNOWN: "Немає даних про тривогу"}


class AlertPanel(tk.Canvas):
    """Червоний — бомбочка в червоному колі; жовтий — в жовтому; немає тривоги й немає даних — лише напис."""

    def __init__(self, parent, on_click):
        super().__init__(parent, width=WIDTH, height=HEIGHT, highlightthickness=0, bd=0, bg="#E9DDBF", cursor="hand2")
        self.on_click = on_click
        self.level = aa.UNKNOWN
        self.place = aa.DEFAULT_PLACE["name"]
        self.detail = ""
        self.stamp = ""
        self._images = []
        self._icons = {}
        self._preview_job = None
        self._real = None
        self.title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.sub_font = tkfont.Font(family="Segoe UI", size=10)
        self.small_font = tkfont.Font(family="Segoe UI", size=8)
        self.bind("<Button-1>", lambda _e: self.on_click())
        self.draw()

    def show(self, status: aa.Status, place: str):
        """Показати реальний стан (під час демонстрації він запам'ятовується й повертається після неї)."""
        self._real = (status, place)
        if self._preview_job:
            return
        self._apply(status, place)

    def _apply(self, status: aa.Status, place: str):
        self.level, self.place, self.detail = status.level, place, status.detail
        self.stamp = time.strftime("Станом на %H:%M", time.localtime(status.checked_at)) \
            if status.level == aa.NONE and status.checked_at else ""
        self.draw()

    def preview(self, level: str, seconds: float = 8.0):
        """Показати, як виглядає стан (для вікна налаштувань), і повернути реальний через кілька секунд."""
        if self._preview_job:
            self.after_cancel(self._preview_job)
        sample = aa.Status(level, TITLES[level], SUBTITLES[level], time.time())
        self._apply(sample, self.place)
        self._preview_job = self.after(int(seconds * 1000), self._end_preview)

    def _end_preview(self):
        self._preview_job = None
        if self._real:
            self._apply(*self._real)

    def _icon(self, level):
        if level not in self._icons and assets.available():
            self._icons[level] = assets.photo(assets.alert_icon(LEVEL_COLORS[level], 108), self)
        return self._icons.get(level)

    def draw(self):
        self.delete("all")
        self._images = []
        if assets.available():
            plate = assets.photo(assets.plate_image(WIDTH - 6, PLATE_HEIGHT), self)
            self._images.append(plate)
            self.create_image(3, 3, anchor="nw", image=plate)
        else:
            self.create_rectangle(3, 3, WIDTH - 3, PLATE_HEIGHT, fill="#242A26", outline="#12150F")
        cream = "#F1EAD2"
        if self.level in LEVEL_COLORS:
            icon = self._icon(self.level)
            if icon:
                self.create_image(WIDTH // 2, 62, image=icon)
            self.create_text(WIDTH // 2, 134, text=TITLES[self.level], font=self.title_font, fill=cream,
                             width=WIDTH - 30, justify="center")
            self.create_text(WIDTH // 2, 176, text=self.detail or SUBTITLES[self.level], font=self.sub_font,
                             fill="#C9C2A8", width=WIDTH - 36, justify="center")
        else:
            self.create_text(WIDTH // 2, 86, text=TITLES[self.level], font=self.title_font,
                             fill=cream if self.level == aa.NONE else "#C9C2A8", width=WIDTH - 30, justify="center")
            self.create_text(WIDTH // 2, 138, font=self.sub_font, fill="#C9C2A8", width=WIDTH - 36, justify="center",
                             text=self.stamp or self.detail or SUBTITLES[self.level])
        self.create_text(WIDTH // 2, PLATE_HEIGHT + 28, text=CAPTION.format(place=self.place), font=self.small_font,
                         fill="#5E5039", width=WIDTH - 18, justify="center")

    def text_items(self) -> list:
        return [self.itemcget(i, "text") for i in self.find_all() if self.type(i) == "text"]


def show_alert_setup(app):
    """Вікно: місце (область/район/громада), джерело (ключ), пояснення кольорів, демонстрація вигляду."""
    from .engine import DATA
    settings = aa.load_settings(DATA)
    win = tk.Toplevel(app)
    win.title("Повітряна тривога: місце й джерело даних")
    fit_work_window(win, "normal")
    win.transient(app)
    win.escape_closes = True
    outer = ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, wraplength=820, justify="left",
              text="Малюнок показує, чи є повітряна тривога в місці, де ви працюєте. Дані беруться з офіційних джерел, "
                   "але доступ до них дають лише за ключем: його видають за заявкою на сайті джерела (умови видачі "
                   "дивіться там). Програма нічого не публікує й не замінює сирену та сповіщення «Повітряна тривога».").pack(anchor="w")

    place_box = ttk.LabelFrame(outer, text=" 1. Де ви працюєте ", padding=10)
    place_box.pack(fill="x", pady=(10, 6))
    chosen = {"place": dict(settings["place"])}
    chosen_var = tk.StringVar(master=win, value="Обрано: " + aa.place_text(settings["place"]))
    win.chosen_var = chosen_var
    query = tk.StringVar(master=win)
    win.query = query
    row = ttk.Frame(place_box)
    row.pack(fill="x")
    ttk.Label(row, text="Пошук:").pack(side="left")
    entry = ttk.Entry(row, textvariable=query)
    entry.pack(side="left", fill="x", expand=True, padx=6)
    box = tk.Listbox(place_box, height=6, exportselection=False)
    box.pack(fill="x", pady=(6, 4))
    win.places_box = box
    ttk.Label(place_box, textvariable=chosen_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
    options = []

    def refill(*_):
        nonlocal options
        index = _cached_index(DATA)
        options = aa.search_places(query.get(), index)
        box.delete(0, "end")
        for label, _place in options:
            box.insert("end", label)
    win.refill = refill

    def pick(_event=None):
        selection = box.curselection()
        if selection:
            chosen["place"] = dict(options[selection[0]][1])
            chosen_var.set("Обрано: " + aa.place_text(chosen["place"]))
    box.bind("<<ListboxSelect>>", pick)
    query.trace_add("write", refill)
    refill()

    source_box = ttk.LabelFrame(outer, text=" 2. Джерело даних ", padding=10)
    source_box.pack(fill="x", pady=(0, 6))
    provider = tk.StringVar(master=win, value=settings["provider"])
    win.provider = provider
    for value, name in aa.PROVIDER_NAMES.items():
        ttk.Radiobutton(source_box, text=name, value=value, variable=provider).pack(anchor="w")
    key_row = ttk.Frame(source_box)
    key_row.pack(fill="x", pady=(6, 0))
    ttk.Label(key_row, text="Ключ:").pack(side="left")
    key = tk.StringVar(master=win, value=settings["key"])
    win.key = key
    ttk.Entry(key_row, textvariable=key, show="•").pack(side="left", fill="x", expand=True, padx=6)
    ttk.Button(key_row, text="Отримати ключ (відкрити сайт)",
               command=lambda: webbrowser.open(aa.KEY_FORMS[provider.get()])).pack(side="left")
    result = tk.StringVar(master=win, value="")
    win.result = result
    ttk.Label(source_box, textvariable=result, wraplength=780, justify="left", foreground="#5E5039").pack(anchor="w", pady=(6, 0))

    legend = ttk.LabelFrame(outer, text=" 3. Що означають кольори ", padding=10)
    legend.pack(fill="x", pady=(0, 6))
    ttk.Label(legend, wraplength=800, justify="left", text=(
        "ЧЕРВОНИЙ (бомбочка в червоному колі) — повітряна тривога у вашому місці або в області чи районі, що його включає.\n"
        "ЖОВТИЙ (бомбочка в жовтому колі) — у вашому місці інша загроза, або тривога в іншій частині вашої області.\n"
        "ТРИВОГИ НЕМАЄ — лише коли дані свіжі (не старші за 3 хвилини). НЕМАЄ ДАНИХ — немає ключа, зв'язку або дані "
        "застаріли; тоді програма НІКОЛИ не пише «тривоги немає».\n"
        "Державні жовтий і червоний рівні загрози запроваджуються, але відкритих даних про рівень поки немає: "
        "тому це правило програми.")).pack(anchor="w")

    demo = ttk.Frame(outer)
    demo.pack(fill="x", pady=(0, 6))
    ttk.Label(demo, text="Показати вигляд на 8 с:").pack(side="left")
    for level, label in ((aa.RED, "Червоний"), (aa.YELLOW, "Жовтий"), (aa.NONE, "Тривоги немає"), (aa.UNKNOWN, "Немає даних")):
        ttk.Button(demo, text=label, command=lambda lv=level: app.alert_panel.preview(lv)).pack(side="left", padx=4)

    def collect():
        return {"provider": provider.get(), "key": key.get().strip(), "place": chosen["place"]}

    def check():
        """Перевірка у фоні; результат забирає головний потік (Tk із чужого потоку не чіпаємо)."""
        result.set("Перевіряю…")
        snapshot = collect()
        holder = {}

        def work():
            holder["status"] = aa.fetch_status(snapshot, DATA)
        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                if not win.winfo_exists():
                    return
                status = holder.get("status")
                if status is None:
                    win.after(150, poll)
                    return
                result.set(f"{status.title}. {status.detail}".strip()
                           + (f" (джерело: {status.source})" if status.source else ""))
            except tk.TclError:
                return
        win.after(150, poll)

    def save():
        aa.save_settings(DATA, collect())
        app.alert_settings_changed()
        show_toast(app, "✓ Налаштування тривоги збережено", 2400)
        win.destroy()

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x", pady=(6, 0))
    ttk.Button(buttons, text="Перевірити зараз", command=check).pack(side="left")
    ttk.Button(buttons, text="Зберегти", command=save).pack(side="right")
    ttk.Button(buttons, text="Закрити", command=win.destroy).pack(side="right", padx=8)
    win.collect, win.save, win.check = collect, save, check
    return win


def _cached_index(data_dir):
    """Дерево областей із кешу (якщо вже завантажувалось із ключем); інакше None."""
    import json
    from pathlib import Path
    try:
        return aa.walk_tree(json.loads((Path(data_dir) / aa.REGIONS_NAME).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
