"""5.6: керування входом у Google (OAuth): invalid_grant, «Увійти заново», «Від'єднати», правдивий стан. Сценарії A–G."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from test_update44 import TempProgram

from classroom_assistant import engine, google_client as gc, google_setup_ui, gui, themed_dialogs

INVALID_GRANT = ("invalid_grant: Token has been expired or revoked.",
                 {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
SECRET_REFRESH, SECRET_ACCESS, SECRET_CLIENT = "1//0gSECRETrefreshTOKEN123", "ya29.SECRETaccessTOKEN456", "GOCSPX-SECRETclient789"


def pump(widget, seconds=0.0, n=0):
    end = time.time() + seconds
    for _ in range(max(n, 1)):
        widget.update()
        time.sleep(0.01)
    while time.time() < end:
        widget.update()
        time.sleep(0.01)


def make_credentials(valid=True, refresh=SECRET_REFRESH, scopes=None):
    expiry = datetime.utcnow() + (timedelta(hours=1) if valid else -timedelta(hours=1))
    return Credentials(token=SECRET_ACCESS, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                       client_id="cid.apps.googleusercontent.com", client_secret=SECRET_CLIENT,
                       scopes=list(scopes or gc.SCOPES), expiry=expiry)


def good_refresh(self, request):
    self.token = "ya29.NEWtoken"
    self.expiry = datetime.utcnow() + timedelta(hours=1)


def bad_refresh(self, request):
    raise RefreshError(*INVALID_GRANT)


class FakeFlow:
    def __init__(self, outcome):
        self.outcome, self.kwargs = outcome, None

    def run_local_server(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class SyncThread:
    """У тестах немає mainloop, тож «фоновий» потік виконуємо одразу в головному (у програмі потік справжній)."""

    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class AccessDeniedError(Exception):
    pass


class WSGITimeoutError(Exception):
    pass


class GoogleDataCase(unittest.TestCase):
    """Тека з даними програми: клієнт OAuth, токени, розклад, КТП, зіставлення, налаштування."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        patcher = mock.patch.object(gc, "DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        gc.reset_session()
        self.addCleanup(gc.reset_session)
        self.program_files = {"Календарні плани.json": '{"ктп": 1}', "Налаштування.json": '{"розклад": 2}',
                              "state.json": '{"course_ids": {"8-Б": "1"}}', "attachment.png": "png"}
        for name, text in self.program_files.items():
            (self.data / name).write_text(text, encoding="utf-8")

    def write_client(self, client_id="cid.apps.googleusercontent.com"):
        (self.data / gc.CLIENT_FILE).write_text(json.dumps({"installed": {
            "client_id": client_id, "client_secret": SECRET_CLIENT, "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}}), encoding="utf-8")

    def write_token(self, name=gc.TOKEN_FILE, **kwargs):
        (self.data / name).write_text(make_credentials(**kwargs).to_json(), encoding="utf-8")

    def assert_program_data_untouched(self):
        for name, text in self.program_files.items():
            self.assertEqual((self.data / name).read_text(encoding="utf-8"), text, name)

    def tokens_left(self):
        return [n for n in gc.USER_TOKEN_FILES if (self.data / n).exists()]


class ClearCredentialsTests(GoogleDataCase):
    def test_only_the_users_permission_goes_away_never_the_client_or_the_program_data(self):
        self.write_client()
        self.write_token()
        self.write_token(gc.ANNOUNCEMENT_TOKEN_FILE)
        removed = gc.clear_google_user_credentials()
        self.assertEqual(sorted(removed), sorted(gc.USER_TOKEN_FILES))
        self.assertEqual(self.tokens_left(), [])
        self.assertTrue(gc.credentials_present())                                   # «паспорт програми» лишається
        self.assert_program_data_untouched()                                        # розклад, КТП, зіставлення, вкладення, налаштування

    def test_it_is_safe_to_call_twice_and_resets_the_session_and_tells_the_listeners(self):
        seen = []
        gc.add_listener(seen.append)
        self.addCleanup(gc.remove_listener, seen.append)
        gc.mark_verified()
        gc.clear_google_user_credentials()
        self.assertEqual(gc.clear_google_user_credentials(), [])
        self.assertEqual(gc.connection_state(), "disconnected")
        self.assertIn("disconnected", seen)

    def test_if_a_file_cannot_be_deleted_its_content_is_neutralised(self):
        self.write_token()
        with mock.patch.object(Path, "unlink", side_effect=OSError("зайнято")):
            gc.clear_google_user_credentials()
        self.assertEqual((self.data / gc.TOKEN_FILE).read_text(encoding="utf-8"), "{}")
        self.assertFalse(gc.token_ready())


class ConnectionStateTests(GoogleDataCase):
    def test_a_token_file_alone_does_not_mean_connected(self):
        self.assertEqual(gc.connection_state(), "disconnected")
        self.write_token()
        self.assertTrue(gc.token_ready())
        self.assertEqual(gc.connection_state(), "connecting")                       # файл є, але Google ще не підтвердив
        gc.mark_verified()
        self.assertEqual(gc.connection_state(), "connected")

    def test_the_states_after_a_failure_are_truthful(self):
        self.write_token()
        gc.mark_verified()
        gc.mark_offline()
        gc.mark_verified()
        self.assertEqual(gc.connection_state(), "connected")
        with self.assertRaises(gc.GoogleReauthRequired):
            gc._auth_failed()
        self.assertEqual(gc.connection_state(), "reauth")                           # ніколи не «підключено» після invalid_grant
        self.assertFalse(gc.token_ready())

    def test_token_ready_checks_scopes_refresh_token_and_expiry(self):
        self.write_token(scopes=gc.SCOPES[:1])
        self.assertFalse(gc.token_ready())                                          # не всі дозволи
        self.write_token(refresh=None, valid=False)
        self.assertFalse(gc.token_ready())                                          # протух і оновити нічим
        self.write_token(refresh=None, valid=True)
        self.assertTrue(gc.token_ready())                                           # ще чинний access token
        self.write_token(refresh=SECRET_REFRESH, valid=False)
        self.assertTrue(gc.token_ready())                                           # протух, але є refresh token
        (self.data / gc.TOKEN_FILE).write_text("не json", encoding="utf-8")
        self.assertFalse(gc.token_ready())

    def test_busy_means_connecting_even_without_a_token(self):
        gc.set_busy(True)
        self.assertEqual(gc.connection_state(), "connecting")
        gc.set_busy(False)
        self.assertEqual(gc.connection_state(), "disconnected")


class ScenarioTests(GoogleDataCase):
    def test_A_normal_start_valid_token_then_a_real_answer_makes_it_connected(self):
        self.write_client()
        self.write_token()
        with mock.patch.object(Credentials, "refresh", side_effect=AssertionError("оновлення не потрібне")):
            creds = gc.authenticate(interactive=False)
        self.assertTrue(creds.valid)
        self.assertEqual(gc.connection_state(), "connecting")
        classroom = mock.Mock()
        classroom.courses.return_value.list.return_value.execute.return_value = {"courses": [{"id": "1", "name": "8-Б"}]}
        with mock.patch.object(gc, "services", return_value=(classroom, mock.Mock())):
            courses = gc.list_teacher_courses()
        self.assertEqual(courses[0]["id"], "1")
        self.assertEqual(gc.connection_state(), "connected")

    def test_B_expired_access_token_with_a_good_refresh_token_is_renewed_silently_and_saved(self):
        self.write_client()
        self.write_token(valid=False)
        refresh = mock.Mock(side_effect=good_refresh, autospec=True)
        with mock.patch.object(Credentials, "refresh", good_refresh):
            creds = gc.authenticate(interactive=False)
        self.assertTrue(creds.valid)
        saved = json.loads((self.data / gc.TOKEN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["token"], "ya29.NEWtoken")                           # оновлений токен збережено
        self.assertEqual(saved["refresh_token"], SECRET_REFRESH)
        self.assertEqual(gc.connection_state(), "connected")                        # успішне оновлення = підтвердження Google

    def test_C_invalid_grant_resets_the_permission_marks_it_disconnected_and_is_not_retried(self):
        self.write_client()
        self.write_token(valid=False)
        calls = []
        with mock.patch.object(Credentials, "refresh", lambda s, r: (calls.append(1), bad_refresh(s, r))):
            with self.assertRaises(gc.GoogleReauthRequired) as caught:
                gc.authenticate(interactive=False)
            self.assertEqual(len(calls), 1)
            with self.assertRaises(gc.GoogleNotConnected):                           # другої спроби оновлення немає: файлу вже немає
                gc.authenticate(interactive=False)
            self.assertEqual(len(calls), 1)
        message = str(caught.exception)
        self.assertIn("Потрібен повторний вхід у Google", message)
        self.assertIn("Це не означає, що втрачено ваш розклад чи дані програми", message)
        self.assertNotIn("invalid_grant", message)                                  # не технічна помилка
        self.assertEqual(self.tokens_left(), [])
        self.assertTrue(gc.credentials_present())
        self.assertEqual(gc.connection_state(), "reauth")
        self.assertFalse(gc.token_ready())
        self.assert_program_data_untouched()

    def test_C_after_invalid_grant_the_whole_chain_ends_with_a_new_working_token(self):
        self.write_client()
        self.write_token(valid=False)
        with mock.patch.object(Credentials, "refresh", bad_refresh), self.assertRaises(gc.GoogleReauthRequired):
            gc.authenticate(interactive=False)
        flow = FakeFlow(make_credentials(refresh="1//BRANDnewREFRESH"))
        classroom = mock.Mock()
        classroom.courses.return_value.list.return_value.execute.return_value = {}
        with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", return_value=flow), \
                mock.patch("googleapiclient.discovery.build", return_value=classroom):
            self.assertTrue(gc.reconnect_google())
        saved = json.loads((self.data / gc.TOKEN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], "1//BRANDnewREFRESH")             # новий refresh token справді збережено
        self.assertEqual(flow.kwargs["prompt"], "consent")                          # Google ТОЧНО видає новий refresh token
        self.assertEqual(flow.kwargs["access_type"], "offline")
        self.assertEqual(flow.kwargs["authorization_prompt_message"], "")           # адреса входу не друкується
        self.assertEqual(gc.connection_state(), "connected")
        classroom.courses.return_value.list.assert_called_once()                     # простий тестовий запит виконано
        self.assert_program_data_untouched()

    def test_C_an_invalid_grant_inside_an_api_call_is_handled_in_one_place_too(self):
        self.write_client()
        self.write_token()
        classroom = mock.Mock()
        classroom.courses.return_value.list.return_value.execute.side_effect = RefreshError(*INVALID_GRANT)
        with mock.patch.object(gc, "services", return_value=(classroom, mock.Mock())):
            with self.assertRaises(gc.GoogleReauthRequired):
                gc.list_teacher_courses()
        self.assertEqual(self.tokens_left(), [])
        self.assertEqual(gc.connection_state(), "reauth")

    def test_C_a_dead_permission_stops_the_whole_sync_instead_of_failing_every_course(self):
        courses = [{"id": str(n), "name": f"{n}-А", "section": "", "courseState": "ACTIVE"} for n in (1, 2, 3)]
        calls = []

        def posts(course_id, service=None):
            calls.append(course_id)
            raise gc.GoogleReauthRequired()
        self.write_token()
        with mock.patch.object(gc, "list_teacher_courses", return_value=courses), \
                mock.patch.object(gc, "services", return_value=(mock.Mock(), mock.Mock())), \
                mock.patch.object(gc, "list_classroom_posts", side_effect=posts):
            with self.assertRaises(gc.GoogleReauthRequired):
                gc.sync_everything(["1-А", "2-А", "3-А"], {})
        self.assertEqual(calls, ["1"])                                               # решта курсів не мучимо

    def test_C_an_ordinary_error_of_one_course_is_still_collected_and_secrets_are_hidden(self):
        courses = [{"id": "1", "name": "1-А", "section": "", "courseState": "ACTIVE"}]
        with mock.patch.object(gc, "list_teacher_courses", return_value=courses), \
                mock.patch.object(gc, "services", return_value=(mock.Mock(), mock.Mock())), \
                mock.patch.object(gc, "list_classroom_posts", side_effect=RuntimeError(f"збій access_token: {SECRET_ACCESS}")):
            result = gc.sync_everything(["1-А"], {})
        self.assertEqual(len(result["errors"]), 1)
        self.assertNotIn(SECRET_ACCESS, result["errors"][0])

    def test_D_disconnect_revokes_remotely_clears_locally_keeps_the_client_and_opens_no_browser(self):
        self.write_client()
        self.write_token()
        requests = []

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout=None):
            requests.append((request.full_url, request.data.decode()))
            return Reply()
        with mock.patch.object(gc, "_run_login", side_effect=AssertionError("браузер не повинен відкриватись")):
            report = gc.disconnect_google(opener=opener)
        self.assertEqual(requests, [(gc.REVOKE_URL, "token=" + SECRET_REFRESH.replace("/", "%2F"))])   # офіційний endpoint
        self.assertEqual(report["revoked"], 1)
        self.assertEqual(self.tokens_left(), [])
        self.assertTrue(gc.credentials_present())
        self.assertEqual(gc.connection_state(), "disconnected")
        self.assert_program_data_untouched()

    def test_D_an_already_revoked_or_unreachable_remote_never_blocks_the_local_disconnect(self):
        for failure, key in ((urllib.error.HTTPError("u", 400, "Bad", {}, None), "already"),
                             (urllib.error.URLError("мережі немає"), "failed"), (TimeoutError(), "failed")):
            self.write_token()

            def opener(request, timeout=None, failure=failure):
                raise failure
            report = gc.disconnect_google(opener=opener)
            self.assertEqual(report[key], 1, failure)
            self.assertEqual(self.tokens_left(), [])
        self.write_token()
        spy = mock.Mock()
        gc.disconnect_google(revoke=False, opener=spy)
        spy.assert_not_called()                                                      # без відкликання — жодного запиту

    def test_E_reconnect_with_the_client_json_already_imported_goes_straight_to_google_login(self):
        self.write_client()
        self.write_token(valid=False)
        flow = FakeFlow(make_credentials(refresh="1//second"))
        classroom = mock.Mock()
        classroom.courses.return_value.list.return_value.execute.return_value = {}
        with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", return_value=flow) as make, \
                mock.patch("googleapiclient.discovery.build", return_value=classroom):
            gc.reconnect_google()
        make.assert_called_once()                                                    # файл клієнта береться з теки даних сам
        self.assertEqual(Path(make.call_args[0][0]), self.data / gc.CLIENT_FILE)

    def test_F_without_the_client_json_it_explains_what_to_do_and_loses_nothing(self):
        self.write_token()
        with self.assertRaises(gc.GoogleClientMissing) as caught:
            gc.reconnect_google()
        self.assertEqual(str(caught.exception), "Спочатку імпортуйте OAuth Client JSON типу Desktop app.")
        self.assertEqual(self.tokens_left(), [gc.TOKEN_FILE])                        # токен не знищено даремно

    def test_G_cancelling_or_denying_access_leaves_a_stable_disconnected_state(self):
        self.write_client()
        self.write_token(valid=False)
        cases = ((AccessDeniedError("(access_denied) Access denied"), "скасовано"),
                 (WSGITimeoutError("Timed out waiting for response from authorization server"), "Час очікування"))
        for error, expected in cases:
            self.write_token(valid=False)
            with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                            return_value=FakeFlow(error)):
                with self.assertRaises(gc.GoogleLoginCancelled) as caught:
                    gc.reconnect_google()
            self.assertIn(expected, str(caught.exception))
            self.assertEqual(self.tokens_left(), [])                                 # старий недійсний токен знову «робочим» не стає
            self.assertEqual(gc.connection_state(), "disconnected")
            self.assertTrue(gc.credentials_present())
        self.assert_program_data_untouched()

    def test_G_a_test_request_that_fails_does_not_leave_a_half_connected_state(self):
        self.write_client()
        classroom = mock.Mock()
        classroom.courses.return_value.list.return_value.execute.side_effect = RuntimeError(f"збій {SECRET_ACCESS}")
        with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                        return_value=FakeFlow(make_credentials())), \
                mock.patch("googleapiclient.discovery.build", return_value=classroom):
            with self.assertRaises(gc.GoogleAuthProblem) as caught:
                gc.reconnect_google()
        self.assertNotIn(SECRET_ACCESS, str(caught.exception))
        self.assertEqual(self.tokens_left(), [])
        self.assertEqual(gc.connection_state(), "disconnected")

    def test_a_login_without_a_permanent_permission_is_refused(self):
        self.write_client()
        with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                        return_value=FakeFlow(make_credentials(refresh=None))):
            with self.assertRaises(gc.GoogleAuthProblem) as caught:
                gc.reconnect_google()
        self.assertIn("постійний дозвіл", str(caught.exception))
        self.assertEqual(self.tokens_left(), [])

    def test_a_network_failure_is_not_mistaken_for_a_revoked_permission(self):
        self.write_client()
        self.write_token(valid=False)

        def offline(self_, request):
            raise ConnectionError("немає мережі")
        with mock.patch.object(Credentials, "refresh", offline), self.assertRaises(ConnectionError):
            gc.authenticate(interactive=False)
        self.assertEqual(self.tokens_left(), [gc.TOKEN_FILE])                       # токен ЦІЛИЙ: мережа не причина його скидати
        self.assertEqual(gc.connection_state(), "offline")

    def test_reset_authorization_is_local_only(self):
        self.write_client()
        self.write_token()
        with mock.patch.object(gc, "revoke_remote", side_effect=AssertionError("жодних запитів до Google")):
            gc.reset_authorization()
        self.assertEqual(self.tokens_left(), [])
        self.assertTrue(gc.credentials_present())
        self.assert_program_data_untouched()


class ClientFileTests(GoogleDataCase):
    def test_importing_another_client_drops_permissions_issued_to_the_old_one(self):
        self.write_client("old")
        self.write_token()
        other = self.data / "other.json"
        other.write_text(json.dumps({"installed": {"client_id": "new", "auth_uri": "a", "token_uri": "t"}}), encoding="utf-8")
        gc.import_credentials_file(other)
        self.assertEqual(self.tokens_left(), [])

    def test_importing_the_same_client_again_keeps_the_login(self):
        self.write_client("same")
        self.write_token()
        again = self.data / "again.json"
        again.write_text(json.dumps({"installed": {"client_id": "same", "auth_uri": "a", "token_uri": "t"}}), encoding="utf-8")
        gc.import_credentials_file(again)
        self.assertEqual(self.tokens_left(), [gc.TOKEN_FILE])


class SecurityTests(unittest.TestCase):
    def test_tokens_and_secrets_never_reach_a_message(self):
        raw = (f'{{"refresh_token": "{SECRET_REFRESH}", "client_secret": "{SECRET_CLIENT}", "access_token": "{SECRET_ACCESS}"}} '
               f"Bearer {SECRET_ACCESS} {SECRET_REFRESH}")
        cleaned = gc.redact(raw)
        for secret in (SECRET_REFRESH, SECRET_ACCESS, SECRET_CLIENT):
            self.assertNotIn(secret, cleaned)
        self.assertNotIn(SECRET_ACCESS, gc.friendly_message(RuntimeError(raw)))

    def test_invalid_grant_is_recognised_in_every_form_google_uses(self):
        for error in (RefreshError(*INVALID_GRANT), Exception("invalid_grant"), Exception("Token has been expired or revoked."),
                      Exception("Token has been revoked")):
            self.assertTrue(gc.is_auth_failure(error), error)
        for error in (Exception("timeout"), ConnectionError("мережа"), gc.GoogleReauthRequired()):
            self.assertFalse(gc.is_auth_failure(error), error)

    def test_the_friendly_messages_are_the_ones_from_the_specification(self):
        self.assertEqual(gc.REAUTH_TEXT, "Попередній дозвіл Google більше не діє або був відкликаний. Це не означає, що втрачено "
                                         "ваш розклад чи дані програми. Увійдіть у Google ще раз, щоб відновити доступ до "
                                         "Classroom і Drive.")


class InterfaceTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.data = engine.DATA
        patcher = mock.patch.object(gc, "DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in gc.USER_TOKEN_FILES:
            (self.data / name).unlink(missing_ok=True)
        (self.data / gc.CLIENT_FILE).unlink(missing_ok=True)
        gc.reset_session()
        self.dialogs = []

    def write_client(self):
        (self.data / gc.CLIENT_FILE).write_text(json.dumps({"installed": {
            "client_id": "cid", "auth_uri": "a", "token_uri": "t"}}), encoding="utf-8")

    def label(self):
        return str(self.app.google_button.cget("text"))

    def test_the_button_text_follows_the_true_state(self):
        self.app._refresh_google_button()
        self.assertEqual(self.label(), "Google не підключено")
        (self.data / gc.TOKEN_FILE).write_text(make_credentials().to_json(), encoding="utf-8")
        self.app._refresh_google_button()
        self.assertEqual(self.label(), "Підключення до Google...")
        gc.mark_verified()
        self.app._refresh_google_button()
        self.assertEqual(self.label(), "✓ Google підключено")
        with self.assertRaises(gc.GoogleReauthRequired):
            gc._auth_failed()
        self.app._refresh_google_button()
        self.assertEqual(self.label(), "Google не підключено")                      # після invalid_grant — НІКОЛИ «підключено»

    def test_a_state_change_from_any_thread_updates_the_button_without_touching_tk(self):
        (self.data / gc.TOKEN_FILE).write_text(make_credentials().to_json(), encoding="utf-8")
        worker = threading.Thread(target=gc.mark_verified)
        worker.start()
        worker.join()
        pump(self.app, 0.9)
        self.assertEqual(self.label(), "✓ Google підключено")

    def test_invalid_grant_shows_the_reauth_window_once_with_the_exact_text_and_buttons(self):
        shown = []

        def fake_choice(title, message, choices, **options):
            shown.append((title, message, [c[0] for c in choices]))
            return False
        with mock.patch.object(themed_dialogs, "ask_choice", side_effect=fake_choice):
            for _ in range(3):
                self.app._on_google_state("reauth")
        self.assertEqual(len(shown), 3)                                             # (повторні виклики по черзі; одночасно — нижче)
        title, message, buttons = shown[0]
        self.assertEqual(title, "Потрібен повторний вхід у Google")
        self.assertEqual(message, gc.REAUTH_TEXT)
        self.assertEqual(buttons, ["Увійти заново", "Скасувати"])

    def test_the_reauth_window_never_opens_twice_at_the_same_time(self):
        calls = []

        def reentrant(title, message, choices, **options):
            self.app.prompt_reauth()                                                 # друге виклик, поки перше відкрито
            calls.append(1)
            return False
        with mock.patch.object(themed_dialogs, "ask_choice", side_effect=reentrant) as ask:
            self.app.prompt_reauth()
        self.assertEqual(ask.call_count, 1)

    def test_choosing_login_again_starts_the_reconnect_without_asking_again(self):
        with mock.patch.object(themed_dialogs, "ask_choice", return_value=True), \
                mock.patch.object(self.app, "google_reconnect") as reconnect:
            self.app.prompt_reauth()
        reconnect.assert_called_once_with(confirm=False)
        with mock.patch.object(themed_dialogs, "ask_choice", return_value=False), \
                mock.patch.object(self.app, "google_reconnect") as reconnect:
            self.app.prompt_reauth()
        reconnect.assert_not_called()

    def test_reconnect_asks_for_confirmation_with_the_exact_text_and_declining_changes_nothing(self):
        self.write_client()
        with mock.patch.object(gui.messagebox, "askyesno", return_value=False) as ask, \
                mock.patch.object(gc, "reconnect_google") as flow:
            self.app.google_reconnect()
        self.assertEqual(ask.call_args.args[0], "Увійти в Google заново")
        self.assertEqual(ask.call_args.args[1], "Поточний сеанс Google буде скинуто. Розклад, КТП, зіставлення курсів та інші "
                                                "дані програми не буде видалено. Продовжити?")
        flow.assert_not_called()

    def test_successful_reconnect_connects_and_syncs(self):
        self.write_client()
        synced = []
        self.app.sync_classroom = lambda **kw: synced.append(kw)

        def login(*a, **k):
            gc.mark_verified()
            return True
        with mock.patch.object(gc, "reconnect_google", side_effect=login), \
                mock.patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.google_reconnect()
            pump(self.app, 1.0)
        self.assertEqual(synced, [{"interactive": True, "announce": True}])
        self.assertFalse(self.app._google_busy)

    def test_E_connect_with_the_json_already_there_logs_in_at_once_without_a_file_chooser(self):
        self.write_client()
        with mock.patch.object(self.app, "google_reconnect") as reconnect, \
                mock.patch.object(gui.filedialog, "askopenfilename", side_effect=AssertionError("вибору JSON не має бути")):
            self.app.connect_google()
        reconnect.assert_called_once_with(confirm=False)

    def test_F_connect_without_the_json_opens_the_instruction_wizard(self):
        with mock.patch("classroom_assistant.google_setup_ui.show_google_wizard") as wizard:
            self.app.connect_google()
        wizard.assert_called_once_with(self.app)
        with mock.patch.object(gui.messagebox, "showinfo") as info:
            self.app.google_reconnect()
        self.assertEqual(info.call_args.args[1], "Спочатку імпортуйте OAuth Client JSON типу Desktop app.")

    def test_G_a_cancelled_login_does_not_crash_and_stays_disconnected(self):
        self.write_client()
        with mock.patch.object(gc, "reconnect_google", side_effect=gc.GoogleLoginCancelled()), \
                mock.patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.google_reconnect()
            pump(self.app, 1.0)
        self.assertFalse(self.app._google_busy)
        self.assertEqual(self.label(), "Google не підключено")
        self.assertIn("скасовано", self.toasts[-1])

    def test_D_disconnect_asks_with_the_exact_text_and_removes_only_the_permission(self):
        self.write_client()
        (self.data / gc.TOKEN_FILE).write_text(make_credentials().to_json(), encoding="utf-8")
        with mock.patch.object(gui.messagebox, "askyesno", return_value=False) as ask, \
                mock.patch.object(gc, "disconnect_google") as off:
            self.app.google_disconnect()
        self.assertEqual(ask.call_args.args[0], "Від'єднати Google")
        self.assertEqual(ask.call_args.args[1], "Від'єднати Google від цієї програми? Розклад, КТП та локальні дані не буде видалено.")
        off.assert_not_called()
        with mock.patch.object(gui.messagebox, "askyesno", return_value=True), \
                mock.patch.object(gc, "revoke_remote", return_value="revoked"):
            self.app.google_disconnect()
            pump(self.app, 1.0)
        self.assertFalse((self.data / gc.TOKEN_FILE).exists())
        self.assertTrue((self.data / gc.CLIENT_FILE).exists())
        self.assertEqual(self.label(), "Google не підключено")

    def test_an_auth_problem_in_a_background_task_gives_the_friendly_window_and_not_a_technical_box(self):
        with mock.patch.object(gui.messagebox, "showerror", side_effect=AssertionError("технічної помилки не має бути")), \
                mock.patch.object(gui.threading, "Thread", SyncThread), \
                mock.patch.object(self.app, "prompt_reauth") as prompt:
            self.app.worker(lambda: (_ for _ in ()).throw(gc.GoogleReauthRequired()), lambda r: None)
            pump(self.app, 0.3)
        prompt.assert_called_once()

    def test_a_dead_permission_during_sync_stops_the_sync_and_the_retries(self):
        self.app._sync_running = True
        self.app._sync_again = True
        with mock.patch.object(self.app, "prompt_reauth") as prompt:
            self.app._sync_auth_problem(gc.GoogleReauthRequired())
        self.assertFalse(self.app._sync_running)
        self.assertFalse(self.app._sync_again)
        prompt.assert_called_once()

    def test_other_errors_shown_to_the_teacher_do_not_carry_secrets(self):
        with mock.patch.object(gui.messagebox, "showerror") as box, mock.patch.object(gui.threading, "Thread", SyncThread):
            self.app.worker(lambda: (_ for _ in ()).throw(RuntimeError(f"збій {SECRET_ACCESS}")), lambda r: None)
            pump(self.app, 0.3)
        self.assertNotIn(SECRET_ACCESS, box.call_args.args[1])

    def test_the_setup_window_offers_the_right_google_buttons_for_each_state(self):
        self.write_client()
        self.app.setup_dialog()
        window = [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel"][-1]
        buttons = window.google_buttons

        def visible():
            window.refresh_google()
            window.update()
            return {name for name, button in buttons.items() if button.winfo_manager()}
        self.assertEqual(visible(), {"connect", "reset"})                           # не підключено: «Підключити»
        (self.data / gc.TOKEN_FILE).write_text(make_credentials().to_json(), encoding="utf-8")
        gc.mark_verified()
        self.assertEqual(visible(), {"again", "disconnect", "reset"})               # підключено: «Увійти заново» і «Від'єднати»
        with self.assertRaises(gc.GoogleReauthRequired):
            gc._auth_failed()
        self.assertEqual(visible(), {"connect", "again", "reset"})                  # з'єднання зламано: «Увійти заново» теж є
        texts = {name: str(button.cget("text")) for name, button in buttons.items()}
        self.assertEqual(texts, {"connect": "Підключити Google", "again": "Увійти в Google заново",
                                 "disconnect": "Від'єднати Google", "reset": "Скинути авторизацію Google"})

    def test_the_setup_window_imports_the_json_through_the_central_function(self):
        self.app.setup_dialog()
        window = [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel"][-1]
        source = Path(self.data.parent / "new_client.json")
        source.write_text(json.dumps({"installed": {"client_id": "x", "auth_uri": "a", "token_uri": "t"}}), encoding="utf-8")
        import_button = next(w for w in self._walk(window) if w.winfo_class() == "TButton"
                             and str(w.cget("text")) == "Імпортувати Google OAuth JSON")
        self.assertIn("OAuth JSON: не імпортовано", window.google_status.get())
        with mock.patch.object(gui.filedialog, "askopenfilename", return_value=str(source)), \
                mock.patch.object(gui.messagebox, "showinfo"):
            import_button.invoke()
        self.assertTrue(gc.credentials_present())
        self.assertIn("OAuth JSON: імпортовано", window.google_status.get())

    def test_the_window_stops_listening_when_it_is_closed(self):
        self.app.setup_dialog()
        window = [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel"][-1]
        self.assertTrue(self.app._google_refreshers)
        window.destroy()
        self.app.update()
        self.assertFalse(self.app._google_refreshers)

    @staticmethod
    def _walk(widget):
        out, stack = [], [widget]
        while stack:
            current = stack.pop()
            stack.extend(current.winfo_children())
            out.append(current)
        return out


class WizardTests(TempProgram):
    def test_the_first_login_in_the_wizard_uses_the_same_central_flow(self):
        self.app.sync_classroom = lambda **kw: None
        with mock.patch.object(gc, "DATA", engine.DATA), mock.patch.object(gc, "credentials_present", return_value=True), \
                mock.patch.object(gc, "reconnect_google", side_effect=gc.GoogleLoginCancelled()) as flow, \
                mock.patch.object(google_setup_ui.messagebox, "showinfo") as info, \
                mock.patch.object(google_setup_ui.messagebox, "showerror", side_effect=AssertionError("скасування — не помилка")):
            wizard = google_setup_ui.GoogleWizard(self.app)
            wizard.login()
            pump(self.app, 1.0)
        flow.assert_called_once()
        self.assertIn("скасовано", info.call_args.args[1])
        self.assertFalse(wizard._busy)


if __name__ == "__main__":
    unittest.main()
