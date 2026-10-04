"""Процедурні деталі «старого приладу»: метал, заклепки, латунні кнопки, циферблат, таблички.

Усе малюється Pillow у пам'яті (жодних файлів-ресурсів у збірці EXE). Якщо Pillow недоступний, програма
працює зі звичайним плоским виглядом.
"""
from __future__ import annotations

import base64
import io
import math
import random
import tkinter as tk

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError:                                     # pragma: no cover
    Image = None

SCALE = 3                                               # згладжування: малюємо втричі більше й зменшуємо


def available() -> bool:
    return Image is not None


def photo(image, master=None):
    """PIL → PhotoImage через PNG (Pillow.ImageTk для цього не потрібен)."""
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return tk.PhotoImage(master=master, data=base64.b64encode(buffer.getvalue()))


def _mix(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


_METAL_CACHE = {}


def metal_image(width, height, base=(82, 94, 84), seed=11):
    """Темний зеленувато-сірий метал: зерно, ледь помітні подряпини й світлий верх.

    Малюється з фіксованим зерном: при кожній зміні розміру вікна метал виглядає однаково (без мерехтіння).
    """
    width, height = max(int(width), 8), max(int(height), 8)
    key = (width, height, tuple(base), seed)
    if key not in _METAL_CACHE:
        if len(_METAL_CACHE) > 12:
            _METAL_CACHE.clear()
        _METAL_CACHE[key] = _metal_image(width, height, base, seed)
    return _METAL_CACHE[key].copy()


def _metal_image(width, height, base, seed):
    rng = random.Random(seed)
    raw = Image.frombytes("L", (width, height), rng.randbytes(width * height))
    grain = raw.point(lambda v: int(128 + (v - 128) * 0.16)).filter(ImageFilter.GaussianBlur(1.1))
    channels = [ImageChops.add(Image.new("L", (width, height), value), grain, 1, -128) for value in base]
    tex = Image.merge("RGB", channels)
    gradient = Image.linear_gradient("L").resize((width, height))          # 0 угорі → 255 унизу
    light = ImageChops.subtract(Image.new("L", (width, height), 150), gradient)
    shade = ImageChops.subtract(gradient, Image.new("L", (width, height), 120))
    tex = ImageChops.add(tex, Image.merge("RGB", [light.point(lambda v: v // 7)] * 3))
    tex = ImageChops.subtract(tex, Image.merge("RGB", [shade.point(lambda v: v // 7)] * 3))
    draw = ImageDraw.Draw(tex, "RGBA")
    for _ in range(max(6, width // 38)):                                   # тонкі подряпини
        x, y = rng.randrange(width), rng.randrange(height)
        length = rng.randrange(18, 90)
        tone = (255, 255, 240, 20) if rng.random() < 0.5 else (0, 0, 0, 28)
        draw.line((x, y, x + length, y + rng.randint(-2, 2)), fill=tone, width=1)
    return tex


def rivet_image(size=14):
    """Опукла металева заклепка з бліком."""
    big = size * SCALE * 2
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = big / 2
    draw.ellipse((2, 3, big - 2, big - 1), fill=(10, 12, 10, 90))            # тінь
    steps = 14
    for i in range(steps):
        k = i / (steps - 1)
        r = c * 0.92 * (1 - k * 0.82)
        tone = _mix((70, 76, 70), (206, 212, 198), k ** 1.4)
        ox, oy = -k * c * 0.18, -k * c * 0.2
        draw.ellipse((c + ox - r, c + oy - r, c + ox + r, c + oy + r), fill=tone + (255,))
    draw.ellipse((2, 2, big - 3, big - 3), outline=(28, 31, 28, 255), width=max(2, SCALE))
    return img.resize((size, size), Image.LANCZOS)


def button_image(state, width=48, height=34):
    """Латунна пластина з темною окантовкою (дев'ятиклітинкова: краї 10 пікселів)."""
    palette = {
        "normal": ((232, 220, 186), (190, 173, 128)),
        "hover": ((244, 234, 202), (205, 188, 142)),
        "pressed": ((176, 160, 118), (214, 200, 160)),
        "disabled": ((206, 200, 184), (184, 178, 160)),
    }
    top, bottom = palette[state]
    w, h = width * SCALE, height * SCALE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = 8 * SCALE
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((SCALE, SCALE, w - SCALE - 1, h - SCALE - 1), radius, fill=255)
    fill = Image.new("RGBA", (w, h))
    fd = ImageDraw.Draw(fill)
    for y in range(h):
        fd.line((0, y, w, y), fill=_mix(top, bottom, y / max(h - 1, 1)) + (255,))
    img.paste(fill, (0, 0), mask)
    edge = (58, 49, 39, 255) if state != "disabled" else (120, 112, 96, 255)
    draw.rounded_rectangle((SCALE, SCALE, w - SCALE - 1, h - SCALE - 1), radius, outline=edge, width=2 * SCALE)
    inner = (255, 250, 232, 150) if state != "pressed" else (80, 70, 50, 120)
    draw.rounded_rectangle((3 * SCALE, 3 * SCALE, w - 3 * SCALE - 1, h - 3 * SCALE - 1), radius - 2 * SCALE,
                           outline=inner, width=SCALE)
    return img.resize((width, height), Image.LANCZOS)


def plate_image(width, height, radius=12, fill=(36, 42, 38), edge=(18, 21, 19)):
    """Темна таблична з світлою окантовкою: під назву програми й автора."""
    w, h = int(width) * SCALE, int(height) * SCALE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((SCALE, SCALE, w - SCALE - 1, h - SCALE - 1), radius * SCALE, fill=255)
    body = Image.new("RGBA", (w, h))
    bd = ImageDraw.Draw(body)
    for y in range(h):
        k = y / max(h - 1, 1)
        bd.line((0, y, w, y), fill=_mix(tuple(min(255, c + 16) for c in fill), fill, min(1, k * 1.6)) + (255,))
    img.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((SCALE, SCALE, w - SCALE - 1, h - SCALE - 1), radius * SCALE, outline=edge + (255,),
                        width=2 * SCALE)
    d.rounded_rectangle((4 * SCALE, 4 * SCALE, w - 4 * SCALE - 1, h - 4 * SCALE - 1), (radius - 3) * SCALE,
                        outline=(170, 178, 160, 120), width=SCALE)
    return img.resize((int(width), int(height)), Image.LANCZOS)


def dial_image(size=96):
    """Циферблат приладу: рамка, шкала (червона зліва — зв'язку немає, зелена справа — є), значок мережі."""
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = big / 2
    radius = c - 2 * SCALE
    for i in range(12):                                                    # металева рамка
        k = i / 11
        r = radius * (1 - k * 0.12)
        d.ellipse((c - r, c - r, c + r, c + r), fill=_mix((176, 184, 170), (70, 78, 70), k) + (255,))
    d.ellipse((c - radius, c - radius, c + radius, c + radius), outline=(20, 23, 20, 255), width=2 * SCALE)
    face = radius * 0.80
    for i in range(16):                                                    # папір циферблата з затемненням до країв
        k = i / 15
        r = face * (1 - k * 0.0)
        tone = _mix((248, 240, 214), (214, 200, 160), k ** 2)
        rr = face * (1 - 0.05 * k)
        d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=tone + (255,))
        break
    shade = Image.new("L", (big, big), 0)
    sd = ImageDraw.Draw(shade)
    for i in range(18):
        k = i / 17
        r = face * (0.45 + 0.55 * k)
        sd.ellipse((c - r, c - r, c + r, c + r), fill=int(k * 70))
    shade = ImageChops.invert(shade)
    dark = Image.new("RGBA", (big, big), (150, 130, 90, 0))
    dark.putalpha(shade.point(lambda v: 255 - v))
    face_mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(face_mask).ellipse((c - face, c - face, c + face, c + face), fill=255)
    img.paste(dark, (0, 0), ImageChops.multiply(dark.getchannel("A"), face_mask))
    d = ImageDraw.Draw(img)
    d.ellipse((c - face, c - face, c + face, c + face), outline=(60, 50, 38, 255), width=SCALE)
    pivot_y = c + face * 0.30
    box = (c - face * 0.88, pivot_y - face * 0.88, c + face * 0.88, pivot_y + face * 0.88)
    d.arc(box, 210, 245, fill=(176, 52, 40, 255), width=int(4.4 * SCALE))      # червона зона
    d.arc(box, 295, 330, fill=(46, 132, 70, 255), width=int(4.4 * SCALE))      # зелена зона
    d.arc(box, 245, 295, fill=(90, 76, 56, 255), width=int(2.2 * SCALE))
    for deg in range(210, 331, 10):                                        # поділки
        a = math.radians(deg)
        major = deg in (210, 270, 330)
        r1, r2 = face * 0.88, face * (0.70 if major else 0.77)
        d.line((c + r1 * math.cos(a), pivot_y + r1 * math.sin(a), c + r2 * math.cos(a), pivot_y + r2 * math.sin(a)),
               fill=(52, 42, 30, 255), width=int((2 if major else 1.3) * SCALE))
    wx, wy = c, c - face * 0.20                                            # значок мережі
    ink = (54, 44, 32, 255)
    d.ellipse((wx - 2.4 * SCALE, wy + 6 * SCALE, wx + 2.4 * SCALE, wy + 10.8 * SCALE), fill=ink)
    for r in (8, 13.5, 19):
        rr = r * SCALE
        d.arc((wx - rr, wy + 8.4 * SCALE - rr, wx + rr, wy + 8.4 * SCALE + rr), 232, 308, fill=ink, width=int(2.2 * SCALE))
    return img.resize((size, size), Image.LANCZOS)


def lamp_bezel_image(size=44):
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = big / 2
    for i in range(10):
        k = i / 9
        r = (c - SCALE) * (1 - k * 0.20)
        d.ellipse((c - r, c - r, c + r, c + r), fill=_mix((168, 176, 162), (52, 58, 52), k) + (255,))
    d.ellipse((SCALE, SCALE, big - SCALE - 1, big - SCALE - 1), outline=(18, 20, 18, 255), width=2 * SCALE)
    inner = c * 0.66
    d.ellipse((c - inner, c - inner, c + inner, c + inner), fill=(20, 24, 21, 255))
    return img.resize((size, size), Image.LANCZOS)


def mortarboard_image(size=40):
    """Академічна шапочка (значок програми) кремовим кольором."""
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cream, shade = (236, 226, 190, 255), (150, 138, 108, 255)
    s = big / 40
    d.polygon([(20 * s, 7 * s), (38 * s, 16 * s), (20 * s, 25 * s), (2 * s, 16 * s)], fill=cream, outline=shade)
    d.polygon([(9 * s, 20 * s), (20 * s, 26 * s), (31 * s, 20 * s), (31 * s, 29 * s), (20 * s, 34 * s), (9 * s, 29 * s)],
              fill=shade, outline=cream)
    d.line((35 * s, 17 * s, 35 * s, 30 * s), fill=cream, width=int(1.6 * s))
    d.ellipse((33 * s, 29 * s, 37 * s, 34 * s), fill=cream)
    return img.resize((size, size), Image.LANCZOS)
