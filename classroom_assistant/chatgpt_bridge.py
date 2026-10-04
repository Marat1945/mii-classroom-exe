"""Безкоштовні лекції через ВЛАСНИЙ ChatGPT учителя: запит → відповідь → Word.

Програма НЕ звертається до ChatGPT сама і не зберігає паролів: підписка ChatGPT
не має програмного доступу. Учитель копіює готовий запит у свій ChatGPT,
а відповідь повертає в програму (вставленням або автоматично з буфера обміну).
Тут лише чиста логіка без Tkinter, щоб її можна було перевірити тестами.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from .engine import is_task_lesson, lesson_base_name

PROMPT_MARKER = "ЗАПИТ ПОМІЧНИКА УЧИТЕЛЯ"
NOTEBOOK_HEADING = "ПЛАН-КОНСПЕКТ УРОКУ ДЛЯ ЗАПИСУ В ЗОШИТ"
DEFAULT_CHATGPT_URL = "https://chatgpt.com/"
MIN_SECTIONS = 5
MIN_NOTEBOOK = 5
SHORT_LECTURE_WORDS = 900

SUBJECTS = {
    "іу": "Історія України",
    "ві": "Всесвітня історія",
    "го": "Громадянська освіта",
    "право": "Правознавство",
    "історія": "Історія",
}

CODE_RE = re.compile(r"КОД\s*УРОКУ\s*[:：\-–—]?\s*#?\s*([A-Z2-7]{6})(?![A-Z0-9])", re.I)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
BOLD_LINE_RE = re.compile(r"^(?:\*\*|__)(.+?)(?:\*\*|__)\s*:?\s*$")
LIST_RE = re.compile(r"^\s*(?:\d{1,3}\s*[.)]|[-–•*·▪●])\s+(.+)$")
HOMEWORK_RE = re.compile(r"^\s*(?:Д/з|Д\.з\.|ДЗ|Домашнє завдання)\s*[:：.\-–—]", re.I)
SKIP_HEADINGS = ("д/з", "домашн", "техніка безпеки", "безпека")
REVIEW_WORDS = ("узагальн", "оцінюван", "контрольн", "підсумков", "повторен")


def lesson_code(lesson) -> str:
    """Короткий незмінний код уроку, щоб відповідь не потрапила до чужого класу."""
    digest = hashlib.sha1(lesson.unique_key.encode("utf-8")).digest()
    return "#" + base64.b32encode(digest).decode("ascii")[:6]


def lesson_profile(stream: str) -> dict:
    """«11 ІУ профіль» → клас 11, Історія України, профільний рівень."""
    match = re.match(r"^\s*(\d{1,2})(?:\s*[-–]\s*[А-ЯІЇЄҐA-Z])?\s+(.+?)\s*$", stream or "", re.I)
    grade = int(match.group(1)) if match else None
    rest = (match.group(2) if match else stream or "").casefold()
    words = rest.replace("+", " ").split()
    subject = next((SUBJECTS[w] for w in words if w in SUBJECTS), stream)
    level = ("профільний" if "профіль" in rest else
             "стандартний" if "стандарт" in rest else "")
    return {"grade": grade, "subject": subject, "level": level}


def level_hint(profile: dict) -> str:
    grade = profile.get("grade") or 0
    subject = profile.get("subject", "")
    if grade and grade <= 6:
        text = (f"{grade} клас: пиши доступно й цікаво, короткими реченнями; кожне нове "
                "поняття пояснюй простими словами; наводь зрозумілі дітям приклади; "
                "не перевантажуй датами.")
    elif grade and grade <= 9:
        text = (f"{grade} клас: системно — передумови, перебіг, наслідки; основні дати, "
                "постаті й поняття з чіткими визначеннями.")
    elif profile.get("level") == "профільний":
        text = (f"{grade} клас, ПРОФІЛЬНИЙ рівень: суттєво глибше — широкий контекст, аналіз "
                "причин і наслідків, порівняння, різні погляди істориків без вигаданих "
                "цитат і прізвищ, точна робота з поняттями.")
    else:
        rank = " стандартний рівень" if profile.get("level") == "стандартний" else ""
        text = (f"{grade or 'старший'} клас{',' if rank else ''}{rank}: глибше пояснення причин "
                "і наслідків, роль особистостей, порівняння; помірна кількість дат.")
    if subject == "Громадянська освіта":
        text += (" Для громадянської освіти — права, обов'язки, інституції, повага, "
                 "комунікація й практичні життєві ситуації.")
    if subject == "Правознавство":
        text += (" Для правознавства — точні загальні положення чинного права України, "
                 "без юридичних порад і без номерів статей, у яких немає певності.")
    return text


TASKS_RULE = (
    "ЗАВДАННЯ ЗАМІСТЬ ЛЕКЦІЇ: у документі має бути розділ «Завдання для самостійного виконання» з НЕ БІЛЬШЕ ніж "
    "3 аналітичними завданнями, які учень виконує, шукаючи інформацію в інтернеті (для кожного: чітке "
    "формулювання; що саме шукати й які пошукові запити спробувати; очікуваний результат — наприклад, таблиця, "
    "порівняння чи висновок на 5–7 речень; критерії оцінювання). Не вигадуй цитат, адрес сайтів, назв джерел чи "
    "прізвищ дослідників. Наприкінці розділу — блок «Як здати»: виконати письмово в зошиті й прикріпити фото або "
    "скан, АБО виконати зручним способом (Word, презентація, схема, відео) і прикріпити до завдання в "
    "Google Classroom. Теорія — лише коротке повторення (до 1 сторінки)."
)


def infographic_lines(lesson, task: bool) -> list:
    """Вимоги до інфографіки: красива, інформативна, оригінальна для кожного уроку й без помилок."""
    subject = lesson.subject if hasattr(lesson, "subject") else ""
    lines = [
        "ВИМОГИ ДО ІНФОГРАФІКИ (вона ОРИГІНАЛЬНА для цього уроку, а не шаблон):",
        "• Формат: горизонтальне зображення 1536×1024 (3:2), PNG, світле «паперове» тло.",
        "• Стиль — яскравий, але спокійний навчальний плакат для школярів. Якщо до цього чату прикріплено файл-зразок, "
        "переймай ЛИШЕ стиль (композицію кольорових карток із заокругленими кутами, нумеровані кружечки, плоскі іконки, "
        "великі заголовки); зміст і малюнок мають бути ІНШІ, під цю тему.",
        "• Угорі ліворуч — плашка «предмет, клас»; поруч — велика назва теми у 2–3 рядки (жирний шрифт із засічками "
        "на кольоровому мазку). Решта — картки різних відтінків, кожна з коротким заголовком, 2–4 пунктами й простою іконкою.",
    ]
    if task:
        lines.append(
            "• Структура практичної чи контрольної роботи: картки «Мета роботи», «Що повторити» (параграфи), «Обсяг "
            "роботи» (кількість завдань), 3 пронумеровані картки-завдання (суть кожного коротко), «Важливо!» (правила "
            "виконання), «Що прикріпити в Classroom?» (фото роботи із зошита або файл; не забути натиснути «Здати»).")
    else:
        lines.append(
            "• 5–7 карток: «Ключові дати» (проста хронологічна лінія), «Постаті» (ім'я + одне речення), «Поняття» "
            "(2–4 терміни з визначенням), «Причини → наслідки» (зі стрілками), «Головна думка» (висновок), за потреби "
            "«Карта» чи «Схема». Для громадянської освіти й права замість дат — «Права й обов'язки», «Інституції», "
            "«Приклад із життя».")
    lines += [
        "• Одна змістовна ілюстрація за темою (оригінальний історичний малюнок, карта, документ чи портрет — не копія "
        "відомої картини чи фото) на вільному місці: вона допомагає зрозуміти тему, а не лише прикрашає.",
        "• Шрифт великий і чіткий (основний текст не менший за ~28 px на ширині 1536), високий контраст, жодного "
        "дрібного тексту; нічого не обрізається й не накладається.",
        "• ТОЧНІСТЬ — найважливіше: вичитай КОЖНЕ слово українською (орфографія, відмінки, апострофи, жодних латинських "
        "літер замість українських); звір усі дати, імена, назви й цифри з текстом лекції; не вигадуй фактів, цитат і "
        "підписів; якщо не впевнений — не включай. Текст на картинці має збігатися з лекцією.",
        "• Вона доповнює документ, а не переказує його: лише найважливіше, зрозуміле учневі з першого погляду.",
    ]
    return lines


def kind_hint(topic: str) -> str:
    low = (topic or "").casefold()
    if "практичн" in low:
        return ("Це ПРАКТИЧНЕ ЗАНЯТТЯ. " + TASKS_RULE)
    if "оцінюван" in low or "контрольн" in low:
        return ("Це УРОК ОЦІНЮВАННЯ (урок контролю). " + TASKS_RULE +
                " Не складай готових відповідей на контрольну роботу.")
    if is_task_lesson(topic):
        kind = ("ЛАБОРАТОРНА РОБОТА" if "лабораторн" in low else
                "НАВЧАЛЬНИЙ ПРОЄКТ" if ("проєкт" in low or "проект" in low) else "ПРАКТИЧНА/КОНТРОЛЬНА РОБОТА")
        return f"Це {kind} (учні здають відповідь). " + TASKS_RULE
    if "узагальн" in low or "повторен" in low or "підсумков" in low:
        return ("Це УРОК УЗАГАЛЬНЕННЯ: систематизуй ключові події, дати, поняття й постаті, "
                "покажи зв'язки між ними, додай запитання для самоперевірки.")
    return ""


def _is_review(topic: str) -> bool:
    low = (topic or "").casefold()
    return any(word in low for word in REVIEW_WORDS)


def preceding_topics(lesson, plan_lessons, limit=12) -> list[str]:
    """Теми розділу перед уроком узагальнення/оцінювання — точно з КТП.

    Без них ChatGPT не знає, що саме узагальнювати, і почне вгадувати.
    """
    ordered = sorted((x for x in plan_lessons or [] if isinstance(x, dict)),
                     key=lambda x: x.get("index", 0))
    topics = []
    for item in reversed([x for x in ordered if x.get("index", 0) < lesson.lesson_number]):
        topic = str(item.get("topic", "")).strip()
        if _is_review(topic):
            if topics:
                break                     # попередній розділ уже закінчився
            continue                      # «Урок узагальнення» перед оцінюванням
        if topic and (not topics or topics[-1] != topic):   # подвійний урок — одна тема
            topics.append(topic)
        if len(topics) >= limit:
            break
    return topics[::-1]


def build_prompt(lesson, plan_lessons=None, mode="file", label=None) -> str:
    """Повний самодостатній запит. mode="file" — готовий Word + одна інфографіка (основний);
    mode="text" — запасний: відповідь текстом певного формату."""
    profile = lesson_profile(lesson.stream)
    code = lesson_code(lesson)
    date_text = f"{lesson.day[8:10]}.{lesson.day[5:7]}.{lesson.day[:4]}"
    short_date = f"{lesson.day[8:10]}.{lesson.day[5:7]}"
    grade = profile["grade"]
    grade_line = (f"{grade}" + (f", {profile['level']} рівень" if profile["level"] else "")
                  if grade else lesson.stream)
    homework = (lesson.homework or "").strip()
    topic = lesson.topic.strip()
    file_mode = mode != "text"
    shown = label or lesson.stream                           # «8-Б-В-Г ГО», якщо урок спільний за один день
    intro = ("Ти — досвідчений учитель і методист. Створи ГОТОВИЙ ФАЙЛ Word (.docx) з лекцією "
             "українською мовою, яку учень прочитає самостійно під час дистанційного навчання, і "
             "ОДНУ картинку-інфографіку до неї. Результат — файли для завантаження, а не текст у чаті."
             if file_mode else
             "Ти — досвідчений учитель і методист. Підготуй повноцінний навчальний матеріал "
             "українською мовою, який учень прочитає самостійно під час дистанційного навчання.")
    lines = [
        f"{PROMPT_MARKER} — лекція для дистанційного уроку",
        f"КОД УРОКУ: {code}",
        "",
        intro,
        "",
        "ДАНІ УРОКУ (з календарно-тематичного плану; не змінюй їх):",
        f"• Предмет: {profile['subject']}",
        f"• Клас: {grade_line} (потік «{lesson.stream}»)",
        f"• Дата: {date_text}, урок №{lesson.lesson_number} за КТП",
        f"• Тема: {topic}",
    ]
    if shown != lesson.stream:
        lines.append(f"• Цей урок у той самий день проводиться для класів «{shown}»: один документ для всіх.")
    if homework:
        lines.append(f"• Д/з за КТП (лише для орієнтації; у відповідь не переписуй): {homework}")
    earlier = preceding_topics(lesson, plan_lessons) if _is_review(lesson.topic) else []
    if earlier:
        lines.append("• Теми попередніх уроків, які охоплює цей урок (з КТП):")
        lines += [f"  – {item}" for item in earlier]
    lines += [
        "",
        "ВИМОГИ ДО ЗМІСТУ:",
        "1. Пиши лише про цю тему. Спирайся на загальновідомі перевірені факти: дати, постаті, "
        "поняття, причини, перебіг, наслідки; де доречно — зв'язок України і світу.",
        "2. Не вигадуй підручників, сторінок, параграфів, цитат, прізвищ дослідників чи джерел. "
        "Якщо не впевнений у деталі — не наводь її.",
        "3. Викладай збалансовано, без політизації та емоційних оцінок; визначення — точні.",
        "4. Рівень: " + level_hint(profile),
    ]
    number = 5
    hint = kind_hint(lesson.topic)
    if hint:
        lines.append(f"{number}. Тип уроку: {hint}")
        number += 1
    lines += [
        (f"{number}. Обсяг: 8–12 змістовних тематичних розділів; у кожному 2–4 повні абзаци (не списки). "
         "Наприкінці — «Основні поняття», «Підсумок уроку» і план-конспект для зошита "
         "(9–13 повних змістовних пунктів, обсяг 1–2 сторінки)." if not is_task_lesson(topic) else
         f"{number}. Обсяг: коротке повторення теорії (2–4 розділи по 1–2 абзаци, разом до 1 сторінки), "
         "розділ «Завдання для самостійного виконання» (до 3 завдань), «Основні поняття», «Підсумок уроку» і "
         "план-конспект для зошита (3–5 коротких пунктів)."),
        f"{number+1}. НЕ пиши привітання, домашнє завдання (воно є лише в повідомленні Classroom: документ має "
        "годитися й для інших цілей), текст про тривогу чи Zoom. Розділ «Техніка безпеки» додасть програма.",
        "",
    ]
    if not file_mode:
        lines += [
            "ФОРМАТ ВІДПОВІДІ — суворо такий, без вступу і без коментарів після плану:",
            f"КОД УРОКУ: {code}",
            "## Назва першого розділу",
            "Перший абзац.",
            "",
            "Другий абзац.",
            "## Назва другого розділу",
            "…",
            f"## {NOTEBOOK_HEADING}",
            "1. Перший пункт.",
            "2. Другий пункт.",
        ]
        return "\n".join(lines)
    word_name = lesson_base_name(lesson, label=shown) + ".docx"
    lines += [
        "ЩО ПОТРІБНО ВІДДАТИ — РІВНО ДВА ФАЙЛИ (текст у чаті — не результат):",
        f"1) Готовий файл Word (.docx) з ТОЧНИМ іменем «{word_name}» (ім'я починається з класу та дати — "
        "НЕ змінюй його). Створи справжній документ "
        "і дай посилання для завантаження.",
        f"2) ОДНА картинка-інфографіка до цієї теми — один файл PNG з іменем "
        f"«{infographic_name(lesson, shown)}.png» (те саме ім'я, що й у Word). Рівно ОДНЕ зображення: не колаж із "
        "кількох файлів і не серія.",
        *infographic_lines(lesson, is_task_lesson(topic)),
        f"У чаті напиши лише одне речення: «Готово. КОД УРОКУ: {code}» і дай посилання на обидва "
        "файли. Лекцію в чат не переписуй.",
        "",
        "ПРАВИЛА ВИКОНАННЯ (без зайвих кроків):",
        "• НЕ став мені жодних уточнювальних запитань і не чекай підтвердження — виконуй одразу.",
        "• НЕ показуй план, чернетку тексту чи проміжні результати в чаті.",
        "• Текст лекції має бути СПРАВЖНІМ ТЕКСТОМ у файлі Word (абзаци, заголовки, таблиці Word) — "
        "НЕ картинкою, НЕ знімком сторінки, НЕ зображенням тексту. Створи .docx програмно "
        "(python-docx) і дай файл для завантаження.",
        "• Видай рівно два файли: спочатку Word, потім ОДИН PNG, а далі одне речення з посиланнями.",
        "",
        "ОФОРМЛЕННЯ DOCX (суворо, як у моєму зразку):",
        "• Аркуш Letter (21,59 × 27,94 см), книжкова. Поля: ліве 2,0 см; праве, верхнє й нижнє "
        "1,7 см; колонтитули 1,27 см від краю.",
        "• Основний шрифт Times New Roman, чорний, 14 pt, по ширині; відступ першого рядка абзацу "
        "1,0 см; інтервал 1,08; після абзацу 6 pt. Ключові поняття й імена виділяй жирним помірно.",
        f"• ПЕРШИЙ абзац документа: «{shown}, Урок {short_date} — {topic.rstrip('.')}.» — жирний, 14 pt, "
        "ліворуч, без відступу, світло-блакитний фон #EAF2F8. У документі НЕ пиши слів «Код уроку».",
        "• Далі назва теми: стиль Title, 19 pt, жирний, #1F4E79, ліворуч; 6 pt перед і 12 pt після; "
        "тему відтворюй ТОЧНО.",
        "• Розділи «1. Назва», «2. Назва» …: Heading 1, 16 pt, жирний, #1F4E79, ліворуч; "
        "14 pt перед і 7 pt після; не відривати заголовок від першого абзацу.",
        "• 3–4 короткі інформаційні блоки (таблиця 1×1 без видимих меж, поля ≈0,15 см, 13,5 pt): "
        "жовтий #FFF2CC — головний акцент, блакитний #D9EAF7 — важлива теза, зелений #EAF4E4 — "
        "висновок. 1–2 порівняльні таблиці за потреби: 13 pt, шапка #D9EAF7 жирна, рядки "
        "чергуються біле / #F7F9FC, тонкі сірі межі; рядок таблиці не розривати між сторінками.",
        "• Передостанні розділи: «Основні поняття» (кожне — «Термін — визначення», термін жирним) і "
        "«Підсумок уроку» (1–2 абзаци).",
        f"• Останній розділ: «N. {NOTEBOOK_HEADING}» (Heading 1, 16 pt, жирний, #385723, заливка "
        "#EAF4E4, нижня лінія #70AD47). Одразу під ним зелений блок #EAF4E4 (1×1): «У зошит потрібно "
        "записати лише цей розділ. Повністю переписувати лекцію не потрібно.» Далі 9–13 нумерованих "
        "пунктів (14 pt, по ширині, без відступу, 5 pt після; назву пункту жирним) і наприкінці "
        "абзац «Головний висновок: …».",
        f"• Верхній колонтитул на всіх сторінках: «{profile['subject'].upper()} • "
        f"{grade or ''} КЛАС • {short_date}» (10 pt, сірий #646464, праворуч). Нижній колонтитул: "
        "тема (10 pt, сірий, по центру).",
        "• Без декоративних картинок у документі, емодзі, зайвих порожніх рядків і рамок. НЕ додавай "
        "розділ «Домашнє завдання / Д/з» (воно лише в повідомленні Classroom) і розділ «Техніка безпеки» — "
        "його додасть програма.",
        "• Перед видачею переглянь усі сторінки: текст не обрізається й не накладається, "
        "заголовки не залишаються самі внизу сторінки.",
    ]
    if is_task_lesson(topic):
        lines += [
            "",
            "ДЛЯ ЦЬОГО УРОКУ (практичне заняття / контроль): перед розділом «ПЛАН-КОНСПЕКТ…» додай розділ "
            "«Завдання для самостійного виконання» (до 3 завдань з пошуком в інтернеті) та блок «Як здати» "
            "(у зошит із фото АБО зручним способом із прикріпленням до завдання в Classroom). У розділі "
            "«ПЛАН-КОНСПЕКТ…» — 3–5 коротких пунктів: що саме записати в зошит за результатами завдань. "
            "Блок «Як здати» оформ зеленим блоком #EAF4E4.",
        ]
    return "\n".join(lines)


def infographic_name(lesson, label=None) -> str:
    """Ім'я картинки = ім'я Word (інше розширення): так обидва файли розпізнаються як один урок."""
    return lesson_base_name(lesson, label=label)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яіїєґ]+", " ", (text or "").casefold()).strip()


def match_score(lesson, filename: str, text: str = "") -> int:
    """Наскільки файл (за назвою та, за можливості, текстом) схожий на цей урок."""
    from .file_match import find_lesson, parse_file
    first = next((line for line in str(text).splitlines() if line.strip()), "")
    if find_lesson([lesson], parse_file(filename, first)) is not None:
        return 10                                          # клас + дата збігаються точно
    score = 0
    name = _norm(Path(filename).stem)
    number = re.search(r"урок\s*(\d+)", name)
    if number and int(number.group(1)) == int(lesson.lesson_number):
        score += 2
    date_text = f"{lesson.day[8:10]} {lesson.day[5:7]} {lesson.day[:4]}"
    if date_text in name:
        score += 2
    topic = _norm(lesson.topic)
    head = topic[:32]
    if head and head in name:
        score += 3
    elif head and head in _norm(text[:4000]):
        score += 2
    return score


def best_lesson_for_file(lessons, filename: str, text: str = ""):
    from .file_match import find_lesson, parse_file
    first = next((line for line in str(text).splitlines() if line.strip()), "")
    exact = find_lesson(list(lessons), parse_file(filename, first))
    if exact is not None:
        return exact
    ranked = sorted(((match_score(x, filename, text), i) for i, x in enumerate(lessons)),
                    reverse=True)
    if not ranked or ranked[0][0] < 3:
        return None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return lessons[ranked[0][1]]


def _clean_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((?:https?://)[^)]+\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"^\s*>\s?", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _heading_text(line: str):
    match = HEADING_RE.match(line)
    if not match:
        bold = BOLD_LINE_RE.match(line)
        # Окремий жирний рядок — заголовок, але не виділене жирним речення.
        if not bold or len(bold.group(1)) > 120 or bold.group(1).rstrip().endswith("."):
            return None
        match = bold
    text = _clean_inline(match.group(1)).strip(" :")
    for _ in range(2):                    # «1. 🏛️ Назва», «🏛️ 1. Назва», «Розділ 2. Назва»
        text = re.sub(r"^[^\w«\"(]+", "", text)
        text = re.sub(r"^(?:розділ\s+)?\d{1,2}\s*[.):]\s*", "", text, flags=re.I)
    return text.strip() or None


def _is_notebook(heading: str) -> bool:
    low = heading.casefold().replace("‑", "-")
    return "план-конспект" in low or "план конспект" in low or ("план" in low and "зошит" in low)


def _from_json(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or "sections" not in data or "notebook" not in data:
        return None
    sections = []
    for item in data.get("sections") or []:
        if not isinstance(item, dict):
            continue
        heading = _clean_inline(str(item.get("heading", ""))) or "Розділ"
        paragraphs = [_clean_inline(str(x)) for x in item.get("paragraphs") or [] if str(x).strip()]
        sections.append({"heading": heading, "paragraphs": paragraphs})
    notebook = [_clean_inline(str(x)) for x in data.get("notebook") or [] if str(x).strip()]
    return sections, notebook


def _from_markdown(text: str):
    sections, notebook = [], []
    current, buffer = None, []
    mode = "preface"          # preface | section | notebook | skip

    def flush():
        if buffer and current is not None:
            current["paragraphs"].append(" ".join(buffer))
        buffer.clear()

    for raw in text.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```") or re.fullmatch(r"[-*_]{3,}", stripped or "x"):
            continue
        if CODE_RE.search(_clean_inline(stripped)) and len(stripped) < 70:
            continue
        if mode == "notebook":
            item = LIST_RE.match(line)
            if item:
                value = _clean_inline(item.group(1))
                if raw[:1] in (" ", "\t") and notebook and not re.match(r"^\s*\d", raw):
                    notebook[-1] = notebook[-1].rstrip(" .;") + "; " + value
                elif value:
                    notebook.append(value)
                continue
        heading = _heading_text(stripped)
        if heading:
            flush()
            if _is_notebook(heading):
                mode, current = "notebook", None
            elif heading.casefold().startswith(SKIP_HEADINGS):
                mode, current = "skip", None
            else:
                mode = "section"
                current = {"heading": heading, "paragraphs": []}
                sections.append(current)
            continue
        if not stripped:
            flush()
            continue
        if mode in ("preface", "skip", "notebook") or HOMEWORK_RE.match(_clean_inline(stripped)):
            continue
        item = LIST_RE.match(line)
        if item:
            flush()
            current["paragraphs"].append("• " + _clean_inline(item.group(1)))
        else:
            buffer.append(_clean_inline(stripped))
    flush()
    return sections, notebook


def parse_answer(text: str, expected_code: str | None = None) -> dict:
    """Розбирає відповідь ChatGPT. Повертає material для documents.create_word."""
    result = {"material": None, "code": None, "code_ok": None,
              "errors": [], "warnings": [], "words": 0}
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        result["errors"].append("Відповідь порожня: вставте сюди текст із ChatGPT.")
        return result
    if PROMPT_MARKER in raw and "ФОРМАТ ВІДПОВІДІ" in raw:
        result["errors"].append("Це сам запит, а не відповідь. Надішліть його в ChatGPT, "
                                "а сюди поверніть відповідь ChatGPT.")
        return result
    found = CODE_RE.search(_clean_inline(raw.replace("\n", " ")))
    if found:
        result["code"] = "#" + found.group(1).upper()
    if expected_code:
        if result["code"] is None:
            result["warnings"].append("У відповіді немає коду уроку — переконайтеся, що це "
                                      "відповідь саме на запит для цього уроку.")
        elif result["code"] != expected_code.upper():
            result["code_ok"] = False
            result["errors"].append(f"Код у відповіді {result['code']} не збігається з цим уроком "
                                    f"{expected_code}: це відповідь для іншого уроку.")
        else:
            result["code_ok"] = True
    parsed = _from_json(raw) or _from_markdown(raw)
    sections, notebook = parsed
    empty = [s["heading"] for s in sections if not s["paragraphs"]]
    sections = [s for s in sections if s["paragraphs"]]
    if empty:
        result["warnings"].append("Розділи без тексту пропущено: " + ", ".join(empty[:4]))
    if len(sections) < MIN_SECTIONS:
        result["errors"].append(f"Розпізнано розділів із текстом: {len(sections)} (потрібно щонайменше "
                                f"{MIN_SECTIONS}). Попросіть ChatGPT: «Оформи відповідь суворо у "
                                "форматі із заголовками ##».")
    if len(notebook) < MIN_NOTEBOOK:
        result["errors"].append(f"У плані-конспекті пунктів: {len(notebook)} (потрібно щонайменше "
                                f"{MIN_NOTEBOOK}) або не знайдено заголовок «{NOTEBOOK_HEADING}».")
    words = sum(len(p.split()) for s in sections for p in s["paragraphs"])
    words += sum(len(x.split()) for x in notebook)
    result["words"] = words
    if sections and words < SHORT_LECTURE_WORDS:
        result["warnings"].append(f"Лекція коротка (≈{words} слів). Можна попросити ChatGPT "
                                  "розширити розділи.")
    result["material"] = {"sections": sections, "notebook": notebook}
    return result


def looks_like_answer(text: str, code: str) -> bool:
    """Чи можна підхопити текст із буфера: лише відповідь саме на цей запит."""
    if not text or not code or PROMPT_MARKER in text:
        return False
    found = CODE_RE.search(_clean_inline(text[:4000].replace("\n", " ")))
    return bool(found) and "#" + found.group(1).upper() == code.upper()


def safe_chatgpt_url(value: str) -> str:
    value = (value or "").strip()
    return value if re.match(r"^https://[^\s]+$", value) else DEFAULT_CHATGPT_URL
