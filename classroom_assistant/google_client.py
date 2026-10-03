"""Офіційний Google Classroom + Drive API; ТІЛЬКИ чернетки, публікація вимкнена."""
import time
from pathlib import Path
from .engine import DATA

SCOPES=[
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/drive.file",
]


# Для історії оголошень потрібен ОКРЕМИЙ дозвіл Google.
# Він запитується тільки якщо вчитель явно натисне «Оголошення».
ANNOUNCEMENT_SCOPES=SCOPES+[
    "https://www.googleapis.com/auth/classroom.announcements.readonly"
]


def authenticate(scopes=None,token_name="google_token.json"):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise RuntimeError("Google пакети не встановлено. Виконайте pip install -r requirements.txt") from e
    import json
    scopes=list(scopes or SCOPES)
    p=DATA/token_name
    creds=None
    if p.exists():
        # Не позначати нові дозволи виданими, доки Google насправді їх не видав.
        try:
            token_info=json.loads(p.read_text(encoding="utf8"))
            granted=set(token_info.get("scopes",[]))
            if granted.issuperset(scopes):
                creds=Credentials.from_authorized_user_file(str(p),scopes)
        except (ValueError,OSError,TypeError):
            creds=None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        secret=DATA/"google_credentials.json"
        if not secret.exists():
            raise FileNotFoundError(
                "Не знайдено data/google_credentials.json. "
                "Створіть OAuth Client ID типу Desktop у Google Cloud, "
                "увімкніть Classroom API та Drive API, завантажте JSON і помістіть його в data/ під цією назвою.")
        flow=InstalledAppFlow.from_client_secrets_file(str(secret),scopes)
        creds=flow.run_local_server(port=0)
    p.write_text(creds.to_json(),encoding="utf-8")
    return creds

def services(with_announcements=False):
    from googleapiclient.discovery import build
    if with_announcements:
        creds=authenticate(ANNOUNCEMENT_SCOPES,
                           token_name="google_announcements_token.json")
    else:
        creds=authenticate()
    return build("classroom","v1",credentials=creds,cache_discovery=False),build("drive","v3",credentials=creds,cache_discovery=False)

def credentials_present():
    """Чи імпортовано файл ключа (OAuth Desktop JSON) вчителя."""
    return (DATA/"google_credentials.json").is_file()


def import_credentials_file(path):
    """Перевіряє й копіює завантажений із Google Cloud JSON. Помилки — зрозумілою мовою."""
    import json
    import shutil
    try:
        content=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError,ValueError) as ex:
        raise ValueError("Файл не вдалося прочитати як JSON. Оберіть файл, який завантажив Google.") from ex
    if isinstance(content,dict) and "web" in content and "installed" not in content:
        raise ValueError("Це ключ типу «Веб-застосунок». Потрібен тип «Комп'ютерний застосунок» "
                         "(Desktop app): створіть новий ключ за інструкцією, крок 5.")
    details=content.get("installed") if isinstance(content,dict) else None
    if not isinstance(details,dict) or not all(k in details for k in ("client_id","auth_uri","token_uri")):
        raise ValueError("Це не той файл. Потрібен JSON ключа типу «Комп'ютерний застосунок» (Desktop app).")
    DATA.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(path,DATA/"google_credentials.json")
    return DATA/"google_credentials.json"


def list_teacher_courses():
    classroom,_=services()
    page=None
    found=[]
    while True:
        # Лише активні курси: заархівовані минулих років не мають плутатися з поточними.
        answer=classroom.courses().list(teacherId="me",courseStates=["ACTIVE"],pageSize=100,
                                        pageToken=page).execute()
        found+=answer.get("courses",[])
        page=answer.get("nextPageToken")
        if not page:break
    return [{"id":c["id"],"name":c.get("name",""),"section":c.get("section",""),"courseState":c.get("courseState","")} for c in found]

