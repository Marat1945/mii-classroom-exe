"""Офіційний Google Classroom + Drive API; ТІЛЬКИ чернетки, публікація вимкнена."""
from pathlib import Path
from .engine import DATA

SCOPES=[
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/drive.file",
]

def authenticate():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise RuntimeError("Google пакети не встановлено. Виконайте pip install -r requirements.txt") from e
    import json
    p=DATA/"google_token.json"
    creds=None
    if p.exists():
        creds=Credentials.from_authorized_user_file(str(p),SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        secret=DATA/"google_credentials.json"
        if not secret.exists():
            raise FileNotFoundError(
                "Не знайдено data/google_credentials.json. "
                "Створіть OAuth Client ID типу Desktop у Google Cloud, "
                "увімкніть Classroom API та Drive API, завантажте JSON і помістіть його в data/ під цією назвою.")
        flow=InstalledAppFlow.from_client_secrets_file(str(secret),SCOPES)
        creds=flow.run_local_server(port=0)
    p.write_text(creds.to_json(),encoding="utf-8")
    return creds

def services():
    from googleapiclient.discovery import build
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

def create_draft(course_id, title, description, docx_path, assignment=False, attachments=None):
    """Усі файли в Google Drive, потім ОДНА чернетка Classroom. Публікації тут немає."""
    from googleapiclient.http import MediaFileUpload
    import mimetypes
    classroom,drive=services()
    attachments=list(attachments or [])
    paths=[Path(docx_path)]+[Path(p) for p in attachments]
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
    if assignment:
        payload={"title":title,"description":description[:30000],
                 "workType":"ASSIGNMENT","state":"DRAFT","materials":materials}
        result=classroom.courses().courseWork().create(courseId=str(course_id),body=payload).execute()
    else:
        payload={"title":title,"description":description[:30000],
                 "state":"DRAFT","materials":materials}
        result=classroom.courses().courseWorkMaterials().create(courseId=str(course_id),body=payload).execute()
    return {"id":result["id"],"drive_id":uploaded_ids[0],"attachment_drive_ids":uploaded_ids[1:],
            "course_id":course_id,
            "kind":"ASSIGNMENT" if assignment else "MATERIAL","state":"DRAFT"}
