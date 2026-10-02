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


def kind_hint(topic: str) -> str:
    low = (topic or "").casefold()
    if "практичн" in low:
        return ("Це ПРАКТИЧНЕ ЗАНЯТТЯ: коротко нагадай потрібну теорію, а більшість розділів "
                "присвяти завданням для самостійної роботи (аналіз ситуації, порівняння, "
                "робота з поняттями) з чіткими інструкціями. Не вигадуй цитат із джерел.")
    if "оцінюван" in low or "контрольн" in low:
        return ("Це УРОК ОЦІНЮВАННЯ: підготуй стислий повторювальний матеріал і запитання "
                "для самоперевірки; не складай готових відповідей на контрольну роботу.")
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


def build_prompt(lesson, plan_lessons=None) -> str:
    """Повний самодостатній запит: працює в будь-якому новому чаті ChatGPT."""
    profile = lesson_profile(lesson.stream)
    code = lesson_code(lesson)
    date_text = f"{lesson.day[8:10]}.{lesson.day[5:7]}.{lesson.day[:4]}"
    grade = profile["grade"]
    grade_line = (f"{grade}" + (f", {profile['level']} рівень" if profile["level"] else "")
                  if grade else lesson.stream)
    homework = (lesson.homework or "").strip()
    lines = [
        f"{PROMPT_MARKER} — лекція для дистанційного уроку",
        f"КОД УРОКУ: {code}",
        "",
        "Ти — досвідчений учитель і методист. Підготуй повноцінний навчальний матеріал "
        "українською мовою, який учень прочитає самостійно під час дистанційного навчання.",
        "",
        "ДАНІ УРОКУ (з календарно-тематичного плану; не змінюй їх):",
        f"• Предмет: {profile['subject']}",
        f"• Клас: {grade_line} (потік «{lesson.stream}»)",
        f"• Дата: {date_text}, урок №{lesson.lesson_number} за КТП",
        f"• Тема: {lesson.topic.strip()}",
    ]
    if homework:
        lines.append(f"• Д/з за КТП (лише для орієнтації; у відповідь не переписуй): {homework}")
    earlier = preceding_topics(lesson, plan_lessons) if _is_review(lesson.topic) else []
    if earlier:
        lines.append("• Теми попередніх уроків, які охоплює цей урок (з КТП):")
        lines += [f"  – {topic}" for topic in earlier]
    lines += [
        "",
        "ВИМОГИ:",
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
        f"{number}. Обсяг: 8–12 змістовних розділів; у кожному 2–4 повні абзаци (не списки).",
        f"{number+1}. Наприкінці — план-конспект для зошита: 9–13 повних змістовних пунктів "
        "(обсяг 1–2 сторінки).",
        f"{number+2}. НЕ пиши привітання, домашнє завдання, техніку безпеки, текст про тривогу "
        "чи Zoom — це додасть програма.",
        "",
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
