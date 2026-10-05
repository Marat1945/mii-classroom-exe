# -*- coding: utf-8 -*-
"""
Ядро программы «Код Марса»: ключи, шифрование AES-256, Base32,
азбука Морзе, QR-коды и бланк шифровки. Интерфейса здесь нет,
поэтому модуль проверяется тестами отдельно от окна программы.

Совместимость с Android-версией «Код Марса» (16.06.2025):
  * ключи из списка — те же 32 значения HEX и тот же порядок;
  * ключ-фраза — SHA-256 от фразы в UTF-8 (пробелы по краям отбрасываются);
  * AES-256, режим CBC, дополнение PKCS#5, случайный IV (16 байт)
    записывается перед шифротекстом;
  * результат кодируется Base32 (RFC 4648) без знаков «=»;
  * морзянка — коды знаков через пробел.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import math
import os
import re

APP_NAME = "Код Марса"
APP_VERSION = "1.2"


class MarsError(Exception):
    """Ошибка, текст которой можно показать пользователю (code — для перевода)."""

    def __init__(self, text, code=None, **params):
        super().__init__(text)
        self.code, self.params = code, params


# ---------------------------------------------------------------------------
# Ключи. Тот же список и порядок, что в Android-версии (KeyList.kt):
# индекс 0 — «Универсальный», индексы 1–31 — ключи по числу месяца.
# ---------------------------------------------------------------------------
BUILTIN_KEYS = [
    ("Универсальный", "0b04d28d29ef14c7b9e8a7d35fe5ea0ede58b80ad95aabd25edeaa280b1892b3"),
    ("Код 1", "a562fb5fc72edeb0aa62a71f0ad2a84bdbc1e3d62b2e038af705844b979cec72"),
    ("Код 2", "eb8c70827117252fee38f848573d2cc15ef145056275bc20a5cf25d40dcd3e25"),
    ("Код 3", "791e9cb85be628afe5c4c5119897f72c62f5fa4437f9ca25289907db78f7f3ff"),
    ("Код 4", "82d8166e76dd61be53945516878d709a68114668daf1ed699186a2cf5ddce862"),
    ("Код 5", "1bcd2c93e3098df7d40fe0d440dce021ce2aa8a2ac865f0f6d5cd724c0a6289e"),
    ("Код 6", "f3eef236a8171b9632f88a2df2bf69468946c3b0ae6aaa69aa620ce7929d01f7"),
    ("Код 7", "bc334f77cbd9dabb13919e675d5b3a01f1b8cb487af8370b212e9b6ee88c83c2"),
    ("Код 8", "63bd298fb8212b2ef6f263351381369a40ea6b33cae6ffc16cc1ac0ef2593481"),
    ("Код 9", "47bf600774421e579bd9e5ea9313dc6b17c9f50b709bd6c695840d58f4390ae6"),
    ("Код 10", "4e113e6199afd527ed0a516f6ebd60668dfe69b226b5e23375251ead82fb2a80"),
    ("Код 11", "2ba258b84ad39e3a8c0bc204a464ee70fef516d7a02018fc4f485b68ff765f9c"),
    ("Код 12", "698f26b4d503df165021e331dafbb4beb1727f0a9e568357ed98292c8e3f1b06"),
    ("Код 13", "5de87b19568a26021327926ae2d8f3b9386e2dbb976bed74622adf8ce7cfb88c"),
    ("Код 14", "57472f1e1cf7708d16d3ddd11b717ac7059813e6c16e68295c1a6fcfdd7b72e9"),
    ("Код 15", "377dd1e125ad2b625826c8b04991fd5d072cecfcf42fd77d1540e72cbdc42bb6"),
    ("Код 16", "6468c9278245b3906aaa0922fa69fe3256b35cc9f18b5987826fe275258eb89d"),
    ("Код 17", "7881b6f347a9b4996374c669743ce66508f85a928ef03489b6cfd7ebdd00a11b"),
    ("Код 18", "f0e1887b7f413503a1654cbd84a82d01cff2817dd1ac81d43e86f887cf213326"),
    ("Код 19", "769c451ba3d36366df3720f600cd80e053f25d4fc5cf9a0db774532736a41a1b"),
    ("Код 20", "c0f6961dd36fee8253078079851d39364cde61d948cbecbbd545499568b7a9f3"),
    ("Код 21", "e227af29fdf8f95bee9ee1d0f88ba20a3fd791a1e9e93f0e3d7a6983c51474b8"),
    ("Код 22", "50000b9a61e500a65adc9b06ccd3e0f0c7fb04379aaaae474ff9abcca90ce75e"),
    ("Код 23", "09fde2761e3b70f823e020feee751d764ff824f54d7e0ef4dde996087c3b0d86"),
    ("Код 24", "89ed998816246ba0c59a968f73c995badd41c2f729a6ef396dbac8f668097de5"),
    ("Код 25", "b0978c1acbef295f326b1a2fc19150ddd06f1d5118bae491bc0039c2d9ee9956"),
    ("Код 26", "7fd10f65654d74ab74e2f9e3ed8a1e9d4662e2387065ca0a6490ad84e6767abb"),
    ("Код 27", "e1de3b8b79961bb86ca2f6433f40a5b8f2b2e02ec733000b54a258e9f93cdefe"),
    ("Код 28", "4d97f02b9c4d8746a1ef2d39153630276d2da973d8c6cd70e3b8f976021efdfe"),
    ("Код 29", "de1a41a5ca97af3521506eed09306ef6add3a70fa24222bd6bd129c77301e36b"),
    ("Код 30", "9e422f069665d7d2dbcf2c75fb05e4352eb885bf5a33276d0a7e5c5ec3d75cad"),
    ("Код 31", "21b8f7a541a290e5114a835b4e73a23ffa7a5e816c1dfe03452c6f924ab8bded"),
]


def key_names():
    return [name for name, _ in BUILTIN_KEYS]


def key_bytes(index):
    return bytes.fromhex(BUILTIN_KEYS[index][1])


def phrase_key(phrase):
    """Ключ из ключ-фразы — так же, как кнопка «Генерировать ключ» на телефоне."""
    return hashlib.sha256(phrase.strip().encode("utf-8")).digest()


def auto_key_index(today=None, count=None):
    """Автокод: номер ключа равен числу месяца, как в Android-версии."""
    count = len(BUILTIN_KEYS) if count is None else count
    if count < 2:
        return 0
    day = (today or _dt.date.today()).day
    return min(max(day, 1), count - 1)


def key_from_spec(spec):
    """Ключ из записи «list:4» или «phrase:текст» (используется в проверках)."""
    if spec.startswith("list:"):
        return key_bytes(int(spec[5:]))
    if spec.startswith("phrase:"):
        return phrase_key(spec[7:])
    raise ValueError(spec)


# ---------------------------------------------------------------------------
# AES-256-CBC
# ---------------------------------------------------------------------------
def _clean_text(text):
    """Tk в Windows может отдавать эмодзи суррогатными парами — склеиваем их."""
    try:
        return text.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return text.encode("utf-8", "replace").decode("utf-8")


def encrypt(text, key):
    """Текст -> IV + шифротекст (байты), как AESUtil.encrypt на телефоне."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    data = _clean_text(text).encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    iv = os.urandom(16)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + enc.update(padded) + enc.finalize()


