"""Невеликі спільні елементи оформлення: помітна кнопка, кольори."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk

ACCENT="#1D4A7D"
ACCENT_HOVER="#2A62A0"
ACCENT_DARK="#143A63"
SOFT="#EFE6CB"


class AccentButton(tk.Button):
    """Яскрава кнопка для головних дій; працює в будь-якій темі Windows."""

    def __init__(self,master,text,command=None,color=ACCENT,hover=ACCENT_HOVER,**kw):
        font=kw.pop("font",("Segoe UI",10,"bold"))
        super().__init__(master,text=text,command=command,bg=color,fg="#F2E9CC",
                         activebackground=ACCENT_DARK,activeforeground="#F2E9CC",
                         relief="raised",bd=3,padx=14,pady=5,font=font,          # опукла металева пластина
                         cursor="hand2",highlightthickness=0,**kw)
        self._color,self._hover=color,hover
        self.bind("<Enter>",lambda _:self.config(bg=self._hover))
        self.bind("<Leave>",lambda _:self.config(bg=self._color))


class FlowRow(ttk.Frame):
    """Рядок кнопок: усе в один ряд, а на вузькому екрані зайве саме переходить на наступний рядок.

    Елементи з right=True на широкому екрані притиснуті до правого краю; на вузькому йдуть у потік останніми.
    Позиції обчислюються й ставляться через place(): рядки не впливають один на одного.
    """

    def __init__(self, master):
        super().__init__(master, height=1)
        self._items = []
        self._last = None
        self.bind("<Configure>", self._layout)

    def add(self, widget, padx=3, pady=2, right=False):
        self._items.append((widget, padx, pady, right))
        self._layout()
        return widget

    def _layout(self, _event=None):
        if not self._items:
            return
        width = self.winfo_width()
        if width <= 1:
            width = 10 ** 6                                  # ще не показано: один рядок
        need = lambda item: item[0].winfo_reqwidth() + 2 * item[1]
        row_height = max(i[0].winfo_reqheight() + 2 * i[2] for i in self._items)
        left = [i for i in self._items if not i[3]]
        right = [i for i in self._items if i[3]]
        places, rows = [], 1
        if sum(map(need, left)) + sum(map(need, right)) <= width:
            x = 0
            for item in left:
                places.append((item, x + item[1], 0))
                x += need(item)
            x = width
            for item in reversed(right):
                x -= need(item)
                places.append((item, x + item[1], 0))
        else:
            x = row = 0
            for item in left + right:
                if x and x + need(item) > width:
                    row, x = row + 1, 0
                places.append((item, x + item[1], row))
                x += need(item)
            rows = row + 1
        for item, x, row in places:
            item[0].place(x=x, y=row * row_height + max(0, (row_height - item[0].winfo_reqheight()) // 2))
        key = (width, rows, row_height)
        if key != self._last:
            self._last = key
            self.configure(height=rows * row_height)
