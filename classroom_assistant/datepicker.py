"""Вибір дати календарем (у Tk немає свого)."""
from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk

MONTHS = ("Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень",
          "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")
ACCENT, SOFT, MUTED = "#1F6FB2", "#EAF2FA", "#9AA9B8"


def parse_ui_date(text):
    try:
        return datetime.strptime(str(text).strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def month_grid(year, month):
    """Тижні місяця (понеділок першим): список списків дат."""
    return calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


class CalendarDialog(tk.Toplevel):
    def __init__(self, parent, initial=None, title="Оберіть дату", weekday=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self.weekday = weekday
        self.selected = initial or date.today()
        self.year, self.month = self.selected.year, self.selected.month
        self.escape_closes = True
        top = parent.winfo_toplevel()
        try:
            self.transient(top)
        except tk.TclError:
            pass
        head = ttk.Frame(self, padding=(8, 8, 8, 2))
        head.pack(fill="x")
        for text, delta, side in (("«", -12, "left"), ("‹", -1, "left")):
            ttk.Button(head, text=text, width=3, command=lambda d=delta: self._move(d)).pack(side=side)
        for text, delta in (("»", 12), ("›", 1)):
            ttk.Button(head, text=text, width=3, command=lambda d=delta: self._move(d)).pack(side="right")
        self.caption = ttk.Label(head, font=("Segoe UI", 11, "bold"), anchor="center")
        self.caption.pack(side="left", expand=True, fill="x")
        self.body = ttk.Frame(self, padding=(8, 2, 8, 4))
        self.body.pack()
        foot = ttk.Frame(self, padding=(8, 2, 8, 8))
        foot.pack(fill="x")
        ttk.Button(foot, text="Сьогодні", command=lambda: self.choose(date.today())).pack(side="left")
        ttk.Button(foot, text="Скасувати", command=self.destroy).pack(side="right")
        if weekday is not None:
            ttk.Label(self, text=f"Доступні лише: {WEEKDAYS[weekday]}", foreground="#365777",
                      padding=(8, 0, 8, 6)).pack(anchor="w")
        self.render()
        self.update_idletasks()
        try:
            x = parent.winfo_rootx()
            y = parent.winfo_rooty() + parent.winfo_height() + 2
            x = min(x, max(0, self.winfo_screenwidth() - self.winfo_reqwidth() - 10))
            y = min(y, max(0, self.winfo_screenheight() - self.winfo_reqheight() - 50))
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.bind("<Escape>", lambda _e: self.destroy())

    def _move(self, delta):
        self.year, self.month = shift_month(self.year, self.month, delta)
        self.render()

    def choose(self, picked):
        if self.weekday is not None and picked.weekday() != self.weekday:
            return
        self.result = picked
        self.destroy()

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.caption.config(text=f"{MONTHS[self.month - 1]} {self.year}")
        for column, name in enumerate(WEEKDAYS):
            ttk.Label(self.body, text=name, width=4, anchor="center",
                      foreground="#9B251F" if column >= 5 else "#245A7C").grid(row=0, column=column)
        today = date.today()
        for row, week in enumerate(month_grid(self.year, self.month), 1):
            for column, day in enumerate(week):
                inside = day.month == self.month
                allowed = self.weekday is None or day.weekday() == self.weekday
                is_selected = day == self.selected
                button = tk.Button(
                    self.body, text=str(day.day), width=4, relief="flat", bd=0, pady=4,
                    bg=ACCENT if is_selected else (SOFT if day == today else "white"),
                    fg="white" if is_selected else (("#1B2A3A" if inside else MUTED) if allowed else "#C9D2DB"),
                    activebackground="#2E7BC4", activeforeground="white",
                    state="normal" if allowed else "disabled",
                    cursor="hand2" if allowed else "arrow",
                    command=lambda d=day: self.choose(d))
                button.grid(row=row, column=column, padx=1, pady=1)
                button.bind("<Double-Button-1>", lambda _e, d=day: self.choose(d))


def pick_date(parent, text="", weekday=None, title="Оберіть дату"):
    """Повертає «ДД.ММ.РРРР» або None, якщо вчитель закрив календар."""
    dialog = CalendarDialog(parent, parse_ui_date(text), title=title, weekday=weekday)
    parent.wait_window(dialog)
    return dialog.result.strftime("%d.%m.%Y") if dialog.result else None


class DateField(ttk.Frame):
    """Поле дати + кнопка календаря."""

    def __init__(self, master, variable, weekday=None, width=14, title="Оберіть дату"):
        super().__init__(master)
        self.variable, self.weekday, self.title_text = variable, weekday, title
        self.entry = ttk.Entry(self, textvariable=variable, width=width)
        self.entry.pack(side="left")
        ttk.Button(self, text="📅", width=3, command=self.open).pack(side="left", padx=(3, 0))

    def open(self):
        chosen = pick_date(self.entry, self.variable.get(), self.weekday, self.title_text)
        if chosen:
            self.variable.set(chosen)