def decrypt(blob, key):
    """IV + шифротекст -> текст. Неподходящий ключ вызывает MarsError."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(blob) < 32 or len(blob) % 16:
        raise MarsError("Шифровка неполная или повреждена: проверьте, что скопирован весь текст.", code="incomplete")
    dec = Cipher(algorithms.AES(key), modes.CBC(blob[:16])).decryptor()
    padded = dec.update(blob[16:]) + dec.finalize()
    try:
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    except ValueError:  # сюда же попадает UnicodeDecodeError
        raise MarsError("Ключ не подходит к этой шифровке.", code="wrong_key") from None


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def plausible(text):
    """Похоже ли на настоящий текст (без управляющих символов)."""
    return not _CONTROL.search(text)


def decrypt_any(blob, candidates):
    """Перебор ключей. candidates: [(ключ, название, выбран_пользователем), ...].

    Возвращает (текст, название ключа, выбран_пользователем).
    Для ключей, которые пользователь не выбирал, дополнительно проверяется,
    что результат похож на обычный текст, — так случайные совпадения исключены.
    """
    if len(blob) < 32 or len(blob) % 16:
        raise MarsError("Шифровка неполная или повреждена: проверьте, что скопирован весь текст.", code="incomplete")
    for key, label, primary in candidates:
        try:
            text = decrypt(blob, key)
        except MarsError:
            continue
        if primary or plausible(text):
            return text, label, primary
    raise MarsError("Не удалось расшифровать: не подошёл ни один ключ. "
                    "Если сообщение зашифровано ключ-фразой, введите ту же фразу.", code="no_key")


# ---------------------------------------------------------------------------
# Base32 (RFC 4648, без «=»)
# ---------------------------------------------------------------------------
B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_B32_INDEX = {c: i for i, c in enumerate(B32_ALPHABET)}
# Цифр 0, 1 и 8 в Base32 нет — при ручном наборе их путают с O, I и B.
_B32_FIX = str.maketrans({"0": "O", "1": "I", "8": "B"})


def b32encode(data):
    return base64.b32encode(data).decode("ascii").rstrip("=")


def normalize_b32(text):
    """Убирает пробелы, переносы, «=» и дефисы, переводит в верхний регистр."""
    return re.sub(r"[\s=\-]+", "", text).upper().translate(_B32_FIX)


def b32decode(text):
    """Декодер, повторяющий Base32Util.decode из Android-версии."""
    buf = bits = 0
    out = bytearray()
    for ch in normalize_b32(text):
        v = _B32_INDEX.get(ch)
        if v is None:
            raise MarsError(f"В шифровке недопустимый знак «{ch}». "
                            "Base32 состоит только из латинских букв A–Z и цифр 2–7.", code="bad_char", ch=ch)
        buf = ((buf << 5) | v) & 0xFFFF
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((buf >> bits) & 0xFF)
    return bytes(out)


def looks_like_b32(text):
    s = normalize_b32(text)
    return len(s) >= 52 and all(c in _B32_INDEX for c in s)


# ---------------------------------------------------------------------------
# Азбука Морзе — та же таблица, что в MorseUtil.kt
# ---------------------------------------------------------------------------
MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "А": ".-", "Б": "-...", "В": ".--", "Г": "--.", "Д": "-..", "Е": ".", "Ё": ".",
    "Ж": "...-", "З": "--..", "И": "..", "Й": ".---", "К": "-.-", "Л": ".-..",
    "М": "--", "Н": "-.", "О": "---", "П": ".--.", "Р": ".-.", "С": "...", "Т": "-",
    "У": "..-", "Ф": "..-.", "Х": "....", "Ц": "-.-.", "Ч": "---.", "Ш": "----",
    "Щ": "--.-", "Ъ": "--.--", "Ы": "-.--", "Ь": "-..-", "Э": "..-..", "Ю": "..--",
    "Я": ".-.-",
    "Ґ": "--.--", "Є": "..-..", "І": "..", "Ї": ".---",
    ".": "......", ",": ".-.-.-", "?": "..--..", "!": "--..--",
}
# Для приёма шифровки нужна только латиница и цифры — там коды однозначны.
_MORSE_TO_LATIN = {v: k for k, v in MORSE.items() if k.isascii() and k.isalnum()}
_MORSE_FIX = str.maketrans({"·": ".", "•": ".", "∙": ".", "⋅": ".",
                            "—": "-", "–": "-", "−": "-", "‒": "-", "_": "-"})


def to_morse(text):
    """Как MorseUtil.toMorse: коды через пробел, пробел между словами — «/»."""
    out = []
    for ch in text.upper():
        if ch in MORSE:
            out.append(MORSE[ch])
        elif ch == " ":
            out.append("/")
    return " ".join(out)


def is_morse(text):
    t = text.translate(_MORSE_FIX)
    return bool(re.fullmatch(r"[.\-/|\s]+", t)) and ("." in t or "-" in t)


def morse_to_b32(text):
    """Принятая морзянка -> шифровка Base32."""
    out = []
    for token in re.split(r"[\s/|]+", text.translate(_MORSE_FIX).strip()):
        if not token:
            continue
        ch = _MORSE_TO_LATIN.get(token)
        if ch is None:
            raise MarsError(f"Неизвестный знак Морзе: {token}", code="morse_unknown", token=token)
        out.append(ch)
    return normalize_b32("".join(out))


# ---------------------------------------------------------------------------
# QR-коды
# ---------------------------------------------------------------------------
def qr_matrix(text, border=4):
    """Матрица QR (список строк из True/False) вместе с белой рамкой."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M
    from qrcode.exceptions import DataOverflowError

    for level in (ERROR_CORRECT_M, ERROR_CORRECT_L):
        try:
            qr = qrcode.QRCode(error_correction=level, box_size=1, border=border)
            qr.add_data(text)
            qr.make(fit=True)
            return qr.get_matrix()
        except (DataOverflowError, ValueError):
            continue
    raise MarsError("Сообщение слишком длинное для QR-кода. Шифровка и морзянка готовы, "
                    "их можно отправить текстом.", code="qr_too_long")


