"""Офіційний Google Classroom + Drive API; ТІЛЬКИ чернетки, публікація вимкнена."""
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

def list_teacher_courses():
    classroom,_=services()
    page=None
    found=[]
    while True:
        answer=classroom.courses().list(teacherId="me",pageSize=100,pageToken=page).execute()
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
            "kind":"ASSIGNMENT" if assignment else "MATERIAL","state":"DRAFT"}


def list_classroom_posts(course_id, include_announcements=False, max_per_kind=1000):
    """Одержує вже наявні матеріали, завдання й (за окремим дозволом) оголошення.
    Тільки GET; жодних змін, видалень чи публікацій. Включає чернетки вчителя.
    """
    from .classroom_archive import normalize_item, fetch_paged_items
    classroom,_drive=services(with_announcements=include_announcements)
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
