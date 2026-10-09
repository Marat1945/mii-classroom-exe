"""Офіційний Google Classroom + Drive API; ТІЛЬКИ чернетки, публікація вимкнена.

Керування входом у Google (OAuth) зосереджено ТУТ, в одному місці:
  • файл клієнта OAuth (data/google_credentials.json — «паспорт програми») НЕ чіпається при виході чи повторному вході;
  • дозвіл КОНКРЕТНОГО користувача (токени data/google_token.json і data/google_announcements_token.json) скидається
    єдиною функцією clear_google_user_credentials(), від якої працюють і «Від'єднати», і «Увійти заново»;
  • invalid_grant («Token has been expired or revoked») розпізнається автоматично: токен скидається, стан стає
    «не підключено», користувачеві пропонується повторний вхід (GoogleReauthRequired), а не технічна помилка.
"""
import functools
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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


CLIENT_FILE="google_credentials.json"                 # OAuth Client JSON (Desktop app): «паспорт програми»
TOKEN_FILE="google_token.json"                        # дозвіл користувача (access + refresh token)
ANNOUNCEMENT_TOKEN_FILE="google_announcements_token.json"
USER_TOKEN_FILES=(TOKEN_FILE,ANNOUNCEMENT_TOKEN_FILE)
REVOKE_URL="https://oauth2.googleapis.com/revoke"
LOGIN_TIMEOUT=240                                     # секунд на вхід у браузері; далі вхід вважається скасованим

REAUTH_TEXT=("Попередній дозвіл Google більше не діє або був відкликаний. Це не означає, що втрачено ваш розклад чи "
             "дані програми. Увійдіть у Google ще раз, щоб відновити доступ до Classroom і Drive.")
NO_CLIENT_TEXT="Спочатку імпортуйте OAuth Client JSON типу Desktop app."


class GoogleAuthProblem(Exception):
    """Проблема входу в Google, яку можна пояснити людською мовою (без технічних кодів і токенів)."""
    default="Не вдалося виконати вхід у Google."

    def __init__(self,message=None):
        super().__init__(message or self.default)


class GoogleReauthRequired(GoogleAuthProblem):
    default="Потрібен повторний вхід у Google. "+REAUTH_TEXT


class GoogleNotConnected(GoogleAuthProblem):
    default="Google не підключено. Натисніть «Підключити Google»."


class GoogleClientMissing(GoogleAuthProblem):
    default=NO_CLIENT_TEXT


class GoogleLoginCancelled(GoogleAuthProblem):
    default="Вхід у Google скасовано або доступ не надано. Нічого не змінено."


# ---------- стан сеансу (спільний для всієї програми) ----------
_lock=threading.RLock()
_session={"verified":False,"failed":False,"offline":False,"busy":False}
_listeners=[]


def add_listener(callback):
    """callback(state) викликається при кожній зміні стану; може викликатись із фонового потоку."""
    if callback not in _listeners:_listeners.append(callback)


def remove_listener(callback):
    if callback in _listeners:_listeners.remove(callback)


def _notify():
    state=connection_state()
    for callback in list(_listeners):
        try:callback(state)
        except Exception:pass


def reset_session():
    with _lock:
        _session.update(verified=False,failed=False,offline=False,busy=False)


def mark_verified():
    """Google ПІДТВЕРДИВ вхід (успішний запит або оновлення токена)."""
    with _lock:
        changed=not _session["verified"] or _session["failed"] or _session["offline"]
        _session.update(verified=True,failed=False,offline=False)
    if changed:_notify()


def mark_offline():
    with _lock:
        changed=not _session["offline"]
        _session["offline"]=True
    if changed:_notify()


def set_busy(flag):
    with _lock:
        _session["busy"]=bool(flag)
    _notify()


def connection_state():
    """«connected» | «connecting» | «offline» | «disconnected» | «reauth» — ПРАВДИВИЙ стан, а не наявність файла.

    «connected» лише коли Google підтвердив дозвіл у цьому сеансі; щойно запущена програма з файлом токена показує
    «connecting», доки перша перевірка не завершиться; після invalid_grant — «reauth»."""
    with _lock:
        flags=dict(_session)
    if flags["busy"]:return "connecting"
    if flags["failed"]:return "reauth"
    if not token_ready():return "disconnected"
    if flags["verified"]:return "connected"
    if flags["offline"]:return "offline"
    return "connecting"