def create_draft(course_id, title, description, docx_path=None, assignment=False, attachments=None):
    """Чернетка з текстом, Word або іншими вкладеннями. Word НЕ обов'язковий.
    Drive API викликаємо лише коли є файли; публікації тут немає.
    """
    from googleapiclient.http import MediaFileUpload
    import mimetypes
    classroom,drive=services()
    attachments=list(attachments or [])
    paths=([Path(docx_path)] if docx_path else [])+[Path(p) for p in attachments]
    if not paths and not str(description or "").strip():
        raise ValueError("Додайте текст або хоча б один файл, перш ніж створювати чернетку.")
    if len(paths)>20:
        raise ValueError("До однієї публікації Classroom можна додати не більше 20 файлів.")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(str(path))
    materials=[]
    uploaded_ids=[]
    for path in paths:
        guessed,_=mimetypes.guess_type(str(path))
        mimetype=guessed or "application/octet-stream"
        blob=MediaFileUpload(str(path),mimetype=mimetype,resumable=False)
        uploaded=drive.files().create(
            body={"name":path.name},media_body=blob,fields="id,webViewLink").execute()
        uploaded_ids.append(uploaded["id"])
        materials.append({"driveFile":{"driveFile":{"id":uploaded["id"]},"shareMode":"VIEW"}})
    payload={"title":title,"description":str(description or "")[:30000],
             "state":"DRAFT"}
    if materials:payload["materials"]=materials
    if assignment:
        payload["workType"]="ASSIGNMENT"
        result=classroom.courses().courseWork().create(
            courseId=str(course_id),body=payload).execute()
    else:
        result=classroom.courses().courseWorkMaterials().create(
            courseId=str(course_id),body=payload).execute()
    # Keep old drive_id field for compatibility: None when no files.
    return {"id":result["id"],"drive_id":uploaded_ids[0] if uploaded_ids else None,
            "attachment_drive_ids":uploaded_ids[1:] if docx_path else uploaded_ids,
            "course_id":course_id,
            "kind":"ASSIGNMENT" if assignment else "MATERIAL","state":"DRAFT","created_at":time.time()}


def token_ready():
    """Є збережений дозвіл Google: можна синхронізувати БЕЗ вікна входу."""
    path=DATA/"google_token.json"
    if not path.exists():return False
    try:
        import json
        info=json.loads(path.read_text(encoding="utf8"))
        granted=set(info.get("scopes",[]))
        return granted.issuperset(SCOPES) and bool(info.get("refresh_token") or info.get("token"))
    except (ValueError,OSError,TypeError):
        return False


def sync_everything(titles,known_ids,progress=None):
    """Курси в порядку Classroom + усі наявні матеріали/завдання (чернетки й опубліковані).

    Лише читання. Курси зіставляються за точною назвою; вручну зіставлені
    курси не змінюються. Помилка одного курсу не зупиняє решту.
    """
    say=progress or (lambda text:None)
    say("Синхронізація з Google Classroom: отримую курси…")
    courses=list_teacher_courses()
    valid={str(c["id"]) for c in courses}
    by_name={}
    for course in courses:
        by_name.setdefault(course["name"].strip().casefold(),[]).append(course)
    mapped={k:str(v) for k,v in known_ids.items() if str(v) in valid}
    from .course_match import match_titles
    # Розумне зіставлення: «10 ІУ» = 10 клас, Історія України; байдуже до регістру,
    # латинських двійників літер і «Право + ГО». Неоднозначне НЕ вгадується.
    for title,course in match_titles([t for t in titles if t not in mapped],courses).items():
        mapped[title]=str(course["id"])
    classroom,drive=services()
    entries={};errors=[];truncated={}
    unique=list(dict.fromkeys(mapped.values()))
    names={cid:t for t,cid in mapped.items()}
    for number,cid in enumerate(unique,1):
        say(f"Синхронізація з Classroom: {names.get(cid,cid)} ({number}/{len(unique)})…")
        try:
            posts=list_classroom_posts(cid,service=(classroom,drive))
            entries[cid]=posts["items"]
            if posts.get("truncated"):truncated[cid]=posts["truncated"]     # список неповний — не звіряти
        except Exception as ex:
            errors.append(f"{names.get(cid,cid)}: {ex}")
    return {"courses":courses,"mapped":mapped,"entries":entries,"errors":errors,"truncated":truncated,
            "unmapped":[t for t in titles if t not in mapped]}


def list_classroom_posts(course_id, include_announcements=False, max_per_kind=1000, service=None):
    """Одержує вже наявні матеріали, завдання й (за окремим дозволом) оголошення.
    Тільки GET; жодних змін, видалень чи публікацій. Включає чернетки вчителя.
    """
    from .classroom_archive import normalize_item, fetch_paged_items
    classroom,_drive=service or services(with_announcements=include_announcements)
    common=[
        ("Матеріал",classroom.courses().courseWorkMaterials(),
         "courseWorkMaterial","courseWorkMaterialStates"),
        ("Завдання",classroom.courses().courseWork(),
         "courseWork","courseWorkStates"),
    ]
    if include_announcements:
        common.append(("Оголошення",classroom.courses().announcements(),
                       "announcements","announcementStates"))
    items=[]
    truncated=[]
    for kind,client,field,state_key in common:
        records,cropped=fetch_paged_items(
            client,course_id,field,state_key,max_per_kind=max_per_kind)
        items.extend(normalize_item(item,kind,course_id) for item in records)
        if cropped:
            truncated.append(kind)
    items.sort(key=lambda x:x["updated"],reverse=True)
    return {"items":items,"truncated":truncated,"course_id":str(course_id)}
