"""4.4: програма не вважає «створеною» чернетку, якої вже немає в Classroom (звірка після синхронізації)."""
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from test_update36 import TkCase

from classroom_assistant import attachments, draft_batch, engine, google_client, gui, material_library
from classroom_assistant.engine import build_calendar

REPO_DATA = Path(__file__).resolve().parents[1] / "data"


class ReconcileTests(TkCase):
    NEEDS_ROOT = False

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / "root"
        (root / "data").mkdir(parents=True)
        for name in ("Налаштування.json", "Календарні плани.json"):
            shutil.copy(REPO_DATA / name, root / "data" / name)
        stack = ExitStack()
        for patcher in (mock.patch.object(engine, "DATA", root / "data"), mock.patch.object(engine, "ROOT", root),
                        mock.patch.object(gui, "DATA", root / "data"), mock.patch.object(gui, "ROOT", root),
                        mock.patch.object(material_library, "LIBRARY_ROOT", root / "Бібліотека"),
                        mock.patch.object(material_library, "INDEX", root / "Бібліотека" / "Індекс.json"),
                        mock.patch.object(attachments, "ATTACHMENT_ROOT", root / "Вкладення")):
            stack.enter_context(patcher)
        self.addCleanup(stack.close)
        self.toasts = []
        stack.enter_context(mock.patch.object(gui, "show_toast", side_effect=lambda p, text, *a, **k: self.toasts.append(text)))
        self.app = gui.MainApp()

        def close():
            try:
                self.app.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        day = [x for x in build_calendar(self.app.cfg) if x.day == "2026-10-05" and x.status == "готово"]
        self.lessons = day[:3]
        self.course_ids = {x.course_title: str(1000 + i) for i, x in enumerate(self.lessons)}
        self.app.state["course_ids"] = dict(self.course_ids)
        self.app._sync_started = time.time()

    def result(self, entries=None, truncated=None, only=None):
        ids = self.course_ids if only is None else {k: v for k, v in self.course_ids.items() if k in only}
        return {"courses": [{"name": t, "id": i} for t, i in ids.items()], "mapped": dict(ids),
                "entries": {i: [] for i in ids.values()} if entries is None else entries,
                "errors": [], "unmapped": [], "truncated": truncated or {}}

    def draft(self, lesson, **extra):
        record = {"id": f"d-{lesson.stream}", "created_at": 1.0}
        record.update(extra)
        self.app.state.setdefault("drafts", {})[lesson.unique_key] = record
        return record

    def statuses(self):
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        return {self.app.rows[int(i)].stream: self.app.grid.item(i, "values")[-1] for i in self.app.grid.get_children()}

    def test_a_draft_deleted_in_classroom_stops_being_reported_as_created(self):
        a, b, c = self.lessons
        for lesson in (a, b, c):
            self.draft(lesson)
        self.app._sync_done(self.result(), False)                              # Classroom прочитано: чернеток там немає
        self.assertEqual(self.app.state["drafts"], {})                          # усе, що видалили, прибрано
        self.assertEqual(sorted(x["id"] for x in self.app.state["drafts_removed"]),
                         sorted(f"d-{x.stream}" for x in (a, b, c)))
        self.assertIn("прибрано зі стану: 3", self.toasts[-1])
        for stream, status in self.statuses().items():
            self.assertFalse(status.startswith("Створено в Google"), (stream, status))
            self.assertNotIn("не знайдено", status)

    def test_after_the_cleanup_the_lesson_can_get_a_new_draft(self):
        lesson = self.lessons[0]
        self.draft(lesson)
        row = lesson
        _, before = draft_batch.plan_day_drafts([row], self.app.state, lambda x: "текст")
        self.assertEqual([reason for _, reason in before], ["чернетку вже створено"])        # саме це й блокувало
        self.app._sync_done(self.result(), False)
        ready, skipped = draft_batch.plan_day_drafts([row], self.app.state, lambda x: "текст")
        self.assertEqual(len(ready), 1)
        self.assertEqual(skipped, [])

    def test_only_the_missing_ones_are_removed(self):
        a, b, c = self.lessons
        for lesson in (a, b, c):
            self.draft(lesson)
        still_there = {self.course_ids[b.course_title]: [{"id": f"d-{b.stream}", "state": "DRAFT", "type": "Матеріал",
                                                          "title": "x", "updated": ""}]}
        entries = {i: [] for i in self.course_ids.values()}
        entries.update(still_there)
        self.app._sync_done(self.result(entries=entries), False)
        self.assertEqual(list(self.app.state["drafts"]), [b.unique_key])                   # у Classroom лишилась — лишилась й тут
        self.assertIn("чернетка в Classroom", self.statuses()[b.stream])

    def test_nothing_is_removed_when_it_cannot_be_verified(self):
        a, b, c = self.lessons
        self.draft(a, created_at=time.time())                                              # свіжа: Classroom ще не встиг
        self.draft(b)                                                                       # курс позначено неповним
        record = self.draft(c)
        record.pop("id")                                                                    # без id перевірити неможливо
        truncated = {self.course_ids[b.course_title]: ["Матеріал"]}
        self.app._sync_done(self.result(truncated=truncated), False)
        self.assertEqual(set(self.app.state["drafts"]), {a.unique_key, b.unique_key, c.unique_key})
        self.assertNotIn("drafts_removed", self.app.state)
        self.assertIn("перевіряю Classroom", self.statuses()[a.stream])                    # свіжу не лякаємо «не знайдено»

    def test_a_course_that_failed_to_load_keeps_its_records(self):
        a, b, _ = self.lessons
        self.draft(a)
        self.draft(b)
        result = self.result(only={a.course_title})                                        # курс b у цій синхронізації не читався
        result["entries"] = {self.course_ids[a.course_title]: []}
        result["errors"] = [f"{b.course_title}: помилка мережі"]
        self.app._sync_done(result, False)
        self.assertEqual(list(self.app.state["drafts"]), [b.unique_key])

    def test_the_cleanup_is_recorded_and_not_undone_by_the_back_arrow(self):
        lesson = self.lessons[0]
        self.draft(lesson)
        self.app._sync_done(self.result(), False)
        self.assertIn("drafts_removed", gui.NON_UNDOABLE)
        self.assertNotIn("drafts_removed", self.app._history_snapshot())
        self.assertEqual(self.app.state["drafts_removed"][0]["reason"], "немає в Classroom")

    def test_returning_to_the_program_refreshes_classroom_but_not_more_than_once_a_minute(self):
        calls = []
        self.app.request_sync = lambda delay=900: calls.append(delay)
        with mock.patch.object(google_client, "token_ready", return_value=True):
            self.app._last_sync_ts = 0
            self.app._on_focus_in(type("E", (), {"widget": self.app})())
            self.assertEqual(len(calls), 1)
            self.app._last_sync_ts = time.time()
            self.app._on_focus_in(type("E", (), {"widget": self.app})())               # щойно синхронізували
            self.assertEqual(len(calls), 1)
            self.app._last_sync_ts = 0
            self.app._on_focus_in(type("E", (), {"widget": self.app.grid})())          # фокус дрібного елемента — ні
            self.assertEqual(len(calls), 1)
        with mock.patch.object(google_client, "token_ready", return_value=False):
            self.app._on_focus_in(type("E", (), {"widget": self.app})())               # Google не підключено — тихо
            self.assertEqual(len(calls), 1)


