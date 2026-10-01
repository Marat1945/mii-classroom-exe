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

def create_draft(course_id, title, description, docx_path, assignment=False):
    """Deliberately no 'publish' method. Upload DOCX to Drive then create Classroom DRAFT."""
    from googleapiclient.http import MediaFileUpload
    classroom,drive=services()
    path=Path(docx_path)
    if not path.is_file():raise FileNotFoundError(str(path))
    blob=MediaFileUpload(str(path),mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",resumable=False)
    uploaded=drive.files().create(body={"name":path.name},media_body=blob,fields="id,webViewLink").execute()
    shared={"driveFile":{"driveFile":{"id":uploaded["id"]},"shareMode":"VIEW"}}
    if assignment:
        payload={"title":title,"description":description[:30000],
                 "workType":"ASSIGNMENT","state":"DRAFT","materials":[shared]}
        result=classroom.courses().courseWork().create(courseId=str(course_id),body=payload).execute()
    else:
        payload={"title":title,"description":description[:30000],
                 "state":"DRAFT","materials":[shared]}
        result=classroom.courses().courseWorkMaterials().create(courseId=str(course_id),body=payload).execute()
    return {"id":result["id"],"drive_id":uploaded["id"],"course_id":course_id,
            "kind":"ASSIGNMENT" if assignment else "MATERIAL","state":"DRAFT"}
