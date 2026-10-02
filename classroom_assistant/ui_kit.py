"""Невеликі спільні елементи оформлення: помітна кнопка, кольори."""
from __future__ import annotations
import tkinter as tk

ACCENT="#1F6FB2"
ACCENT_HOVER="#2B86D1"
ACCENT_DARK="#164F82"
SOFT="#EAF2FA"


class AccentButton(tk.Button):
    """Яскрава кнопка для головних дій; працює в будь-якій темі Windows."""

    def __init__(self,master,text,command=None,color=ACCENT,hover=ACCENT_HOVER,**kw):
        font=kw.pop("font",("Segoe UI",10,"bold"))
        super().__init__(master,text=text,command=command,bg=color,fg="white",
                         activebackground=ACCENT_DARK,activeforeground="white",
                         relief="flat",bd=0,padx=16,pady=7,font=font,
                         cursor="hand2",highlightthickness=0,**kw)
        self._color,self._hover=color,hover
        self.bind("<Enter>",lambda _:self.config(bg=self._hover))
        self.bind("<Leave>",lambda _:self.config(bg=self._color))
