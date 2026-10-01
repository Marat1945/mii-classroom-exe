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
HEADER_TOPIC = ("тема", "зміст уроку", "зміст навчального", "зміст (тема)", "навчальний матеріал")
HEADER_HW = ("д/з", "дз", "домашн", "примітк")
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
    homework = locate(HEADER_HW, len(lower)-1)
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
    rows=[]
    for table in document.tables:
        for row in table.rows:
            rows.append([tidy(cell.text) for cell in row.cells])
    if not rows:
        raise ValueError("У DOCX не знайдено таблиць. Скопіюйте теми вручну або збережіть план у таблиці Word.")
    return rows


def csv_rows(path: str | Path) -> list[list[str]]:
    text=Path(path).read_text(encoding="utf-8-sig")
    try: dialect=csv.Sniffer().sniff(text[:2048],delimiters=";,\t")
    except csv.Error: dialect=csv.excel
    return [[tidy(c) for c in row] for row in csv.reader(io.StringIO(text),dialect)]


def extract_lessons(rows: list[list[str]], topic_col: int, hw_col: int,
                    number_col: int|None=0, require_number: bool=True)->list[dict]:
    """Не домислює тем/ДЗ: тільки текст вибраних користувачем колонок.

    Рядки розділів та заголовків відкидаються, якщо число уроку відсутнє.
    """
    if topic_col < 0 or hw_col < 0:
        raise ValueError("Номери стовпців повинні бути додатними")
    result=[]
    seen=set()
    for row in rows:
        cell=lambda col: row[col] if col is not None and col<len(row) else ""
        topic=tidy(cell(topic_col)); hw=tidy(cell(hw_col))
        if not topic or topic.casefold() in ("тема","тема уроку","зміст навчального матеріалу"):
            continue
        numbertext=tidy(cell(number_col)) if number_col is not None else ""
        matched=NUMBER.fullmatch(numbertext)
        if require_number and not matched:
            continue
        if matched:
            index=int(matched.group(1))
            # Same index sometimes repeated across multiple tables; duplicates should be inspected.
            if index in seen: continue
            seen.add(index)
        else:
            index=len(result)+1
        if len(topic)>4000:
            # Mis-chosen results or explanatory outcome column; always leave review possible
            topic=topic[:4000]
        result.append({"index":index,"topic":topic,"homework":hw})
    return result


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


def persist(config: dict, plans: dict, state: dict, label="редагування")->Path:
    errors=validate_working(config,plans)
    if errors:
        raise ValueError("Не можна зберегти:\n"+" \n".join(errors[:25]))
    previous,old_plans=deep_copy_data()
    backup=safe_backup(previous,old_plans,state,label)
    atomic_json_write("Налаштування.json",config)
    atomic_json_write("Календарні плани.json",plans)
    return backup
