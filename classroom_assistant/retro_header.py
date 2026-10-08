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
    """Шапка-прилад. Малюється у «проєктних» розмірах і масштабується (set_scale): на низьких екранах вона стискається,
    щоб лишилось місце таблиці й повідомленню."""

    def __init__(self, parent, title, subtitle="", author="", rng=None, animate=True, on_materials=None):
        super().__init__(parent, height=HEIGHT, highlightthickness=0, bd=0, bg="#2f3631")
        self.title_text, self.subtitle_text, self.author_text = title, subtitle, author
        self.on_materials = on_materials
        self.s = 1.0
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
        self._mat_images = {}
        self._mat_item = None
        self.pivot = (62, 66)
        self.bind("<Configure>", self._schedule_layout)
        self.bind("<Destroy>", self._on_destroy)
        if animate:
            self._tick_job = self.after(80, self._tick)
            self._glint_job = self.after(min(4000, next_glint_delay_ms(self.rng)), self._start_glint)

    # ---------- масштаб ----------
    def px(self, value) -> int:
        return max(1, round(value * self.s))

    def set_scale(self, s):
        """Стиснути чи розтягнути шапку (0,55…1): на низьких екранах вона займає менше місця."""
        s = max(0.5, min(1.0, float(s)))
        if abs(s - self.s) < 0.01:
            return
        self.s = s
        self.configure(height=self.px(HEIGHT))
        self._width_drawn = 0
        self._schedule_layout()

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
        self._mat_item = None
        self._geometry(width)
        if not assets.available():
            self.configure(bg="#2f3631")
        else:
            self._draw_textures(width)
        self._draw_materials_button()
        self._draw_text(width)
        self._draw_needle_and_lamp()

    def _keep(self, image):
        self._images.append(image)
        return image

    def _geometry(self, width):
        """Розкладка шапки (усе кратне масштабу): прилад, табличка назви, кнопка «Навчальні матеріали», табличка автора."""
        p, height = self.px, self.px(HEIGHT)
        author_w = p(360 if width >= 1000 else 300)
        self._author_box = (width - author_w - p(16), p(12), width - p(16), height - p(12))
        button_w = p(150) if self.on_materials else 0
        gap = p(12) if self.on_materials else 0
        self._button_box = (self._author_box[0] - gap - button_w, p(22), self._author_box[0] - gap, height - p(22))
        right = (self._button_box[0] - p(12)) if self.on_materials else self._author_box[0] - p(14)
        self._title_box = (p(196), p(10), right, height - p(10))
        self.pivot = (p(62), p(66))

    def _draw_textures(self, width):
        p, height = self.px, self.px(HEIGHT)
        self.create_image(0, 0, anchor="nw", image=self._keep(assets.photo(assets.metal_image(width, height), self)))
        self.create_image(p(14), p(6), anchor="nw", image=self._keep(assets.photo(assets.dial_image(p(96)), self)))
        self.create_image(p(128), p(32), anchor="nw", image=self._keep(assets.photo(assets.lamp_bezel_image(p(44)), self)))
        for box in (self._title_box, self._author_box):
            w, h = box[2] - box[0], box[3] - box[1]
            self.create_image(box[0], box[1], anchor="nw",
                              image=self._keep(assets.photo(assets.plate_image(w, h, radius=p(12)), self)))
        rivet = self._keep(assets.photo(assets.rivet_image(p(11)), self))
        inset = p(9)
        for box in (self._title_box, self._author_box):
            for x, y in ((box[0] + inset, box[1] + inset), (box[2] - inset, box[1] + inset),
                         (box[0] + inset, box[3] - inset), (box[2] - inset, box[3] - inset)):
                self.create_image(x, y, image=rivet)

    def _draw_materials_button(self):
        """Кнопка «Навчальні матеріали» ліворуч від таблички автора: латунна пластина, при наведенні світлішає."""
        if not self.on_materials:
            return
        left, top, right, bottom = self._button_box
        w, h = right - left, bottom - top
        font = tkfont.Font(family=TITLE_FONT_FAMILY, size=-self.px(14), weight="bold")
        if assets.available():
            self._mat_images = {state: assets.photo(assets.button_image(state, w, h), self) for state in ("normal", "hover", "pressed")}
            self._images.extend(self._mat_images.values())
            self._mat_item = self.create_image(left, top, anchor="nw", image=self._mat_images["normal"], tags="materials")
        else:
            self._mat_item = self.create_rectangle(left, top, right, bottom, fill="#D4C497", outline="#3A3127", tags="materials")
        self.create_text((left + right) / 2, (top + bottom) / 2, text="Навчальні\nматеріали", justify="center", font=font,
                         fill="#2A2118", tags=("materials", "materials_text"))
        self.tag_bind("materials", "<Enter>", lambda _e: self._mat_state("hover"))
        self.tag_bind("materials", "<Leave>", lambda _e: self._mat_state("normal"))
        self.tag_bind("materials", "<ButtonPress-1>", lambda _e: self._mat_state("pressed"))
        self.tag_bind("materials", "<ButtonRelease-1>", self._mat_release)
        self.tag_bind("materials", "<Enter>", lambda _e: (self._mat_state("hover"), self.configure(cursor="hand2")), add="+")
        self.tag_bind("materials", "<Leave>", lambda _e: self.configure(cursor=""), add="+")

    def _mat_state(self, state):
        if self._mat_item and self._mat_images:
            self.itemconfigure(self._mat_item, image=self._mat_images[state])

    def _mat_release(self, _event=None):
        self._mat_state("hover")
        if self.on_materials:
            self.on_materials()

    def _draw_text(self, width):
        p = self.px
        left, top, right, bottom = self._title_box
        center = (left + right) / 2
        title_font = tkfont.Font(family=TITLE_FONT_FAMILY, size=-p(30), weight="bold")
        small = tkfont.Font(family=TITLE_FONT_FAMILY, size=-max(8, p(12)))
        total = title_font.measure(self.title_text)
        icon_w = p(44) if assets.available() else 0
        while total + icon_w > (right - left) - p(36) and title_font.cget("size") < -9:       # вузька табличка: зменшити назву
            title_font = tkfont.Font(family=TITLE_FONT_FAMILY, size=title_font.cget("size") + 1, weight="bold")
            total = title_font.measure(self.title_text)
        start = center - (total + icon_w) / 2 + icon_w
        title_y, subtitle_y = p(40), p(75)
        if assets.available():
            self.create_image(start - p(26), p(38), image=self._keep(assets.photo(assets.mortarboard_image(p(40)), self)))
        self.create_text(center, title_y, text=self.title_text, state="hidden", tags="title_full")
        self._char_xs, self._char_items = [], []
        for index, char in enumerate(self.title_text):
            x = start + title_font.measure(self.title_text[:index])
            self._char_xs.append(x - start)
            self._char_items.append(self.create_text(x + 1, title_y, text=char, anchor="w", font=title_font,
                                                     fill=hexcolor(BASE_TITLE)))
        self._title_span = (start, max(total, 1))
        if self.subtitle_text and self.s >= 0.7:
            self.create_text(center, subtitle_y, text=self.subtitle_text, font=small, fill="#cfc7a6")
        if self.author_text:
            lines = self.author_text
            if "—" in lines and "\n" not in lines:
                head, tail = lines.split("—", 1)
                lines = head.strip() + " —\n" + tail.strip()
            box = self._author_box
            self.create_text((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, text=lines, justify="center",
                             font=tkfont.Font(family=TITLE_FONT_FAMILY, size=-max(9, p(13)), weight="bold"), fill="#e8dfbd",
                             tags="author_text")

    def _draw_needle_and_lamp(self):
        p = self.px
        px_, py = self.pivot
        self._needle_len = p(30)
        self._needle_shadow = self.create_line(px_ + 1, py + 1, px_ + 1, py - self._needle_len, fill="#8a7d62",
                                               width=max(2, p(3)), capstyle="round")
        self._needle = self.create_line(px_, py, px_, py - self._needle_len, fill="#8b1f16", width=max(1, p(2)), capstyle="round")
        cap = max(3, p(5))
        self._cap = self.create_oval(px_ - cap, py - cap, px_ + cap, py + cap, fill="#3a3127", outline="#1b1712")
        cx, cy = p(150), p(54)
        self._lamp = [self.create_oval(cx - p(r), cy - p(r), cx + p(r), cy + p(r), fill="#161a17", outline="")
                      for r in (16.5, 14, 11.5, 8.5, 5.5)]
        self._lamp_spark = self.create_oval(cx - p(5), cy - p(6), cx - p(1), cy - p(2), fill="#e9fff0", outline="")
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
        px_, py = self.pivot
        a = math.radians(self.angle)
        length = getattr(self, "_needle_len", 30)
        end = (px_ + length * math.sin(a), py - length * math.cos(a))
        self.coords(self._needle, px_, py, *end)
        self.coords(self._needle_shadow, px_ + 1, py + 1, end[0] + 1, end[1] + 1)

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
            pass
        try:
            self._tick_job = self.after(34 if self._glint_start else 70, self._tick)
        except tk.TclError:
            self._tick_job = None

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
