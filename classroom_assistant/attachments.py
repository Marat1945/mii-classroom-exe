"""Локальні прикріплення до конкретного уроку; нічого не надсилає автоматично."""
from __future__ import annotations
import hashlib
import os
import re
import shutil
from pathlib import Path
from .engine import ROOT

ATTACHMENT_ROOT=ROOT / "Вкладення Classroom"
BANNED_EXT={".pem",".p12",".pfx",".key",".env",".json"}
BANNED_NAMES={"credentials.json","google_credentials.json","google_token.json","token.json"}
MAX_ATTACHMENTS=19  # One slot reserved for the main Word; Classroom accepts a bounded list.

def safe_attachment_name(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",str(text)).strip(" .")[:130] or "файл"

def normalize_attachment(source):
    path=Path(source).expanduser()
    if path.suffix.casefold() in BANNED_EXT or path.name.casefold() in BANNED_NAMES:
        raise ValueError("Файл налаштувань або секретів не можна прикріплювати до Classroom.")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if path.stat().st_size > 200*1024*1024:
        raise ValueError("Файл більший за 200 МБ. Додайте його до Google Drive вручну.")
    return path

def add_attachments(state,lesson_key,paths):
    """Скопіювати в окрему локальну папку; перевірені вкладення залишаються незмінними."""
    current=state.setdefault("attachments",{}).setdefault(lesson_key,[])
    incoming=[normalize_attachment(p) for p in paths]
    if len(current)+len(incoming)>MAX_ATTACHMENTS:
        raise ValueError(f"Не більше {MAX_ATTACHMENTS} додаткових вкладень до одного Word.")
    folder=ATTACHMENT_ROOT/hashlib.sha256(lesson_key.encode("utf8")).hexdigest()[:20]
    folder.mkdir(parents=True,exist_ok=True)
    appended=[]
    for original in incoming:
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        if any(i.get("sha256")==digest for i in current):
            continue
        target=folder/(digest[:10]+" "+safe_attachment_name(original.name))
        if original.resolve()!=target.resolve():
            shutil.copy2(original,target)
        entry={"path":str(target),"name":original.name,"sha256":digest}
        current.append(entry)
        appended.append(entry)
    return appended

def files_for_lesson(state,lesson_key):
    result=[]
    for entry in state.get("attachments",{}).get(lesson_key,[]):
        path=Path(entry.get("path",""))
        if path.is_file():
            result.append(str(path))
    return result

def copy_attachments(state,source_key,target_key):
    sources=files_for_lesson(state,source_key)
    if not sources:
        state.setdefault("attachments",{}).pop(target_key,None)
        return []
    state.setdefault("attachments",{}).pop(target_key,None)
    return add_attachments(state,target_key,sources)

def remove_attachment(state,lesson_key,index):
    """Відв'язує запис без видалення оригінальних файлів або Google Drive."""
    current=state.setdefault("attachments",{}).get(lesson_key,[])
    if index<0 or index>=len(current):
        return False
    current.pop(index)
    return True