# ---------- безпека: у повідомленнях ніколи немає токенів і секретів ----------
_SECRET_PATTERNS=[
    (re.compile(r"ya29\.[A-Za-z0-9_\-\.]+"),"[токен]"),
    (re.compile(r"1//[A-Za-z0-9_\-]{10,}"),"[токен]"),
    (re.compile(r"GOCSPX-[A-Za-z0-9_\-]+"),"[секрет]"),
    (re.compile(r"(?i)(\"?(?:refresh_token|access_token|client_secret|id_token)\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,}]+)"),r"\1[приховано]"),
]


def redact(text):
    text=str(text)
    for pattern,replacement in _SECRET_PATTERNS:
        text=pattern.sub(replacement,text)
    return text


def is_auth_failure(error):
    """invalid_grant / відкликаний чи прострочений refresh token / еквівалентні відповіді Google."""
    if isinstance(error,GoogleAuthProblem):return False
    text=str(error).casefold()
    return ("invalid_grant" in text or "token has been expired or revoked" in text
            or "token has been revoked" in text)


def friendly_message(error):
    """Текст для вікна: зрозумілий і без секретів."""
    if isinstance(error,GoogleAuthProblem):return str(error)
    return redact(error)


def _user_token_paths():
    return [DATA/name for name in USER_TOKEN_FILES]


def clear_google_user_credentials():
    """ЄДИНЕ місце, де скидається дозвіл КОРИСТУВАЧА: токени з диска, стан сеансу. Файл клієнта OAuth, розклад,
    КТП, зіставлення, вкладення й налаштування НЕ чіпаються. Повертає імена видалених файлів."""
    removed=[]
    with _lock:
        for path in _user_token_paths():
            try:
                if path.exists():
                    path.unlink()
                    removed.append(path.name)
            except OSError:
                try:path.write_text("{}",encoding="utf-8")        # не вдалося видалити — принаймні знецінити вміст
                except OSError:pass
        _session.update(verified=False,failed=False,offline=False,busy=False)
    _notify()
    return removed


def _auth_failed(token_name=TOKEN_FILE):
    """Google сказав invalid_grant: знецінити саме цей токен, позначити стан і запропонувати повторний вхід."""
    with _lock:
        path=DATA/token_name
        try:
            if path.exists():path.unlink()
        except OSError:
            try:path.write_text("{}",encoding="utf-8")
            except OSError:pass
        if token_name==TOKEN_FILE:
            _session.update(verified=False,failed=True,offline=False,busy=False)
    _notify()
    raise GoogleReauthRequired()


def guarded(function):
    """Будь-яка помилка invalid_grant у запиті до Google перетворюється на GoogleReauthRequired (один раз, без повторів)."""
    @functools.wraps(function)
    def wrapper(*args,**kwargs):
        try:
            return function(*args,**kwargs)
        except GoogleAuthProblem:
            raise
        except Exception as error:
            if is_auth_failure(error):_auth_failed()
            raise
    return wrapper


def _write_token(path,creds):
    """Надійний запис: спершу тимчасовий файл, потім підміна (збій посеред запису не знищить робочий токен)."""
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(creds.to_json(),encoding="utf-8")
    os.replace(temp,path)


def _load_credentials(path,scopes):
    from google.oauth2.credentials import Credentials
    if not path.exists():return None
    try:
        info=json.loads(path.read_text(encoding="utf8"))
        # Не позначати нові дозволи виданими, доки Google насправді їх не видав.
        if set(info.get("scopes",[])).issuperset(scopes):
            return Credentials.from_authorized_user_file(str(path),scopes)
    except (ValueError,OSError,TypeError,KeyError):
        pass
    return None


def _classify_login_error(error):
    text=str(error)
    low=text.casefold()
    name=type(error).__name__
    if "access_denied" in low or name in ("AccessDeniedError",):
        return GoogleLoginCancelled()
    if "timed out" in low or name in ("WSGITimeoutError","TimeoutError"):
        return GoogleLoginCancelled("Час очікування входу минув: вхід у Google не завершено. Нічого не змінено.")
    if "scope has changed" in low:
        return GoogleAuthProblem("Google видав не всі дозволи. Увійдіть ще раз і поставте ВСІ галочки доступу.")
    return GoogleAuthProblem("Не вдалося увійти в Google: "+redact(text))


