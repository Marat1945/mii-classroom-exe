"""3.6: автовставка в ChatGPT, галочки на день, Enter, меню, порожня програма."""
import tempfile
import time
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    from tkinterdnd2 import TkinterDnD
    BaseRoot = TkinterDnD.Tk
except ImportError:                                     # pragma: no cover
    BaseRoot = tk.Tk

from classroom_assistant import autopaste, chatgpt_ui, data_tools, editor_ui, gui, samples_ui
from classroom_assistant.chatgpt_bridge import build_prompt
from classroom_assistant.editor_core import validate_working
from classroom_assistant.engine import build_calendar, day_lessons, read_json


class FakeBackend:
    available = True

    def __init__(self, front=(111, "chrome.exe"), own=999):
        self.front, self.own, self.calls = front, own, []

    def own_pid(self):
        return self.own

    def foreground(self):
        return self.front

    def paste(self, send_enter=False):
        self.calls.append(("paste", send_enter))


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


class TkCase(unittest.TestCase):
    NEEDS_ROOT = True

    def setUp(self):
        self.root = None
        try:
            if self.NEEDS_ROOT:
                self.root = BaseRoot()
                self.root.withdraw()
            else:
                probe = BaseRoot()
                probe.destroy()
        except tk.TclError:
            self.skipTest("немає дисплея")
        for name, value in (("showinfo", None), ("showwarning", None), ("showerror", None),
                            ("askyesno", True), ("askyesnocancel", False)):
            for module in (editor_ui, chatgpt_ui, gui, samples_ui):
                patcher = mock.patch.object(module.messagebox, name, return_value=value)
                patcher.start()
                self.addCleanup(patcher.stop)

    def tearDown(self):
        if self.root is not None:
            self.root.destroy()


class AutoPasteTests(TkCase):
    def run_auto(self, backend, send_enter=False, delay=1, extra=2):
        messages, recopies = [], []
        task = autopaste.AutoPaste(self.root, backend, lambda: recopies.append(1), messages.append,
                                   delay=delay, send_enter=send_enter, extra_wait=extra).start()
        pump(self.root, delay + extra + 1.6)
        return task, messages, recopies

    def test_pastes_only_into_a_browser(self):
        backend = FakeBackend()
        _task, messages, recopies = self.run_auto(backend)
        self.assertEqual(backend.calls, [("paste", False)])
        self.assertEqual(len(recopies), 1)
        self.assertIn("натисніть Enter", messages[-1])

    def test_enter_only_when_the_teacher_asked(self):
        backend = FakeBackend()
        self.run_auto(backend, send_enter=True)
        self.assertEqual(backend.calls, [("paste", True)])

    def test_never_pastes_into_our_own_window_or_other_programs(self):
        for front in ((999, "python.exe"), (555, "winword.exe"), (0, "")):
            backend = FakeBackend(front=front)
            _task, messages, _ = self.run_auto(backend, extra=1)
            self.assertEqual(backend.calls, [], front)
            self.assertIn("Ctrl+V", messages[-1])

    def test_waits_for_the_browser_to_come_forward(self):
        backend = FakeBackend(front=(999, "python.exe"))
        messages = []
        autopaste.AutoPaste(self.root, backend, lambda: None, messages.append, delay=1, extra_wait=4).start()
        pump(self.root, 1.4)
        backend.front = (111, "msedge.exe")
        pump(self.root, 2.5)
        self.assertEqual(backend.calls, [("paste", False)])

    def test_closing_the_window_cancels(self):
        backend = FakeBackend()
        task = autopaste.AutoPaste(self.root, backend, lambda: None, lambda t: None, delay=2).start()
        task.finished = True
        pump(self.root, 3.2)
        self.assertEqual(backend.calls, [])

    def test_disabled_or_unavailable(self):
        said = []
        backend = FakeBackend()
        self.assertIsNone(autopaste.start_autopaste(self.root, {"autopaste": False}, lambda: None,
                                                    said.append, backend))
        backend.available = False
        self.assertIsNone(autopaste.start_autopaste(self.root, {}, lambda: None, said.append, backend))
        self.assertIn("лише у Windows", said[-1])


