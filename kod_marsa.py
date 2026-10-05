# -*- coding: utf-8 -*-
"""
«Код Марса» для компьютера (Windows).

Перенос Android-приложения «Код Марса» (16.06.2025) в альбомное окно.
Ключи, автокод по дате, ключ-фраза, AES-256 + Base32, морзянка и QR
устроены так же, как на телефоне, поэтому шифровки свободно ходят
между телефонами и компьютерами в обе стороны.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
import urllib.parse
import webbrowser
import zipfile
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageFilter, ImageTk

import marscore as core
import marsform as forms
import marsi18n as i18n
import marsmorse as morse
import marssstv as sstv
from marsi18n import T

try:
    from tkinterdnd2 import COPY, DND_FILES, DND_TEXT, TkinterDnD
    HAS_DND = True
except Exception:  # без перетаскивания программа тоже работает
    HAS_DND = False

IS_WIN = sys.platform == "win32"
OUT_FOLDER = "Код Марса"
SHARE_APPS = [("telegram", "Telegram"), ("viber", "Viber"), ("instagram", "Instagram"), ("deltachat", "Delta Chat")]

C = {
    "space": "#0C0F16", "space_text": "#F3EDE2", "space_dim": "#4C5262", "space_hover": "#252A38",
    "paper": "#F4EFE5", "card": "#FFFEFA", "line": "#DED5C4", "ink": "#1F1B16", "muted": "#766C60",
    "faint": "#A39888", "mars": "#C20000", "mars_hover": "#990000", "mars_soft": "#F5D8D3", "hover": "#EEE6D8",
}


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def enable_dpi_awareness():
    """Чёткие шрифты на экранах с масштабом 125–150 %."""
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KodMarsa.Desktop")
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def documents_dir():
    """Папка «Документы» (в Windows — настоящая, даже если перенесена в OneDrive)."""
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            folder_id = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                             (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            ptr = ctypes.c_wchar_p()
            fn = ctypes.windll.shell32.SHGetKnownFolderPath
            fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
            if fn(ctypes.byref(folder_id), 0, None, ctypes.byref(ptr)) == 0:
                path = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if path and os.path.isdir(path):
                    return path
        except Exception:
            pass
    home = os.path.expanduser("~")
    for name in ("Documents", "Документы"):
        if os.path.isdir(os.path.join(home, name)):
            return os.path.join(home, name)
    return home


def output_dir():
    folder = os.path.join(documents_dir(), OUT_FOLDER)
    os.makedirs(folder, exist_ok=True)
    return folder


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


def open_folder(path):
    try:
        if IS_WIN:
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------------- настройки (язык и т. п.)
def prefs_path():
    base = os.environ.get("APPDATA") if IS_WIN else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base or os.path.expanduser("~"), "KodMarsa", "settings.json")


def load_prefs():
    prefs = {"lang": "ru", "share": {k: True for k, _ in SHARE_APPS}, "morse": dict(morse.DEFAULTS), "sstv": ""}
    try:
        with open(prefs_path(), encoding="utf-8") as fh:
            saved = json.load(fh)
        prefs["lang"] = saved.get("lang", "ru")
        prefs["share"].update({k: bool(v) for k, v in saved.get("share", {}).items() if k in prefs["share"]})
        prefs["morse"].update({k: v for k, v in saved.get("morse", {}).items() if k in morse.DEFAULTS})
        prefs["sstv"] = saved.get("sstv", "") if saved.get("sstv", "") in sstv.MODES else ""
    except Exception:
        pass
    return prefs


def save_prefs(prefs):
    try:
        os.makedirs(os.path.dirname(prefs_path()), exist_ok=True)
        with open(prefs_path(), "w", encoding="utf-8") as fh:
            json.dump(prefs, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ---------------------------------------------------------------------- «Поделиться»
def _env_path(var, *parts):
    base = os.environ.get(var, "")
    return os.path.join(base, *parts) if base else ""


def find_exe(paths):
    return next((p for p in paths if p and os.path.isfile(p)), None)


def has_protocol(name):
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name + r"\shell\open\command"):
            return True
    except OSError:
        return False


def start_target(target):
    try:
        if IS_WIN and not os.path.isfile(target):
            os.startfile(target)
        elif os.path.isfile(target):
            subprocess.Popen([target])
        else:
            return False
        return True
    except Exception:
        return False


def copy_image_to_clipboard(img, hwnd):
    """Кладёт картинку в буфер обмена Windows (CF_DIB + PNG)."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]

    bmp, png = io.BytesIO(), io.BytesIO()
    img.convert("RGB").save(bmp, "BMP")
    img.convert("RGB").save(png, "PNG")

    def put(fmt, data):
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        if not handle:
            raise MemoryError("GlobalAlloc")
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(fmt, handle):
            kernel32.GlobalFree(handle)
            raise OSError("SetClipboardData")

    for _ in range(20):
        if user32.OpenClipboard(hwnd):
            break
        time.sleep(0.05)
    else:
        raise OSError("clipboard busy")
    try:
        user32.EmptyClipboard()
        put(8, bmp.getvalue()[14:])  # CF_DIB: BMP без файлового заголовка
        fmt_png = user32.RegisterClipboardFormatW("PNG")
        if fmt_png:
            put(fmt_png, png.getvalue())
    finally:
        user32.CloseClipboard()


