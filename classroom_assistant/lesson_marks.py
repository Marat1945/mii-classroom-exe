"""Позначки в таблиці дня: дзвіночок за 10 хвилин до уроку й червона рамка навколо часу уроку, що йде.

• Дзвіночок з'являється праворуч від номера уроку, ледь помітно гойдається й зникає, коли урок починається.
• З початком уроку навколо його часу (стовпчик «Час») з'являється червона рамка без заливки: тонка лінія, по якій
  повільно пробігає ніжний відблиск; з кінцем уроку рамка зникає.
Усе рахується за годинником комп'ютера (app.clock) і часом уроків у розкладі.
"""
from __future__ import annotations

import io
import math
import time
import tkinter as tk
from datetime import datetime

from . import lesson_clock, retro_assets
from .lesson_clock import BELL, NOW

BASE_RED = (196, 36, 30)
GLINT = (255, 150, 132)
THICKNESS = 2
SEGMENT = 5
BELL_PX = 24
SWING_DEGREES = 8.0
SWING_SECONDS = 2.8
GLINT_SECONDS = 3.4
FRAMES = 17
ROW_DEFAULT_BG = "#F4ECD6"
ROW_SELECTED_BG = "#3E7DBA"


def mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def hexcolor(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def swing_angle(t: float) -> float:
    """Кут гойдання дзвіночка (градуси): плавна синусоїда, без ривків."""
    return SWING_DEGREES * math.sin(2 * math.pi * t / SWING_SECONDS)


def edge_color(fraction: float, t: float):
    """Колір точки рамки: ледь «дихає», а по периметру повільно біжить світліший відблиск (fraction — позиція 0…1)."""
    base = tuple(c * (0.86 + 0.14 * math.sin(2 * math.pi * t / 2.6)) for c in BASE_RED)
    centre = (t / GLINT_SECONDS) % 1.0
    distance = abs(fraction - centre)
    distance = min(distance, 1.0 - distance)
    return mix(base, GLINT, 0.9 * math.exp(-(distance / 0.05) ** 2))


class EdgeFrame:
    """Червона рамка без заливки з чотирьох тонких смужок (дочірні віджети таблиці: обрізаються її краями)."""

    def __init__(self, parent):
        self.parent = parent
        self.strips = [tk.Canvas(parent, highlightthickness=0, bd=0, bg=hexcolor(BASE_RED)) for _ in range(4)]
        self.rect = None
        self.items = [[], [], [], []]
        self.colors = {}

    def _build(self, width, height):
        lengths = (width, height, width, height)
        for strip, length, items in zip(self.strips, lengths, self.items):
            strip.delete("all")
            items.clear()
            count = max(1, math.ceil(length / SEGMENT))
            horizontal = strip in (self.strips[0], self.strips[2])
            for k in range(count):
                a, b = k * SEGMENT, min(length, (k + 1) * SEGMENT)
                coords = (a, 0, b, THICKNESS) if horizontal else (0, a, THICKNESS, b)
                items.append(strip.create_rectangle(*coords, fill=hexcolor(BASE_RED), outline=""))
        self.colors = {}

    def show(self, rect, t):
        x, y, width, height = rect
        width, height = max(width, 6), max(height, 6)
        if self.rect is None or self.rect[2:] != (width, height):
            self._build(width, height)
        self.rect = (x, y, width, height)
        top, right, bottom, left = self.strips
        top.place(x=x, y=y, width=width, height=THICKNESS)
        bottom.place(x=x, y=y + height - THICKNESS, width=width, height=THICKNESS)
        left.place(x=x, y=y, width=THICKNESS, height=height)
        right.place(x=x + width - THICKNESS, y=y, width=THICKNESS, height=height)
        for strip in self.strips:
            strip.tk.call("raise", str(strip))                          # саме віджет (Canvas.lift піднімає малюнок на полотні)
        total = 2 * (width + height)
        for index, items in enumerate(self.items):
            for k, item in enumerate(items):
                centre = k * SEGMENT + SEGMENT / 2
                if index == 0:                                            # верх: зліва направо
                    s = centre
                elif index == 1:                                          # право: згори вниз
                    s = width + centre
                elif index == 2:                                          # низ: справа наліво
                    s = width + height + (width - centre)
                else:                                                     # ліво: знизу вгору
                    s = 2 * width + height + (height - centre)
                color = hexcolor(edge_color(s / total, t))
                if self.colors.get(item) != color:
                    self.strips[index].itemconfigure(item, fill=color)
                    self.colors[item] = color

    def hide(self):
        for strip in self.strips:
            strip.place_forget()
        self.rect = None


class Bell:
    """Дзвіночок: кадри з поворотом навколо ручки, змальовані на кольорі рядка (Tk не вміє напівпрозорість)."""

    def __init__(self, master):
        self.master = master
        self._base = None
        self._cache = {}

    def _source(self):
        if self._base is None:
            from PIL import Image
            from .bell_data import png_bytes
            image = Image.open(io.BytesIO(png_bytes())).convert("RGBA")
            canvas = Image.new("RGBA", (image.width * 3 // 2, image.height * 3 // 2), (0, 0, 0, 0))
            canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2), image)
            self._base = canvas                                              # запас навколо, щоб гойдання не обрізалось
        return self._base

    def frames(self, bg: str, side: int = round(BELL_PX * 1.5)):
        key = (bg, side)
        if key not in self._cache:
            from PIL import Image
            base = self._source()
            pivot = (base.width * 0.36, base.height * 0.27)                  # ручка дзвіночка
            frames = []
            bg_rgb = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))
            for i in range(FRAMES):
                angle = -SWING_DEGREES + 2 * SWING_DEGREES * i / (FRAMES - 1)
                rotated = base.rotate(angle, resample=Image.BICUBIC, center=pivot)
                small = rotated.resize((side, side), Image.LANCZOS)
                tile = Image.new("RGBA", (side, side), bg_rgb + (255,))
                tile.alpha_composite(small)
                frames.append(retro_assets.photo(tile, self.master))
            self._cache[key] = frames
        return self._cache[key]

    def frame_for(self, bg: str, t: float, side: int = round(BELL_PX * 1.5)):
        frames = self.frames(bg, side)
        position = (swing_angle(t) + SWING_DEGREES) / (2 * SWING_DEGREES)
        return frames[max(0, min(FRAMES - 1, round(position * (FRAMES - 1))))]