class DayDialogTests(TkCase):
    def make(self):
        lessons = day_lessons("2026-10-01", read_json("Налаштування.json"))[:3]
        self.root.state = {}
        self.root._parallel = lambda lesson: [lesson, lesson]
        return lessons, chatgpt_ui.ChatGPTDayDialog(self.root, lessons)

    def test_all_checked_then_one_removed_from_the_request(self):
        lessons, dialog = self.make()
        text = dialog.prompt.get("1.0", "end")
        for lesson in lessons:
            self.assertIn(lesson.topic, text)
        dialog._toggle(1)
        text = dialog.prompt.get("1.0", "end")
        self.assertNotIn(lessons[1].topic, text)
        self.assertIn(lessons[0].topic, text)
        self.assertIn("ЗАВДАННЯ 2 з 2", text)
        self.assertIn("Вибрано для лекції: 2 з 3", dialog.counter.cget("text"))
        self.assertEqual(dialog.table.item("1", "values")[0], "☐")
        dialog.destroy()

    def test_click_on_the_checkbox_column_toggles(self):
        _lessons, dialog = self.make()
        dialog.tk.call("wm", "transient", dialog._w, "")      # батько прихований — показуємо вікно самі
        dialog.deiconify()
        dialog.update()
        x, y, w, h = dialog.table.bbox("0", "#1")
        dialog.table.event_generate("<Button-1>", x=x + 5, y=y + 5)
        dialog.update()
        self.assertNotIn(0, dialog.checked)
        dialog.table.selection_set("2")
        dialog._space()
        self.assertNotIn(2, dialog.checked)
        dialog._set_all(False)
        self.assertIn("Не вибрано жодного класу", dialog.prompt.get("1.0", "end"))
        dialog._set_all(True)
        self.assertEqual(len(dialog.checked), 3)
        dialog.destroy()

    def test_nothing_checked_blocks_opening_chatgpt(self):
        _lessons, dialog = self.make()
        dialog._set_all(False)
        with mock.patch.object(chatgpt_ui.webbrowser, "open") as opener:
            dialog.open_chatgpt()
        opener.assert_not_called()
        dialog.destroy()

    def test_open_chatgpt_copies_and_starts_autopaste(self):
        _lessons, dialog = self.make()
        with mock.patch.object(chatgpt_ui.webbrowser, "open") as opener, \
                mock.patch.object(chatgpt_ui.autopaste, "start_autopaste") as starter:
            dialog.open_chatgpt()
        opener.assert_called_once()
        starter.assert_called_once()
        self.assertIn("ЗАПИТ ПОМІЧНИКА УЧИТЕЛЯ", dialog.clipboard_get())
        dialog.destroy()


class MainWindowTests(TkCase):
    NEEDS_ROOT = False

    def make(self):
        app = gui.MainApp()
        def close_app():
            try:
                app.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close_app)
        pump(app, 0.3)
        return app

    def test_enter_on_the_selected_row_creates_a_draft(self):
        app = self.make()
        app.datevar.set("01.10.2026")
        app.update_day()
        self.assertTrue(app.rows)
        app.grid.selection_set("0")
        app.grid.focus_force()
        app.update()
        with mock.patch.object(app, "draft") as draft:
            app.grid.event_generate("<Return>")
            app.update()
        draft.assert_called_once()

    def test_context_menu_on_rows_header_and_empty_space(self):
        app = self.make()
        app.datevar.set("01.10.2026")
        app.update_day()
        app.update()
        popped = []
        with mock.patch.object(tk.Menu, "tk_popup", lambda menu, x, y, entry="": popped.append(menu)):
            row = app.grid.get_children()[0]
            bx, by, bw, bh = app.grid.bbox(row)
            for x, y in ((bx + 30, by + 5), (200, app.grid.winfo_height() - 20), (100, 8)):
                before = len(popped)
                app.grid.event_generate("<Button-3>", x=x, y=y)
                app.update()
                self.assertEqual(len(popped), before + 1, (x, y))

    def test_description_starts_from_the_top(self):
        app = self.make()
        app.datevar.set("01.10.2026")
        app.update_day()
        self.assertEqual(app.desc.yview()[0], 0.0)