def qr_image(matrix, module=8):
    """Чёрно-белая картинка QR; module — размер одной клетки в пикселях."""
    from PIL import Image

    n = len(matrix)
    data = bytes(0 if cell else 255 for row in matrix for cell in row)
    img = Image.frombytes("L", (n, n), data)
    if module > 1:
        img = img.resize((n * module, n * module), Image.NEAREST)
    return img


def read_qr(image):
    """Все тексты QR-кодов, найденных на картинке."""
    import zxingcpp
    from PIL import Image

    img = image
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        white.alpha_composite(rgba)
        img = white
    if img.mode != "L":
        img = img.convert("L")

    def scan(picture):
        try:
            found = zxingcpp.read_barcodes(picture, formats=zxingcpp.BarcodeFormat.QRCode)
        except Exception:
            found = zxingcpp.read_barcodes(picture)
        return [r.text for r in found if getattr(r, "text", "")]

    texts = scan(img)
    if not texts and max(img.size) < 700:  # маленькая картинка из мессенджера
        texts = scan(img.resize((img.width * 3, img.height * 3), Image.LANCZOS))
    return texts


def pick_cipher(texts):
    """Из найденных QR выбирает тот, где записана шифровка или морзянка."""
    for t in texts:
        if looks_like_b32(t) or is_morse(t):
            return t.strip()
    return None


