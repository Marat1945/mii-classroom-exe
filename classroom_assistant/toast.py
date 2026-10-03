"""Короткі спливні повідомлення без кнопок: з'являються на 2–3 секунди й зникають самі."""
from __future__ import annotations

import tkinter as tk


def show_toast(parent, text, ms=2400, kind="ok"):
    """Повідомлення знизу по центру вікна. Без кнопок, не забирає фокус, зникає саме."""
    try:
        top_level = parent.winfo_toplevel()
        toast = tk.Toplevel(top_level)
        toast.overrideredirect(True)
        try:
            toast.attributes("-topmost", True)
        except tk.TclError:
            pass
        colors = {"ok": ("#1F4E79", "white"), "warn": ("#9B6A00", "white")}
        background, foreground = colors.get(kind, colors["ok"])
        label = tk.Label(toast, text=text, bg=background, fg=foreground, font=("Segoe UI", 11, "bold"),
                         padx=20, pady=11, justify="left", wraplength=860)
        label.pack()
        toast.update_idletasks()
        width, height = toast.winfo_reqwidth(), toast.winfo_reqheight()
        x = top_level.winfo_rootx() + max(0, (top_level.winfo_width() - width) // 2)
        y = top_level.winfo_rooty() + max(0, top_level.winfo_height() - height - 70)
        toast.geometry(f"+{x}+{y}")
        toast.after(ms, lambda: _close(toast))
        parent_toasts = getattr(top_level, "_toasts", [])
        parent_toasts.append(toast)
        top_level._toasts = parent_toasts
        return toast
    except tk.TclError:
        return None


def _close(toast):
    try:
        toast.destroy()
    except tk.TclError:
        pass
