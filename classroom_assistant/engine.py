"""Розклад, незмінна парність тижнів і послідовні календарні плани."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import re

# Використовувати окрему робочу папку у Windows: PyInstaller --onefile
# розпаковує вбудовані ресурси у тимчасовий каталог лише для читання.
import os
import sys
import shutil

def ensure_default_data(data_dir):
    """Створює порожні розклад і КТП, лише якщо їх ще немає (існуючі дані не чіпає)."""
    from .blank_data import blank_config
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = data_dir / "Налаштування.json"
    if not settings.exists():
        settings.write_text(json.dumps(blank_config(), ensure_ascii=False, indent=2), encoding="utf-8")
    plans = data_dir / "Календарні плани.json"
    if not plans.exists():
        plans.write_text("{}", encoding="utf-8")


if getattr(sys, "frozen", False):
    ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PomichnykUchyteliaClassroom"
    DATA = ROOT / "data"
    DATA.mkdir(parents=True, exist_ok=True)
    # Користувацькі налаштування та OAuth-токени НІКОЛИ не перезаписуються.
    # Нова установка = ПОРОЖНЯ програма: розклад і КТП вчитель завантажує сам.
    ensure_default_data(DATA)
else:
    ROOT = Path(__file__).resolve().parent.parent
    DATA = ROOT / "data"

def read_json(name):
    with (DATA / name).open("r",encoding="utf-8") as f:
        return json.load(f)

def write_json(name, data):
    p=DATA/name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def iso_day(s):
    return date.fromisoformat(s)

def week_phase(day: date, config=None):
    config = read_json("Налаштування.json") if config is None else config
    anchor = iso_day(config["anchor_monday"])
    anchor_phase=config.get("anchor_phase","чисельник")
    # Другий семестр: лише ЯВНО дозволений виняток. Без прапорця парність
    # безперервна, зокрема протягом зимових канікул.
    if config.get("semester2_override", False):
        semester_start=iso_day(config["semester2_start"])
        if day >= semester_start:
            anchor=iso_day(config["semester2_anchor_monday"])
            anchor_phase=config["semester2_anchor_phase"]
    # Канікули не зупиняють парність у межах кожного правила.
    weeks=(day - timedelta(days=day.weekday())-anchor).days // 7
    return anchor_phase if weeks % 2 == 0 else ("знаменник" if anchor_phase=="чисельник" else "чисельник")

def is_holiday(day: date, config=None):
    config=read_json("Налаштування.json") if config is None else config
    return any(iso_day(i["start"]) <= day <= iso_day(i["end"]) for i in config["holidays"])

def slot_key(day, period, stream):
    return f"{day.isoformat()}|{period}|{stream}"

@dataclass(frozen=True)
class Lesson:
    day: str
    weekday: int
    period: int
    begin: str
    end: str
    stream: str
    course_title: str
    plan_id: str
    lesson_number: int
    topic: str
    homework: str
    source_file: str
    status: str = "готово"
    @property
    def unique_key(self):
        return f"{self.day}|{self.period}|{self.stream}"

def build_calendar(config=None, plans=None, until=None):
    config=read_json("Налаштування.json") if config is None else config
    plans=read_json("Календарні плани.json") if plans is None else plans
    start=iso_day(config["year_start"])
    end=iso_day(config["year_end"])
    if until:
        end=min(end,iso_day(until) if isinstance(until,str) else until)
    counts={}
    items=[]
    day=start
    while day<=end:
        if day.weekday()<5 and not is_holiday(day,config):
            phase=week_phase(day,config)
            for index, pair in enumerate(config["days"].get(str(day.weekday()),[]),1):
                stream=pair[0] if phase=="чисельник" else pair[1]
                if not stream:
                    continue
                meta=config["course_map"][stream]
                plan_id=meta["plan"]
                counts[stream]=counts.get(stream,0)+1
                row_index=counts[stream]-1
                plan=plans[plan_id]
                entries=plan["lessons"]
                if plan.get("needs_review",False):
                    topic="КТП попереднього року: потрібне підтвердження або імпорт нового плану"
                    hw=""
                    status="потрібен КТП нового року"
                elif row_index>=len(entries):
                    topic="Немає наступної теми у КТП — перевірте план"
                    hw=""
                    status="вичерпано КТП"
                else:
                    row=entries[row_index]
                    topic=row["topic"]
                    hw=row["homework"]
                    status="готово"
                begin,endtime=config["period_times"][index-1]
                items.append(Lesson(day.isoformat(),day.weekday(),index,begin,endtime,stream,meta["course_title"],plan_id,row_index+1,topic,hw,plans[plan_id]["filename"],status))
        day += timedelta(days=1)
    return items

def day_lessons(day: str, config=None, plans=None):
    return [i for i in build_calendar(config, plans, until=day) if i.day==day]

def check_configuration(config=None,plans=None):
    config=read_json("Налаштування.json") if config is None else config
    plans=read_json("Календарні плани.json") if plans is None else plans
    warnings=[]
    for day, periods in config["days"].items():
        if len(periods)!=len(config["period_times"]): warnings.append(f"День {day}: число уроків не збігається з налаштуванням дзвоників")
        for num, pair in enumerate(periods,1):
            for stream in pair:
                if stream and stream not in config["course_map"]:
                    warnings.append(f"Невідомий потік: {stream} (день {day}, урок {num})")
    for stream, info in config["course_map"].items():
        if info["plan"] not in plans:
            warnings.append(f"Відсутній КТП для {stream}: {info['plan']}")
    for plan_id,p in plans.items():
        if not p["lessons"]: warnings.append(f"Порожній КТП {plan_id}")
    return warnings

def html_classroom_text(lesson:Lesson, asynchronous=True, video=True):
    intro=(f"Урок {lesson.day[8:10]}.{lesson.day[5:7]} — {lesson.topic.strip()}\n")
    if asynchronous:
        intro += "(Асинхронно — без виходу у Zoom у зв’язку з довготривалою повітряною тривогою і загрозою для життя і здоров’я)\n"
    return (intro+
      "\nДоброго дня, шановні учні! 👋\n\n"
      f"Сьогодні опрацьовуємо тему: «{lesson.topic}».\n\n"
      + ("1. Перегляньте прикріплене відео до теми.\n" if video else "")
      + "2. Уважно опрацюйте прикріплений матеріал уроку.\n"
        "3. Наприкінці Word-документа знайдіть «ПЛАН-КОНСПЕКТ УРОКУ ДЛЯ ЗАПИСУ В ЗОШИТ».\n"
        "4. ✍️ Запишіть лише цей план-конспект; всю лекцію переписувати не потрібно.\n\n"
        "❗ Під час повітряної тривоги перебувайте в безпечному місці. "
        "Жовта тривога також означає небезпеку. До навчання повертайтеся лише тоді, коли це безпечно.\n\n"
        "Бережіть себе!\n\n"
        f"Д/з: {lesson.homework or 'Не зазначено в календарному плані — уточнити у вчителя.'}")

def lesson_base_name(lesson:Lesson,limit=120):
    """«Урок № 8, 02.10.2026 Тема» — назва, що говорить сама за себе."""
    date_text=f"{lesson.day[8:10]}.{lesson.day[5:7]}.{lesson.day[:4]}"
    head=f"Урок № {lesson.lesson_number}, {date_text} "
    topic=re.sub(r'[<>:"/\\|?*\u0000-\u001f]+',' ',lesson.topic)
    topic=re.sub(r'\s+',' ',topic).strip(' .')
    room=max(20,limit-len(head))
    if len(topic)>room:
        cut=topic[:room]
        topic=(cut.rsplit(' ',1)[0] if ' ' in cut[20:] else cut).rstrip(' .,;:—-')
    return (head+topic).strip(' .')

def safe_name(lesson:Lesson):
    return lesson_base_name(lesson)+".docx"

def word_path(lesson:Lesson):
    """Готові Word/<дата>/<потік>/Урок № …docx — потік у папці, щоб імена не збігалися."""
    stream=re.sub(r'[<>:"/\\|?*\u0000-\u001f]+',' ',lesson.stream)
    stream=re.sub(r'\s+',' ',stream).strip(' .') or "потік"
    return ROOT/"Готові Word"/lesson.day/stream/safe_name(lesson)

def read_state():
    path=DATA/"Стан.json"
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else {"drafts":{},"files":{},"course_ids":{}}
def save_state(state):
    write_json("Стан.json",state)
