"""Шапка-«прилад»: циферблат зі стрілкою, лампочка зв'язку й назва, що переливається.

• Є інтернет — стрілка праворуч (трохи гойдається), лампочка м'яко мерехтить зеленим.
• Нема інтернету — стрілка ліворуч, лампочка червона, теж ледь мерехтить.
• Раз на 10–15 секунд по назві програми зліва направо пробігає відблиск.
Уся динаміка — прості функції без Tk, тож вона перевіряється тестами без вікна.
"""
from __future__ import annotations

import math
import random
import time
import tkinter as tk
from tkinter import font as tkfont

from . import retro_assets as assets

HEIGHT = 108
TITLE_FONT_FAMILY = "Georgia"
BASE_TITLE = (214, 188, 112)                           # глибоке золото
GLINT_TITLE = (255, 255, 242)                          # спалах «білого золота»
AMBER = (214, 164, 64)
GREEN = (104, 224, 138)
RED = (255, 98, 84)
LAMP_DARK = (22, 26, 23)
NEEDLE_RANGE = 52.0                                    # градусів від вертикалі


def mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def hexcolor(rgb):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, c))) for c in rgb)


def needle_target(online):
    """Куди дивиться стрілка: праворуч — зв'язок є, ліворуч — немає, посередині — ще не знаємо."""
    if online is None:
        return 0.0
    return NEEDLE_RANGE if online else -NEEDLE_RANGE


def needle_wobble(online, t):
    """Легке «живе» коливання стрілки (поки є зв'язок — плавніше й більше; нема — дрібне тремтіння)."""
    if online is None:
        return 2.0 * math.sin(t * 1.3)
    if online:
        return 4.0 * math.sin(t * 1.7) + 1.4 * math.sin(t * 4.3 + 0.7)
    return 1.3 * math.sin(t * 5.1) + 0.6 * math.sin(t * 9.4)


def lamp_intensity(t):
    """Ледь помітне мерехтіння лампочки: 0.72…1.0."""
    return 0.86 + 0.09 * math.sin(2.2 * t) + 0.05 * math.sin(5.9 * t + 1.0)


def lamp_core(online):
    return AMBER if online is None else (GREEN if online else RED)


def lamp_layers(online, t):
    """Кольори п'яти шарів сяйва лампочки — від м'якого ореолу до яскравого ядра."""
    glow = lamp_intensity(t)
    core = lamp_core(online)
    return tuple(mix(LAMP_DARK, core, k * glow) for k in (0.10, 0.24, 0.44, 0.70, 0.97))


def glint_color(char_x, progress, total_width, band=95.0):
    """Колір літери назви під час відблиску: progress 0…1 — положення світлої смуги зліва направо."""
    centre = -band + (total_width + 2 * band) * progress
    k = max(0.0, 1.0 - abs(char_x - centre) / band) ** 2
    return mix(BASE_TITLE, GLINT_TITLE, k)


def next_glint_delay_ms(rng=random):
    return int(rng.uniform(10000, 15000))