# ---------------------------------------------------------------------------
# Бланк шифровки (картинка form_blank.png из Android-проекта)
# ---------------------------------------------------------------------------
FORM_QR_BOX = (68, 1666, 632, 2229)      # квадрат под QR-код
FORM_KEY_FIELD = (72, 2342, 590)         # поле под квадратом: x, середина по y, правый край
FORM_NUMBER = (1765, 452)                # «ШИФРОВКА №»
FORM_FILED = (1135, 586)                 # «Подана»
FORM_TEXT = (790, 800, 2400, 2960)       # поле для текста шифровки
FORM_INK = (28, 32, 52)                  # цвет «машинописи»


def _form_font(size):
    from PIL import ImageFont

    for name in ("courbd.ttf", "cour.ttf", "consolab.ttf", "consola.ttf",
                 "DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf", "LiberationMono-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_form(form_path, b32, key_label, when=None):
    """Заполняет бланк: QR в квадрат, шифровка группами по 5 знаков, дата и номер.

    Сама ключ-фраза на бланк не попадает — только название ключа.
    """
    from PIL import Image, ImageDraw

    when = when or _dt.datetime.now()
    s = normalize_b32(b32)
    img = Image.open(form_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # QR-код в квадрат
    x0, y0, x1, y1 = FORM_QR_BOX
    inner = min(x1 - x0, y1 - y0) - 44
    try:
        matrix = qr_matrix(s, border=2)
        q = qr_image(matrix, max(1, inner // len(matrix))).convert("RGB")
        img.paste(q, (x0 + (x1 - x0 - q.width) // 2, y0 + (y1 - y0 - q.height) // 2))
    except MarsError:
        draw.text(((x0 + x1) // 2, (y0 + y1) // 2), "QR не\nпомещается", font=_form_font(40),
                  fill=FORM_INK, anchor="mm", align="center")

    # номер, дата, ключ
    draw.text(FORM_NUMBER, when.strftime("%d%m/%H%M"), font=_form_font(58), fill=FORM_INK, anchor="ls")
    draw.text(FORM_FILED, when.strftime("%d.%m.%Y %H:%M"), font=_form_font(42), fill=FORM_INK, anchor="ls")
    kx, ky, kright = FORM_KEY_FIELD
    label = f"Ключ: {key_label}"
    size = 40
    font = _form_font(size)
    while font.getlength(label) > kright - kx and size > 18:
        size -= 2
        font = _form_font(size)
    draw.text((kx, ky), label, font=font, fill=FORM_INK, anchor="lm")

    # шифровка группами по 5 знаков, как в телеграммах
    groups = [s[i:i + 5] for i in range(0, len(s), 5)]
    tx0, ty0, tx1, ty1 = FORM_TEXT
    width, height = tx1 - tx0, ty1 - ty0
    fitted = None
    for size in range(56, 21, -2):
        font = _form_font(size)
        cw = font.getlength("M")
        per_line = max(1, int((width + 2 * cw) // (7 * cw)))
        line_h = int(size * 1.55)
        lines = math.ceil(len(groups) / per_line)
        if (lines + 2) * line_h <= height:
            fitted = (font, cw, per_line, line_h, size)
            break
    overflow = fitted is None
    if overflow:
        font = _form_font(22)
        cw = font.getlength("M")
        fitted = (font, cw, max(1, int((width + 2 * cw) // (7 * cw))), int(22 * 1.55), 22)
    font, cw, per_line, line_h, size = fitted
    max_lines = max(1, height // line_h - 2)
    y = ty0
    for li in range(min(max_lines, math.ceil(len(groups) / per_line))):
        for ci, g in enumerate(groups[li * per_line:(li + 1) * per_line]):
            draw.text((tx0 + ci * 7 * cw, y), g, font=font, fill=FORM_INK)
        y += line_h
    footer = f"Групп: {len(groups)}"
    if overflow and math.ceil(len(groups) / per_line) > max_lines:
        footer += " (полностью шифровка записана в QR-коде)"
    draw.text((tx0, y + line_h // 2), footer, font=_form_font(max(22, int(size * 0.8))), fill=FORM_INK)
    return img


# ---------------------------------------------------------------------------
# Самопроверка (запускается в сборке на GitHub: KodMarsa.exe --selftest)
# ---------------------------------------------------------------------------
# Эти шифровки сделаны настоящим кодом из APK «Код Марса» (16.06.2025).
ANDROID_SAMPLES = [
    ('list:4',
     'Привет, Марс!',
     'HKPJGAZLKZH5UBW5XPBEQBF4D65RBXAWX4JXJYZYA5AJZL5ACZNUSQV3X7D37HTBY36IGOJPNGZTO'),
    ('list:0',
     'Та нехай сміється неспокійна річка — ґанок, їжак, єнот, Ї Є Ґ',
     'O3EEFAOSSKUO3QXOVFEIO3RCYKKQLDZYBVCLSIIWTECRVZYZDBL37LPMX5EMQS6ICD2L5IZD5W73ZUV3OZAX255RQPUSPJT7ELVKEE2R3RUQJJHZZ632QCYONZ3IZU6NNH5DX3ODZOIIO3ROIYS7EPT47X65VEOYAZF4NOEQDIVWLAVZ6C7O3PPEBIONOQP4AFZH4SRJ5WSOC'),
    ('phrase:Красная планета',
     'Многострочное\nсообщение\n\nс пустой строкой',
     '7KODG5KHIOVAHZWELZL336MO7R3FGNWSYVHYCKJ7TEQAIEWJSRCQFZOR3DZF6GCWJWYOB4GEAYTVSKBEZGWUQKYWL2U4VZAZKAQ3M3ULZAWHCIQ7NAX6X65ZAFOPGUDXATSQ34WIHM6NTHISMJW4CSINME'),
    ('list:31',
     'Emoji test 🚀🔐 ✓',
     'KLLV4CZANCMTAGAXZIBSLIY3CMNO32UNGNHHW6R7DXGXAEEAYV7YNFUIKBPYBT5CKIBTRCL6MZHKI'),
]


def selftest():
    log = []
    assert len(BUILTIN_KEYS) == 32 and all(len(bytes.fromhex(h)) == 32 for _, h in BUILTIN_KEYS)
    log.append("ключи: 32 шт., формат верный")
    for spec, plain, cipher in ANDROID_SAMPLES:
        assert decrypt(b32decode(cipher), key_from_spec(spec)) == plain, spec
    log.append(f"шифровки с телефона: {len(ANDROID_SAMPLES)} из {len(ANDROID_SAMPLES)} расшифрованы")
    sample = "Проверка связи ✓ Їжак, ґанок"
    for i in range(len(BUILTIN_KEYS)):
        c = b32encode(encrypt(sample, key_bytes(i)))
        assert decrypt(b32decode(c), key_bytes(i)) == sample
    log.append("шифрование и расшифровка всеми ключами: ок")
    assert morse_to_b32(to_morse(c)) == c
    log.append("азбука Морзе туда и обратно: ок")
    assert read_qr(qr_image(qr_matrix(c), 6)) == [c]
    log.append("QR: создание и распознавание: ок")
    blob = b32decode(c)
    cands = [(key_bytes(4), "Код 4", True)] + [(key_bytes(i), BUILTIN_KEYS[i][0], False) for i in range(32)]
    assert decrypt_any(blob, cands)[1] == BUILTIN_KEYS[31][0]
    log.append("автоподбор ключа: ок")
    return log
