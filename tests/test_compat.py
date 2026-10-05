# -*- coding: utf-8 -*-
"""
Проверка совместимости ПК-версии с Android-версией «Код Марса».

Файл android_vectors.tsv получен запуском НАСТОЯЩЕГО кода из APK
(16.06.2025): там названия и HEX всех ключей, HEX ключ-фраз и шифровки,
сделанные телефонным кодом. Тест проверяет, что компьютер:
  * знает те же ключи в том же порядке;
  * получает тот же HEX из ключ-фразы;
  * расшифровывает шифровки телефона и выдаёт ту же морзянку.

Запуск:  python tests/test_compat.py
Экспорт шифровок ПК для обратной проверки телефонным кодом:
         python tests/test_compat.py --export pc_vectors.tsv
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import marscore as core  # noqa: E402

# На Windows-сервере GitHub вывод идёт в кодировке cp1252, и русский текст
# роняет программу. Переключаем вывод на UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def unb64(s):
    return base64.b64decode(s).decode("utf-8")


def spec_key(spec):
    if spec.startswith("list:"):
        return core.key_bytes(int(spec[5:]))
    return core.phrase_key(unb64(spec[len("phrase:"):]))


def load():
    names, keys, vectors, phrases = None, {}, [], []
    with open(os.path.join(HERE, "android_vectors.tsv"), encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[0] == "NAMES":
                names = unb64(p[1]).split("|")
            elif p[0] == "KEY":
                keys[int(p[1])] = p[2]
            elif p[0] == "VEC":
                vectors.append(p[1:])
            elif p[0] == "PHRASEHEX":
                phrases.append((unb64(p[1]), p[2]))
    return names, keys, vectors, phrases


def main():
    names, keys, vectors, phrases = load()
    errors = []

    def check(ok, what):
        if not ok:
            errors.append(what)

    check(names == core.key_names(), "названия ключей не совпадают с телефоном")
    check(len(keys) == 32, "в эталоне должно быть 32 ключа")
    for i, h in keys.items():
        check(core.BUILTIN_KEYS[i][1] == h, f"HEX ключа №{i} не совпадает")
    for phrase, h in phrases:
        check(core.phrase_key(phrase).hex() == h, f"HEX ключ-фразы «{phrase}» не совпадает")

    for spec, plain_b64, cipher, morse in vectors:
        key, plain = spec_key(spec), unb64(plain_b64)
        check(core.decrypt(core.b32decode(cipher), key) == plain, f"не расшифрована шифровка телефона ({spec})")
        if morse != "-":
            check(core.to_morse(cipher) == morse, f"морзянка отличается от телефонной ({spec})")
            check(core.morse_to_b32(morse) == cipher, f"морзянка не переводится обратно ({spec})")
        mine = core.b32encode(core.encrypt(plain, key))
        check(core.decrypt(core.b32decode(mine), key) == plain, f"круг ПК→ПК не сошёлся ({spec})")

    # автоподбор: шифровка ключом «Код 31», выбран «Код 4»
    spec, plain_b64, cipher, _ = next(v for v in vectors if v[0] == "list:31")
    cands = [(core.key_bytes(4), "Код 4", True)] + [
        (core.key_bytes(i), core.BUILTIN_KEYS[i][0], False) for i in range(32)]
    text, label, primary = core.decrypt_any(core.b32decode(cipher), cands)
    check(text == unb64(plain_b64) and label == "Код 31" and not primary, "автоподбор ключа")

    # шифровка с пробелами и строчными буквами (как переписанная с бланка)
    spaced = " ".join(cipher[i:i + 5] for i in range(0, len(cipher), 5)).lower()
    check(core.decrypt(core.b32decode(spaced), spec_key(spec)) == unb64(plain_b64), "шифровка с пробелами")

    # QR туда и обратно
    for _, _, cipher, _ in vectors[:6]:
        check(core.read_qr(core.qr_image(core.qr_matrix(cipher), 4)) == [cipher], "QR не распознан")

    # азбука Морзе: шифровка звучит так же, как на телефоне, все разделители читаются
    import io
    import re
    import zipfile
    import marsform as forms
    import marsmorse as morse

    for _, _, cipher, morse_android in vectors[:8]:
        if morse_android != "-":
            check(morse.encode(cipher, "auto", "space_slash")[0] == morse_android, "морзянка не как на телефоне")
        for sep in morse.SEPARATOR_MAP:
            check(morse.latin_text(morse.encode(cipher, "latin", sep)[0]) == cipher, f"разделители {sep}")
    for text, lang in (("Привет, как дела? Встречаемся завтра у реки в шесть вечера", "russian"),
                       ("Hello, how are you? We meet tomorrow near the river at six", "latin"),
                       ("Привіт, як справи? Зустрічаємося завтра біля річки о шостій вечора", "ukrainian")):
        check(morse.decode(morse.encode(text)[0])[1] == lang, f"автоопределение языка: {lang}")
    events, total_ms = morse.timeline(morse.encode("PARIS", "latin")[0], morse.DEFAULTS)
    check(abs(events[-1][0] + events[-1][1] - morse.LEAD_MS - 43 * 80) < 1e-6, "длительность PARIS на 15 WPM")
    wav = io.BytesIO()
    morse.render_wav(events, total_ms, morse.DEFAULTS, wav)
    check(len(wav.getvalue()) > 10000, "звук Морзе")

    # бланк: листы по 112 групп, номера, копирование из Word без пробелов
    form = os.path.join(os.path.dirname(HERE), "assets", "form_blank.png")
    long_cipher = core.b32encode(core.encrypt("Проверка листов бланка. " * 30, core.key_bytes(7)))
    groups = forms.groups_of(long_cipher)
    pages = forms.paginate(groups)
    check(len(pages) > 1 and all(len(p) == forms.PER_PAGE for p in pages[:-1]), "деление на листы")
    check(forms.form_number(__import__("datetime").datetime(2026, 10, 4), 1) == "041026/001", "номер бланка")
    images = forms.render_png_pages(form, long_cipher, "ванька", "041026/001")
    check(len(images) == len(pages), "листы PNG")
    docx = io.BytesIO()
    forms.build_docx(form, long_cipher, "ванька", "041026/001", docx)
    names = zipfile.ZipFile(docx).namelist()
    xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    body = re.sub(r"<w:txbxContent>.*?</w:txbxContent>", "", xml, flags=re.S)
    check("".join(re.findall(r'<w:t xml:space="preserve">(.*?)</w:t>', body)) == "".join(groups),
          "Word: «Выделить всё» берёт только шифровку, без пробелов")
    check("Ключ: ванька" in xml and "041026/001" in xml, "Word: номер и ключ на бланке")
    check(not any("header" in n for n in names), "Word: без колонтитулов")

    # языки: все фразы окна переведены на украинский, польский и английский
    import ast
    import marsi18n as i18n
    src = open(os.path.join(os.path.dirname(HERE), "kod_marsa.py"), encoding="utf-8").read()
    used = {n.args[0].value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "T" and n.args
            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
    used |= set(morse.LANG_NAMES.values()) | {lbl for _, lbl, _, _ in morse.SEPARATORS}
    used |= {name for _, name in morse.ALPHABET_CHOICES} | set(i18n.ERRORS.values())
    missing = sorted(k for k in used if k not in i18n.TR)
    check(not missing, f"нет перевода: {missing[:3]}")

    def fields(text):
        return set(re.findall(r"{(\w+)}", text))

    check(all(len(v) == 3 and all(v) and all(fields(x) == fields(k.replace("_form", "")) for x in v)
              for k, v in i18n.TR.items()), "переводы: все языки и подстановки на месте")
    check(all(len(i18n.HELP_TR[c]) == len(i18n.HELP) for c in ("uk", "pl", "en")), "справка на всех языках")

    # SSTV: длительность и код VIS в заголовке передачи
    import marssstv as sstv
    for name in ("Robot 36", "Martin 1", "PD 120"):
        img, _ = sstv.qr_frame(core.qr_matrix(vectors[0][2]), name)
        samples = sstv.synthesize(img, name)
        check(abs(len(samples) / sstv.SAMPLE_RATE * 1000 - sstv.duration_ms(name)) < 5, f"SSTV {name}: длительность")
        bits = []
        for b in range(8):  # 7 бит кода и бит чётности, по 30 мс после 640 мс заголовка
            a = int((640 + 30 * b + 5) * sstv.SAMPLE_RATE / 1000)
            z = int((640 + 30 * b + 25) * sstv.SAMPLE_RATE / 1000)
            seg = samples[a:z]
            crossings = sum(1 for i in range(1, len(seg)) if (seg[i - 1] < 0) != (seg[i] < 0))
            bits.append(1 if crossings / 2 / ((z - a) / sstv.SAMPLE_RATE) < 1200 else 0)
        code = sum(bit << i for i, bit in enumerate(bits[:7]))
        check(code == sstv.MODES[name]["vis"] and bits[7] == sum(bits[:7]) % 2, f"SSTV {name}: код VIS")

    total = len(vectors)
    if errors:
        print("ОШИБКИ:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print(f"OK: 32 ключа, {len(phrases)} ключ-фразы, {total} шифровок телефона расшифрованы, "
          f"морзянка совпадает, QR и автоподбор ключа работают.")

    if "--export" in sys.argv:
        out = sys.argv[sys.argv.index("--export") + 1]
        with open(out, "w", encoding="utf-8") as f:
            for spec, plain_b64, _, _ in vectors:
                cipher = core.b32encode(core.encrypt(unb64(plain_b64), spec_key(spec)))
                f.write(f"{spec}\t{plain_b64}\t{cipher}\n")
        print("шифровки ПК записаны в", out)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # сообщение попадёт в сводку GitHub Actions
        print(f"::error::Проверка совместимости упала: {exc!r}")
        raise