class InstrumentHeader(tk.Canvas):
    def __init__(self, parent, title, subtitle="", author="", rng=None, animate=True):
        super().__init__(parent, height=HEIGHT, highlightthickness=0, bd=0, bg="#2f3631")
        self.title_text, self.subtitle_text, self.author_text = title, subtitle, author
        self.online = None
        self.angle = 0.0
        self.rng = rng or random.Random()
        self._animate = animate
        self._images = []
        self._char_items = []
        self._char_xs = []
        self._title_span = (0, 1)
        self._glint_start = None
        self._layout_job = None
        self._tick_job = None
        self._glint_job = None
        self._width_drawn = 0
        self.pivot = (62, 66)
        self.bind("<Configure>", self._schedule_layout)
        self.bind("<Destroy>", self._on_destroy)
        if animate:
            self._tick_job = self.after(80, self._tick)
            self._glint_job = self.after(min(4000, next_glint_delay_ms(self.rng)), self._start_glint)

    # ---------- стан ----------
    def set_online(self, online):
        self.online = online

    # ---------- малювання ----------
    def _schedule_layout(self, _event=None):
        if self._layout_job:
            try:
                self.after_cancel(self._layout_job)
            except tk.TclError:
                pass
        self._layout_job = self.after(60, self.layout)

    def layout(self):
        self._layout_job = None
        width = max(self.winfo_width(), 640)
        if width == self._width_drawn and self._char_items:
            return
        self._width_drawn = width
        self.delete("all")
        self._images = []
        self._char_items = []
        if not assets.available():
            self.configure(bg="#2f3631")
        else:
            self._draw_textures(width)
        self._draw_text(width)
        self._draw_needle_and_lamp()

    def _keep(self, image):
        self._images.append(image)
        return image

    def _draw_textures(self, width):
        self.create_image(0, 0, anchor="nw", image=self._keep(assets.photo(assets.metal_image(width, HEIGHT), self)))
        self.create_image(14, 6, anchor="nw", image=self._keep(assets.photo(assets.dial_image(96), self)))
        self.create_image(128, 32, anchor="nw", image=self._keep(assets.photo(assets.lamp_bezel_image(44), self)))
        author_w = 360 if width >= 1000 else 300
        self._author_box = (width - author_w - 16, 12, width - 16, HEIGHT - 12)
        left = 196
        right = self._author_box[0] - 14
        self._title_box = (left, 10, right, HEIGHT - 10)
        for box in (self._title_box, self._author_box):
            w, h = box[2] - box[0], box[3] - box[1]
            self.create_image(box[0], box[1], anchor="nw", image=self._keep(assets.photo(assets.plate_image(w, h), self)))
        rivet = self._keep(assets.photo(assets.rivet_image(11), self))
        for box in (self._title_box, self._author_box):
            for x, y in ((box[0] + 9, box[1] + 9), (box[2] - 9, box[1] + 9), (box[0] + 9, box[3] - 9), (box[2] - 9, box[3] - 9)):
                self.create_image(x, y, image=rivet)

    def _draw_text(self, width):
        if not hasattr(self, "_title_box"):
            self._title_box = (196, 10, width - 392, HEIGHT - 10)
            self._author_box = (width - 376, 12, width - 16, HEIGHT - 12)
        left, top, right, bottom = self._title_box
        center = (left + right) / 2
        title_font = tkfont.Font(family=TITLE_FONT_FAMILY, size=23, weight="bold")
        small = tkfont.Font(family=TITLE_FONT_FAMILY, size=9)
        total = title_font.measure(self.title_text)
        icon_w = 44 if assets.available() else 0
        start = center - (total + icon_w) / 2 + icon_w
        if assets.available():
            self.create_image(start - 26, 38, image=self._keep(assets.photo(assets.mortarboard_image(40), self)))
        self.create_text(center, 38, text=self.title_text, state="hidden", tags="title_full")
        self._char_xs, self._char_items = [], []
        for index, char in enumerate(self.title_text):
            x = start + title_font.measure(self.title_text[:index])
            self._char_xs.append(x - start)
            self._char_items.append(self.create_text(x + 1, 40, text=char, anchor="w", font=title_font,
                                                     fill=hexcolor(BASE_TITLE)))
        self._title_span = (start, max(total, 1))
        if self.subtitle_text:
            self.create_text(center, 74, text=self.subtitle_text, font=small, fill="#cfc7a6")
        if self.author_text:
            lines = self.author_text
            if "—" in lines and "\n" not in lines:
                head, tail = lines.split("—", 1)
                lines = head.strip() + " —\n" + tail.strip()
            box = self._author_box
            self.create_text((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, text=lines, justify="center",
                             font=tkfont.Font(family=TITLE_FONT_FAMILY, size=10, weight="bold"), fill="#e8dfbd",
                             tags="author_text")

    def _draw_needle_and_lamp(self):
        px, py = self.pivot
        self._needle_shadow = self.create_line(px + 1, py + 1, px + 1, py - 29, fill="#8a7d62", width=3, capstyle="round")
        self._needle = self.create_line(px, py, px, py - 30, fill="#8b1f16", width=2, capstyle="round")
        self._cap = self.create_oval(px - 5, py - 5, px + 5, py + 5, fill="#3a3127", outline="#1b1712")
        cx, cy = 150, 54
        self._lamp = [self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#161a17", outline="")
                      for r in (16.5, 14, 11.5, 8.5, 5.5)]
        self._lamp_spark = self.create_oval(cx - 5, cy - 6, cx - 1, cy - 2, fill="#e9fff0", outline="")
        self._apply_needle()
        self._apply_lamp(time.monotonic())

    # ---------- анімація ----------
    def step(self, t, smooth=0.18):
        """Один кадр: стрілка наближається до цілі (з коливанням). Окремо для тестів."""
        goal = needle_target(self.online) + needle_wobble(self.online, t)
        self.angle += (goal - self.angle) * smooth
        return self.angle

    def _apply_needle(self):
        if not getattr(self, "_needle", None):
            return
        px, py = self.pivot
        a = math.radians(self.angle)
        length = 30
        end = (px + length * math.sin(a), py - length * math.cos(a))
        self.coords(self._needle, px, py, *end)
        self.coords(self._needle_shadow, px + 1, py + 1, end[0] + 1, end[1] + 1)

    def _apply_lamp(self, t):
        if not getattr(self, "_lamp", None):
            return
        for item, rgb in zip(self._lamp, lamp_layers(self.online, t)):
            self.itemconfigure(item, fill=hexcolor(rgb))
        self.itemconfigure(self._lamp_spark, fill=hexcolor(mix(LAMP_DARK, (233, 255, 240), 0.55 * lamp_intensity(t))))

    def _tick(self):
        self._tick_job = None
        try:
            if not self.winfo_exists():
                return
            t = time.monotonic()
            self.step(t)
            self._apply_needle()
            self._apply_lamp(t)
            self._apply_glint(t)
        except tk.TclError:
            return
        self._tick_job = self.after(34 if self._glint_start else 70, self._tick)

    def _start_glint(self):
        self._glint_job = None
        self._glint_start = time.monotonic()
        self._glint_job = self.after(next_glint_delay_ms(self.rng), self._start_glint)

    def _apply_glint(self, t):
        if self._glint_start is None or not self._char_items:
            return
        progress = (t - self._glint_start) / 1.5
        done = progress >= 1.0
        progress = min(progress, 1.0)
        total = self._title_span[1]
        for item, x in zip(self._char_items, self._char_xs):
            color = BASE_TITLE if done else glint_color(x, progress, total)
            self.itemconfigure(item, fill=hexcolor(color))
        if done:
            self._glint_start = None

    def _on_destroy(self, _event=None):
        for name in ("_tick_job", "_glint_job", "_layout_job"):
            job = getattr(self, name, None)
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
