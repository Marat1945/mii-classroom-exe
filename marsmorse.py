# -*- coding: utf-8 -*-
"""
Азбука Морзе для «Кода Марса»: таблицы знаков, разделители, автоопределение
языка передачи и звуковой генератор (тон, громкость, помехи, скорость,
паузы по Фарнсворту). Только стандартная библиотека Python.
"""
from __future__ import annotations

import array
import math
import random
import re
import shutil
import subprocess
import sys
import wave

INTERNATIONAL = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
}
DIGITS = {"0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
          "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----."}
PUNCT_INTL = {".": ".-.-.-", ",": "--..--", "?": "..--..", "!": "-.-.--", "/": "-..-.", "=": "-...-",
              "-": "-....-", "(": "-.--.", ")": "-.--.-", "'": ".----.", '"': ".-..-.", ":": "---...",
              ";": "-.-.-.", "+": ".-.-.", "@": ".--.-."}
PUNCT_CYR = {".": "......", ",": ".-.-.-", "?": "..--..", "!": "--..--", "-": "-....-", ":": "---...",
             ";": "-.-.-.", "/": "-..-.", '"': ".-..-.", "(": "-.--.-", ")": "-.--.-"}
RUSSIAN = {
    "А": ".-", "Б": "-...", "В": ".--", "Г": "--.", "Д": "-..", "Е": ".", "Ж": "...-", "З": "--..",
    "И": "..", "Й": ".---", "К": "-.-", "Л": ".-..", "М": "--", "Н": "-.", "О": "---", "П": ".--.",
    "Р": ".-.", "С": "...", "Т": "-", "У": "..-", "Ф": "..-.", "Х": "....", "Ц": "-.-.", "Ч": "---.",
    "Ш": "----", "Щ": "--.-", "Ъ": "--.--", "Ы": "-.--", "Ь": "-..-", "Э": "..-..", "Ю": "..--",
    "Я": ".-.-",
}
UKRAINIAN = {k: v for k, v in RUSSIAN.items() if k not in ("Ъ", "Ы", "Э")}
UKRAINIAN.update({"И": "-.--", "І": "..", "Ї": ".---", "Є": "..-..", "Ґ": "--.--"})


def _reverse(*tables):
    rev = {}
    for table in tables:
        for ch, code in table.items():
            rev.setdefault(code, ch)
    return rev


REVERSE = {
    "latin": _reverse(INTERNATIONAL, DIGITS, PUNCT_INTL),
    "russian": _reverse(RUSSIAN, DIGITS, PUNCT_CYR),
    "ukrainian": _reverse({k: v for k, v in UKRAINIAN.items() if k != "Ї"}, DIGITS, PUNCT_CYR),
}
LANG_NAMES = {"latin": "международная азбука (латиница)", "russian": "русская азбука",
              "ukrainian": "украинская азбука"}
ALPHABET_CHOICES = [("auto", "Автоопределение языка"), ("latin", "Международная (латиница)"),
                    ("russian", "Русская (кириллица)"), ("ukrainian", "Украинская (кириллица)")]
SEPARATORS = [
    ("slash", "Косая черта (/) между буквами и две косые черты (//) между словами", "/", "//"),
    ("space", "Пробел между буквами и два пробела между словами", " ", "  "),
    ("space_slash", "Пробел между буквами и косая черта (/) между словами", " ", " / "),
]
SEPARATOR_MAP = {key: (letter, word) for key, _, letter, word in SEPARATORS}
DEFAULTS = {"wpm": 15, "farnsworth": False, "fwpm": 10, "tone": 880, "volume": 80, "noise": 10,
            "separator": "space_slash", "alphabet": "auto"}

# частота букв, % (для автоопределения языка)
_EN = {"A": 8.2, "B": 1.5, "C": 2.8, "D": 4.3, "E": 12.7, "F": 2.2, "G": 2.0, "H": 6.1, "I": 7.0,
       "J": 0.15, "K": 0.77, "L": 4.0, "M": 2.4, "N": 6.7, "O": 7.5, "P": 1.9, "Q": 0.095, "R": 6.0,
       "S": 6.3, "T": 9.1, "U": 2.8, "V": 0.98, "W": 2.4, "X": 0.15, "Y": 2.0, "Z": 0.074}
_RU = {"О": 10.97, "Е": 8.45, "А": 8.01, "И": 7.35, "Н": 6.70, "Т": 6.26, "С": 5.47, "Р": 4.73,
       "В": 4.54, "Л": 4.40, "К": 3.49, "М": 3.21, "Д": 2.98, "П": 2.81, "У": 2.62, "Я": 2.01,
       "Ы": 1.90, "Ь": 1.74, "Г": 1.70, "З": 1.65, "Б": 1.59, "Ч": 1.44, "Й": 1.21, "Х": 0.97,
       "Ж": 0.94, "Ш": 0.73, "Ю": 0.64, "Ц": 0.48, "Щ": 0.36, "Э": 0.32, "Ф": 0.26, "Ъ": 0.04}
