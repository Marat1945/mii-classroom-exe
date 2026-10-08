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


def alert_icon(color, size=112):
    """Бомбочка в кольоровому колі (як на сповіщенні «Повітряна тривога»): носом донизу праворуч."""
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, big - 1, big - 1), fill=tuple(color) + (255,))
    unit = big / 100
    bomb = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(bomb)
    ink = (22, 22, 22, 255)

    def p(*points):
        return [(x * unit, y * unit) for x, y in points]
    d.rounded_rectangle([x * unit for x in (22, 39, 64, 61)], radius=9 * unit, fill=ink)       # корпус
    d.polygon(p((58, 39), (86, 50), (58, 61)), fill=ink)                                        # носова частина
    d.polygon(p((22, 39), (13, 22), (31, 22), (36, 39)), fill=ink)                              # верхній стабілізатор
    d.polygon(p((22, 61), (13, 78), (31, 78), (36, 61)), fill=ink)                              # нижній стабілізатор
    d.line([x * unit for x in (60, 39, 60, 61)], fill=tuple(color) + (255,), width=max(2, int(3 * unit)))   # смужка
    bomb = bomb.rotate(-45, resample=Image.BICUBIC, center=(big / 2, big / 2))
    scaled = int(big * 0.78)
    bomb = bomb.resize((scaled, scaled), Image.LANCZOS)
    img.alpha_composite(bomb, ((big - scaled) // 2, (big - scaled) // 2))
    return img.resize((size, size), Image.LANCZOS)


def paper_image(width, height, seed=5):
    """Старий календарний папір: тепла охра, зерно, затемнені краї, плями й підігнуті заокруглені кути (RGBA)."""
    width, height = max(int(width), 16), max(int(height), 16)
    rng = random.Random(seed)
    base = (238, 219, 182)
    raw = Image.frombytes("L", (width, height), rng.randbytes(width * height))
    grain = raw.point(lambda v: int(128 + (v - 128) * 0.10)).filter(ImageFilter.GaussianBlur(0.6))
    paper = Image.merge("RGB", [ImageChops.add(Image.new("L", (width, height), c), grain, 1, -128) for c in base])
    vignette = Image.new("L", (width, height), 0)
    d = ImageDraw.Draw(vignette)
    steps = 24
    for i in range(steps):                                  # від країв до центру світлішає
        k = i / (steps - 1)
        inset = int(min(width, height) * 0.22 * k)
        d.rectangle((inset, inset, width - inset - 1, height - inset - 1), fill=int(40 * (1 - k)))
    vignette = vignette.filter(ImageFilter.GaussianBlur(max(3, min(width, height) // 14)))
    paper = ImageChops.subtract(paper, Image.merge("RGB", [vignette.point(lambda v: v // 2)] * 3))
    stains = Image.new("L", (width, height), 0)
    sd = ImageDraw.Draw(stains)
    for _ in range(7):                                      # легкі плями часу
        x, y = rng.randrange(width), rng.randrange(height)
        r = rng.randrange(max(6, width // 14), max(10, width // 5))
        sd.ellipse((x - r, y - r // 2, x + r, y + r // 2), fill=rng.randrange(8, 20))
    stains = stains.filter(ImageFilter.GaussianBlur(max(4, width // 22)))
    paper = ImageChops.subtract(paper, Image.merge("RGB", [stains] * 3))
    mask = Image.new("L", (width, height), 0)
    radius = max(6, int(min(width, height) * 0.04))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius, fill=255)
    out = paper.convert("RGBA")
    edge = ImageDraw.Draw(out)
    edge.rounded_rectangle((0, 0, width - 1, height - 1), radius, outline=(150, 128, 92, 255), width=max(1, width // 160))
    fold = Image.new("RGBA", (width, height), (0, 0, 0, 0))     # підігнутий верхній правий кут: світліший трикутник
    size = max(10, int(min(width, height) * 0.10))
    ImageDraw.Draw(fold).polygon([(width - size, 0), (width, 0), (width, size)], fill=(250, 238, 206, 235), outline=(150, 128, 92, 255))
    out.alpha_composite(fold)
    out.putalpha(mask)
    return out


def dialog_icon(kind, size=64):
    """Значок вікна повідомлення: «i» (синій), «!» (бурштиновий), «✕» (червоний), «?» (мідний): круглі, з металевим обідком."""
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    palette = {"info": ((54, 118, 190), (255, 255, 255)), "warning": ((226, 164, 40), (60, 40, 10)),
               "error": ((196, 52, 44), (255, 255, 255)), "question": ((196, 150, 84), (52, 36, 20))}
    fill, ink = palette.get(kind, palette["info"])
    c = big / 2
    for i in range(10):                                                # металевий обідок
        k = i / 9
        r = c - SCALE - k * big * 0.05
        d.ellipse((c - r, c - r, c + r, c + r), fill=_mix((176, 170, 150), (58, 50, 40), k) + (255,))
    inner = c * 0.80
    for i in range(12):                                                # коло з легким світлом зверху
        k = i / 11
        r = inner * (1 - k * 0.04)
        d.ellipse((c - r, c - r - k * big * 0.02, c + r, c + r - k * big * 0.02),
                  fill=_mix(tuple(min(255, int(v * 1.18)) for v in fill), fill, k) + (255,))
    w = max(2, int(big * 0.09))
    ink4 = ink + (255,)
    if kind == "info":
        d.ellipse((c - w * 0.9, c - big * 0.27, c + w * 0.9, c - big * 0.27 + w * 1.8), fill=ink4)
        d.rounded_rectangle((c - w * 0.9, c - big * 0.10, c + w * 0.9, c + big * 0.27), w // 2, fill=ink4)
    elif kind == "warning":
        d.rounded_rectangle((c - w * 0.9, c - big * 0.27, c + w * 0.9, c + big * 0.06), w // 2, fill=ink4)
        d.ellipse((c - w * 0.95, c + big * 0.13, c + w * 0.95, c + big * 0.13 + w * 1.9), fill=ink4)
    elif kind == "error":
        a = big * 0.20
        d.line((c - a, c - a, c + a, c + a), fill=ink4, width=int(w * 1.3))
        d.line((c - a, c + a, c + a, c - a), fill=ink4, width=int(w * 1.3))
    else:
        d.arc((c - big * 0.17, c - big * 0.30, c + big * 0.17, c + big * 0.04), 180, 400, fill=ink4, width=int(w * 1.15))
        d.line((c + big * 0.14, c - big * 0.07, c + big * 0.02, c + big * 0.03), fill=ink4, width=int(w * 1.15))
        d.line((c, c + big * 0.03, c, c + big * 0.10), fill=ink4, width=int(w * 1.15))
        d.ellipse((c - w * 0.9, c + big * 0.16, c + w * 0.9, c + big * 0.16 + w * 1.8), fill=ink4)
    return img.resize((size, size), Image.LANCZOS)


def frame_strip_image(length, thickness, vertical=False, seed=3):
    """Смужка металевої рамки вікна: зеленувато-сірий метал, іржа, подряпини й тонка мідна лінія з внутрішнього боку."""
    length, thickness = max(int(length), 8), max(int(thickness), 4)
    rng = random.Random(seed)
    base = metal_image(length, thickness, base=(88, 98, 88), seed=seed).convert("RGBA")
    rust = Image.new("RGBA", (length, thickness), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rust)
    for _ in range(max(10, length // 26)):                                      # іржаві плями й патьоки
        x, y = rng.randrange(length), rng.randrange(thickness)
        rx, ry = rng.randrange(5, 30), rng.randrange(1, max(2, thickness // 2 + 1))
        tone = rng.choice(((150, 76, 36), (126, 62, 30), (170, 98, 48), (104, 54, 28)))
        rd.ellipse((x - rx, y - ry, x + rx, y + ry), fill=tone + (rng.randrange(60, 150),))
    rust = rust.filter(ImageFilter.GaussianBlur(1.1))
    base.alpha_composite(rust)
    inner = ImageDraw.Draw(base)
    inner.line((0, thickness - 2, length, thickness - 2), fill=(176, 132, 62, 255), width=1)       # мідний кант (внутрішній бік)
    inner.line((0, thickness - 1, length, thickness - 1), fill=(60, 44, 24, 255), width=1)
    inner.line((0, 0, length, 0), fill=(150, 160, 146, 200), width=1)                                # світла грань зовні
    return base.transpose(Image.ROTATE_90) if vertical else base
