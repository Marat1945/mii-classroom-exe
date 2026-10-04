"""Іконка програми: багаторозмірний .ico з логотипу (для Провідника, панелі завдань і заголовка вікна).

Малі розміри (до 64 пікселів) записуються класичним BMP із прозорістю, великі (128, 256) — PNG: так іконку
коректно показують усі версії Windows, а PyInstaller вбудовує її у .exe.
"""
from __future__ import annotations

import io
import struct

from PIL import Image, ImageFilter

SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_LIMIT = 128                                           # від цього розміру кадр зберігається як PNG


def clean_alpha(image: Image.Image, floor: int) -> Image.Image:
    """Майже невидиму напівпрозорість (сліди «сяйва» по краях) робимо повністю прозорою: кути без «крапок»."""
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(lambda v: 0 if v < floor else v)
    image.putalpha(alpha)
    return image


def tight_square(image: Image.Image, margin: float = 0.02) -> Image.Image:
    """Обрізати порожні поля навколо логотипу й вирівняти до квадрата з невеликим відступом."""
    image = clean_alpha(image, 6)
    box = image.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    if box:
        image = image.crop(box)
    side = int(max(image.size) * (1 + 2 * margin))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2), image)
    return canvas


def render(image: Image.Image, size: int) -> Image.Image:
    """Стиснути до size пікселів із м'яким згладжуванням; дрібні розміри трохи підгострюємо для читабельності."""
    small = image.resize((size, size), Image.LANCZOS, reducing_gap=3.0)
    if size <= 48:
        small = small.filter(ImageFilter.UnsharpMask(radius=0.7, percent=70, threshold=2))
    return clean_alpha(small, 3)


def _bmp_frame(image: Image.Image) -> bytes:
    width, height = image.size
    pixels = bytearray()
    rgba = image.convert("RGBA")
    for y in range(height - 1, -1, -1):                   # рядки знизу вгору
        for x in range(width):
            r, g, b, a = rgba.getpixel((x, y))
            pixels += bytes((b, g, r, a))
    mask_row = ((width + 31) // 32) * 4                    # маска прозорості: усе 0, альфа вже в пікселях
    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(pixels) + mask_row * height, 0, 0, 0, 0)
    return header + bytes(pixels) + bytes(mask_row * height)


def _png_frame(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def build_ico(source: Image.Image, sizes=SIZES) -> bytes:
    """Зібрати .ico з усіх розмірів (кадри: BMP до 64 пікселів, PNG для 128 і 256)."""
    square = tight_square(source)
    frames = []
    for size in sizes:
        picture = render(square, size)
        frames.append((size, _png_frame(picture) if size >= PNG_LIMIT else _bmp_frame(picture)))
    data = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    body = b""
    for size, blob in frames:
        shown = 0 if size >= 256 else size
        data += struct.pack("<BBBBHHII", shown, shown, 0, 0, 1, 32, len(blob), offset + len(body))
        body += blob
    return data + body


def build_png(source: Image.Image, size: int = 256) -> bytes:
    """PNG для вікна програми (вбудовується в код: файл поруч не потрібен)."""
    return _png_frame(render(tight_square(source), size))
