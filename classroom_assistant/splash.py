"""Заставка з логотипом: щонайменше 3 секунди перед входом у програму.

Поки програма завантажується, зелена лампочка на логотипі швидко й хаотично блимає; щойно завантаження завершилось,
лампочка горить рівно й стабільно, і на третій секунді відкривається головне вікно.
Малювання ведеться вручну (без обробки подій), тож заставка не заважає завантаженню головного вікна.
"""
from __future__ import annotations

import io
import random
import time
import tkinter as tk
from tkinter import _tkinter
from tkinter import font as tkfont

BACKGROUND = "#171A17"
CREAM = "#E8DFBD"
MIN_SECONDS = 3.0                                     # загальна тривалість заставки
STEADY_MIN = 0.6                                      # скільки лампочка горить рівно перед запуском
BLINK_INTERVAL = 0.085                                # зміна яскравості під час завантаження
LEVELS = (0.0, 0.22, 0.5, 0.8, 1.0)                   # яскравість лампочки у «блиманні»


def render_frames(size: int):
    """Кадри заставки: [(яскравість, PIL-зображення)] та рівне світіння (останній елемент). Лампочка змінюється плавно."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    from .splash_data import LED_CENTER, LED_CORE, png_bytes
    logo = Image.open(io.BytesIO(png_bytes())).convert("RGBA").resize((size, size), Image.LANCZOS)
    base = Image.new("RGBA", (size, size), BACKGROUND)
    base.alpha_composite(logo)
    base = base.convert("RGB")
    cx, cy, core = LED_CENTER[0] * size, LED_CENTER[1] * size, LED_CORE * size
    radius = core * 1.18
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1.0, core * 0.12)))
    dark = Image.new("RGB", (size, size), (16, 34, 20))
    off = Image.composite(dark, base, mask)                                   # «погаслий» — тільки ядро, обідок лишається
    halo = Image.new("L", (size, size), 0)
    ImageDraw.Draw(halo).ellipse((cx - core * 2.6, cy - core * 2.6, cx + core * 2.6, cy + core * 2.6), fill=255)
    halo = halo.filter(ImageFilter.GaussianBlur(core * 1.1))
    glow = Image.merge("RGB", (halo.point(lambda v: int(v * 0.10)), halo.point(lambda v: int(v * 0.55)),
                               halo.point(lambda v: int(v * 0.16))))

    def frame(level, glowing):
        picture = Image.blend(off, base, level)
        return ImageChops.screen(picture, glow) if glowing else picture
    frames = [(level, frame(level, level >= 0.8)) for level in LEVELS]
    steady = frame(1.0, True)
    return frames, steady


class Splash:
    """Заставка. pump() викликають під час завантаження (блимає), finish() — коли все готово (рівне світло, потім закриття)."""

    def __init__(self, root, min_seconds=MIN_SECONDS, clock=time.monotonic, sleep=time.sleep, rng=None, size=None):
        self.root = root
        self.min_seconds = min_seconds
        self.clock, self.sleep = clock, sleep
        self.rng = rng or random.Random()
        self.started = clock()
        self.loaded_at = None
        self.closed = False
        self.level = None
        self._last_change = -1.0
        self._hid_with_alpha = False
        self._hide_root()
        screen_h = root.winfo_screenheight()
        side = size or int(max(300, min(520, screen_h * 0.52)))
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.win.configure(bg=BACKGROUND)
        height = side + 46
        x = (root.winfo_screenwidth() - side) // 2
        y = max(0, (screen_h - height) // 2)
        self.win.geometry(f"{side}x{height}+{x}+{y}")
        self.canvas = tk.Canvas(self.win, width=side, height=height, bg=BACKGROUND, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.frames, self.steady = render_frames(side)
        from . import retro_assets
        self._photos = [retro_assets.photo(image, self.canvas) for _, image in self.frames]
        self._steady_photo = retro_assets.photo(self.steady, self.canvas)
        self.item = self.canvas.create_image(0, 0, anchor="nw", image=self._photos[0])
        self.label = self.canvas.create_text(side / 2, side + 22, text="Завантаження…", fill=CREAM,
                                             font=tkfont.Font(family="Georgia", size=12))
        self._service()
        self.pump()

    # ---------- головне вікно ховаємо, доки заставка не закінчиться ----------
    def _hide_root(self):
        try:
            self.root.attributes("-alpha", 0.0)
            self._hid_with_alpha = True
        except tk.TclError:
            self.root.withdraw()

    def _show_root(self):
        try:
            if self._hid_with_alpha:
                self.root.attributes("-alpha", 1.0)
            else:
                self.root.deiconify()
        except tk.TclError:
            pass

    # ---------- стан лампочки ----------
    @property
    def elapsed(self) -> float:
        return self.clock() - self.started

    @property
    def steady_now(self) -> bool:
        return self.loaded_at is not None

    def _choose_level(self) -> int:
        """Хаотичне блимання: наступний кадр завжди відрізняється від поточного, часті різкі перемикання."""
        options = [k for k in range(len(self.frames)) if k != self.level]
        return self.rng.choice(options)

    def _service(self):
        """Намалювати заставку: обробляємо лише події вікна й «простою», але НЕ таймери програми (їх запуск відкладається
        до того, як заставка закриється: нічого не з'являється поверх неї)."""
        try:
            flags = _tkinter.DONT_WAIT | _tkinter.WINDOW_EVENTS | _tkinter.IDLE_EVENTS
            for _ in range(30):
                if not self.root.tk.dooneevent(flags):
                    break
        except (tk.TclError, AttributeError):
            try:
                self.win.update_idletasks()
            except tk.TclError:
                self.closed = True

    def pump(self):
        """Одне оновлення під час завантаження: коли настав час — інша яскравість лампочки (без обробки подій)."""
        if self.closed:
            return
        now = self.elapsed
        if self.steady_now:
            if self.level != "steady":
                self.level = "steady"
                self.canvas.itemconfigure(self.item, image=self._steady_photo)
                self.canvas.itemconfigure(self.label, text="Готово")
        elif now - self._last_change >= BLINK_INTERVAL:
            self._last_change = now
            self.level = self._choose_level()
            self.canvas.itemconfigure(self.item, image=self._photos[self.level])
        self._service()

    def finish(self):
        """Завантаження завершено: рівне світло; заставка триває до 3 секунд від початку (і щонайменше STEADY_MIN рівного світла)."""
        if self.closed:
            return
        self.loaded_at = self.elapsed
        deadline = max(self.min_seconds, self.loaded_at + STEADY_MIN)
        while True:
            self.pump()
            if self.closed or self.elapsed >= deadline:
                break
            self.sleep(0.016)
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self._show_root()