_UA = {"О": 9.28, "А": 8.04, "Н": 6.53, "И": 6.11, "І": 5.86, "Т": 5.39, "В": 4.73, "Е": 4.69,
       "Р": 4.65, "С": 4.21, "Л": 3.61, "У": 3.53, "К": 3.52, "Д": 3.37, "М": 3.21, "П": 2.86,
       "Я": 2.65, "З": 2.25, "Ь": 1.73, "Б": 1.62, "Г": 1.60, "Ч": 1.43, "Х": 1.18, "Й": 1.09,
       "Ж": 0.88, "Ю": 0.84, "Ш": 0.79, "Є": 0.79, "Ц": 0.70, "Ї": 0.57, "Щ": 0.47, "Ф": 0.30, "Ґ": 0.01}
_CYRILLIC_ONLY = {"---.", "----", "..--", ".-.-", "..-..", "--.--"}
_FIX = str.maketrans({"·": ".", "•": ".", "∙": ".", "⋅": ".", "—": "-", "–": "-", "−": "-",
                      "‒": "-", "_": "-"})
_CYR = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
_UA_ONLY = re.compile(r"[ІіЇїЄєҐґ]")


def normalize(text):
    """Точки и тире любого начертания -> «.» и «-» (длина текста не меняется)."""
    return text.translate(_FIX)


def is_morse(text):
    t = normalize(text)
    return bool(t.strip()) and re.fullmatch(r"[.\-/|\s]+", t) is not None and ("." in t or "-" in t)


def split_words(morse):
    """Морзянка любого из трёх форматов -> [[коды слова 1], [коды слова 2], ...]."""
    t = normalize(morse).replace("|", "//")
    t = re.sub(r"\s*//+\s*", "\x00", t)
    t = re.sub(r"\s+/\s+", "\x00", t)
    t = re.sub(r"[ \t]{2,}|\s*\n\s*", "\x00", t)
    words = []
    for w in t.split("\x00"):
        letters = [x for x in re.split(r"[\s/]+", w.strip()) if x]
        if letters:
            words.append(letters)
    return words


def text_language(text):
    if _CYR.search(text):
        return "ukrainian" if _UA_ONLY.search(text) else "russian"
    return "latin"


def encode(text, alphabet="auto", separator="space_slash"):
    """Текст -> морзянка. Возвращает (морзянка, использованная азбука)."""
    lang = text_language(text) if alphabet == "auto" else alphabet
    cyr = UKRAINIAN if lang == "ukrainian" else RUSSIAN
    punct = PUNCT_INTL if lang == "latin" else PUNCT_CYR
    letter_sep, word_sep = SEPARATOR_MAP.get(separator, SEPARATOR_MAP["space_slash"])
    words = []
    for word in text.upper().split():
        codes = []
        for ch in word:
            ch = "Е" if ch == "Ё" else ch
            code = (INTERNATIONAL.get(ch) or cyr.get(ch) or RUSSIAN.get(ch) or DIGITS.get(ch)
                    or punct.get(ch) or PUNCT_INTL.get(ch))
            if code:
                codes.append(code)
        if codes:
            words.append(letter_sep.join(codes))
    return word_sep.join(words), lang


def _loglik(text, freq):
    total = sum(freq.values())
    return sum(math.log(freq.get(ch, 0.01) / total) for ch in text if ch.isalpha())


def detect_alphabet(words):
    """Автоопределение языка передачи по самим сигналам."""
    codes = [c for w in words for c in w]
    if not codes:
        return "latin"
    cyr = any(c in _CYRILLIC_ONLY for c in codes)
    if not cyr:
        lat = "".join(REVERSE["latin"].get(c, "") for c in codes)
        ru = "".join(REVERSE["russian"].get(c, "") for c in codes)
        cyr = _loglik(ru, _RU) - _loglik(lat, _EN) > 1.0
    if not cyr:
        return "latin"
    ru = "".join(REVERSE["russian"].get(c, "") for c in codes)
    ua = "".join(REVERSE["ukrainian"].get(c, "") for c in codes)
    return "ukrainian" if _loglik(ua, _UA) > _loglik(ru, _RU) else "russian"


def decode(morse, alphabet="auto"):
    """Морзянка -> (текст, азбука, неизвестные коды)."""
    words = split_words(morse)
    lang = detect_alphabet(words) if alphabet == "auto" else alphabet
    rev = REVERSE[lang]
    unknown, out = [], []
    for w in words:
        chars = []
        for code in w:
            ch = rev.get(code)
            if ch is None:
                unknown.append(code)
                ch = "□"
            chars.append(ch)
        out.append("".join(chars))
    return " ".join(out), lang, unknown


def latin_text(morse):
    """Морзянка -> латиница без пробелов (для шифровки Base32) или None."""
    out = []
    for w in split_words(morse):
        for code in w:
            ch = REVERSE["latin"].get(code)
            if ch is None:
                return None
            out.append(ch)
    return "".join(out) or None


