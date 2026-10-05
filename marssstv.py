# -*- coding: utf-8 -*-
"""
SSTV для «Кода Марса»: передача картинки QR-кода звуком по узкополосному
радиоканалу. Чистый Python, без дополнительных библиотек: заголовок VIS
и строки изображения синтезируются частотной модуляцией с непрерывной фазой
(1500 Гц — чёрный, 2300 Гц — белый, 1200 Гц — синхроимпульс).
"""
from __future__ import annotations

import array
import math
import wave

import marscore as core

SAMPLE_RATE = 11025
HEADER_MS = 910.0
TAIL_MS = 300.0

MODES = {
    "Martin 1": dict(vis=44, w=320, h=256, kind="martin", scan=146.432),
    "Martin 2": dict(vis=40, w=320, h=256, kind="martin", scan=73.216),
    "PD 50": dict(vis=93, w=320, h=256, kind="pd", scan=91.52),
    "PD 90": dict(vis=99, w=320, h=256, kind="pd", scan=170.24),
    "PD 120": dict(vis=95, w=640, h=496, kind="pd", scan=121.6),
    "PD 160": dict(vis=98, w=512, h=400, kind="pd", scan=195.584),
    "PD 180": dict(vis=96, w=640, h=496, kind="pd", scan=183.04),
    "PD 240": dict(vis=97, w=640, h=496, kind="pd", scan=244.48),
    "PD 290": dict(vis=94, w=800, h=616, kind="pd", scan=228.8),
    "Scottie 1": dict(vis=60, w=320, h=256, kind="scottie", scan=138.24),
    "Scottie 2": dict(vis=56, w=320, h=256, kind="scottie", scan=88.064),
    "Scottie DX": dict(vis=76, w=320, h=256, kind="scottie", scan=345.6),
    "Robot 36": dict(vis=8, w=320, h=240, kind="robot36", scan=88.0),
    "Robot 72": dict(vis=12, w=320, h=240, kind="robot72", scan=138.0),
    "Wraase SC2-180": dict(vis=55, w=320, h=256, kind="wraase", scan=235.0),
}
MODE_NAMES = list(MODES)


def _row_ms(m):
    """Время передачи одной строки изображения, мс."""
    s, k = m["scan"], m["kind"]
    if k == "martin":
        return 4.862 + 0.572 + 3 * (s + 0.572)
    if k == "scottie":
        return 1.5 + s + 1.5 + s + 9.0 + 1.5 + s
    if k == "wraase":
        return 5.5225 + 0.5 + 3 * s
    if k == "robot36":
        return 9.0 + 3.0 + 88.0 + 4.5 + 1.5 + 44.0
    if k == "robot72":
        return 9.0 + 3.0 + 138.0 + 4.5 + 1.5 + 69.0 + 4.5 + 1.5 + 69.0
    return (20.0 + 2.08 + 4 * s) / 2   # PD: две строки за один кадр


def _image_start(m):
    return HEADER_MS + (9.0 if m["kind"] == "scottie" else 0.0)


def duration_ms(name):
    m = MODES[name]
    return _image_start(m) + m["h"] * _row_ms(m) + TAIL_MS


def progress(name, elapsed_ms):
    """Доля уже переданных строк картинки (0…1)."""
    m = MODES[name]
    done = (elapsed_ms - _image_start(m)) / (m["h"] * _row_ms(m))
    return max(0.0, min(1.0, done))


