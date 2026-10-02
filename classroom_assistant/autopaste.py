"""Автоматичне вставлення запиту у вікно ChatGPT у браузері (лише Windows).

Програма НЕ керує сайтом ChatGPT: вона лише імітує ваше натискання Ctrl+V
(і, якщо ви самі ввімкнули, Enter) у вікні браузера. Запобіжники:
вставляємо ТІЛЬКИ коли поверх справді вікно браузера (не наша програма й не
Word чи інша), і перед вставкою ще раз кладемо запит у буфер обміну.
"""
from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from tkinter import ttk

BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe",
            "browser.exe", "yandex.exe", "iexplore.exe", "chrome_proxy.exe", "chatgpt.exe")
DEFAULT_DELAY = 5
EXTRA_WAIT = 8


class Win32Backend:
    """Справжнє Windows-середовище (ctypes, без додаткових бібліотек)."""

    available = sys.platform == "win32"

    def own_pid(self):
        return os.getpid()

    def foreground(self):
        """(pid, ім'я exe малими літерами) активного вікна або (0, '')."""
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0, ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)   # QUERY_LIMITED_INFORMATION
        if not handle:
            return pid.value, ""
        try:
            size = wintypes.DWORD(520)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return pid.value, os.path.basename(buffer.value).lower()
            return pid.value, ""
        finally:
            kernel32.CloseHandle(handle)

    def paste(self, send_enter=False):
        import ctypes
        keybd = ctypes.windll.user32.keybd_event
        CTRL, V, ENTER, UP = 0x11, 0x56, 0x0D, 0x0002
        keybd(CTRL, 0, 0, 0)
        keybd(V, 0, 0, 0)
        keybd(V, 0, UP, 0)
        keybd(CTRL, 0, UP, 0)
        if send_enter:
            time.sleep(0.5)
            keybd(ENTER, 0, 0, 0)
            keybd(ENTER, 0, UP, 0)


def browser_in_front(backend) -> bool:
    pid, name = backend.foreground()
    return bool(pid) and pid != backend.own_pid() and name in BROWSERS


class AutoPaste:
    """Відлік → перевірка вікна → вставка. Усі кроки повідомляються вчителю."""

    def __init__(self, window, backend, recopy, say, delay=DEFAULT_DELAY, send_enter=False,
                 extra_wait=EXTRA_WAIT):
        self.window, self.backend, self.recopy, self.say = window, backend, recopy, say
        self.left = max(1, int(delay))
        self.send_enter = send_enter
        self.extra = extra_wait
        self.finished = False

    def start(self):
        self._tick()
        return self

    def _later(self, callback):
        try:
            self.window.after(1000, callback)
        except tk.TclError:
            self.finished = True

    def _tick(self):
        if self.finished:
            return
        if self.left > 0:
            self.say(f"Через {self.left} с програма вставить запит у ChatGPT — "
                     "не торкайтесь клавіатури й миші…")
            self.left -= 1
            self._later(self._tick)
            return
        self._try()

    def _try(self):
        if self.finished:
            return
        if browser_in_front(self.backend):
            self.finished = True
            self.recopy()
            self.backend.paste(self.send_enter)
            self.say("Запит вставлено у ChatGPT" + (" і надіслано." if self.send_enter else
                     ". Перегляньте його й натисніть Enter."))
            return
        if self.extra > 0:
            self.extra -= 1
            self.say("Чекаю, поки браузер з ChatGPT вийде на передній план…")
            self._later(self._try)
            return
        self.finished = True
        self.say("Браузер не вийшов на передній план, тому автовставку не виконано. "
                 "Запит уже в буфері обміну: у ChatGPT натисніть Ctrl+V.")


def build_controls(parent, state, save):
    """Галочки «вставити автоматично» / «і надіслати» та час очікування (зберігаються)."""
    frame = ttk.Frame(parent)
    paste = tk.BooleanVar(value=bool(state.get("autopaste", True)))
    send = tk.BooleanVar(value=bool(state.get("autosend", False)))
    delay = tk.StringVar(value=str(state.get("autopaste_delay", DEFAULT_DELAY)))

    def store(*_):
        state["autopaste"] = paste.get()
        state["autosend"] = send.get()
        try:
            state["autopaste_delay"] = min(20, max(2, int(delay.get())))
        except ValueError:
            state["autopaste_delay"] = DEFAULT_DELAY
        try:
            save(state)
        except Exception:
            pass

    ttk.Checkbutton(frame, text="Вставити запит у ChatGPT автоматично (Ctrl+V)",
                    variable=paste, command=store).pack(side="left")
    ttk.Checkbutton(frame, text="і одразу надіслати (Enter)", variable=send,
                    command=store).pack(side="left", padx=(12, 0))
    ttk.Label(frame, text="чекати сторінку, с:").pack(side="left", padx=(12, 3))
    box = ttk.Spinbox(frame, from_=2, to=20, width=4, textvariable=delay, command=store)
    box.pack(side="left")
    box.bind("<FocusOut>", store)
    return frame


def start_autopaste(window, state, recopy, say, backend=None):
    """Запустити, якщо ввімкнено й це Windows. Повертає AutoPaste або None."""
    backend = backend or Win32Backend()
    if not state.get("autopaste", True):
        return None
    if not getattr(backend, "available", False):
        say("Автовставка працює лише у Windows. Запит у буфері: у ChatGPT натисніть Ctrl+V.")
        return None
    try:
        delay = int(state.get("autopaste_delay", DEFAULT_DELAY))
    except (TypeError, ValueError):
        delay = DEFAULT_DELAY
    return AutoPaste(window, backend, recopy, say, delay=delay,
                     send_enter=bool(state.get("autosend", False))).start()