# ---------------------------------------------------------------------------
# Звук
# ---------------------------------------------------------------------------
SAMPLE_RATE = 22050
LEAD_MS = TAIL_MS = 200


def gaps(cfg):
    """Длительности (мс): точка, пауза между буквами, пауза между словами."""
    wpm = max(1, int(cfg.get("wpm", 15)))
    unit = 1200.0 / wpm
    letter, word = 3 * unit, 7 * unit
    fwpm = int(cfg.get("fwpm", wpm))
    if cfg.get("farnsworth") and 0 < fwpm < wpm:
        ta = (60.0 * wpm - 37.2 * fwpm) / (wpm * fwpm) * 1000.0
        letter, word = 3 * ta / 19, 7 * ta / 19
    return unit, letter, word


def _is_word_gap(sep):
    return "//" in sep or "|" in sep or "\n" in sep or re.search(r"\s/\s|\s{2,}", sep) is not None


def timeline(morse, cfg):
    """[(начало_мс, длительность_мс, номер_знака_в_тексте, номер_буквы), ...] и общая длительность."""
    unit, letter_gap, word_gap = gaps(cfg)
    events, t, sep, last_end, letter = [], float(LEAD_MS), None, None, 0
    for idx, ch in enumerate(normalize(morse)):
        if ch in ".-":
            if last_end is not None:
                if sep is None:
                    t = last_end + unit
                else:
                    t = last_end + (word_gap if _is_word_gap(sep) else letter_gap)
                    letter += 1
            dur = unit if ch == "." else 3 * unit
            events.append((t, dur, idx, letter))
            last_end, sep = t + dur, None
        else:
            sep = (sep or "") + ch
    return events, (last_end or LEAD_MS) + TAIL_MS


def shift(events, start):
    """События начиная с номера start; время сдвинуто к началу записи."""
    if not events:
        return [], LEAD_MS + TAIL_MS
    start = max(0, min(start, len(events) - 1))
    base = events[start][0] - LEAD_MS
    out = [(t - base, d, i, l) for t, d, i, l in events[start:]]
    return out, out[-1][0] + out[-1][1] + TAIL_MS


def _segment(kind, n, tone, vol, noise, variant):
    rnd = random.Random(variant * 7919 + n * 31 + (1 if kind == "tone" else 0))
    amp_t = 0.55 * vol * 32767.0
    amp_n = 0.9 * vol * noise * 32767.0
    ramp = max(1, int(0.006 * SAMPLE_RATE))
    w = 2.0 * math.pi * tone / SAMPLE_RATE
    out = array.array("h", bytes(2 * n))
    lp = 0.0
    for i in range(n):
        v = 0.0
        if kind == "tone":
            if i < ramp:
                env = 0.5 - 0.5 * math.cos(math.pi * i / ramp)
            elif i >= n - ramp:
                env = 0.5 - 0.5 * math.cos(math.pi * (n - 1 - i) / ramp)
            else:
                env = 1.0
            v = amp_t * env * math.sin(w * i)
        if amp_n:
            lp += 0.35 * (rnd.random() * 2.0 - 1.0 - lp)
            v += amp_n * lp
            if rnd.random() < 0.0004:  # треск эфира
                v += amp_n * rnd.uniform(-2.5, 2.5)
        out[i] = int(max(-32767.0, min(32767.0, v)))
    return out.tobytes()


def render_wav(events, total_ms, cfg, target):
    """Записывает WAV (путь или файловый объект)."""
    vol = max(0, min(100, int(cfg.get("volume", 80)))) / 100.0
    noise = max(0, min(100, int(cfg.get("noise", 0)))) / 100.0
    tone = max(100, min(4000, int(cfg.get("tone", 880))))
    rnd, cache, chunks, cursor = random.Random(1945), {}, [], 0

    def seg(kind, n):
        key = (kind, n, rnd.randrange(4))
        if key not in cache:
            cache[key] = _segment(kind, n, tone, vol, noise, key[2])
        return cache[key]

    for start, dur, *_ in events:
        s0 = int(round(start * SAMPLE_RATE / 1000.0))
        n = int(round(dur * SAMPLE_RATE / 1000.0))
        if s0 > cursor:
            chunks.append(seg("gap", s0 - cursor))
        chunks.append(seg("tone", n))
        cursor = s0 + n
    end = int(round(total_ms * SAMPLE_RATE / 1000.0))
    if end > cursor:
        chunks.append(seg("gap", end - cursor))
    with wave.open(target, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(chunks))


class Player:
    """Проигрывание WAV без блокировки окна."""

    def __init__(self):
        self._proc = None

    def play(self, path):
        self.stop()
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return True
        for cmd in (["paplay", path], ["aplay", "-q", path], ["afplay", path]):
            if shutil.which(cmd[0]):
                try:
                    self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                except OSError:
                    continue
        return False

    def stop(self):
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