def qr_frame(matrix, name):
    """Кадр SSTV: QR-код по центру белого поля. Возвращает (картинка, размер клетки в px)."""
    from PIL import Image

    m = MODES[name]
    mod = max(1, (m["h"] - 8) // len(matrix))
    q = core.qr_image(matrix, mod).convert("RGB")
    img = Image.new("RGB", (m["w"], m["h"]), "white")
    img.paste(q, ((m["w"] - q.width) // 2, (m["h"] - q.height) // 2))
    return img, mod


class _Synth:
    """Генератор тона с непрерывной фазой и точным счётом времени."""

    def __init__(self, amp):
        self.table = [int(amp * math.sin(2 * math.pi * i / 4096)) for i in range(4096)]
        self.out = array.array("h")
        self.t = 0.0
        self.n = 0
        self.phase = 0.0

    def tone(self, freq, ms):
        self.t += ms
        end = int(round(self.t * SAMPLE_RATE / 1000.0))
        inc = freq * 4096.0 / SAMPLE_RATE
        ph, tab, out = self.phase, self.table, self.out
        for _ in range(end - self.n):
            out.append(tab[int(ph) & 4095])
            ph += inc
        self.phase = ph % 4096.0
        self.n = end

    def scan(self, values, px_ms):
        tone = self.tone
        for v in values:
            tone(1500.0 + v * (800.0 / 255.0), px_ms)


def _yuv(r, g, b):
    y = 16.0 + (65.738 * r + 129.057 * g + 25.064 * b) / 256.0
    u = 128.0 + (-37.945 * r - 74.494 * g + 112.439 * b) / 256.0
    v = 128.0 + (112.439 * r - 94.154 * g - 18.285 * b) / 256.0
    return y, u, v


def synthesize(img, name, volume=80):
    """Звук SSTV для картинки (размер картинки — как у режима). Возвращает array('h')."""
    m = MODES[name]
    w, h, s, kind = m["w"], m["h"], m["scan"], m["kind"]
    img = img.convert("RGB")
    if img.size != (w, h):
        img = img.resize((w, h))
    px = img.load()
    rows = [[px[x, y] for x in range(w)] for y in range(h)]
    syn = _Synth(0.7 * 32767 * max(0, min(100, volume)) / 100.0)
    tone, scan, p = syn.tone, syn.scan, s / w

    # заголовок VIS: два «лидера» по 1900 Гц, стартовый бит, 7 бит кода, чётность, стоп
    tone(1900, 300); tone(1200, 10); tone(1900, 300); tone(1200, 30)
    bits = [(m["vis"] >> i) & 1 for i in range(7)]
    for b in bits + [sum(bits) % 2]:
        tone(1100 if b else 1300, 30)
    tone(1200, 30)

    if kind == "martin":
        for row in rows:
            tone(1200, 4.862); tone(1500, 0.572)
            for c in (1, 2, 0):          # G, B, R
                scan([px_[c] for px_ in row], p); tone(1500, 0.572)
    elif kind == "scottie":
        tone(1200, 9.0)
        for row in rows:
            tone(1500, 1.5); scan([px_[1] for px_ in row], p)
            tone(1500, 1.5); scan([px_[2] for px_ in row], p)
            tone(1200, 9.0); tone(1500, 1.5); scan([px_[0] for px_ in row], p)
    elif kind == "wraase":
        for row in rows:
            tone(1200, 5.5225); tone(1500, 0.5)
            for c in (0, 1, 2):          # R, G, B
                scan([px_[c] for px_ in row], p)
    else:
        yuv = [[_yuv(*px_) for px_ in row] for row in rows]
        if kind == "pd":
            for y in range(0, h - 1, 2):
                a, b = yuv[y], yuv[y + 1]
                tone(1200, 20.0); tone(1500, 2.08)
                scan([q[0] for q in a], p)
                scan([(q[2] + r[2]) / 2 for q, r in zip(a, b)], p)   # R-Y
                scan([(q[1] + r[1]) / 2 for q, r in zip(a, b)], p)   # B-Y
                scan([q[0] for q in b], p)
        elif kind == "robot36":
            for y in range(h):
                row, pair = yuv[y], yuv[y + 1 if y % 2 == 0 else y - 1]
                tone(1200, 9.0); tone(1500, 3.0); scan([q[0] for q in row], 88.0 / w)
                if y % 2 == 0:
                    tone(1500, 4.5); tone(1900, 1.5)
                    scan([(q[2] + r[2]) / 2 for q, r in zip(row, pair)], 44.0 / w)
                else:
                    tone(2300, 4.5); tone(1900, 1.5)
                    scan([(q[1] + r[1]) / 2 for q, r in zip(row, pair)], 44.0 / w)
        elif kind == "robot72":
            for row in yuv:
                tone(1200, 9.0); tone(1500, 3.0); scan([q[0] for q in row], 138.0 / w)
                tone(1500, 4.5); tone(1900, 1.5); scan([q[2] for q in row], 69.0 / w)
                tone(2300, 4.5); tone(1900, 1.5); scan([q[1] for q in row], 69.0 / w)
    tone(1500, TAIL_MS)
    return syn.out


def write_wav(samples, target):
    with wave.open(target, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
