"""Тільки читання попередніх публікацій Google Classroom.

Немає жодних методів редагування/публікації. Безпечна нормалізація
посилань і вкладень для внутрішнього перегляду вікна Windows.
"""
from __future__ import annotations
from datetime import datetime
from urllib.parse import urlsplit
import re

STATUSES={"PUBLISHED":"Опубліковано","DRAFT":"Чернетка",
          "SCHEDULED":"Заплановано","DELETED":"Видалено"}


def fetch_paged_items(client,course_id,field,state_key,max_per_kind=1000):
    """Явно вибираємо й опубліковані, й чернетки, інакше API повертає
    лише PUBLISHED. Не допускати прихованого обрізання довгих курсів."""
    records=[]
    token=None
    truncated=False
    while len(records)<max_per_kind:
        kwargs={"courseId":str(course_id),"pageSize":min(100,max_per_kind-len(records)),
                state_key:["PUBLISHED","DRAFT"]}
        if token:kwargs["pageToken"]=token
        reply=client.list(**kwargs).execute()
        current=reply.get(field,[])
        records.extend(current)
        token=reply.get("nextPageToken")
        if not token:break
    if token:truncated=True
    return records,truncated


def _google_time(value):
    if not value:return ""
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError,TypeError):return str(value)[:19]


def safe_url(value):
    """Дозволені лише звичайні HTTPS-адреси з API."""
    candidate=str(value or "").strip()
    try:
        parts=urlsplit(candidate)
        return candidate if parts.scheme=="https" and parts.netloc and not parts.username else ""
    except ValueError:return ""


def normalize_attachment(item):
    if "driveFile" in item:
        part=item.get("driveFile",{}).get("driveFile",{}) or {}
        fileid=str(part.get("id",""))
        link=part.get("alternateLink") or part.get("webViewLink") or ""
        if not link and re.fullmatch(r"[A-Za-z0-9_-]{10,200}",fileid):
            link=f"https://drive.google.com/file/d/{fileid}/view"
        return {"kind":"Google Drive","title":part.get("title") or part.get("name") or "Документ у Google Drive",
                "url":safe_url(link),
                "thumbnail_url":safe_url(part.get("thumbnailUrl"))}
    if "youtubeVideo" in item:
        video=item.get("youtubeVideo",{}) or {}
        videoid=str(video.get("id",""))
        link=video.get("alternateLink") or ""
        if not link and re.fullmatch(r"[A-Za-z0-9_-]{11}",videoid):
            link=f"https://www.youtube.com/watch?v={videoid}"
        return {"kind":"YouTube","title":video.get("title","Відео YouTube"),
                "url":safe_url(link),
                "thumbnail_url":safe_url(video.get("thumbnailUrl"))}
    if "link" in item:
        link=item.get("link",{}) or {}
        return {"kind":"Посилання","title":link.get("title") or link.get("url") or "Посилання",
                 "url":safe_url(link.get("url")),
                "thumbnail_url":safe_url(link.get("thumbnailUrl"))}
    if "form" in item:
        form=item.get("form",{}) or {}
        return {"kind":"Google Форми","title":form.get("title","Форма"),
                "url":safe_url(form.get("formUrl"))}
    for key,label in (("gem","Gemini"),("notebook","NotebookLM")):
        if key in item:
            entry=item.get(key,{}) or {}
            return {"kind":label,"title":entry.get("title",label),
                    "url":safe_url(entry.get("url"))}
    return {"kind":"Інший файл","title":"Вкладення","url":""}


def normalize_item(item,kind,course_id):
    """Жодного витоку інформації про учнів — тільки самі матеріали."""
    attachments=[normalize_attachment(a) for a in item.get("materials",[])]
    rawtext=item.get("text") if kind=="Оголошення" else item.get("description")
    title=item.get("title") or (
        rawtext[:85].replace("\n"," ") if rawtext else "Оголошення")
    return {
        "id":str(item.get("id","")),
        "course_id":str(item.get("courseId") or course_id),
        "type":kind,
        "title":str(title),
        "description":str(rawtext or ""),
        "state":str(item.get("state","")),
        "state_ua":STATUSES.get(item.get("state"),str(item.get("state",""))),
        "updated":str(item.get("updateTime") or item.get("creationTime") or ""),
        "date":_google_time(item.get("creationTime")),
        "attachments":attachments,
        "url":safe_url(item.get("alternateLink")),
    }


def compatible_classroom_title(lesson,record):
    """Лише точний збіг дати й теми, а не здогад за схожим предметом."""
    if record.get("course_id") is None:return False
    short=f"{lesson.day[8:10]}.{lesson.day[5:7]}"
    title=record.get("title","").casefold().replace("—","-")
    topic=lesson.topic.casefold().replace("—","-").strip()
    return bool(topic and f"урок {short}" in title and topic in title)
