"""Локальні редаговані навчальні дані, імпорт КТП і архівування. Без Google/AI викликів."""
from __future__ import annotations
import csv
import copy
import io
import json
import re
import shutil
import tempfile
import subprocess
import base64
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .engine import ROOT, DATA, read_json, check_configuration

NUMBER = re.compile(r"^\s*(\d{1,4})[\.\)]?\s*$")
# Подвійний урок однією темою: «46-47», «16 -17», «16–17.».
NUMBER_RANGE = re.compile(r"^\s*(\d{1,4})\s*[-–—]\s*(\d{1,4})[\.\)]?\s*$")
HEADER_TOPIC = ("тема", "зміст уроку", "зміст навчального", "зміст (тема)", "навчальний матеріал")
HEADER_HW = ("д/з", "дз", "домашн", "примітк")
# Справжня графа Д/з має перевагу над «Примітками» (КТП 10 ГО має обидві).
HEADER_HW_PRIMARY = ("д/з", "домашн", "дз")
HEADER_HW_FALLBACK = ("примітк",)
HEADER_ROW_TOPICS = ("тема", "тема уроку", "зміст навчального матеріалу",
                     "зміст уроку", "зміст (тема)", "навчальний матеріал")
HEADER_NUMBER = ("№", "номер")
TERM = re.compile(r"\s+")


def tidy(value: Any) -> str:
    return TERM.sub(" ", str(value or "").replace("\u00a0", " ")).strip()


def deep_copy_data():
    return (copy.deepcopy(read_json("Налаштування.json")),
            copy.deepcopy(read_json("Календарні плани.json")))


def guess_columns(headers: list[str]) -> tuple[int, int, int]:
    lower = [tidy(h).casefold() for h in headers]
    def locate(terms, default):
        return next((i for i, s in enumerate(lower) if any(w in s for w in terms)), default)
    topic = locate(HEADER_TOPIC, 1 if len(lower)>2 else 0)
    homework = locate(HEADER_HW_PRIMARY, None)
    if homework is None:
        homework = locate(HEADER_HW_FALLBACK, len(lower)-1)
    number = locate(HEADER_NUMBER, 0)
    if topic == homework and len(lower)>1:
        homework=len(lower)-1
    return topic, homework, number


def docx_table_rows(path: str | Path) -> list[list[str]]:
    """Формат DOCX; повертає всі рядки таблиць (об'єднані комірки залишаються в рядках).

    Старі DOC і скани автоматично не інтерпретуємо: краще чесно повідомити користувачу.
    """
    path=Path(path)
    if path.suffix.lower()==".doc":
        if os.name != "nt":
            raise ValueError("Для імпорту DOC потрібен Windows із встановленим Microsoft Word. Або відкрийте файл у Word і збережіть як DOCX.")
        with tempfile.TemporaryDirectory(prefix="KTP_IMPORT_") as folder:
            target=Path(folder)/"converted.docx"
            def psquote(string):
                return str(string).replace("'","''")
            script=(f"$src='{psquote(path.resolve())}'; $dst='{psquote(target)}'; "
                    "$app=New-Object -ComObject Word.Application; $app.Visible=$false; "
                    "$app.DisplayAlerts=0; $app.AutomationSecurity=3; "
                    "try { $doc=$app.Documents.Open($src,$false,$true); "
                    "try { $doc.SaveAs2($dst,16) } finally { $doc.Close($false) } } "
                    "finally { $app.Quit() }")
            encoded=base64.b64encode(script.encode("utf-16le")).decode("ascii")
            result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
                         "-EncodedCommand",encoded],capture_output=True,text=True,timeout=70)
            if result.returncode!=0 or not target.is_file():
                raise ValueError("Не вдалося перетворити DOC через Microsoft Word. "
                                 "Відкрийте файл самостійно і виберіть «Зберегти як» → DOCX.")
            return docx_table_rows(target)
    if path.suffix.lower() != ".docx":
        raise ValueError("Підтримуються DOCX, DOC (за наявності Microsoft Word) та CSV.")
    from docx import Document
    document=Document(path)
    auto=_word_auto_numbers(document)
    rows=[]
    for table in document.tables:
        for row in table.rows:
            values=[]
            for cell in row.cells:
                text=tidy(cell.text)
                if not text and auto:
                    # Графа «№» з автоматичною нумерацією Word: python-docx
                    # не бачить цих чисел, хоча вчитель бачить їх у документі.
                    text=next((str(auto[p._p]) for p in cell.paragraphs
                               if p._p in auto),"")
                values.append(text)
            rows.append(values)
    if not rows:
        raise ValueError("У DOCX не знайдено таблиць. Скопіюйте теми вручну або збережіть план у таблиці Word.")
    return rows