class BlankProgramTests(TkCase):
    def test_blank_config_is_valid_and_empty(self):
        config = data_tools.blank_config()
        self.assertEqual(validate_working(config, {}), [])
        self.assertEqual(build_calendar(config, {}), [])           # {} не означає «читати з диска»
        self.assertEqual(config["course_map"], {})
        self.assertEqual(len(config["period_times"]), 8)

    def test_reset_backs_up_first_and_restore_returns_everything(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "root"
            for relative, text in (("data/Налаштування.json", '{"ai_model": "x", "year_start": "2026-09-01"}'),
                                   ("data/Календарні плани.json", '{"p": {"lessons": []}}'),
                                   ("data/Стан.json", '{"drafts": {"a": 1}}'),
                                   ("data/google_token.json", "SECRET"),
                                   ("Готові Word/2026-10-01/a.docx", "word"),
                                   ("Вкладення Classroom/x/img.png", "img")):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            backup = Path(folder) / "before.zip"
            data_tools.reset_to_blank(backup, root)
            with zipfile.ZipFile(backup) as z:
                names = set(z.namelist())
            self.assertIn("Готові Word/2026-10-01/a.docx", names)
            self.assertNotIn("data/google_token.json", names)
            self.assertFalse((root / "Готові Word").exists())
            self.assertFalse((root / "data/Стан.json").exists())
            self.assertTrue((root / "data/google_token.json").exists())          # вхід у Google лишається
            self.assertEqual((root / "data/Календарні плани.json").read_text("utf-8").strip(), "{}")
            self.assertEqual(data_tools.json.loads((root / "data/Налаштування.json").read_text("utf-8"))["ai_model"], "x")
            safety = Path(folder) / "safety.zip"
            count = data_tools.restore_from_zip(backup, safety, root)
            self.assertGreaterEqual(count, 4)
            self.assertEqual((root / "Готові Word/2026-10-01/a.docx").read_text("utf-8"), "word")
            self.assertIn('"drafts"', (root / "data/Стан.json").read_text("utf-8"))
            self.assertTrue(safety.exists())

    def test_restore_rejects_foreign_zip_and_path_tricks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "root"
            (root / "data").mkdir(parents=True)
            bad = Path(folder) / "bad.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("hello.txt", "x")
            with self.assertRaises(ValueError):
                data_tools.restore_from_zip(bad, Path(folder) / "s.zip", root)
            tricky = Path(folder) / "tricky.zip"
            with zipfile.ZipFile(tricky, "w") as z:
                z.writestr("data/Налаштування.json", "{}")
                z.writestr("data/Календарні плани.json", "{}")
                z.writestr("../evil.txt", "boom")
                z.writestr("data/google_token.json", "secret")
            data_tools.restore_from_zip(tricky, Path(folder) / "s2.zip", root)
            self.assertFalse((Path(folder) / "evil.txt").exists())
            self.assertFalse((root / "data/google_token.json").exists())

    def test_full_self_loading_flow_in_the_editor(self):
        """Порожня програма → розклад-навантаження → КТП на клас → паралелі → календар."""
        blank = data_tools.blank_config()
        self.root.state = {}
        self.root.google_courses = []
        self.root.update_day = lambda: None
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(editor_ui, "deep_copy_data", return_value=(blank, {})):
            workload = Path(folder) / "n.docx"
            samples_ui.build_sample_workload(workload)
            ktp = Path(folder) / "ktp.docx"
            samples_ui.build_sample_ktp(ktp)
            editor = editor_ui.SchoolEditor(self.root, lambda: None)
            def close_editor():
                try:
                    editor.destroy()
                except tk.TclError:
                    pass
            self.addCleanup(close_editor)
            self.assertEqual(editor.list_entries, [])
            self.assertIn("порожній", editor.plan_name.cget("text"))
            editor.import_schedule(path=workload)
            streams = set(editor.cfg["course_map"])
            self.assertIn("8-Б ІУ", streams)
            self.assertIn("8-Б ГО", streams)
            self.assertIn("11 ІУ профіль", streams)
            self.assertEqual([e["course"] for e in editor.list_entries[:1]], [sorted(streams)[0]])
            index = next(i for i, e in enumerate(editor.list_entries) if e["course"] == "8-Б ІУ")
            editor.planlist.selection_clear(0, "end")
            editor.planlist.selection_set(index)
            editor.plan_selected()
            self.assertIn("КТП ще не підключено", editor.plan_name.cget("text"))
            editor.import_plan(path=ktp)
            preview = next(w for w in editor.winfo_children() if isinstance(w, editor_ui.ImportPreview))
            preview.commit()
            plan = editor.cfg["course_map"]["8-Б ІУ"]["plan"]
            self.assertEqual(len(editor.plans[plan]["lessons"]), 5)
            # паралельні 8-В ІУ (та сама тема й клас) отримали той самий КТП, зайві порожні плани зникли
            self.assertEqual(editor.cfg["course_map"]["8-В ІУ"]["plan"], plan)
            self.assertEqual(editor.cfg["course_map"]["8-Б ГО"]["plan"] == plan, False)
            self.assertTrue(editor._is_dirty())
            problems = [p for p in validate_working(editor.cfg, editor.plans)
                        if not p.startswith("Порожній КТП")]
            self.assertEqual(problems, [])
            calendar = build_calendar(editor.cfg, editor.plans)
            mine = [x for x in calendar if x.stream == "8-В ІУ"]
            self.assertTrue(mine)
            self.assertEqual(mine[0].topic, "Перша тема уроку, записана повністю")


class WrongClassGuardTests(TkCase):
    def test_file_for_9g_is_not_silently_added_to_9b(self):
        blank = data_tools.blank_config()
        blank["course_map"] = {"9-Б ІУ": {"plan": "9-Б ІУ", "course_title": "9-Б ІУ"}}
        plans = {"9-Б ІУ": {"filename": "Очікує файл КТП", "lessons": [], "needs_review": True}}
        self.root.state = {}
        self.root.google_courses = []
        self.root.update_day = lambda: None
        source = next(Path(__file__).resolve().parents[1].joinpath("КТП джерела").glob("*9-Г_2026*"))
        with mock.patch.object(editor_ui, "deep_copy_data", return_value=(blank, plans)):
            editor = editor_ui.SchoolEditor(self.root, lambda: None)
        try:
            editor.planlist.selection_set(0)
            editor.plan_selected()
            asked = []
            def refuse(title, text, **kw):
                asked.append(title)
                return title != "Перевірте клас"
            with mock.patch.object(editor_ui.messagebox, "askyesno", refuse):
                editor.import_plan(path=source)
                preview = next(w for w in editor.winfo_children() if isinstance(w, editor_ui.ImportPreview))
                preview.commit()
            self.assertIn("Перевірте клас", asked)
            self.assertEqual(editor.plans["9-Б ІУ"]["lessons"], [])
        finally:
            editor.destroy()


class PromptTests(unittest.TestCase):
    def test_prompt_forbids_text_as_picture_and_questions(self):
        lesson = day_lessons("2026-10-01", read_json("Налаштування.json"))[0]
        prompt = build_prompt(lesson)
        self.assertIn("НЕ картинкою", prompt)
        self.assertIn("НЕ став мені жодних уточнювальних запитань", prompt)
        self.assertIn("рівно два файли", prompt)


if __name__ == "__main__":
    unittest.main()
