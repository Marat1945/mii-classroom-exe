"""Планування безпечної групової підготовки чернеток для одного дня.
Жодних викликів Google, доки користувач не підтвердить список.
"""
from __future__ import annotations
from pathlib import Path

ASYNC_NOTE=(
    "Асинхронно — без виходу у Zoom у зв’язку з довготривалою "
    "повітряною тривогою і загрозою для життя і здоров’я"
)


def draft_title(lesson):
    return f"Урок {lesson.day[8:10]}.{lesson.day[5:7]} — {lesson.topic}. ({ASYNC_NOTE})"


def plan_day_drafts(rows, state, description_for):
    """Повертає (готові, пропущені). Word не обов'язковий:
    достатньо тексту або файлів. Не додає неготові Word-заготовки.
    """
    ready=[]
    skipped=[]
    seen=set()
    course_ids=state.get("course_ids",{})
    drafts=state.get("drafts",{})
    files=state.get("files",{})
    for lesson in rows:
        key=lesson.unique_key
        reason=None
        if key in seen:
            reason="повторний рядок цього уроку"
        elif lesson.status!="готово":
            reason="немає перевіреного КТП"
        elif key in drafts:
            reason="чернетку вже створено"
        elif not course_ids.get(lesson.course_title):
            reason="Google-курс не зіставлено"
        else:
            from .attachments import files_for_lesson
            attachments=files_for_lesson(state,key)
            if len(attachments)!=len(state.get("attachments",{}).get(key,[])):
                reason="деякі вкладення відсутні на диску"
            elif len(attachments)>19:
                reason="забагато вкладень"
            else:
                doc=files.get(key,{})
                word_path=(str(doc["path"]) if
                    doc.get("validated") and doc.get("complete")
                    and Path(doc.get("path","")).is_file() else None)
                content=(description_for(lesson) or "").strip()
                if not content and not word_path and not attachments:
                    reason="немає тексту й прикріплених файлів"
                else:
                    ready.append({
                        "key":key,"lesson":lesson,
                        "course_id":str(course_ids[lesson.course_title]),
                        "title":draft_title(lesson),
                        "description":content,
                        "docx_path":word_path,
                        "attachments":attachments,
                    })
        if reason:
            skipped.append((lesson,reason))
        seen.add(key)
    return ready,skipped