def _run_login(scopes):
    """Звичайний вхід через браузер. Просимо постійний дозвіл (offline) і явну згоду, щоб Google ТОЧНО видав НОВИЙ refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    secret=DATA/CLIENT_FILE
    if not secret.exists():
        raise GoogleClientMissing()
    flow=InstalledAppFlow.from_client_secrets_file(str(secret),scopes)
    try:
        creds=flow.run_local_server(port=0,access_type="offline",prompt="consent",authorization_prompt_message="",
                                    timeout_seconds=LOGIN_TIMEOUT)
    except Exception as error:
        raise _classify_login_error(error) from None
    if not getattr(creds,"refresh_token",None):
        raise GoogleAuthProblem("Google не видав постійний дозвіл. Спробуйте ще раз: у браузері дозвольте доступ повністю.")
    return creds


def authenticate(scopes=None,token_name=TOKEN_FILE,interactive=True):
    """Робочі дані входу. Дозвіл оновлюється ОДИН раз; invalid_grant → GoogleReauthRequired (токен скинуто, стан «не підключено»).
    interactive=False: без дозволу НЕ відкривати браузер, а повідомити GoogleNotConnected."""
    try:
        from google.auth.transport.requests import Request
        import google_auth_oauthlib.flow  # noqa: F401  (перевірка, що пакети встановлено)
    except ImportError as e:
        raise RuntimeError("Google пакети не встановлено. Виконайте pip install -r requirements.txt") from e
    scopes=list(scopes or SCOPES)
    path=DATA/token_name
    creds=_load_credentials(path,scopes)
    if creds and not creds.valid:
        if creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as error:
                if is_auth_failure(error):_auth_failed(token_name)
                if isinstance(error,OSError) or type(error).__name__ in ("TransportError","ConnectionError"):mark_offline()
                raise
            _write_token(path,creds)
            if token_name==TOKEN_FILE:mark_verified()              # успішне оновлення = Google підтвердив дозвіл
        else:
            creds=None
    if not creds or not creds.valid:
        if not interactive:
            raise GoogleNotConnected()
        creds=_run_login(scopes)
        _write_token(path,creds)
    return creds


def services(with_announcements=False):
    from googleapiclient.discovery import build
    if with_announcements:
        # Окремий дозвіл на оголошення запитується лише за явною командою вчителя: тут вхід у браузері дозволений.
        creds=authenticate(ANNOUNCEMENT_SCOPES,token_name=ANNOUNCEMENT_TOKEN_FILE,interactive=True)
    else:
        creds=authenticate(interactive=False)
    return build("classroom","v1",credentials=creds,cache_discovery=False),build("drive","v3",credentials=creds,cache_discovery=False)


def reconnect_google(cancel=None):
    """«Увійти в Google заново»: скинути дозвіл користувача → (файл клієнта вже є) → браузер → новий дозвіл →
    ПРОСТИЙ тестовий запит → лише тоді «підключено». Збій чи скасування лишають стан «не підключено»."""
    if not credentials_present():                                 # без файла клієнта повторний вхід неможливий: нічого не скидаємо
        raise GoogleClientMissing()
    clear_google_user_credentials()
    set_busy(True)
    try:
        creds=authenticate(interactive=True)
        if cancel is not None and cancel.is_set():
            raise GoogleLoginCancelled()
        from googleapiclient.discovery import build
        classroom=build("classroom","v1",credentials=creds,cache_discovery=False)
        classroom.courses().list(pageSize=1).execute()             # перевірка, що дозвіл справді працює
    except BaseException as error:
        clear_google_user_credentials()
        if isinstance(error,GoogleAuthProblem):raise
        if is_auth_failure(error):raise GoogleReauthRequired() from None
        raise GoogleAuthProblem("Вхід виконано, але Google не відповів на перевірку: "+redact(error)) from None
    finally:
        with _lock:_session["busy"]=False
    mark_verified()
    return True


def _revocable_tokens():
    found=[]
    for path in _user_token_paths():
        try:
            info=json.loads(path.read_text(encoding="utf8"))
        except (OSError,ValueError):
            continue
        token=info.get("refresh_token") or info.get("token")
        if token and token not in found:found.append(token)
    return found


def revoke_remote(token,opener=urllib.request.urlopen,timeout=8):
    """Відкликати токен на боці Google (офіційний endpoint). 'revoked' | 'already' (уже відкликано) | 'failed'. Ніколи не кидає."""
    data=urllib.parse.urlencode({"token":token}).encode("ascii")
    request=urllib.request.Request(REVOKE_URL,data=data,headers={"Content-Type":"application/x-www-form-urlencoded"})
    try:
        with opener(request,timeout=timeout):
            return "revoked"
    except urllib.error.HTTPError as error:
        return "already" if error.code==400 else "failed"        # 400 invalid_token = уже відкликано або прострочено
    except Exception:
        return "failed"


def disconnect_google(revoke=True,opener=urllib.request.urlopen):
    """«Від'єднати Google»: (за можливості) відкликати токен у Google, потім ЗАВЖДИ очистити локальний дозвіл.
    Збій відкликання не заважає локальному відключенню. Браузер не запускається; файл клієнта OAuth лишається."""
    report={"revoked":0,"already":0,"failed":0}
    if revoke:
        for token in _revocable_tokens():
            report[{"revoked":"revoked","already":"already","failed":"failed"}[revoke_remote(token,opener)]]+=1
    report["removed"]=clear_google_user_credentials()
    return report


def reset_authorization():
    """Діагностичний скид: лише локальний дозвіл і внутрішній стан (без запитів до Google, без браузера)."""
    return clear_google_user_credentials()


def credentials_present():
    """Чи імпортовано файл клієнта OAuth (Desktop JSON) вчителя."""
    return (DATA/CLIENT_FILE).is_file()


def _client_id(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig")).get("installed",{}).get("client_id")
    except (OSError,ValueError,AttributeError):
        return None


def import_credentials_file(path):
    """Перевіряє й копіює завантажений із Google Cloud JSON. Помилки — зрозумілою мовою.
    Якщо це ІНШИЙ клієнт, старі дозволи користувача втрачають силу й скидаються (нових файлів вводити не треба)."""
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
    previous=_client_id(DATA/CLIENT_FILE)
    shutil.copyfile(path,DATA/CLIENT_FILE)
    if previous and previous!=details["client_id"]:
        clear_google_user_credentials()                          # дозволи видані іншому клієнту: вони більше не діють
    return DATA/CLIENT_FILE


@guarded
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
    mark_verified()                                       # Google відповів: дозвіл справді працює
    return [{"id":c["id"],"name":c.get("name",""),"section":c.get("section",""),"courseState":c.get("courseState","")} for c in found]

@guarded
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
    mark_verified()
    # Keep old drive_id field for compatibility: None when no files.
    return {"id":result["id"],"drive_id":uploaded_ids[0] if uploaded_ids else None,
            "attachment_drive_ids":uploaded_ids[1:] if docx_path else uploaded_ids,
            "course_id":course_id,
            "kind":"ASSIGNMENT" if assignment else "MATERIAL","state":"DRAFT","created_at":time.time()}


def token_ready():
    """Є збережений дозвіл, який МОЖЕ працювати: потрібні всі дозволи, і постійний refresh token (або ще чинний access token).
    Позначка про відкликання (invalid_grant) у цьому сеансі робить результат хибним. Це НЕ підтвердження від Google:
    підтвердження дає connection_state() == «connected»."""
    if _session["failed"]:return False
    path=DATA/TOKEN_FILE
    if not path.exists():return False
    try:
        info=json.loads(path.read_text(encoding="utf8"))
        if not set(info.get("scopes",[])).issuperset(SCOPES):return False
        if info.get("refresh_token"):return True
        if info.get("token"):
            expiry=info.get("expiry")
            if not expiry:return True
            from datetime import datetime,timezone
            moment=datetime.fromisoformat(str(expiry).replace("Z","+00:00"))
            if moment.tzinfo is None:moment=moment.replace(tzinfo=timezone.utc)
            return moment>datetime.now(timezone.utc)
        return False
    except (ValueError,OSError,TypeError,AttributeError):
        return False


@guarded
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
        except GoogleAuthProblem:
            raise                                                  # дозвіл Google недійсний: далі пробувати марно
        except Exception as ex:
            errors.append(f"{names.get(cid,cid)}: {redact(ex)}")
    return {"courses":courses,"mapped":mapped,"entries":entries,"errors":errors,"truncated":truncated,
            "unmapped":[t for t in titles if t not in mapped]}


@guarded
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