class SyncReportsTruncationTests(unittest.TestCase):
    def test_sync_everything_returns_which_courses_were_cut_short(self):
        posts = {"1": {"items": [{"id": "x"}], "truncated": ["Матеріал"]}, "2": {"items": [], "truncated": []}}
        with mock.patch.object(google_client, "list_teacher_courses",
                               return_value=[{"id": "1", "name": "8-Б ІУ"}, {"id": "2", "name": "8-В ІУ"}]), \
                mock.patch.object(google_client, "services", return_value=(object(), object())), \
                mock.patch.object(google_client, "list_classroom_posts", side_effect=lambda cid, service=None: posts[cid]):
            result = google_client.sync_everything(["8-Б ІУ", "8-В ІУ"], {})
        self.assertEqual(result["truncated"], {"1": ["Матеріал"]})
        self.assertEqual(set(result["entries"]), {"1", "2"})


if __name__ == "__main__":
    unittest.main()


class GoogleButtonTests(ReconcileTests):
    """Кнопка «Підключити Google» завжди відповідає: коротка підказка без «ОК»."""

    def test_label_shows_whether_google_is_connected(self):
        with mock.patch.object(google_client, "token_ready", return_value=True):
            self.app._refresh_google_button()
            self.assertEqual(str(self.app.google_button.cget("text")), "✓ Google підключено")
        with mock.patch.object(google_client, "token_ready", return_value=False):
            self.app._refresh_google_button()
            self.assertEqual(str(self.app.google_button.cget("text")), "Підключити Google")

    def test_header_is_laid_out_again_when_the_label_changes_width(self):
        row = self.app.google_button.master
        calls = []
        original = row._layout
        row._layout = lambda *a: (calls.append(1), original(*a))[1]
        with mock.patch.object(google_client, "token_ready", return_value=True):
            self.app._refresh_google_button()
            self.app.update()
        self.assertTrue(calls)

    def test_click_when_connected_answers_at_once_and_after_the_update(self):
        started = []
        self.app.sync_classroom = lambda **kw: started.append(kw)
        with mock.patch.object(google_client, "token_ready", return_value=True), \
                mock.patch.object(gui.messagebox, "showinfo", side_effect=AssertionError("вікно з «ОК»!")):
            self.app.connect_google()
            self.assertIn("Google уже підключено", self.toasts[-1])               # відповідь одразу
            self.assertEqual(started, [{"interactive": True, "announce": True}])
            self.app._sync_done(self.result(), True, True)                        # оновлення завершилось
        self.assertIn("✓ Classroom оновлено: курсів — 3, записів — 0", self.toasts[-1])

    def test_click_during_a_running_update_says_so_instead_of_silence(self):
        started = []
        self.app.sync_classroom = lambda **kw: started.append(kw)
        self.app._sync_running = True
        with mock.patch.object(google_client, "token_ready", return_value=True):
            self.app.connect_google()
        self.assertIn("уже триває", self.toasts[-1])
        self.assertEqual(started, [])

    def test_real_problems_still_need_reading_but_missing_courses_are_only_a_warning_toast(self):
        result = self.result()
        result["errors"] = ["8-Б ІУ: мережа"]
        with mock.patch.object(gui.messagebox, "showinfo") as modal:
            self.app._sync_done(result, True, True)
        modal.assert_called_once()                                                # помилка читання — вікно
        result = self.result()
        result["unmapped"] = ["10-Б ГО"]
        with mock.patch.object(gui.messagebox, "showinfo", side_effect=AssertionError("вікно!")):
            self.app._sync_done(result, True, True)
        self.assertIn("не зіставлено курсів: 1", self.toasts[-1])

    def test_not_connected_opens_the_step_by_step_wizard(self):
        with mock.patch.object(google_client, "token_ready", return_value=False), \
                mock.patch("classroom_assistant.google_setup_ui.show_google_wizard") as wizard:
            self.app.connect_google()
        wizard.assert_called_once_with(self.app)
