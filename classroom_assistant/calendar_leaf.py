"""Листочок відривного календаря (за зразком старих календарів): старий папір, рік, велике червоне число з місяцем
і днем тижня, схід і захід сонця, а нижче — хроніка дня: свята й події (насамперед Друга світова війна та історія України).

Один і той самий малюнок у двох масштабах: зменшений на головному екрані (повний, нічого не обрізано) і великий у
власному вікні після клацу. Усю розкладку (переноси рядків, місце під кожну подію) рахує програма в «проєктних»
розмірах 420×620, а потім масштабує, тож мініатюра — точна зменшена копія великого листка.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import font as tkfont

from . import retro_assets, sun_moon

MONTHS = ("СІЧЕНЬ", "ЛЮТИЙ", "БЕРЕЗЕНЬ", "КВІТЕНЬ", "ТРАВЕНЬ", "ЧЕРВЕНЬ", "ЛИПЕНЬ", "СЕРПЕНЬ", "ВЕРЕСЕНЬ",
          "ЖОВТЕНЬ", "ЛИСТОПАД", "ГРУДЕНЬ")
WEEKDAYS = ("ПОНЕДІЛОК", "ВІВТОРОК", "СЕРЕДА", "ЧЕТВЕР", "П'ЯТНИЦЯ", "СУБОТА", "НЕДІЛЯ")
INK, RED, MUTED = "#2B2218", "#C7332D", "#5E5039"
SHADOW, BACKGROUND = "#7A6F55", "#E9DDBF"
DESIGN_W, DESIGN_H = 420, 620                          # «проєктний» розмір листка
PAPER_BOX = (8, 8, DESIGN_W - 12, DESIGN_H - 12)       # де лежить папір
BODY_BOTTOM = DESIGN_H - 56                            # нижче цього подій немає (там підпис джерела)
SERIF = "Times New Roman"
HEAVY_FAMILIES = ("Arial Black", "Impact", "Franklin Gothic Heavy", "Segoe UI Black", "Georgia")
YEAR_X, TEXT_X, TEXT_RIGHT = 32, 98, DESIGN_W - 34     # стовпчик років і стовпчик тексту


def spaced(text: str) -> str:
    return " ".join(text)


def wrap(text: str, font: tkfont.Font, width: int) -> list:
    """Жадібний перенос за словами за вимірюваною шириною (однаково для будь-якого масштабу)."""
    lines, current = [], ""
    for word in text.split():
        trial = word if not current else current + " " + word
        if font.measure(trial) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class CalendarLeaf(tk.Canvas):
    def __init__(self, parent, scale: float = 0.47, on_click=None):
        self.scale = scale
        super().__init__(parent, width=round(DESIGN_W * scale), height=round(DESIGN_H * scale),
                         highlightthickness=0, bd=0, bg=BACKGROUND, cursor="hand2" if on_click else "")
        self._dirty = False
        self.day = None
        self.lines = []
        self.note = ""
        self.data = None                                   # Сонце: схід, захід, тривалість дня
        self.shown = []                                    # [(вид, текст)] — що справді вмістилося на листку
        self._design, self._real, self._images = {}, {}, []
        self._heavy = None
        if on_click:
            self.bind("<Button-1>", lambda _e: on_click())
        self.draw()

    # ---------- шрифти: проєктні (для вимірювання) і справжні (масштабовані) ----------
    def _font(self, px, weight="normal", slant="roman", real=False, family=None):
        cache = self._real if real else self._design
        size = max(4, int(px * self.scale)) if real else px                  # округлення вниз: текст не виступає за папір
        key = (px, weight, slant, real, family)
        if key not in cache:
            cache[key] = tkfont.Font(family=family or SERIF, size=-size, weight=weight, slant=slant)
        return cache[key]

    def _heavy_family(self):
        if self._heavy is None:
            available = set(tkfont.families(self))
            self._heavy = next((f for f in HEAVY_FAMILIES if f in available), "Georgia")
        return self._heavy

    def _text(self, x, y, text, px, weight="normal", slant="roman", fill=INK, anchor="nw", family=None):
        k = self.scale
        return self.create_text(x * k, y * k, anchor=anchor, text=text, fill=fill,
                                font=self._font(px, weight, slant, real=True, family=family))

    def _line(self, x1, y1, x2, y2, fill=INK, width=2):
        k = self.scale
        self.create_line(x1 * k, y1 * k, x2 * k, y2 * k, fill=fill, width=max(1, round(width * k)))

    def set_scale(self, scale: float, redraw: bool = True):
        """Інший розмір того самого листка (на низьких екранах мініатюра стискається)."""
        same = abs(scale - self.scale) < 0.003 and int(self.cget("height")) == round(DESIGN_H * scale)
        if same and not (redraw and self._dirty):
            return
        self.scale = scale
        self._real = {}
        self.configure(width=round(DESIGN_W * scale), height=round(DESIGN_H * scale))
        if redraw:
            self.draw()
        else:
            self._dirty = True

    # ---------- дані ----------
    def show(self, day: date, lat: float, lon: float, lines, note: str = ""):
        """note — підпис джерела внизу: «за матеріалами Вікіпедії (CC BY-SA)» лише коли дані справді звідти."""
        self.day, self.lines, self.note = day, list(lines), note
        self.data = sun_moon.sun_card(day, lat, lon)
        self.draw()

    # ---------- малювання ----------
    def draw(self):
        self.delete("all")
        self._dirty = False
        self.shown, self._images = [], []
        k = self.scale
        left, top, right, bottom = PAPER_BOX
        self.create_rectangle((left + 8) * k, (top + 10) * k, (right + 8) * k, (bottom + 10) * k, fill=SHADOW, outline="")
        if retro_assets.available():                                                      # папір зі слідами часу
            width, height = round((right - left) * k), round((bottom - top) * k)
            paper = retro_assets.photo(retro_assets.paper_image(width, height, seed=7), self)
            self._images.append(paper)
            self.create_image(left * k, top * k, anchor="nw", image=paper)
        else:
            self.create_rectangle(left * k, top * k, right * k, bottom * k, fill="#EEDBB6", outline="#96805C")
        if self.day is None:
            return
        day = self.day
        self._header(day)
        self._columns(day)
        self._body(312)
        if self.note:
            self._text(DESIGN_W / 2 - 4, DESIGN_H - 34, self.note, 12, fill=MUTED, anchor="center")

    def _header(self, day):
        self._text(YEAR_X, 46, spaced(str(day.year)), 22, "bold", anchor="w")
        self._text(DESIGN_W - YEAR_X - 4, 46, spaced(str(day.year)), 22, "bold", anchor="e")
        self._line(26, 66, DESIGN_W - 30, 66, width=4)

    def _columns(self, day):
        cx = DESIGN_W / 2 - 4
        month, month_px = spaced(MONTHS[day.month - 1]), 26
        while month_px > 16 and self._font(month_px, "bold").measure(month) > 188:        # довга назва не наїжджає на колонки
            month_px -= 1
        self._text(cx, 96, month, month_px, "bold", fill=RED, anchor="center")
        heavy = self._heavy_family()
        number, px = str(day.day), 168
        while px > 90 and self._font(px, "bold", family=heavy).measure(number) > 196:       # число має вмістись у середину
            px -= 6
        self._text(cx, 178, number, px, "bold", fill=RED, anchor="center", family=heavy)
        weekday = WEEKDAYS[day.weekday()]
        label = spaced(weekday) if self._font(21, "bold").measure(spaced(weekday)) <= 190 else weekday
        self._text(cx, 264, label, 21, "bold", fill=RED, anchor="center")
        data = self.data
        left_x, right_x = 69, DESIGN_W - 69
        if data:
            for y, text, px_, weight in ((98, "Схід сонця", 14, "normal"), (121, data["sunrise"], 22, "bold"),
                                         (158, "Захід сонця", 14, "normal"), (181, data["sunset"], 22, "bold")):
                self._text(left_x, y, text, px_, weight, anchor="center")
            for y, text, px_, weight in ((98, "Тривалість", 14, "normal"), (115, "дня", 14, "normal"),
                                         (141, data["hours"], 20, "bold"), (166, data["minutes"], 20, "bold")):
                self._text(right_x, y, text, px_, weight, anchor="center")
        self._line(26, 206, 112, 206, width=2)
        self._line(DESIGN_W - 112, 206, DESIGN_W - 26, 206, width=2)
        self._text(right_x, 224, "День року", 14, anchor="center")
        self._text(right_x, 246, f"{day.timetuple().tm_yday}-й", 20, "bold", anchor="center")
        self._line(26, 292, DESIGN_W - 30, 292, width=2)

    def _body(self, y):
        """Хроніка дня: цілі пункти, скільки вміститься (рік — у лівому стовпчику, текст — праворуч)."""
        width, line_height, gap = TEXT_RIGHT - TEXT_X, 19, 10
        if not self.lines:
            for text in wrap("Свята й події цього дня з'являться, коли буде зв'язок з інтернетом.",
                             self._font(15, slant="italic"), TEXT_RIGHT - YEAR_X):
                self._text(YEAR_X, y, text, 15, slant="italic", fill=MUTED)
                y += line_height
            return
        for kind, text in self.lines:
            holiday = kind == "holiday"
            year = None
            if not holiday and " р. — " in text:
                year, text = text.split(" р. — ", 1)
            weight, slant = ("bold", "roman") if holiday else ("normal", "italic")
            rows = wrap(text, self._font(14, weight, slant), width)
            if y + len(rows) * line_height > BODY_BOTTOM and self.shown:
                break                                                                       # пункт цілком не вміщається — пропускаємо
            if holiday:
                self._text(YEAR_X, y + 2, "Свято", 13, "bold", fill=RED)
            elif year:
                self._text(YEAR_X, y - 1, year, 18, "bold")
            for row in rows:
                self._text(TEXT_X, y, row, 14, weight, slant, fill=RED if holiday else INK)
                y += line_height
            self.shown.append((kind, f"{year} р. — {text}" if year and not holiday else text))
            y += gap

    def text_items(self) -> list:
        return [self.itemcget(i, "text") for i in self.find_all() if self.type(i) == "text"]


def full_scale(screen_height: int) -> float:
    """Масштаб великого листка: збільшений для читабельності, але щоб вмістився на екрані (із запасом на рамку вікна)."""
    return max(0.55, min(1.2, (screen_height * 0.88 - 60) / DESIGN_H))


def show_leaf_window(app):
    """Великий листок. Відкривається ОДИН раз: повторний клац лише виносить його наперед."""
    from .theme import add_rivets
    from .window_ui import remember_window, reuse_window
    existing = reuse_window(app, "leaf")
    if existing:
        return existing
    win = tk.Toplevel(app)
    remember_window(app, "leaf", win)
    win.title("Листочок календаря")
    win.resizable(False, False)
    win.transient(app)
    win.escape_closes = True
    leaf = CalendarLeaf(win, scale=full_scale(win.winfo_screenheight()))
    leaf.pack(padx=16, pady=16)
    win.leaf = leaf
    add_rivets(win)
    app._refresh_leaf()                                                   # наповнити листок (і малий, і великий)
    win.update_idletasks()
    x = max(0, (win.winfo_screenwidth() - win.winfo_reqwidth()) // 2)
    y = max(0, (win.winfo_screenheight() - win.winfo_reqheight()) // 3)
    win.geometry(f"+{x}+{y}")
    return win