def _word_auto_numbers(document) -> dict:
    """Числа автоматичних нумерованих списків Word (лише десятковий формат).

    Повертає словник «абзац → номер», як його показує Word: лічильник на кожен
    список (numId) і рівень, початок зі start / startOverride.
    """
    try:
        from docx.oxml.ns import qn
        numbering=document.part.numbering_part.element
    except Exception:
        return {}
    level_info={}
    for abstract in numbering.findall(qn("w:abstractNum")):
        aid=abstract.get(qn("w:abstractNumId"))
        for level in abstract.findall(qn("w:lvl")):
            start=level.find(qn("w:start"))
            fmt=level.find(qn("w:numFmt"))
            level_info[(aid,level.get(qn("w:ilvl")))]=(
                int(start.get(qn("w:val"))) if start is not None else 1,
                fmt.get(qn("w:val")) if fmt is not None else "decimal")
    abstract_of={}
    overrides={}
    for num in numbering.findall(qn("w:num")):
        nid=num.get(qn("w:numId"))
        ref=num.find(qn("w:abstractNumId"))
        abstract_of[nid]=ref.get(qn("w:val")) if ref is not None else None
        for override in num.findall(qn("w:lvlOverride")):
            start=override.find(qn("w:startOverride"))
            if start is not None:
                overrides[(nid,override.get(qn("w:ilvl")))]=int(start.get(qn("w:val")))
    counters={}
    found={}
    for paragraph in document.element.body.iter(qn("w:p")):
        props=paragraph.find(qn("w:pPr"))
        numbering_props=props.find(qn("w:numPr")) if props is not None else None
        if numbering_props is None:
            continue
        nid_el=numbering_props.find(qn("w:numId"))
        lvl_el=numbering_props.find(qn("w:ilvl"))
        nid=nid_el.get(qn("w:val")) if nid_el is not None else None
        ilvl=lvl_el.get(qn("w:val")) if lvl_el is not None else "0"
        if not nid or nid=="0":
            continue
        start,fmt=level_info.get((abstract_of.get(nid),ilvl),(1,"decimal"))
        key=(nid,ilvl)
        counters[key]=counters[key]+1 if key in counters else overrides.get(key,start)
        for other in [k for k in counters if k[0]==nid and int(k[1])>int(ilvl)]:
            del counters[other]
        if fmt=="decimal":
            found[paragraph]=counters[key]
    return found