class LessonMarks:
    def __init__(self, app):
        self.app = app
        self.grid = app.grid
        self.bell = Bell(self.grid)
        self.frames = []                                                     # EdgeFrame на кожен урок, що йде
        self.labels = []                                                     # Label з дзвіночком на кожен урок, що скоро
        self.state = {}
        self.errors = 0
        self._job = None
        self._t0 = time.monotonic()

    # ---------- допоміжне ----------
    def now(self) -> datetime:
        return self.app.clock()

    def viewed_day(self):
        try:
            from .gui import parse_date
            return parse_date(self.app.datevar.get())
        except Exception:
            return None

    def row_background(self, iid) -> str:
        if iid in self.grid.selection():
            return ROW_SELECTED_BG
        for tag in self.grid.item(iid, "tags") or ():
            color = str(self.grid.tag_configure(tag, "background") or "")
            if color.startswith("#") and len(color) == 7:
                return color
        return ROW_DEFAULT_BG

    # ---------- цикл ----------
    def start(self):
        self.tick()

    def stop(self):
        if self._job:
            try:
                self.app.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def tick(self, t=None):
        """Один крок: перерахувати, хто зараз має позначку, і намалювати. t — час для анімації (у тестах задається)."""
        self._job = None
        try:
            if not self.grid.winfo_exists():
                return
            t = (time.monotonic() - self._t0) if t is None else t
            day = self.viewed_day()
            self.state = lesson_clock.phases(self.app.rows, day, self.now()) if day else {}
            self._draw(t)
        except tk.TclError:
            self.errors += 1                                             # збій одного кадру не зупиняє позначки назавжди
        busy = bool(self.state)
        try:
            self._job = self.app.after(90 if busy else 1000, self.tick)
        except tk.TclError:
            self._job = None

    def refresh(self):
        """Негайно (наприклад, після зміни дати чи розкладу)."""
        self.stop()
        self.tick()

    def _draw(self, t):
        current = [iid for iid, phase in self.state.items() if phase == NOW]
        soon = [iid for iid, phase in self.state.items() if phase == BELL]
        while len(self.frames) < len(current):
            self.frames.append(EdgeFrame(self.grid))
        while len(self.labels) < len(soon):
            self.labels.append(tk.Label(self.grid, bd=0, highlightthickness=0))
        shown_frames = 0
        for iid in current:
            box = self.grid.bbox(iid, "#2") if self.grid.exists(iid) else ""
            if box and shown_frames < len(self.frames):
                x, y, width, height = box
                self.frames[shown_frames].show((x, y, width, height), t)
                shown_frames += 1
        for frame in self.frames[shown_frames:]:
            frame.hide()
        shown_labels = 0
        for iid in soon:
            box = self.grid.bbox(iid, "#1") if self.grid.exists(iid) else ""
            if box:
                x, y, width, height = box
                bg = self.row_background(iid)
                label = self.labels[shown_labels]
                side = max(16, min(round(BELL_PX * 1.5), height - 2))          # не вищий за рядок: не налізає на сусідній
                label.configure(image=self.bell.frame_for(bg, t, side), bg=bg)
                label.place(x=x + width - side - 1, y=y + (height - side) // 2, width=side, height=side)
                shown_labels += 1
        for label in self.labels[shown_labels:]:
            label.place_forget()

    @property
    def visible(self) -> dict:
        """Що показано зараз: {'frames': кількість рамок, 'bells': кількість дзвіночків} — для перевірки."""
        return {"frames": sum(1 for f in self.frames if f.rect is not None),
                "bells": sum(1 for label in self.labels if label.winfo_manager())}