class App:
    def __init__(self, root):
        self.root = root
        self.scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
        self.prefs = load_prefs()
        i18n.set_lang(self.prefs["lang"])
        self.morse_cfg = self.prefs["morse"]
        self.sstv_mode = self.prefs["sstv"] or None
        self.today = dt.date.today()
        self.auto_idx = core.auto_key_index(self.today)
        self.qr_mat = None          # матрица текущего QR-кода
        self.qr_err = None          # почему QR-кода нет (ошибка ядра)
        self.cipher_kid = None      # ключ текущей шифровки: ("list", n) / ("phrase", текст) / ("empty",)
        self._b32_prog = self._b32_last = ""
        self._morse_prog = self._morse_last = ""
        self._morse_src = None
        self._b32_job = self._morse_job = self._bs_job = None
        self._bs_press_t = 0.0
        self._toast_win = self._toast_job = None
        self._help_win = self._settings_win = None
        self._redraw_job = None
        self._drag_on = False
        self._status_err = False
        self._qr_box = None
        self._menu_vars = []
        self.history, self.hpos = [], -1          # операции этого сеанса
        self.form_seq, self.form_numbers = 0, {}  # номера бланков этого сеанса
        self.player = morse.Player()
        self._playing, self._play_job, self._glow_i, self._wav_n = False, None, 0, 0
        self._play = {}
        self._sstv_active, self._sstv_job, self._sstv_frac = False, None, None
        self._art_src = Image.open(resource("assets", "background.jpg")).convert("RGB")
        self._art_cache = {}
        self._make_fonts()
        self._make_style()
        self._make_images()
        self._build()
        self._bind_global()
        self._commit()
        self.root.after(60_000, self._day_tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def px(self, value):
        return int(round(value * self.scale))

    def _on_close(self):
        self.player.stop()
        self.root.destroy()

    def _save_prefs(self):
        self.prefs["morse"] = self.morse_cfg
        self.prefs["sstv"] = self.sstv_mode or ""
        save_prefs(self.prefs)

    # ------------------------------------------------------------------ вид
    def _make_fonts(self):
        families = set(tkfont.families(self.root))

        def pick(options, size):
            for family, weight in options:
                if family in families:
                    return tkfont.Font(root=self.root, family=family, size=size, weight=weight)
            f = tkfont.nametofont("TkDefaultFont").copy()
            f.configure(size=size)
            return f

        ui = [("Segoe UI", "normal"), ("DejaVu Sans", "normal")]
        ui_bold = [("Segoe UI Semibold", "normal"), ("DejaVu Sans", "bold")]
        mono = [("Consolas", "normal"), ("Cascadia Mono", "normal"),
                ("DejaVu Sans Mono", "normal"), ("Courier New", "normal")]
        self.f_title = pick([("Bahnschrift SemiBold Condensed", "normal"), ("Bahnschrift", "bold"),
                             ("Segoe UI Semibold", "normal"), ("DejaVu Sans Condensed", "bold"),
                             ("DejaVu Sans", "bold")], 19)
        self.f_head = pick([("Bahnschrift SemiBold", "normal"), ("Segoe UI Semibold", "normal"),
                            ("DejaVu Sans", "bold")], 12)
        self.f_btn = pick(ui_bold, 10)
        self.f_btn_small = pick(ui_bold, 9)
        self.f_arrow = pick(ui_bold, 13)
        self.f_body = pick(ui, 10)
        self.f_small = pick(ui, 9)
        self.f_text = pick(ui, 11)
        self.f_mono = pick(mono, 11)
        self.f_mono_small = pick(mono, 9)

    def _make_style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Mars.TCombobox", fieldbackground=C["card"], background=C["card"],
                     foreground=C["ink"], arrowcolor=C["ink"], bordercolor=C["line"],
                     lightcolor=C["card"], darkcolor=C["card"], padding=(self.px(8), self.px(5)),
                     arrowsize=self.px(14))
        st.map("Mars.TCombobox",
               fieldbackground=[("readonly", C["card"])], foreground=[("readonly", C["ink"])],
               selectbackground=[("readonly", C["card"])], selectforeground=[("readonly", C["ink"])],
               bordercolor=[("focus", C["mars"])], arrowcolor=[("active", C["mars"])],
               background=[("active", C["hover"])])
        for opt, val in (("background", C["card"]), ("foreground", C["ink"]),
                         ("selectBackground", C["mars"]), ("selectForeground", "#FFFFFF")):
            self.root.option_add(f"*TCombobox*Listbox.{opt}", val)
        self.root.option_add("*TCombobox*Listbox.font", str(self.f_text))
        st.configure("Mars.Vertical.TScrollbar", background=C["line"], troughcolor=C["card"],
                     bordercolor=C["card"], lightcolor=C["line"], darkcolor=C["line"],
                     arrowcolor=C["muted"], gripcount=0)
        st.map("Mars.Vertical.TScrollbar", background=[("active", C["faint"])])

    def _make_images(self):
        size, pad = self.px(28), self.px(5)
        full = size + 2 * pad
        icon = Image.open(resource("assets", "sound.png")).convert("RGBA").resize((size, size), Image.LANCZOS)
        self._snd_frames = []
        for k in range(14):
            im = Image.new("RGBA", (full, full), (0, 0, 0, 0))
            if k:
                glow = 0.55 + 0.45 * math.sin(2 * math.pi * (k - 1) / 13)
                halo = Image.new("RGBA", (full, full), (0, 0, 0, 0))
                r, c = size / 2 + pad * glow, full / 2
                ImageDraw.Draw(halo).ellipse((c - r, c - r, c + r, c + r), fill=(255, 186, 0, int(190 * glow)))
                im.alpha_composite(halo.filter(ImageFilter.GaussianBlur(pad * 0.55)))
            im.alpha_composite(icon, (pad, pad))
            self._snd_frames.append(ImageTk.PhotoImage(im))
        s = self.px(38)
        hdr = Image.open(resource("assets", "icon.png")).convert("RGBA").resize((s, s), Image.LANCZOS)
        self._hdr_icon = ImageTk.PhotoImage(hdr)
        self._icon_photo = ImageTk.PhotoImage(Image.open(resource("assets", "icon.png")))
        lang = Image.open(resource("assets", "lang.png")).convert("RGBA")
        self._lang_icon = ImageTk.PhotoImage(lang.resize((self.px(34), self.px(24)), Image.LANCZOS))
        menu_img = Image.open(resource("assets", "menu.png")).convert("RGBA")
        self._menu_icon = ImageTk.PhotoImage(menu_img.resize((self.px(22), self.px(18)), Image.LANCZOS))

    def _button(self, parent, text, command, kind="secondary", font=None, padx=14, pady=6, **extra):
        bg, fg, hover, border = {
            "primary": (C["mars"], "#FFFFFF", C["mars_hover"], C["mars"]),
            "secondary": (C["card"], C["ink"], C["hover"], C["line"]),
            "outline": (C["paper"], C["mars"], C["mars_soft"], C["mars"]),
            "dark": (C["space"], C["space_text"], C["space_hover"], "#3A3F4D"),
        }[kind]
        b = tk.Button(parent, text=text, command=command, font=font or self.f_btn, bg=bg, fg=fg,
                      activebackground=hover, activeforeground=fg, relief="flat", bd=0, justify="center",
                      highlightthickness=1, highlightbackground=border, disabledforeground=C["faint"],
                      highlightcolor=C["ink"] if kind == "primary" else C["mars"],
                      padx=self.px(padx), pady=self.px(pady), cursor="hand2", **extra)
        b.bind("<Enter>", lambda e: b.configure(bg=hover) if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def _small(self, parent, text, command):
        """Контурная кнопка «Копировать» / «Вставить»."""
        return self._button(parent, text, command, "outline", font=self.f_btn_small, padx=8, pady=1)

    def _heading(self, parent, text):
        return tk.Label(parent, text=text, font=self.f_head, fg=C["ink"], bg=parent.cget("bg"))

    def _note(self, parent, text):
        lbl = tk.Label(parent, text=text, font=self.f_small, fg=C["muted"], bg=parent.cget("bg"),
                       justify="left", anchor="w", wraplength=self.px(300))
        lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(self.px(120), e.width - 4)))
        return lbl

    def _menu(self, parent=None):
        return tk.Menu(parent or self.root, tearoff=0, font=self.f_body, bg=C["card"], fg=C["ink"],
                       activebackground=C["mars"], activeforeground="#FFFFFF", bd=1, relief="solid")

    def _popup_under(self, menu, widget):
        menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def _textbox(self, parent, font, wrap):
        box = tk.Frame(parent, bg=C["card"])
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)
        t = tk.Text(box, font=font, wrap=wrap, width=10, height=3, bg=C["card"], fg=C["ink"],
                    insertbackground=C["ink"], selectbackground=C["mars_soft"], selectforeground=C["ink"],
                    inactiveselectbackground=C["mars_soft"], relief="flat", bd=0, highlightthickness=1,
                    highlightbackground=C["line"], highlightcolor=C["mars"], padx=self.px(12),
                    pady=self.px(10), undo=True, maxundo=-1, spacing2=self.px(2), insertwidth=self.px(2))
        sb = ttk.Scrollbar(box, orient="vertical", command=t.yview, style="Mars.Vertical.TScrollbar")

        def on_scroll(first, last):
            if float(first) <= 0.0 and float(last) >= 1.0:
                sb.grid_remove()
            else:
                sb.grid(row=0, column=1, sticky="ns")
            sb.set(first, last)

        t.configure(yscrollcommand=on_scroll)
        t.grid(row=0, column=0, sticky="nsew")

        def on_modified(_e):
            if not t.edit_modified():
                return
            t.edit_modified(False)
            self._refresh_placeholder(t)
            if t is getattr(self, "b32", None):
                self._b32_changed()
            elif t is getattr(self, "morse", None):
                self._morse_changed()

        t.bind("<<Modified>>", on_modified, add="+")
        t.bind("<Button-3>", self._text_menu)
        t.bind("<KeyPress-BackSpace>", self._bs_press, add="+")
        t.bind("<KeyRelease-BackSpace>", self._bs_release, add="+")
        return box, t

    def _placeholder(self, widget, text):
        lbl = tk.Label(widget, text=text, font=self.f_body, fg=C["faint"], bg=widget.cget("bg"),
                       justify="left", anchor="nw", cursor="xterm")
        lbl.bind("<Button-1>", lambda e: widget.focus_set())
        if isinstance(widget, tk.Text):
            x, y = int(widget.cget("padx")) + 1, int(widget.cget("pady")) + 1
            place = {"x": x, "y": y}
            lbl.configure(wraplength=self.px(260))
            widget.bind("<Configure>", lambda e: lbl.configure(wraplength=max(60, e.width - 2 * x - 6)), add="+")
            lbl.bind("<Button-3>", lambda e: self._text_menu(e, widget))
        else:
            place = {"x": int(widget.cget("bd")) + 2, "rely": 0.5, "anchor": "w"}
        self._placeholders[widget] = (lbl, place)
        self._refresh_placeholder(widget)

    def _refresh_placeholder(self, widget):
        item = self._placeholders.get(widget)
        if not item:
            return
        lbl, place = item
        empty = widget.get("1.0", "end-1c") == "" if isinstance(widget, tk.Text) else widget.get() == ""
        if empty:
            lbl.place(**place)
        else:
            lbl.place_forget()

    # ------------------------------------------------------------------ окно
    def _build(self):
        r = self.root
        r.title(T("Код Марса"))
        r.configure(bg=C["paper"])
        self._placeholders = {}
        try:
            if IS_WIN:
                r.iconbitmap(default=resource("assets", "icon.ico"))
        except tk.TclError:
            pass
        try:
            r.iconphoto(True, self._icon_photo)
        except Exception:
            pass
        if not getattr(self, "_geometry_set", False):
            sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
            w, h = min(self.px(1240), sw - self.px(40)), min(self.px(740), sh - self.px(90))
            r.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - self.px(20))}")
            r.minsize(min(self.px(1180), w), min(self.px(640), h))
            self._geometry_set = True
        self._build_header()
        body = tk.Frame(r, bg=C["paper"])
        body.pack(fill="both", expand=True, padx=self.px(20), pady=(self.px(16), self.px(18)))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1, uniform="col")
        body.grid_columnconfigure(1, weight=1, uniform="col")
        body.grid_columnconfigure(2, weight=0)
        cols = [tk.Frame(body, bg=C["paper"]) for _ in range(3)]
        gap = self.px(20)
        cols[0].grid(row=0, column=0, sticky="nsew", padx=(0, gap))
        cols[1].grid(row=0, column=1, sticky="nsew", padx=(0, gap))
        cols[2].grid(row=0, column=2, sticky="nsew")
        self._build_message(cols[0])
        self._build_cipher(cols[1])
        self._build_qr(cols[2])
        self._bind_widgets()
        self._setup_dnd()
        self._update_nav()

    def _build_header(self):
        self.header = tk.Canvas(self.root, height=self.px(60), bg=C["space"], highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        self.menu_btn = self._button(self.header, "", self._main_menu, "dark", padx=8, pady=6, image=self._menu_icon)
        self.lang_btn = self._button(self.header, " " + T("Язык"), self._lang_menu, "dark", padx=10, pady=3,
                                     image=self._lang_icon, compound="left")
        self.help_btn = self._button(self.header, T("Справка"), self.show_help, "dark")
        self.back_btn = self._button(self.header, "←", self.history_back, "dark", font=self.f_arrow, padx=10, pady=1)
        self.fwd_btn = self._button(self.header, "→", self.history_forward, "dark", font=self.f_arrow, padx=10, pady=1)
        self.header.bind("<Configure>", lambda e: self._draw_header())

    def _draw_header(self):
        cv = self.header
        w, h = max(cv.winfo_width(), 1), max(cv.winfo_height(), 1)
        cv.delete("all")
        rnd = random.Random(1945)
        for _ in range(max(20, w // 12)):
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            b = rnd.randint(60, 190)
            s = 2 if rnd.random() < 0.15 else 1
            cv.create_rectangle(x, y, x + s, y + s, fill=f"#{b:02x}{b:02x}{min(255, b + 18):02x}", outline="")
        pad = self.px(16)
        cv.create_window(pad, h // 2, window=self.menu_btn, anchor="w")
        x = pad + self.menu_btn.winfo_reqwidth() + self.px(14)
        cv.create_image(x, h // 2, image=self._hdr_icon, anchor="w")
        cv.create_text(x + self.px(50), h // 2, text=T("Код Марса"), font=self.f_title, fill=C["space_text"], anchor="w")
        x = w - pad
        for btn, gap in ((self.fwd_btn, 6), (self.back_btn, 18), (self.help_btn, 10), (self.lang_btn, 0)):
            cv.create_window(x, h // 2, window=btn, anchor="e")
            x -= btn.winfo_reqwidth() + self.px(gap)

    def _build_message(self, f):
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        top = tk.Frame(f, bg=C["paper"])
        top.grid(row=0, column=0, sticky="ew", pady=(0, self.px(8)))
        self._heading(top, T("Сообщение")).pack(side="left")
        self._button(top, T("Очистить всё"), self.clear_all, "primary", font=self.f_btn_small,
                     padx=10, pady=2).pack(side="right")
        box, self.msg = self._textbox(f, self.f_text, "word")
        box.grid(row=1, column=0, sticky="nsew")
        self._placeholder(self.msg, T("Напишите сообщение и нажмите Enter. Расшифрованный текст тоже появляется здесь."))
        self._note(f, T("Shift+Enter переносит строку. Если удерживать Backspace 2 секунды, очистятся все поля.")).grid(
            row=2, column=0, sticky="ew", pady=(self.px(6), 0))
        key = tk.Frame(f, bg=C["paper"])
        key.grid(row=3, column=0, sticky="ew", pady=(self.px(16), 0))
        self._build_key(key)
        btns = tk.Frame(f, bg=C["paper"])
        btns.grid(row=4, column=0, sticky="ew", pady=(self.px(18), 0))
        self._button(btns, T("Зашифровать"), self.encrypt, "primary").pack(side="left")
        self._button(btns, T("Расшифровать"), self.decrypt_manual).pack(side="left", padx=(self.px(8), 0))

    def _key_name(self, idx):
        return T("Универсальный") if idx == 0 else T("Код {n}", n=idx)

    def _key_label(self, kid):
        if not kid:
            return "—"
        if kid[0] == "list":
            return self._key_name(kid[1])
        if kid[0] == "phrase":
            return kid[1]
        return T("пустая ключ-фраза")

    def _build_key(self, f):
        f.grid_columnconfigure(0, weight=1)
        row = tk.Frame(f, bg=C["paper"])
        row.grid(row=0, column=0, sticky="ew")
        self._heading(row, T("Ключ")).pack(side="left")
        self.mode = tk.StringVar(value="list")
        for text, value in ((T("Выбрать ключ"), "list"), (T("Ключ-фраза"), "phrase")):
            tk.Radiobutton(row, text=text, value=value, variable=self.mode, command=self._on_mode,
                           font=self.f_body, bg=C["paper"], fg=C["ink"], activebackground=C["paper"],
                           activeforeground=C["ink"], selectcolor=C["card"], highlightthickness=0,
                           bd=0, cursor="hand2").pack(side="left", padx=(self.px(18), 0))
        self.list_frame = tk.Frame(f, bg=C["paper"])
        self.combo = ttk.Combobox(self.list_frame, state="readonly", style="Mars.TCombobox", font=self.f_text,
                                  values=[self._key_name(i) for i in range(len(core.BUILTIN_KEYS))], height=17)
        self.combo.current(self.auto_idx)
        self.combo.pack(fill="x")
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.combo.selection_clear())
        self._note(self.list_frame, T("Автокод: каждый день выбирается ключ с номером текущего числа, как на телефоне. "
                                      "Если сообщение зашифровано ключом другого дня, программа подберёт ключ сама.")).pack(
            fill="x", pady=(self.px(6), 0))
        self.phrase_frame = tk.Frame(f, bg=C["paper"])
        self.phrase = tk.StringVar()
        self.phrase.trace_add("write", lambda *a: self._update_hex())
        self.phrase_entry = tk.Entry(self.phrase_frame, textvariable=self.phrase, font=self.f_text,
                                     bg=C["card"], fg=C["ink"], insertbackground=C["ink"], relief="flat",
                                     bd=self.px(7), highlightthickness=1, highlightbackground=C["line"],
                                     highlightcolor=C["mars"])
        self.phrase_entry.pack(fill="x")
        self.phrase_entry.bind("<Button-3>", self._text_menu)
        self._placeholder(self.phrase_entry, T("Введите ключ-фразу"))
        hexrow = tk.Frame(self.phrase_frame, bg=C["paper"])
        hexrow.pack(fill="x", pady=(self.px(6), 0))
        tk.Label(hexrow, text=T("HEX-ключ:"), font=self.f_small, fg=C["muted"], bg=C["paper"]).pack(side="left")
        self.hex_var = tk.StringVar()
        tk.Entry(hexrow, textvariable=self.hex_var, state="readonly", font=self.f_mono_small,
                 readonlybackground=C["paper"], fg=C["ink"], relief="flat", bd=0,
                 highlightthickness=0, width=10).pack(side="left", fill="x", expand=True,
                                                     padx=(self.px(6), self.px(8)))
        self._small(hexrow, T("Копировать"), lambda: self._copy(self.hex_var.get(), T("HEX-ключ скопирован"))).pack(side="right")
        self._note(self.phrase_frame, T("Ключ вычисляется из фразы через SHA-256 так же, как на телефоне. "
                                        "У получателя должна быть та же фраза.")).pack(fill="x", pady=(self.px(4), 0))
        self._on_mode()

    def _build_cipher(self, f):
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=3)
        f.grid_rowconfigure(4, weight=2)
        top = tk.Frame(f, bg=C["paper"])
        top.grid(row=0, column=0, sticky="ew", pady=(0, self.px(8)))
        self._heading(top, T("Шифровка Base32")).pack(side="left")
        self._small(top, T("Вставить"), self.paste_cipher).pack(side="right")
        self._small(top, T("Копировать"), lambda: self._copy(self.b32_get(), T("Шифровка скопирована"))).pack(
            side="right", padx=(0, self.px(8)))
        box, self.b32 = self._textbox(f, self.f_mono, "char")
        box.grid(row=1, column=0, sticky="nsew")
        self.b32.tag_configure("sent", foreground=C["mars"], underline=True)
        self.b32.tag_configure("sending", foreground=C["mars"], background=C["mars_soft"], underline=True)
        self._placeholder(self.b32, T("Здесь появится шифровка. Чтобы расшифровать сообщение, вставьте сюда его "
                                      "шифровку: программа расшифрует её сама."))
        self.status = self._note(f, "")
        self.status.grid(row=2, column=0, sticky="ew", pady=(self.px(6), self.px(12)))
        mid = tk.Frame(f, bg=C["paper"])
        mid.grid(row=3, column=0, sticky="ew", pady=(0, self.px(6)))
        self._heading(mid, T("Азбука Морзе")).pack(side="left")
        self.sound_btn = tk.Label(mid, image=self._snd_frames[0], bg=C["paper"], bd=0, cursor="hand2")
        self.sound_btn.pack(side="left", padx=(self.px(2), 0))
        self.sound_btn.bind("<Button-1>", lambda e: self.toggle_sound())
        self._button(mid, T("Настройка\nазбуки Морзе"), self.show_morse_settings, font=self.f_btn_small,
                     padx=6, pady=1).pack(side="right")
        self._small(mid, T("Копировать"), lambda: self._copy(self.morse_get(), T("Морзянка скопирована"))).pack(
            side="right", padx=(0, self.px(8)))
        box2, self.morse = self._textbox(f, self.f_mono, "word")
        box2.grid(row=4, column=0, sticky="nsew")
        self.morse.tag_configure("played", foreground=C["mars"], underline=True)
        self.morse.tag_configure("current", background=C["mars_soft"])
        self._placeholder(self.morse, T("Морзянка появится после шифрования. Сюда можно вставить принятую морзянку "
                                        "или написать текст и нажать Enter."))

    def _build_qr(self, f):
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)
        self.qr_cv = tk.Canvas(f, width=self.px(320), height=self.px(260), bg=C["card"],
                               highlightthickness=1, highlightbackground=C["line"], bd=0)
        self.qr_cv.grid(row=0, column=0, sticky="nsew")
        self.qr_cv.bind("<Configure>", lambda e: self._schedule_qr_redraw())
        self.qr_cv.bind("<Button-3>", self._qr_menu)
        s = self.px(4)
        tv = tk.Frame(f, bg=C["paper"])
        tv.grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))
        tv.grid_columnconfigure(0, weight=1, uniform="tv")
        tv.grid_columnconfigure(1, weight=1, uniform="tv")
        self.sstv_btn = self._button(tv, T("Передать SSTV"), self.toggle_sstv, "primary", font=self.f_btn_small, padx=6)
        self.sstv_btn.grid(row=0, column=0, sticky="ew", padx=(0, s))
        self.sstv_mode_btn = self._button(tv, "", self._sstv_menu, font=self.f_btn_small, padx=6)
        self.sstv_mode_btn.grid(row=0, column=1, sticky="ew", padx=(s, 0))
        self._sstv_buttons()
        g = tk.Frame(f, bg=C["paper"])
        g.grid(row=2, column=0, sticky="ew", pady=(self.px(8), 0))
        for i in range(3):
            g.grid_columnconfigure(i, weight=1, uniform="q3")
        self._button(g, T("Сохранить QR"), self.save_qr, font=self.f_btn_small, padx=6).grid(
            row=0, column=0, sticky="ew", padx=(0, s))
        self._button(g, T("Копировать QR"), self.copy_qr, font=self.f_btn_small, padx=6).grid(
            row=0, column=1, sticky="ew", padx=s)
        self.open_btn = self._button(g, T("Открыть QR"), self._open_menu, font=self.f_btn_small, padx=6)
        self.open_btn.grid(row=0, column=2, sticky="ew", padx=(s, 0))
        g2 = tk.Frame(f, bg=C["paper"])
        g2.grid(row=3, column=0, sticky="ew", pady=(self.px(8), 0))
        g2.grid_columnconfigure(0, weight=1, uniform="q2")
        g2.grid_columnconfigure(1, weight=1, uniform="q2")
        self._button(g2, T("Бланк шифровки\npng"), self.form_png, font=self.f_btn_small, padx=6, pady=3).grid(
            row=0, column=0, sticky="ew", padx=(0, s))
        self._button(g2, T("Бланк шифровки\ndoc"), self.form_docx, font=self.f_btn_small, padx=6, pady=3).grid(
            row=0, column=1, sticky="ew", padx=(s, 0))

    # ------------------------------------------------------------------ язык и меню
    def set_language(self, code):
        if code == i18n.lang():
            return
        state = (self.msg_get(), self.b32_get(), self.morse_get(), self.mode.get(), self.phrase.get(),
                 self.combo.current(), self.status.cget("text"), self._status_err)
        self.stop_sound()
        self.stop_sstv()
        i18n.set_lang(code)
        self.prefs["lang"] = code
        self._save_prefs()
        for w in self.root.winfo_children():
            w.destroy()
        self._help_win = self._settings_win = self._toast_win = None
        self._drag_on = False
        self._build()
        msg, b32, mrs, mode, phrase, idx, status, err = state
        self.mode.set(mode)
        self._on_mode()
        self.phrase.set(phrase)
        self.combo.current(idx if idx >= 0 else self.auto_idx)
        self._set(self.msg, msg)
        self._set_b32(b32)
        self._set_morse(mrs, src=self._morse_src)
        self._set_status("")  # прежняя строка состояния была на другом языке
        self._update_drag_source()
        self._schedule_qr_redraw()

    def _lang_menu(self):
        m = self._menu()
        self._lang_var = tk.StringVar(value=i18n.lang())
        for code, name, _ in i18n.LANGS:
            m.add_radiobutton(label=name, value=code, variable=self._lang_var,
                              command=lambda c=code: self.root.after(10, lambda: self.set_language(c)))
        self._popup_under(m, self.lang_btn)

    def _main_menu(self):
        m = self._menu()
        m.add_command(label=T("Поделиться: показывать в меню"), state="disabled")
        self._menu_vars = []
        for key, name in SHARE_APPS:
            var = tk.BooleanVar(value=self.prefs["share"].get(key, True))
            self._menu_vars.append(var)
            m.add_checkbutton(label=name, variable=var, command=lambda k=key, v=var: self._toggle_share(k, v.get()))
        m.add_separator()
        m.add_command(label=T("Открыть папку «Код Марса»"), command=lambda: open_folder(output_dir()))
        m.add_command(label=T("Справка"), command=self.show_help)
        self._popup_under(m, self.menu_btn)

    def _toggle_share(self, key, on):
        self.prefs["share"][key] = bool(on)
        self._save_prefs()

    def _add_share(self, menu, text_fn=None, image=False):
        sub = self._menu(menu)
        apps = [(k, n) for k, n in SHARE_APPS if self.prefs["share"].get(k, True)]
        for key, name in apps:
            sub.add_command(label=name, command=(lambda k=key: self.share(k, image=True)) if image
                            else (lambda k=key: self.share(k, text=text_fn())))
        menu.add_cascade(label=T("Поделиться"), menu=sub, state="normal" if apps else "disabled")

    def share(self, app, text=None, image=False):
        """Копирует шифровку, морзянку или QR-код и открывает мессенджер."""
        name = dict(SHARE_APPS)[app]
        if image:
            if not self._need_qr():
                return
            if not IS_WIN:
                self.toast(T("Копирование картинки работает в Windows. Используйте «Сохранить QR»"), error=True)
                return
            try:
                copy_image_to_clipboard(self._qr_export(), self.root.winfo_id())
            except Exception as e:
                self.toast(T("Не удалось скопировать картинку: {e}", e=e), error=True)
                return
        else:
            if not text or not text.strip():
                self.toast(T("Нечем поделиться: поле пустое"), error=True)
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(text.strip())
        opened = prefilled = False
        if app == "telegram":
            exe = find_exe([_env_path("APPDATA", "Telegram Desktop", "Telegram.exe")])
            if not image and (exe or has_protocol("tg")):
                opened = prefilled = start_target("tg://msg?text=" + urllib.parse.quote(text.strip()))
            if not opened and exe:
                opened = start_target(exe)
            if not opened:
                opened = webbrowser.open("https://web.telegram.org/")
        elif app == "viber":
            exe = find_exe([_env_path("LOCALAPPDATA", "Viber", "Viber.exe")])
            opened = start_target(exe) if exe else (has_protocol("viber") and start_target("viber://"))
        elif app == "instagram":
            opened = webbrowser.open("https://www.instagram.com/direct/inbox/")
        elif app == "deltachat":
            exe = find_exe([_env_path("LOCALAPPDATA", "Programs", "deltachat-desktop", "DeltaChat.exe"),
                            _env_path("ProgramFiles", "DeltaChat", "DeltaChat.exe"),
                            _env_path("LOCALAPPDATA", "Programs", "DeltaChat", "DeltaChat.exe")])
            opened = start_target(exe) if exe else False
        if prefilled:
            self.toast(T("В {app} выберите чат: текст уже подготовлен", app=name))
        elif opened:
            self.toast(T("Скопировано. В {app} выберите чат и нажмите Ctrl+V", app=name))
        else:
            self.toast(T("{app} не найден на этом компьютере. Содержимое скопировано: откройте {app} и нажмите Ctrl+V",
                         app=name), error=True)

    # ------------------------------------------------------------------ QR-холст
    def _schedule_qr_redraw(self):
        if self._redraw_job:
            self.root.after_cancel(self._redraw_job)
        self._redraw_job = self.root.after(40, self._redraw_qr)

    def _art(self, w, h, faded):
        key = (w, h, faded)
        if key not in self._art_cache:
            src = self._art_src
            k = max(w / src.width, h / src.height)
            im = src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)
            left, top = (im.width - w) // 2, (im.height - h) // 2
            im = im.crop((left, top, left + w, top + h))
            if faded:
                im = Image.blend(im, Image.new("RGB", im.size, (255, 254, 250)), 0.5)
            if len(self._art_cache) > 4:
                self._art_cache.clear()
            self._art_cache[key] = ImageTk.PhotoImage(im)
        return self._art_cache[key]

    def _redraw_qr(self):
        self._redraw_job = None
        cv = self.qr_cv
        try:
            w, h = cv.winfo_width(), cv.winfo_height()
        except tk.TclError:
            return
        if w < 20 or h < 20:
            return
        cv.delete("all")
        self._qr_box = None
        cv.create_image(0, 0, image=self._art(w, h, self.qr_mat is not None), anchor="nw")
        if self.qr_mat is not None:
            n = len(self.qr_mat)
            mod = max(1, min(w - self.px(60), int(h * 0.66)) // n)
            size = n * mod
            self._qr_photo = ImageTk.PhotoImage(core.qr_image(self.qr_mat, mod))
            pad, cap = self.px(12), self.px(30)
            x0, y0 = w // 2 - size // 2 - pad, int(h * 0.44) - size // 2 - pad
            x1, y1 = x0 + size + 2 * pad, y0 + size + 2 * pad + cap
            cv.create_rectangle(x0 + 3, y0 + 4, x1 + 3, y1 + 4, fill="#E6DED0", outline="")
            cv.create_rectangle(x0, y0, x1, y1, fill="#FFFFFF", outline=C["line"])
            qx, qy = w // 2 - size // 2, y0 + pad
            cv.create_image(qx, qy, image=self._qr_photo, anchor="nw")
            self._qr_box = (qx, qy, qx + size, qy + size)
            cv.create_text(w // 2, y1 - cap // 2 - self.px(2), text=T("Ключ: {key}", key=self._key_label(self.cipher_kid)),
                           width=size + 2 * pad - self.px(8), font=self.f_small, fill=C["muted"])
        else:
            text = self._err(self.qr_err) if self.qr_err else T(
                "Здесь появится QR-код.\nЧтобы расшифровать картинку с QR, перетащите её в окно или нажмите «Открыть QR».")
            cv.create_text(w // 2, h - self.px(56), text=text, width=w - self.px(48), justify="center",
                           font=self.f_small, fill=C["mars"] if self.qr_err else C["muted"])
        self._sstv_overlay()

    def _show_qr(self, b32, kid):
        self.cipher_kid = kid
        try:
            self.qr_mat, self.qr_err = core.qr_matrix(b32), None
        except core.MarsError as e:
            self.qr_mat, self.qr_err = None, e
        self._update_drag_source()
        self._redraw_qr()

    def _qr_export(self):
        return core.qr_image(self.qr_mat, max(4, 640 // len(self.qr_mat)))

    def _err(self, e):
        code = getattr(e, "code", None)
        return T(i18n.ERRORS[code], **getattr(e, "params", {})) if code in i18n.ERRORS else str(e)

    # ------------------------------------------------------------------ поля
    def msg_get(self):
        return self.msg.get("1.0", "end-1c")

    def b32_get(self):
        return self.b32.get("1.0", "end-1c")

    def morse_get(self):
        return self.morse.get("1.0", "end-1c")

    def _set(self, widget, value):
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)
        self._refresh_placeholder(widget)

    def _set_b32(self, value):
        self._b32_prog = value.strip()
        self._set(self.b32, value)

    def _set_morse(self, value, src=None):
        self._morse_prog, self._morse_src = value.strip(), src
        self._set(self.morse, value)

    def _morse_for(self, b32):
        return morse.encode(b32, "latin", self.morse_cfg["separator"])[0]

    def _set_status(self, text, error=False):
        self._status_err = bool(error and text)
        self.status.configure(text=text, fg=C["mars"] if error else C["muted"])

    def _copy(self, text, done):
        if not text.strip():
            self.toast(T("Поле пустое, копировать нечего"), error=True)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.toast(done)

    def _cipher_in_field(self):
        raw = self.b32_get().strip()
        b = core.normalize_b32(raw) if raw and not morse.is_morse(raw) else ""
        return b if core.looks_like_b32(b) else None

    # ------------------------------------------------------------------ история операций
    def _state(self):
        return (self.msg_get(), self.b32_get(), self.morse_get(), self.cipher_kid,
                self.status.cget("text"), self._status_err)

    def _commit(self):
        st = self._state()
        if not (0 <= self.hpos < len(self.history) and self.history[self.hpos] == st):
            del self.history[self.hpos + 1:]
            self.history.append(st)
            if len(self.history) > 200:
                del self.history[0]
            self.hpos = len(self.history) - 1
        self._update_nav()

    def _apply_state(self, st):
        msg, b32, mrs, kid, status, err = st
        self.stop_sound()
        self.stop_sstv()
        self._set(self.msg, msg)
        self._set_b32(b32)
        self._b32_last = b32.strip()
        self._set_morse(mrs)
        self._morse_last = mrs.strip()
        cipher = self._cipher_in_field()
        self._morse_src = cipher
        if cipher:
            self._show_qr(cipher, kid)
        else:
            self.cipher_kid, self.qr_mat, self.qr_err = kid, None, None
            self._update_drag_source()
            self._redraw_qr()
        self._set_status(status, err)

    def history_back(self, _e=None):
        if self.history and self._state() != self.history[self.hpos]:
            self._commit()
        if self.hpos <= 0:
            self.toast(T("Раньше операций нет"))
            return "break"
        self.hpos -= 1
        self._apply_state(self.history[self.hpos])
        self._update_nav()
        return "break"

    def history_forward(self, _e=None):
        if self.hpos >= len(self.history) - 1:
            self.toast(T("Это последняя операция"))
            return "break"
        self.hpos += 1
        self._apply_state(self.history[self.hpos])
        self._update_nav()
        return "break"

    def _update_nav(self):
        if not hasattr(self, "back_btn"):
            return
        for btn, active in ((self.back_btn, self.hpos > 0), (self.fwd_btn, self.hpos < len(self.history) - 1)):
            color = C["space_text"] if active else C["space_dim"]
            btn.configure(fg=color, activeforeground=color)

    # ------------------------------------------------------------------ ключи
    def _on_mode(self):
        if self.mode.get() == "phrase":
            self.list_frame.grid_forget()
            self.phrase_frame.grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))
            self.phrase_entry.focus_set()
        else:
            self.phrase.set("")  # как на телефоне: фраза стирается при возврате к списку
            self.phrase_frame.grid_forget()
            self.list_frame.grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))

    def _update_hex(self):
        phrase = self.phrase.get().strip()
        self.hex_var.set(core.phrase_key(phrase).hex() if phrase else "")
        self._refresh_placeholder(self.phrase_entry)

    def _selected_key(self, feedback):
        if self.mode.get() == "phrase":
            phrase = self.phrase.get().strip()
            if not phrase:
                if feedback:
                    self.toast(T("Введите ключ-фразу или вернитесь к списку ключей"), error=True)
                    self.phrase_entry.focus_set()
                return None
            return core.phrase_key(phrase), ("phrase", phrase)
        idx = self.combo.current()
        idx = self.auto_idx if idx < 0 else idx
        return core.key_bytes(idx), ("list", idx)

    def _candidates(self):
        """Сначала выбранный ключ, затем ключ дня и остальные ключи списка."""
        seen, out = set(), []

        def add(key, kid, primary=False):
            if key not in seen:
                seen.add(key)
                out.append((key, kid, primary))

        sel = self._selected_key(feedback=False)
        if sel:
            add(sel[0], sel[1], True)
        for i in [self.auto_idx] + [i for i in range(len(core.BUILTIN_KEYS)) if i != self.auto_idx]:
            add(core.key_bytes(i), ("list", i))
        add(core.phrase_key(""), ("empty",))
        return out

    def _day_tick(self):
        today = dt.date.today()
        if today != self.today:
            old = self.auto_idx
            self.today, self.auto_idx = today, core.auto_key_index(today)
            if self.combo.current() == old:
                self.combo.current(self.auto_idx)
                if self.mode.get() == "list":
                    self.toast(T("Наступил новый день: выбран ключ «{key}»", key=self._key_name(self.auto_idx)))
        self.root.after(60_000, self._day_tick)

    # ------------------------------------------------------------------ шифрование
    def encrypt(self, _event=None):
        text = self.msg_get()
        if not text.strip():
            self.toast(T("Сначала напишите сообщение"), error=True)
            self.msg.focus_set()
            return "break"
        sel = self._selected_key(feedback=True)
        if sel is None:
            return "break"
        key, kid = sel
        try:
            b32 = core.b32encode(core.encrypt(text, key))
        except Exception as e:
            self.toast(T("Ошибка при шифровании: {e}", e=e), error=True)
            return "break"
        self.stop_sound()
        self.stop_sstv()
        self._set_b32(b32)
        self._set_morse(self._morse_for(b32), src=b32)
        self._show_qr(b32, kid)
        self._set_status(T("Зашифровано ключом «{key}». В шифровке {n} знаков.", key=self._key_label(kid), n=len(b32)))
        self._commit()
        return "break"

    def decrypt_manual(self, _event=None):
        raw = self.b32_get().strip()
        if not raw:
            self.toast(T("Вставьте шифровку в поле Base32 или откройте QR-код"), error=True)
            return "break"
        self._decrypt_and_show(raw, explicit=True)
        return "break"

    def _b32_changed(self):
        if self._b32_job:
            self.root.after_cancel(self._b32_job)
        self._b32_job = self.root.after(350, self._b32_auto)

    def _b32_auto(self):
        """Как на телефоне: вставленная шифровка расшифровывается сама."""
        self._b32_job = None
        try:
            raw = self.b32_get().strip()
        except tk.TclError:
            return
        if not raw or raw in (self._b32_prog, self._b32_last):
            return
        if morse.is_morse(raw) or core.looks_like_b32(raw):
            self._b32_last = raw
            self._decrypt_and_show(raw, explicit=False)

    def _decrypt_and_show(self, raw, explicit, keep_morse=False):
        if morse.is_morse(raw):
            lat = morse.latin_text(raw)
            if not lat:
                return self._fail(T("В морзянке есть сигналы, которых не бывает в шифровке."), explicit)
            b32 = core.normalize_b32(lat)
            self._set_b32(b32)
        else:
            b32 = core.normalize_b32(raw)
        try:
            text, kid, primary = core.decrypt_any(core.b32decode(b32), self._candidates())
        except core.MarsError as e:
            return self._fail(self._err(e), explicit)
        self.stop_sound()
        self.stop_sstv()
        self._set(self.msg, text)
        if not keep_morse:
            self._set_morse(self._morse_for(b32), src=b32)
        self._show_qr(b32, kid)
        label = self._key_label(kid)
        self._set_status(T("Расшифровано ключом «{key}».", key=label))
        if not primary:
            self.toast(T("Расшифровано ключом «{key}»", key=label))
        elif explicit:
            self.toast(T("Успешно расшифровано"))
        self._commit()
        return True

    def _fail(self, message, explicit):
        self._set_status(message, error=True)
        if explicit:
            self.toast(message, error=True)
        return False

    def _receive_cipher_text(self, text):
        t = text.strip()
        if morse.is_morse(t):
            self._set(self.morse, t)
            self.morse_enter()
            return
        self._set_b32(t)
        self._b32_last = t
        self._decrypt_and_show(t, explicit=True)

    def clear_all(self):
        self.stop_sound()
        self.stop_sstv()
        self._set(self.msg, "")
        self._set_morse("")
        self._set_b32("")
        self.qr_mat = self.qr_err = self.cipher_kid = None
        self._b32_last = self._morse_last = ""
        self._set_status("")
        self._update_drag_source()
        self._redraw_qr()
        self._commit()
        self.msg.focus_set()

    # ------------------------------------------------------------------ азбука Морзе
    def _morse_changed(self):
        if self._playing and self.morse_get() != self._play.get("text"):
            self.stop_sound()
        if self._morse_job:
            self.root.after_cancel(self._morse_job)
        self._morse_job = self.root.after(600, self._morse_auto)

    def _morse_auto(self):
        """Вставленная морзянка шифровки распознаётся сама."""
        self._morse_job = None
        try:
            raw = self.morse_get().strip()
        except tk.TclError:
            return
        if not raw or raw in (self._morse_prog, self._morse_last) or not morse.is_morse(raw):
            return
        lat = morse.latin_text(raw)
        if lat and core.looks_like_b32(lat):
            self._morse_last = raw
            b32 = core.normalize_b32(lat)
            self._set_b32(b32)
            self._b32_last = b32
            self._decrypt_and_show(b32, explicit=False, keep_morse=True)

    def morse_enter(self, _event=None):
        raw = self.morse_get().strip()
        if not raw:
            self.toast(T("Поле «Азбука Морзе» пустое"), error=True)
            return "break"
        self.stop_sound()
        if not morse.is_morse(raw):
            self._text_to_morse(raw)
            return "break"
        lat = morse.latin_text(raw)
        if lat and core.looks_like_b32(lat):
            b32 = core.normalize_b32(lat)
            self._morse_last = raw
            self._set_b32(b32)
            self._b32_last = b32
            self._decrypt_and_show(b32, explicit=True, keep_morse=True)
            return "break"
        text, lang, unknown = morse.decode(raw, self.morse_cfg["alphabet"])
        self._set(self.msg, text)
        note = T("Морзянка переведена в текст: {lang}.", lang=T(morse.LANG_NAMES[lang]))
        if unknown:
            note += T(" Неизвестные сигналы: {codes}", codes=" ".join(unknown[:4]))
        self._set_status(note)
        self.toast(T("Морзянка переведена в текст"))
        self._commit()
        return "break"

    def _text_to_morse(self, text):
        m, lang = morse.encode(text, self.morse_cfg["alphabet"], self.morse_cfg["separator"])
        if not m:
            self.toast(T("Этот текст нельзя передать азбукой Морзе"), error=True)
            return False
        self._set_morse(m)
        self._set_status(T("Текст переведён в морзянку: {lang}.", lang=T(morse.LANG_NAMES[lang])))
        self._commit()
        return True

    def _morse_for_sound(self):
        text = self.morse_get().strip()
        if not text:
            cipher = self._cipher_in_field()
            if not cipher:
                self.toast(T("Нечего передавать: зашифруйте сообщение или вставьте морзянку"), error=True)
                return None
            self._set_morse(self._morse_for(cipher), src=cipher)
        elif not morse.is_morse(text) and not self._text_to_morse(text):
            return None
        return self.morse_get()

    def toggle_sound(self):
        if self._playing:
            self.stop_sound()
        else:
            self.start_sound()

    def _start_index(self, events, b32pos):
        """С какого сигнала начать: с места курсора в поле шифровки или Морзе."""
        w = self.root.focus_get()
        if w is self.morse:
            off, n = len(self.morse.get("1.0", "insert")), len(self.morse_get())
            if 0 < off < n:
                return next((k for k, e in enumerate(events) if e[2] >= off), 0)
        elif w is self.b32 and b32pos:
            off = len(self.b32.get("1.0", "insert"))
            letter = sum(1 for p in b32pos if p < off)
            if 0 < letter < len(b32pos):
                return next((k for k, e in enumerate(events) if e[3] >= letter), 0)
        return 0

    def start_sound(self):
        full = self._morse_for_sound()
        if full is None:
            return
        events, _ = morse.timeline(full, self.morse_cfg)
        if not events:
            self.toast(T("В поле нет сигналов Морзе"), error=True)
            return
        self.stop_sstv()
        b32_text = self.b32_get()
        pos = [i for i, ch in enumerate(b32_text) if not ch.isspace()]
        lat = morse.latin_text(full)
        linked = bool(lat) and core.normalize_b32(b32_text) == lat and len(pos) == events[-1][3] + 1
        start = self._start_index(events, pos if linked else None)
        play_events, total = morse.shift(events, start)
        ranges = {}
        for _, _, idx, letter in events:
            a, b = ranges.get(letter, (idx, idx + 1))
            ranges[letter] = (min(a, idx), max(b, idx + 1))
        folder = os.path.join(tempfile.gettempdir(), "KodMarsa")
        self.player.stop()
        try:
            os.makedirs(folder, exist_ok=True)
            self._wav_n ^= 1  # два файла по очереди: пока один звучит, второй можно переписать
            path = os.path.join(folder, f"morse_{os.getpid()}_{self._wav_n}.wav")
            morse.render_wav(play_events, total, self.morse_cfg, path)
        except Exception as e:
            self.toast(T("Не удалось подготовить звук: {e}", e=e), error=True)
            return
        for tag in ("played", "current"):
            self.morse.tag_remove(tag, "1.0", "end")
        for tag in ("sent", "sending"):
            self.b32.tag_remove(tag, "1.0", "end")
        try:
            audible = self.player.play(path)
        except Exception:
            audible = False
        if not audible:
            self.toast(T("Звук в этой системе недоступен: передача показана без звука"))
        self._playing = True
        self._play = {"text": full, "events": play_events, "total": total, "next": 0, "letter": None,
                      "ranges": ranges, "pos": pos if linked else None, "t0": time.perf_counter() + 0.05}
        self._tick_sound()

    def _mark_letter(self, letter, done):
        p = self._play
        if done:
            if p["pos"] and letter < len(p["pos"]):
                i = p["pos"][letter]
                self.b32.tag_add("sent", f"1.0+{i}c", f"1.0+{i + 1}c")
            return
        self.morse.tag_remove("current", "1.0", "end")
        a, b = p["ranges"].get(letter, (0, 0))
        self.morse.tag_add("current", f"1.0+{a}c", f"1.0+{b}c")
        self.morse.see(f"1.0+{a}c")
        if p["pos"] and letter < len(p["pos"]):
            i = p["pos"][letter]
            self.b32.tag_remove("sending", "1.0", "end")
            self.b32.tag_add("sending", f"1.0+{i}c", f"1.0+{i + 1}c")
            self.b32.see(f"1.0+{i}c")

    def _tick_sound(self):
        if not self._playing:
            return
        p = self._play
        elapsed = (time.perf_counter() - p["t0"]) * 1000.0
        ev = p["events"]
        while p["next"] < len(ev) and ev[p["next"]][0] <= elapsed:
            _, _, idx, letter = ev[p["next"]]
            if letter != p["letter"]:
                if p["letter"] is not None:
                    self._mark_letter(p["letter"], done=True)
                p["letter"] = letter
                self._mark_letter(letter, done=False)
            self.morse.tag_add("played", f"1.0+{idx}c", f"1.0+{idx + 1}c")
            p["next"] += 1
        self._glow_i = self._glow_i % 13 + 1
        self.sound_btn.configure(image=self._snd_frames[self._glow_i])
        if elapsed >= p["total"]:
            if p["letter"] is not None:
                self._mark_letter(p["letter"], done=True)
            self.stop_sound(finished=True)
            return
        self._play_job = self.root.after(30, self._tick_sound)

    def stop_sound(self, finished=False):
        if self._play_job:
            self.root.after_cancel(self._play_job)
            self._play_job = None
        if self._playing and not finished:
            self.player.stop()
        self._playing = False
        try:
            self.sound_btn.configure(image=self._snd_frames[0])
            self.morse.tag_remove("current", "1.0", "end")
            self.b32.tag_remove("sending", "1.0", "end")
        except tk.TclError:
            pass

    def _set_separator(self, sep):
        self.morse_cfg["separator"] = sep
        self._save_prefs()
        if self._morse_src and self.morse_get().strip() == self._morse_prog:
            self.stop_sound()
            self._set_morse(self._morse_for(self._morse_src), src=self._morse_src)

    def save_wav(self):
        full = self._morse_for_sound()
        if full is None:
            return
        folder = self._out_dir()
        if not folder:
            return
        events, total = morse.timeline(full, self.morse_cfg)
        try:
            path = unique_path(folder, f"{T('Морзе')} {dt.datetime.now():%d.%m.%Y %H-%M-%S}.wav")
            morse.render_wav(events, total, self.morse_cfg, path)
        except Exception as e:
            self.toast(T("Не удалось сохранить звук: {e}", e=e), error=True)
            return
        self.toast(T("Звук Морзе сохранён ({sec} с) в «Документы\\Код Марса»", sec=round(total / 1000)), folder=folder)

    def show_morse_settings(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        cfg, ui = self.morse_cfg, {}
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title(T("Настройка азбуки Морзе"))
        win.configure(bg=C["paper"])
        win.transient(self.root)
        win.resizable(False, False)
        body = tk.Frame(win, bg=C["paper"])
        body.pack(fill="both", expand=True, padx=self.px(22), pady=(self.px(14), self.px(18)))
        body.grid_columnconfigure(1, weight=1)
        row = [0]
        wrap = self.px(460)

        def refresh():
            if cfg["fwpm"] > cfg["wpm"]:
                cfg["fwpm"] = cfg["wpm"]
                if "fw_var" in ui:
                    ui["fw_var"].set(cfg["wpm"])
                    ui["fw_val"].configure(text=str(cfg["wpm"]))
            if "fw_scale" in ui:
                ui["fw_scale"].configure(state="normal" if cfg["farnsworth"] else "disabled")
            if "speed_note" in ui:
                ui["speed_note"].configure(text=T("Скорость {wpm} слов в минуту (стандартное слово PARIS): длина точки {ms} мс.",
                                                  wpm=cfg["wpm"], ms=round(1200 / cfg["wpm"])))
            self._save_prefs()

        def section(title):
            tk.Label(body, text=title, font=self.f_head, fg=C["ink"], bg=C["paper"]).grid(
                row=row[0], column=0, columnspan=3, sticky="w", pady=(self.px(14) if row[0] else 0, self.px(2)))
            tk.Frame(body, bg=C["line"], height=1).grid(row=row[0] + 1, column=0, columnspan=3, sticky="ew",
                                                         pady=(0, self.px(6)))
            row[0] += 2

        def slider(label, key, lo, hi, step, fmt):
            var = tk.IntVar(value=cfg[key])
            tk.Label(body, text=label, font=self.f_body, fg=C["ink"], bg=C["paper"]).grid(row=row[0], column=0, sticky="w")
            val = tk.Label(body, text=fmt(cfg[key]), font=self.f_body, fg=C["ink"], bg=C["paper"], width=6, anchor="e")

            def changed(v):
                cfg[key] = int(float(v))
                val.configure(text=fmt(cfg[key]))
                refresh()

            sc = tk.Scale(body, from_=lo, to=hi, resolution=step, orient="horizontal", showvalue=False,
                          variable=var, command=changed, length=self.px(230), bg=C["mars"],
                          troughcolor=C["line"], activebackground=C["mars_hover"], highlightthickness=0, bd=0,
                          sliderrelief="flat", sliderlength=self.px(14), width=self.px(8))
            sc.grid(row=row[0], column=1, sticky="ew", padx=self.px(10), pady=self.px(3))
            val.grid(row=row[0], column=2, sticky="e")
            row[0] += 1
            return sc, var, val

        def note(text):
            lbl = tk.Label(body, text=text, font=self.f_small, fg=C["muted"], bg=C["paper"], justify="left",
                           anchor="w", wraplength=wrap)
            lbl.grid(row=row[0], column=0, columnspan=3, sticky="w", pady=(self.px(2), 0))
            row[0] += 1
            return lbl

        section(T("Скорость"))
        slider(T("Скорость, слов в минуту"), "wpm", 5, 40, 1, str)
        ui["speed_note"] = note("")
        farn = tk.BooleanVar(value=cfg["farnsworth"])
        tk.Checkbutton(body, text=T("Паузы между буквами и словами медленнее (скорость Фарнсворта)"), variable=farn,
                       command=lambda: (cfg.__setitem__("farnsworth", farn.get()), refresh()), font=self.f_body,
                       bg=C["paper"], fg=C["ink"], activebackground=C["paper"], selectcolor=C["card"],
                       highlightthickness=0, bd=0, anchor="w", justify="left", wraplength=wrap).grid(
            row=row[0], column=0, columnspan=3, sticky="w", pady=(self.px(6), 0))
        row[0] += 1
        ui["fw_scale"], ui["fw_var"], ui["fw_val"] = slider(T("Скорость пауз"), "fwpm", 5, 40, 1, str)
        section(T("Воспроизведение"))
        slider(T("Частота тона, Гц"), "tone", 300, 1200, 10, str)
        slider(T("Громкость"), "volume", 0, 100, 5, lambda v: f"{v} %")
        slider(T("Помехи"), "noise", 0, 100, 5, lambda v: f"{v} %")
        section(T("Разделители в коде Морзе"))
        sep = tk.StringVar(value=cfg["separator"])
        for key, label, _, _ in morse.SEPARATORS:
            tk.Radiobutton(body, text=T(label), variable=sep, value=key, command=lambda: self._set_separator(sep.get()),
                           font=self.f_body, bg=C["paper"], fg=C["ink"], activebackground=C["paper"],
                           selectcolor=C["card"], highlightthickness=0, bd=0, anchor="w", justify="left",
                           wraplength=wrap).grid(row=row[0], column=0, columnspan=3, sticky="w", pady=self.px(2))
            row[0] += 1
        section(T("Азбука и язык передачи"))
        keys = [k for k, _ in morse.ALPHABET_CHOICES]
        combo = ttk.Combobox(body, state="readonly", style="Mars.TCombobox", font=self.f_body,
                             values=[T(n) for _, n in morse.ALPHABET_CHOICES])
        combo.current(keys.index(cfg["alphabet"]) if cfg["alphabet"] in keys else 0)
        combo.bind("<<ComboboxSelected>>", lambda e: (cfg.__setitem__("alphabet", keys[combo.current()]),
                                                      combo.selection_clear(), self._save_prefs()))
        combo.grid(row=row[0], column=0, columnspan=3, sticky="ew", pady=(self.px(2), 0))
        row[0] += 1
        note(T("При автоопределении азбука выбирается сама: по буквам текста при передаче и по самим сигналам при приёме. "
               "Шифровка всегда передаётся латиницей, как на телефоне."))
        btns = tk.Frame(body, bg=C["paper"])
        btns.grid(row=row[0], column=0, columnspan=3, sticky="ew", pady=(self.px(18), 0))

        def reset():
            cfg.clear()
            cfg.update(morse.DEFAULTS)
            win.destroy()
            self._set_separator(cfg["separator"])
            self.show_morse_settings()

        self._button(btns, T("Прослушать"), self.toggle_sound, "primary").pack(side="left")
        self._button(btns, T("Сохранить звук WAV"), self.save_wav).pack(side="left", padx=(self.px(8), 0))
        self._button(btns, T("Закрыть"), win.destroy).pack(side="right")
        self._button(btns, T("Сброс"), reset).pack(side="right", padx=(0, self.px(8)))
        refresh()
        win.bind("<Escape>", lambda e: win.destroy())

    # ------------------------------------------------------------------ SSTV
    def _sstv_buttons(self):
        ready = bool(self.sstv_mode)
        self.sstv_mode_btn.configure(text=(self.sstv_mode if ready else T("Модель SSTV")) + "  ▾")
        if not self._sstv_active:
            self.sstv_btn.configure(text=T("Передать SSTV"), state="normal" if ready else "disabled",
                                    bg=C["mars"] if ready else C["hover"])

    def _sstv_menu(self):
        m = self._menu()
        for name in sstv.MODE_NAMES:
            m.add_command(label=T("{name}  ·  {sec} с", name=name, sec=round(sstv.duration_ms(name) / 1000)),
                          command=lambda n=name: self._choose_sstv(n))
        self._popup_under(m, self.sstv_mode_btn)

    def _choose_sstv(self, name):
        self.sstv_mode = name
        self._save_prefs()
        self._sstv_buttons()

    def toggle_sstv(self):
        if self._sstv_active:
            self.stop_sstv()
            return
        if not self.sstv_mode:
            return
        if self.qr_mat is None:
            self.toast(T("Сначала зашифруйте сообщение: SSTV передаёт QR-код"), error=True)
            return
        self.stop_sound()
        mode = self.sstv_mode
        img, mod = sstv.qr_frame(self.qr_mat, mode)
        if mod < 3:
            self.toast(T("QR-код слишком мелкий для {mode}: выберите PD 120, PD 180, PD 240 или PD 290", mode=mode),
                       error=True)
        self._sstv_active = True
        self.sstv_btn.configure(text=T("Готовлю SSTV…"))
        volume = self.morse_cfg.get("volume", 80)
        self._wav_n ^= 1
        path = os.path.join(tempfile.gettempdir(), "KodMarsa", f"sstv_{os.getpid()}_{self._wav_n}.wav")
        result = {}

        def work():
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                sstv.write_wav(sstv.synthesize(img, mode, volume), path)
                result["path"] = path
            except Exception as e:
                result["error"] = e

        threading.Thread(target=work, daemon=True).start()
        self._sstv_wait(result, mode)

    def _sstv_wait(self, result, mode):
        if not self._sstv_active:
            return
        if not result:
            self._sstv_job = self.root.after(100, lambda: self._sstv_wait(result, mode))
            return
        if "error" in result:
            self.toast(T("Не удалось подготовить сигнал SSTV: {e}", e=result["error"]), error=True)
            self.stop_sstv()
            return
        self.player.stop()
        try:
            audible = self.player.play(result["path"])
        except Exception:
            audible = False
        if not audible:
            self.toast(T("Звук в этой системе недоступен: передача показана без звука"))
        self._sstv_run = {"mode": mode, "t0": time.perf_counter() + 0.05, "total": sstv.duration_ms(mode)}
        self.sstv_btn.configure(text=T("Остановить SSTV"))
        self._sstv_tick()

    def _sstv_tick(self):
        if not self._sstv_active:
            return
        run = self._sstv_run
        elapsed = (time.perf_counter() - run["t0"]) * 1000.0
        self._sstv_frac = sstv.progress(run["mode"], elapsed)
        self._sstv_overlay()
        if elapsed >= run["total"]:
            self.stop_sstv(finished=True)
            self.toast(T("Передача SSTV завершена"))
            return
        self._sstv_job = self.root.after(100, self._sstv_tick)

    def stop_sstv(self, finished=False):
        if self._sstv_job:
            self.root.after_cancel(self._sstv_job)
            self._sstv_job = None
        if self._sstv_active and not finished:
            self.player.stop()
        self._sstv_active, self._sstv_frac = False, None
        try:
            self._sstv_buttons()
            self._sstv_overlay()
        except tk.TclError:
            pass

    def _sstv_overlay(self):
        cv = self.qr_cv
        cv.delete("sstv")
        if self._sstv_frac is None or not self._qr_box:
            return
        x0, y0, x1, y1 = self._qr_box
        ys = y0 + (y1 - y0) * self._sstv_frac
        if ys < y1:
            cv.create_rectangle(x0, ys, x1, y1, fill="#FFFFFF", stipple="gray50", outline="", tags="sstv")
        cv.create_line(x0 - self.px(8), ys, x1 + self.px(8), ys, fill=C["mars"], width=self.px(3), tags="sstv")

    # ------------------------------------------------------------------ получение QR
    def paste_cipher(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if text.strip():
            self._receive_cipher_text(text)
            return
        img = self._clipboard_image()
        if img is not None:
            self._receive_image(img)
        else:
            self.toast(T("В буфере обмена нет шифровки"), error=True)

    def _clipboard_image(self):
        try:
            from PIL import ImageGrab
            data = ImageGrab.grabclipboard()
        except Exception:
            return None
        if isinstance(data, Image.Image):
            return data
        if isinstance(data, list):
            for path in data:
                try:
                    im = Image.open(path)
                    im.load()
                    return im
                except Exception:
                    continue
        return None

    def _open_menu(self):
        m = self._menu()
        m.add_command(label=T("Из файла…"), command=self.open_qr_file)
        m.add_command(label=T("Из буфера обмена"), command=self.qr_from_clipboard)
        m.add_command(label=T("Найти на экране"), command=self.qr_from_screen)
        self._popup_under(m, self.open_btn)

    def open_qr_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, title=T("Открыть картинку с QR-кодом"),
            filetypes=[(T("Изображения"), "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                       (T("Текст шифровки"), "*.txt"), (T("Все файлы"), "*.*")])
        if path:
            self.open_path(path)

    def open_path(self, path):
        if os.path.splitext(path)[1].lower() == ".txt":
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as e:
                self.toast(T("Не удалось открыть файл: {e}", e=e), error=True)
                return
            if core.looks_like_b32(text) or morse.is_morse(text):
                self._receive_cipher_text(text)
            else:
                self._set(self.msg, text)
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            self.toast(T("Этот файл не открывается как картинка"), error=True)
            return
        self._receive_image(img)

    def _receive_image(self, img):
        try:
            texts = core.read_qr(img)
        except Exception as e:
            self.toast(T("Не удалось прочитать QR-код: {e}", e=e), error=True)
            return
        self._receive_qr_texts(texts, T("QR-код на картинке не найден"))

    def _receive_qr_texts(self, texts, not_found):
        if not texts:
            self.toast(not_found, error=True)
            return
        cipher = core.pick_cipher(texts)
        if cipher is None:
            self.toast(T("QR-код найден, но в нём не шифровка «Кода Марса»"), error=True)
            return
        self._receive_cipher_text(cipher)

    def qr_from_clipboard(self):
        img = self._clipboard_image()
        if img is None:
            self.toast(T("В буфере обмена нет картинки. Скопируйте QR-код и повторите"), error=True)
            return
        self._receive_image(img)

    def qr_from_screen(self):
        self.root.withdraw()
        self.root.after(450, self._grab_screen)

    def _grab_screen(self):
        img = None
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True) if IS_WIN else ImageGrab.grab()
        except Exception:
            img = None
        finally:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        if img is None:
            self.toast(T("Не удалось сделать снимок экрана"), error=True)
            return
        try:
            texts = core.read_qr(img)
        except Exception:
            texts = []
        self._receive_qr_texts(texts, T("На экране не найден QR-код. Откройте его крупнее и повторите"))

    # ------------------------------------------------------------------ сохранение
    def _need_qr(self):
        if self.qr_mat is None:
            self.toast(self._err(self.qr_err) if self.qr_err else T("QR-кода пока нет: сначала зашифруйте сообщение"),
                       error=True)
            return False
        return True

    def _out_dir(self):
        try:
            return output_dir()
        except OSError as e:
            self.toast(T("Не удалось создать папку «Код Марса» в Документах: {e}", e=e), error=True)
            return None

    def save_qr(self):
        if not self._need_qr():
            return
        folder = self._out_dir()
        if not folder:
            return
        try:
            self._qr_export().save(unique_path(folder, f"QR {dt.datetime.now():%d.%m.%Y %H-%M-%S}.png"))
        except Exception as e:
            self.toast(T("Не удалось сохранить: {e}", e=e), error=True)
            return
        self.toast(T("QR-код сохранён в «Документы\\Код Марса»"), folder=folder)

    def copy_qr(self):
        if not self._need_qr():
            return
        if not IS_WIN:
            self.toast(T("Копирование картинки работает в Windows. Используйте «Сохранить QR»"), error=True)
            return
        try:
            copy_image_to_clipboard(self._qr_export(), self.root.winfo_id())
        except Exception as e:
            self.toast(T("Не удалось скопировать картинку: {e}", e=e), error=True)
            return
        self.toast(T("QR-код скопирован. Вставьте его в мессенджер: Ctrl+V"))

    def _form_cipher(self):
        """Шифровка для бланка и её номер: дата отправки / порядковый номер в этом сеансе."""
        cipher = self._cipher_in_field()
        if not cipher:
            self.toast(T("Сначала зашифруйте сообщение: бланк заполняется шифровкой"), error=True)
            return None
        if cipher not in self.form_numbers:
            self.form_seq += 1
            now = dt.datetime.now()
            self.form_numbers[cipher] = (forms.form_number(now, self.form_seq), now)
        return cipher

    def form_png(self):
        cipher = self._form_cipher()
        folder = self._out_dir() if cipher else None
        if not folder:
            return
        number, when = self.form_numbers[cipher]
        stem = f"{T('Шифровка')} {number.replace('/', '-')}"
        try:
            pages = forms.render_png_pages(resource("assets", "form_blank.png"), cipher,
                                           self._key_label(self.cipher_kid), number, when, i18n.form_labels())
            for i, img in enumerate(pages, 1):
                name = f"{stem}.png" if len(pages) == 1 else f"{stem} {T('(лист {i})', i=i)}.png"
                img.save(unique_path(folder, name))
        except Exception as e:
            self.toast(T("Не удалось сохранить бланк: {e}", e=e), error=True)
            return
        n = len(pages)
        self.toast(T("Бланк {number} сохранён: {n} {sheets} PNG в «Документы\\Код Марса»", number=number, n=n,
                     sheets=i18n.plural(n, ("лист", "листа", "листов"))), folder=folder)

    def form_docx(self):
        cipher = self._form_cipher()
        folder = self._out_dir() if cipher else None
        if not folder:
            return
        number, when = self.form_numbers[cipher]
        try:
            forms.build_docx(resource("assets", "form_blank.png"), cipher, self._key_label(self.cipher_kid), number,
                             unique_path(folder, f"{T('Шифровка')} {number.replace('/', '-')}.docx"), when,
                             i18n.form_labels())
        except Exception as e:
            self.toast(T("Не удалось сохранить бланк: {e}", e=e), error=True)
            return
        n = len(forms.paginate(forms.groups_of(cipher)))
        self.toast(T("Бланк {number} для Word сохранён ({n} {sheets}) в «Документы\\Код Марса»", number=number, n=n,
                     sheets=i18n.plural(n, ("лист", "листа", "листов"))), folder=folder)

    # ------------------------------------------------------------------ перетаскивание
    def _setup_dnd(self):
        if not HAS_DND:
            return
        targets = [(self.root, "cipher"), (self.qr_cv, "cipher"), (self.b32, "cipher"),
                   (self.morse, "cipher"), (self.msg, "message")]
        targets += [(lbl, "message" if w is self.msg else "cipher")
                    for w, (lbl, _) in self._placeholders.items() if isinstance(w, tk.Text)]
        for widget, role in targets:
            try:
                widget.drop_target_register(DND_FILES, DND_TEXT)
                widget.dnd_bind("<<Drop>>", lambda e, r=role: self._on_drop(e, r))
            except Exception:
                pass

    def _on_drop(self, event, role):
        data = event.data or ""
        try:
            items = list(self.root.tk.splitlist(data))
        except tk.TclError:
            items = [data]
        files = [p for p in items if os.path.isfile(p)]
        if files:
            self.root.after(10, lambda: self.open_path(files[0]))
        elif data.strip():
            if role == "message" and not (core.looks_like_b32(data) or morse.is_morse(data)):
                self.msg.insert("insert", data)
            else:
                self.root.after(10, lambda: self._receive_cipher_text(data))
        return getattr(event, "action", COPY)

    def _update_drag_source(self):
        """QR-код можно утащить мышью в чат или папку, когда он есть."""
        if not HAS_DND:
            return
        try:
            if self.qr_mat is not None and not self._drag_on:
                self.qr_cv.drag_source_register(1, DND_FILES)
                self.qr_cv.dnd_bind("<<DragInitCmd>>", self._drag_init)
                self._drag_on = True
            elif self.qr_mat is None and self._drag_on:
                self.qr_cv.drag_source_unregister()
                self._drag_on = False
        except Exception:
            self._drag_on = False

    def _drag_init(self, _event):
        if self.qr_mat is None:
            return (COPY, DND_TEXT, self.b32_get() or " ")
        folder = os.path.join(tempfile.gettempdir(), "KodMarsa")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "qr_kod_marsa.png")
        self._qr_export().save(path)
        return (COPY, DND_FILES, (path,))

    # ------------------------------------------------------------------ клавиатура и меню
    def _bind_global(self):
        self.root.bind_all("<F1>", lambda e: self.show_help())
        self.root.bind_all("<Alt-Left>", self.history_back)
        self.root.bind_all("<Alt-Right>", self.history_forward)
        if IS_WIN:
            self.root.bind_all("<Control-KeyPress>", self._ctrl_fix, add="+")

    def _bind_widgets(self):
        self.msg.bind("<Return>", self.encrypt)
        self.msg.bind("<KP_Enter>", self.encrypt)
        self.msg.bind("<Shift-Return>", lambda e: self._newline(self.msg))
        self.b32.bind("<Return>", self.decrypt_manual)
        self.b32.bind("<KP_Enter>", self.decrypt_manual)
        self.b32.bind("<Shift-Return>", lambda e: "break")
        self.morse.bind("<Return>", self.morse_enter)
        self.morse.bind("<KP_Enter>", self.morse_enter)
        self.morse.bind("<Shift-Return>", lambda e: self._newline(self.morse))

    def _newline(self, widget):
        widget.insert("insert", "\n")
        widget.see("insert")
        return "break"

    def _ctrl_fix(self, event):
        """Ctrl+C/V/X/A/Z при русской и украинской раскладке."""
        if event.keysym.isascii() and len(event.keysym) == 1:
            return None
        action = {67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>", 65: "<<SelectAll>>",
                  90: "<<Undo>>", 89: "<<Redo>>"}.get(event.keycode)
        if not action:
            return None
        w = event.widget
        if action == "<<SelectAll>>" and isinstance(w, tk.Text):
            w.tag_add("sel", "1.0", "end-1c")
        else:
            w.event_generate(action)
        return "break"

    def _bs_press(self, _event):
        self._bs_press_t = time.monotonic()
        if self._bs_job is None:
            self._bs_job = self.root.after(2000, self._bs_fire)

    def _bs_release(self, _event):
        released = time.monotonic()
        self.root.after(70, lambda: self._bs_check(released))

    def _bs_check(self, released):
        if self._bs_press_t <= released and self._bs_job is not None:
            self.root.after_cancel(self._bs_job)
            self._bs_job = None

    def _bs_fire(self):
        self._bs_job = None
        self.clear_all()
        self.toast(T("Все поля очищены"))

    def _text_menu(self, event, widget=None):
        w = widget or event.widget
        w.focus_set()
        is_text = isinstance(w, tk.Text)
        try:
            has_sel = bool(w.tag_ranges("sel")) if is_text else w.selection_present()
        except tk.TclError:
            has_sel = False
        get_all = (lambda: w.get("1.0", "end-1c")) if is_text else w.get
        m = self._menu()
        m.add_command(label=T("Вырезать"), command=lambda: w.event_generate("<<Cut>>"),
                      state="normal" if has_sel else "disabled")
        if has_sel:
            m.add_command(label=T("Копировать"), command=lambda: w.event_generate("<<Copy>>"))
        else:
            m.add_command(label=T("Копировать всё"), command=lambda: self._copy(get_all(), T("Скопировано")))
        m.add_command(label=T("Вставить"),
                      command=self.paste_cipher if w is self.b32 else (lambda: w.event_generate("<<Paste>>")))
        m.add_separator()
        if is_text:
            m.add_command(label=T("Выделить всё"), command=lambda: w.tag_add("sel", "1.0", "end-1c"))
        if w is self.b32:
            clear = lambda: self._set_b32("")
        elif w is self.morse:
            clear = lambda: self._set_morse("")
        elif is_text:
            clear = lambda: self._set(w, "")
        else:
            clear = lambda: w.delete(0, "end")
        m.add_command(label=T("Очистить поле"), command=clear)
        if w is self.b32 or w is self.morse:
            m.add_separator()
            self._add_share(m, text_fn=get_all)
        m.tk_popup(event.x_root, event.y_root)

    def _qr_menu(self, event):
        m = self._menu()
        m.add_command(label=T("Сохранить QR"), command=self.save_qr)
        m.add_command(label=T("Копировать QR"), command=self.copy_qr)
        self._add_share(m, image=True)
        m.add_separator()
        m.add_command(label=T("Открыть QR из файла…"), command=self.open_qr_file)
        m.add_command(label=T("Вставить QR из буфера обмена"), command=self.qr_from_clipboard)
        m.add_command(label=T("Найти QR на экране"), command=self.qr_from_screen)
        m.add_separator()
        m.add_command(label=T("Бланк шифровки PNG"), command=self.form_png)
        m.add_command(label=T("Бланк шифровки Word"), command=self.form_docx)
        m.add_command(label=T("Открыть папку «Код Марса»"), command=lambda: open_folder(output_dir()))
        m.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------ уведомления и справка
    def toast(self, text, error=False, folder=None):
        """Короткое уведомление, которое исчезает само, как Toast на телефоне."""
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._hide_toast()
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        if folder:
            text += T("\nНажмите здесь, чтобы открыть папку.")
        lbl = tk.Label(win, text=text, font=self.f_body, fg="#FFFFFF", bg=C["mars"] if error else C["space"],
                       padx=self.px(18), pady=self.px(10), wraplength=self.px(520), justify="center")
        lbl.pack()
        if folder:
            lbl.configure(cursor="hand2")
            lbl.bind("<Button-1>", lambda e: (open_folder(folder), self._hide_toast()))
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + self.root.winfo_height() - win.winfo_reqheight() - self.px(26)
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._toast_win = win
        self._toast_job = self.root.after(3200 if error else (4500 if folder else 2200), self._hide_toast)

    def _hide_toast(self):
        self._toast_job = None
        if self._toast_win is not None:
            try:
                self._toast_win.destroy()
            except tk.TclError:
                pass
            self._toast_win = None

    def show_help(self):
        if self._help_win is not None and self._help_win.winfo_exists():
            self._help_win.lift()
            return
        win = tk.Toplevel(self.root)
        win.title(T("Справка — Код Марса"))
        win.configure(bg=C["paper"])
        win.geometry(f"{self.px(660)}x{self.px(600)}")
        t = tk.Text(win, wrap="word", font=self.f_text, bg=C["card"], fg=C["ink"], relief="flat",
                    padx=self.px(22), pady=self.px(16), highlightthickness=0, spacing2=self.px(3))
        sb = ttk.Scrollbar(win, orient="vertical", command=t.yview, style="Mars.Vertical.TScrollbar")
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=self.px(14))
        t.pack(fill="both", expand=True, padx=(self.px(14), 0), pady=self.px(14))
        t.tag_configure("h", font=self.f_head, spacing1=self.px(12), spacing3=self.px(4))
        for i, (title, body) in enumerate(i18n.help_sections()):
            t.insert("end", ("" if i == 0 else "\n") + title + "\n", "h")
            t.insert("end", body + "\n")
        t.insert("end", f"\n{T('Код Марса')} v{core.APP_VERSION}")
        t.configure(state="disabled")
        win.bind("<Escape>", lambda e: win.destroy())
        self._help_win = win


def show_splash(root, scale, done):
    """Заставка, как на телефоне: логотип на чёрном фоне."""
    try:
        img = Image.open(resource("assets", "logo.jpg")).convert("RGB")
    except Exception:
        done()
        return
    sh = root.winfo_screenheight()
    h = min(int(560 * scale), int(sh * 0.66))
    w = int(h * img.width / img.height)
    photo = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.configure(bg="black")
    lbl = tk.Label(win, image=photo, bd=0, bg="black")
    lbl.image = photo
    lbl.pack()
    win.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(sh - h) // 2}")
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    state = {"done": False}

    def finish(_e=None):
        if state["done"]:
            return
        state["done"] = True
        win.destroy()
        done()

    lbl.bind("<Button-1>", finish)
    root.after(1800, finish)


def run_selftest():
    """KodMarsa.exe --selftest: проверка собранной программы (пишет selftest.log)."""
    lines = [f"Код Марса {core.APP_VERSION}: самопроверка {dt.datetime.now():%d.%m.%Y %H:%M}"]
    ok = True
    try:
        lines += core.selftest()
        for name in ("logo.jpg", "background.jpg", "form_blank.png", "icon.png", "icon.ico", "sound.png",
                     "lang.png", "menu.png"):
            assert os.path.isfile(resource("assets", name)), f"нет файла assets/{name}"
        lines.append("картинки программы: на месте")
        sample = core.b32encode(core.encrypt("проверка бланка", core.key_bytes(1)))
        when = dt.datetime(2026, 10, 4, 12, 0)
        pages = forms.render_png_pages(resource("assets", "form_blank.png"), sample, "Код 1", "041026/001", when)
        assert len(pages) == 1 and pages[0].size == (forms.FORM_W, forms.FORM_H)
        buf = io.BytesIO()
        forms.build_docx(resource("assets", "form_blank.png"), sample, "Код 1", "041026/001", buf, when)
        assert "word/document.xml" in zipfile.ZipFile(buf).namelist()
        lines.append("бланк шифровки PNG и Word: ок")
        m, _ = morse.encode("Привет, как дела? Встречаемся завтра у реки")
        assert morse.decode(m)[1] == "russian"
        events, total = morse.timeline(morse.encode("PARIS", "latin")[0], morse.DEFAULTS)
        wav = io.BytesIO()
        morse.render_wav(events, total, morse.DEFAULTS, wav)
        assert len(wav.getvalue()) > 10000
        lines.append("азбука Морзе: язык и звук ок")
        img, _ = sstv.qr_frame(core.qr_matrix(sample), "Robot 36")
        assert len(sstv.synthesize(img, "Robot 36")) > sstv.SAMPLE_RATE * 30
        lines.append("SSTV: сигнал Robot 36 собирается")
        for code, _, _ in i18n.LANGS:
            i18n.set_lang(code)
            assert T("Зашифровать") and i18n.help_sections()
        i18n.set_lang("ru")
        lines.append("языки: русский, украинский, польский, английский")
        if not HAS_DND:
            raise AssertionError("модуль tkinterdnd2 не попал в сборку")
        import tkinterdnd2
        assert os.path.isdir(os.path.join(os.path.dirname(tkinterdnd2.__file__), "tkdnd")), "нет папки tkdnd"
        lines.append("перетаскивание: библиотека tkdnd на месте")
        try:
            r = TkinterDnD.Tk()
            r.withdraw()
            lines.append(f"перетаскивание: tkdnd {r.TkdndVersion} загружается")
            r.destroy()
        except Exception as e:  # без экрана окно создать нельзя, это не ошибка сборки
            lines.append(f"предупреждение: окно для проверки tkdnd не создано ({e})")
    except Exception as e:
        ok = False
        lines.append(f"ОШИБКА: {e!r}")
        lines.append(traceback.format_exc())
    lines.append("ИТОГ: " + ("всё в порядке" if ok else "есть ошибки"))
    text = "\n".join(lines) + "\n"
    for folder in (app_dir(), tempfile.gettempdir()):
        try:
            with open(os.path.join(folder, "selftest.log"), "w", encoding="utf-8") as fh:
                fh.write(text)
            break
        except OSError:
            continue
    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1


def main():
    global HAS_DND
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    enable_dpi_awareness()
    root = None
    if HAS_DND:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            HAS_DND = False
            root = getattr(tk, "_default_root", None)
    if root is None:
        root = tk.Tk()
    root.withdraw()
    app = App(root)

    def start():
        root.deiconify()
        root.lift()
        root.focus_force()
        app.msg.focus_set()
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        if args and os.path.isfile(args[0]):  # файл, перетащенный на значок программы
            root.after(300, lambda: app.open_path(args[0]))

    if "--no-splash" in sys.argv:
        start()
    else:
        show_splash(root, app.scale, start)
    root.mainloop()


if __name__ == "__main__":
    main()