def csv_rows(path: str | Path) -> list[list[str]]:
    text=Path(path).read_text(encoding="utf-8-sig")
    # Excel в українській локалі зберігає CSV з «;». Обираємо роздільник, що дає найбільше
    # однакових колонок у більшості рядків (назва з комами в першому рядку не збиває).
    best=(1,0,None)
    for delimiter in (";","\t",","):
        widths={}
        rows=[r for r in csv.reader(io.StringIO(text),delimiter=delimiter) if r]
        for row in rows:widths[len(row)]=widths.get(len(row),0)+1
        if not widths:continue
        width,count=max(widths.items(),key=lambda kv:(kv[1],kv[0]))
        if width>1 and count>=max(2,len(rows)//3) and (width,count)>best[:2]:
            best=(width,count,delimiter)
    if best[2]:dialect=csv.excel;delimiter=best[2]
    else:
        try:
            dialect=csv.Sniffer().sniff(text[:2048],delimiters=";,\t");delimiter=dialect.delimiter
        except csv.Error:dialect=csv.excel;delimiter=","
    return [[tidy(c) for c in row] for row in csv.reader(io.StringIO(text),delimiter=delimiter)]


def extract_lessons(rows: list[list[str]], topic_col: int, hw_col: int,
                    number_col: int|None=0, require_number: bool=True)->list[dict]:
    """Не домислює тем/ДЗ: тільки текст вибраних користувачем колонок.

    Рядки розділів та заголовків відкидаються, якщо число уроку відсутнє.
    Подвійний урок «46-47» і повтор номера з іншою темою НЕ губляться:
    кожен рядок-урок стає окремим записом, а номер у файлі зберігається
    в source_number для перевірки. Порядковий index — суцільний 1, 2, 3…
    """
    if topic_col < 0 or hw_col < 0:
        raise ValueError("Номери стовпців повинні бути додатними")
    result=[]
    seen=set()
    for position,row in enumerate(rows,1):
        cell=lambda col: row[col] if col is not None and col<len(row) else ""
        topic=tidy(cell(topic_col)); hw=tidy(cell(hw_col))
        if not topic or topic.casefold() in HEADER_ROW_TOPICS:
            continue
        if NUMBER.fullmatch(topic):
            # Рядок нумерації граф під шапкою: «1. | 2. | 3. | 4.».
            continue
        numbertext=tidy(cell(number_col)) if number_col is not None else ""
        numbered=NUMBER.fullmatch(numbertext) or NUMBER_RANGE.fullmatch(numbertext)
        if require_number and not numbered:
            continue
        if numbered:
            # Таблиця, повторена у файлі двічі: однаковий номер І однакова тема.
            twin=(numbertext.replace(" ",""),topic.casefold())
            if twin in seen: continue
            seen.add(twin)
        if len(topic)>4000:
            # Mis-chosen results or explanatory outcome column; always leave review possible
            topic=topic[:4000]
        result.append({"index":len(result)+1,"topic":topic,"homework":hw,
                       "source_row":position,
                       "source_number":numbertext if numbered else ""})
    return result


def import_notes(lessons: list[dict]) -> list[str]:
    """Що варто перевірити в попередньому перегляді імпорту."""
    notes=[]
    doubles=[x["source_number"] for x in lessons
             if NUMBER_RANGE.fullmatch(x.get("source_number") or "")]
    if doubles:
        notes.append("подвійні уроки однією темою: "+", ".join(doubles)
                     +" (кожен — один запис; за потреби додайте копію)")
    numbers=[NUMBER.fullmatch(x.get("source_number") or "") for x in lessons]
    values=[int(m.group(1)) for m in numbers if m]
    repeated=sorted({v for v in values if values.count(v)>1})
    if repeated:
        notes.append("номер повторюється з іншою темою: "
                     +", ".join(map(str,repeated))+" (імпортовано всі рядки)")
    return notes



# Дата джерела КТП має пріоритет у візуальному відображенні. Це НЕ змінює
# розклад, тижневу парність або фактично призначений урок у Google.
DATE_PATTERN=re.compile(
    r"(?<!\d)(?P<day>0?[1-9]|[12]\d|3[01])[./](?P<month>0?[1-9]|1[012])"
    r"(?:[./](?P<year>(?:20)?\d{2}))?[.]?(?!\d)"
)
CLASS_DATE_PATTERN=re.compile(
    r"(?<!\d)(?P<klass>(?:[5-9]|10|11)\s*[-–]\s*[А-ЯІЇЄҐA-Z])"
    r"\s*[:\-–]?\s*(?P<day>0?[1-9]|[12]\d|3[01])[./]"
    # 1[012] перед 0?[1-9] і (?!\d): інакше «04.12.» читалося як 04.01 (жовтень–грудень → січень).
    r"(?P<month>1[012]|0?[1-9])(?!\d)(?:[./](?P<year>(?:20)?\d{2}))?",
    re.IGNORECASE
)


def source_date_iso(day,month,year=None,academic_start=2026):
    """01.09 → 2026-09-01; 01.02 → 2027-02-01."""
    mon=int(month)
    if year:
        yr=int(year)
        if yr<100:yr+=2000
    else:yr=academic_start+int(mon<=7)
    try:return date(yr,mon,int(day)).isoformat()
    except ValueError:return None


def parse_source_dates(value,academic_start=2026):
    """Підтримує «8-Б 04.09. / 8-В 04.09. / 8-Г 03.09.» і «07.09.»."""
    text=str(value or "")
    matches=list(CLASS_DATE_PATTERN.finditer(text))
    found={}
    for match in matches:
        g=match.groupdict()
        klass=re.sub(r"\s*[-–]\s*","-",g["klass"].upper())
        day=source_date_iso(g["day"],g["month"],g["year"],academic_start)
        if day:found[klass]=day
    if found:return found
    # Unlabelled date only when not a multi-grade text fragment.
    candidate=DATE_PATTERN.search(text)
    if candidate:
        g=candidate.groupdict()
        day=source_date_iso(g["day"],g["month"],g["year"],academic_start)
        if day:return {"*":day}
    return {}


def import_source_dates(rows,lessons,topic_col,number_col,academic_start=2026):
    """Збагачує ІСНУЮЧІ записи даними з DOCX. Клас/дата — тільки з документа."""
    if not lessons:return lessons
    headers=next((row for row in rows[:12]
                  if any("тема" in tidy(cell).casefold() or "зміст" in tidy(cell).casefold()
                         for cell in row)),rows[0] if rows else [])
    date_columns=[i for i,x in enumerate(headers) if "дата" in tidy(x).casefold()]
    def enrich(lesson,raw):
        columns=date_columns or [
            col for col in range(len(raw)) if col not in (topic_col,number_col)
            and any(ch.isdigit() for ch in raw[col])
        ]
        found={}
        for col in columns:
            if col>=len(raw):continue
            parsed=parse_source_dates(raw[col],academic_start)
            for key,value in parsed.items():found.setdefault(key,value)
        if found:lesson["source_dates"]=found
    pending=[]
    for lesson in lessons:
        # Новий імпорт пам'ятає свій рядок: дата не «з'їжджає» після
        # подвійного уроку чи повтору номера у файлі.
        position=lesson.get("source_row")
        if isinstance(position,int) and 1<=position<=len(rows):
            raw=rows[position-1]
            if (len(raw)>max(topic_col,number_col)
                    and tidy(raw[topic_col])[:4000]==tidy(lesson["topic"])):
                enrich(lesson,raw);continue
        pending.append(lesson)
    by_number={r["index"]:r for r in pending}
    for raw in rows:
        if not by_number:break
        if len(raw)<=max(topic_col,number_col):continue
        matched=NUMBER.fullmatch(tidy(raw[number_col]))
        if not matched:continue
        lesson=by_number.get(int(matched.group(1)))
        if not lesson or tidy(lesson["topic"])!=tidy(raw[topic_col]):continue
        enrich(lesson,raw)
    return lessons


def source_date_for_stream(lesson,stream):
    """«8-Б ІУ» → «8-Б»; без позначення класу * для всіх."""
    dates=lesson.get("source_dates") or {}
    klass=re.match(r"^(\d{1,2}\s*[-–]\s*[А-ЯІЇЄҐA-Z])",stream.strip(),re.IGNORECASE)
    if klass:
        key=re.sub(r"\s*[-–]\s*","-",klass.group(1).upper())
        if key in dates:return dates[key]
    return dates.get("*")

def validate_working(config: dict, plans: dict) -> list[str]:
    problems=[]
    try:
        start=date.fromisoformat(config["year_start"])
        end=date.fromisoformat(config["year_end"])
        anchor=date.fromisoformat(config["anchor_monday"])
        if end<start: problems.append("Кінець року раніше від початку")
        if anchor.weekday()!=0: problems.append("Опорний день чисельника/знаменника повинен бути понеділком")
    except (KeyError, ValueError): problems.append("Некоректні дати навчального року")
    if config.get("anchor_phase","чисельник") not in ("чисельник","знаменник"):
        problems.append("Парність опорного тижня повинна бути чисельник/знаменник")
    if config.get("semester2_override",False):
        try:
            second=date.fromisoformat(config["semester2_start"])
            second_anchor=date.fromisoformat(config["semester2_anchor_monday"])
            if not start<=second<=end:
                problems.append("Початок другого семестру за межами навчального року")
            if second.weekday()!=0 or second_anchor.weekday()!=0:
                problems.append("Другий семестр і його опорний тиждень мають починатися з понеділка")
            if second_anchor!=second:
                problems.append("Опорний понеділок другого семестру має збігатися з його початком")
            if config.get("semester2_anchor_phase") not in ("чисельник","знаменник"):
                problems.append("Оберіть чисельник або знаменник для другого семестру")
        except (KeyError, ValueError):
            problems.append("Перевірте дати другого семестру")
    if not 1<=len(config.get("period_times",[]))<=12:
        problems.append("Потрібно задати час для 1–12 уроків")
    else:
        for ix,pair in enumerate(config["period_times"],1):
            if len(pair)!=2 or not all(re.fullmatch(r"\d{2}:\d{2}",t) for t in pair):
                problems.append(f"Помилка часу уроку №{ix}")
    for idx,interval in enumerate(config.get("holidays",[]),1):
        try:
            if date.fromisoformat(interval["end"])<date.fromisoformat(interval["start"]):
                problems.append(f"Канікули {idx}: кінець раніше початку")
        except (KeyError,ValueError): problems.append(f"Канікули {idx}: невірний формат")
    try:problems.extend(check_configuration(config,plans))
    except Exception as exc: problems.append(str(exc))
    return problems


def safe_backup(config: dict, plans: dict, state: dict | None, label: str="редагування")->Path:
    """Архів лише навчальних даних. НІКОЛИ не архівує токени, OAuth secret або API-ключ."""
    tag=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder=ROOT/"Архів навчальних даних"/(config.get("year_start","невідомий рік")[:4])/tag
    folder.mkdir(parents=True,exist_ok=False)
    (folder/"Налаштування.json").write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"Календарні плани.json").write_text(json.dumps(plans,ensure_ascii=False,indent=2),encoding="utf-8")
    if state is not None:
        # No credential fields stored here.
        (folder/"Стан.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"ПРИЧИНА.txt").write_text(label,encoding="utf-8")
    return folder


def atomic_json_write(filename: str, data: dict):
    DATA.mkdir(parents=True,exist_ok=True)
    target=DATA/filename
    fd,tmp=tempfile.mkstemp(suffix=".json",prefix="tmp_",dir=DATA)
    try:
        import os
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        Path(tmp).replace(target)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()


_LESSON_KEY=re.compile(r"^(\d{4}-\d{2}-\d{2}\|\d+\|)(.+)$")


def migrate_stream_keys(state: dict, renames: dict) -> int:
    """Перейменований потік: переносить Word, вкладення, чернетки й тексти на нову назву.

    Ключ уроку — «РРРР-ММ-ДД|урок|потік», тож без цього після перейменування все збережене «загубилося» б.
    """
    moved=0
    for value in list(state.values()):
        if not isinstance(value,dict):continue
        for key in list(value):
            found=_LESSON_KEY.match(key) if isinstance(key,str) else None
            if found and found.group(2) in renames:
                new=found.group(1)+renames[found.group(2)]
                if new not in value:
                    value[new]=value.pop(key);moved+=1
    return moved


def persist(config: dict, plans: dict, state: dict, label="редагування")->Path:
    # Клас без КТП — не помилка: вчитель може завантажити КТП пізніше.
    errors=[e for e in validate_working(config,plans) if not e.startswith("Порожній КТП")]
    if errors:
        raise ValueError("Не можна зберегти:\n"+" \n".join(errors[:25]))
    previous,old_plans=deep_copy_data()
    backup=safe_backup(previous,old_plans,state,label)
    atomic_json_write("Налаштування.json",config)
    atomic_json_write("Календарні плани.json",plans)
    return backup
