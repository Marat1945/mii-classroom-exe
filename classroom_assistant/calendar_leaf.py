"""Листочок відривного календаря (у дусі старих настінних календарів): число, місяць, день тижня, схід і захід
сонця, Місяць і коротко — свята та події цього дня."""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import font as tkfont

from . import sun_moon

MONTHS = ("СІЧЕНЬ", "ЛЮТИЙ", "БЕРЕЗЕНЬ", "КВІТЕНЬ", "ТРАВЕНЬ", "ЧЕРВЕНЬ", "ЛИПЕНЬ", "СЕРПЕНЬ", "ВЕРЕСЕНЬ",
          "ЖОВТЕНЬ", "ЛИСТОПАД", "ГРУДЕНЬ")
WEEKDAYS = ("ПОНЕДІЛОК", "ВІВТОРОК", "СЕРЕДА", "ЧЕТВЕР", "П'ЯТНИЦЯ", "СУБОТА", "НЕДІЛЯ")
PAPER, PAPER_EDGE, SHADOW, INK = "#F1E3BD", "#A89466", "#7A6F55", "#1B1710"
WIDTH, HEIGHT = 250, 268


def spaced(text: str) -> str:
    return " ".join(text)


class CalendarLeaf(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=WIDTH, height=HEIGHT, highlightthickness=0, bd=0)
        self.day = None
        self.lines = []
        self.sun = None
        self.fonts = {
            "big": tkfont.Font(family="Georgia", size=62, weight="bold"),
            "head": tkfont.Font(family="Georgia", size=9, weight="bold"),
            "small": tkfont.Font(family="Georgia", size=8),
            "month": tkfont.Font(family="Georgia", size=11, weight="bold"),
            "body": tkfont.Font(family="Georgia", size=9, slant="italic"),
            "bodyb": tkfont.Font(family="Georgia", size=9, weight="bold"),
            "tiny": tkfont.Font(family="Georgia", size=7),
        }
        self.draw()

    note = ""

    def show(self, day: date, lat: float, lon: float, lines, note: str = ""):
        """note — підпис джерела внизу: «за матеріалами Вікіпедії (CC BY-SA)» лише коли дані справді звідти."""
        self.day, self.lines, self.note = day, list(lines), note
        self.sun = sun_moon.sun_summary(day, lat, lon)
        self.draw()

    def draw(self):
        self.delete("all")
        self.configure(bg="#E9DDBF")
        self.create_rectangle(7, 9, WIDTH - 1, HEIGHT - 1, fill=SHADOW, outline="")               # тінь листка
        self.create_rectangle(3, 3, WIDTH - 6, HEIGHT - 8, fill=PAPER, outline=PAPER_EDGE, width=1)
        for x in (WIDTH // 2 - 40, WIDTH // 2 + 40):                                                 # лінія відриву
            self.create_oval(x - 3, 8, x + 3, 14, fill="#CDBE9A", outline=PAPER_EDGE)
        if self.day is None:
            return
        day = self.day
        doy = day.timetuple().tm_yday
        self.create_text(14, 28, anchor="w", text=str(day.year), font=self.fonts["head"], fill=INK)
        self.create_text(WIDTH // 2, 28, text="КАЛЕНДАР", font=self.fonts["tiny"], fill="#5E5039")
        self.create_text(WIDTH - 16, 28, anchor="e", text=f"№ {doy}", font=self.fonts["head"], fill=INK)
        self.create_line(10, 38, WIDTH - 12, 38, fill=INK)
        self.create_text(12, 78, anchor="w", text=str(day.day), font=self.fonts["big"], fill=INK)
        x = 132
        if self.sun:
            rise, sunset, length = self.sun
            for k, text in enumerate((f"Схід {rise}", f"Захід {sunset}", f"День {length}")):
                self.create_text(x, 52 + k * 14, anchor="w", text=text, font=self.fonts["small"], fill=INK)
        phase, light = sun_moon.moon_phase(day)
        kind, when = sun_moon.next_moon_event(day)
        self.create_text(x, 94, anchor="w", text=phase, font=self.fonts["tiny"], fill=INK)
        self.create_text(x, 106, anchor="w", text=f"{kind} {when.day:02d}.{when.month:02d}", font=self.fonts["tiny"],
                         fill=INK)
        self.create_line(10, 120, WIDTH - 12, 120, fill=PAPER_EDGE)
        month, weekday = spaced(MONTHS[day.month - 1]), WEEKDAYS[day.weekday()]
        red = "#7A1F1F" if day.weekday() >= 5 else INK
        self.create_text(12, 134, anchor="w", text=month, font=self.fonts["month"], fill=INK)
        fits = self.fonts["month"].measure(month) + self.fonts["head"].measure(weekday) + 24 < WIDTH - 26
        if fits:
            self.create_text(WIDTH - 14, 134, anchor="e", text=weekday, font=self.fonts["head"], fill=red)
            rule = 146
        else:                                                    # довгі назви: день тижня на власному рядку
            self.create_text(WIDTH - 14, 152, anchor="e", text=spaced(weekday), font=self.fonts["head"], fill=red)
            rule = 164
        self.create_line(10, rule, WIDTH - 12, rule, fill=INK)
        y = rule + 9
        if not self.lines:
            self.create_text(14, y, anchor="nw", width=WIDTH - 34, font=self.fonts["body"], fill="#5E5039",
                             text="Свята й події цього дня з'являться, коли буде зв'язок з інтернетом.")
        for kind, text in self.lines[:3]:
            head = "Свято: " if kind == "holiday" else "У цей день: "
            item = self.create_text(14, y, anchor="nw", width=WIDTH - 30, font=self.fonts["body"], fill=INK,
                                    text=head + text)
            box = self.bbox(item)
            y = (box[3] if box else y + 26) + 5
            if y > HEIGHT - 30:
                break
        if self.note:
            self.create_text(WIDTH // 2 - 2, HEIGHT - 17, text=self.note, font=self.fonts["tiny"], fill="#6B5E40")

    def text_items(self) -> list:
        return [self.itemcget(i, "text") for i in self.find_all() if self.type(i) == "text"]
