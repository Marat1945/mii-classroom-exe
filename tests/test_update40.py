"""4.0: збереження з порожніми КТП (справжній запис), імпорт багатьох файлів без запитань, drop у будь-яке місце."""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from docx import Document

from test_update36 import TkCase
from test_update38 import config_with, make_ktp

from classroom_assistant import data_tools, editor_core, editor_ui, engine, ktp_import, samples_ui

SOURCES = Path(__file__).resolve().parents[1] / "КТП джерела"
ALL_STREAMS = ["5-Г ІУ", "8-Б ІУ", "8-В ІУ", "8-Г ІУ", "8-Б ВІ", "8-В ВІ", "8-Г ВІ", "8-Б ГО", "8-В ГО", "8-Г ГО",
               "9-Б ІУ", "9-Г ІУ", "9-Б ВІ", "9-Г ВІ", "9-Б Право", "9-Г Право", "9-Б ГО", "9-Г ГО",
               "10 ІУ профіль", "10-Б ВІ", "10-Б ГО", "11 ІУ профіль", "11 ІУ стандарт", "11-А ВІ", "11-В ВІ"]


class SaveWithEmptyKtpTests(TkCase):
    """БЕЗ підміни persist: перевіряємо справжній запис на диск (раніше помилка лишалась)."""

    def prepare(self, folder):
        root = Path(folder)
        (root / "data").mkdir()
        config, plans = config_with(["8-Б ІУ", "9-Б Право"])
        config["days"]["0"][0] = ["8-Б ІУ", "9-Б Право"]
        for name, data in (("Налаштування.json", config), ("Календарні плани.json", plans)):
            (root / "data" / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root, config, plans

    def test_persist_writes_files_when_plans_are_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config, plans = self.prepare(folder)
            with mock.patch.object(engine, "DATA", root / "data"), \
                    mock.patch.object(editor_core, "DATA", root / "data"), \
                    mock.patch.object(editor_core, "ROOT", root):
                self.assertTrue(any(e.startswith("Порожній КТП") for e in editor_core.validate_working(config, plans)))
                editor_core.persist(config, plans, {}, "тест")
            saved = json.loads((root / "data" / "Календарні плани.json").read_text("utf-8"))
            self.assertEqual(set(saved), {"8-Б ІУ", "9-Б Право"})

    def test_real_errors_still_block_saving(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config, plans = self.prepare(folder)
            config["year_end"] = "2020-01-01"                       # кінець раніше початку
            with mock.patch.object(engine, "DATA", root / "data"), \
                    mock.patch.object(editor_core, "DATA", root / "data"), \
                    mock.patch.object(editor_core, "ROOT", root):
                with self.assertRaises(ValueError):
                    editor_core.persist(config, plans, {}, "тест")

    def test_editor_save_button_works_end_to_end_with_empty_ktp(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config, plans = self.prepare(folder)
            self.root.state, self.root.google_courses, self.root.update_day = {}, [], lambda: None
            self.root.cfg = config
            shown = []
            with mock.patch.object(engine, "DATA", root / "data"), \
                    mock.patch.object(editor_core, "DATA", root / "data"), \
                    mock.patch.object(editor_core, "ROOT", root), \
                    mock.patch.object(editor_ui.messagebox, "showerror",
                                      side_effect=lambda *a, **k: shown.append(a)), \
                    mock.patch.object(editor_ui, "deep_copy_data",
                                      return_value=(json.loads(json.dumps(config)), json.loads(json.dumps(plans)))):
                editor = editor_ui.SchoolEditor(self.root, lambda: None)
                try:
                    editor.cfg["holidays"].append({"start": "2026-10-26", "end": "2026-11-01"})   # є що зберігати
                    self.assertTrue(editor.save(confirm=False))
                finally:
                    editor.destroy()
            self.assertEqual(shown, [])
            saved = json.loads((root / "data" / "Налаштування.json").read_text("utf-8"))
            self.assertEqual(saved["holidays"], [{"start": "2026-10-26", "end": "2026-11-01"}])


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            schedule = folder / "щось.docx"
            samples_ui.build_sample_workload(schedule)
            ktp = samples_ui.build_sample_ktp(folder / "x.docx")
            self.assertEqual(ktp_import.classify_file(schedule), "schedule")            # за змістом, а не назвою
            self.assertEqual(ktp_import.classify_file(ktp), "ktp")
            self.assertEqual(ktp_import.classify_file(folder / "Навантаження_2026-2027.jpg"), "image")
            self.assertEqual(ktp_import.classify_file(folder / "нотатки.txt"), "unsupported")
            self.assertEqual(ktp_import.classify_file(folder / "Навантаження 2026.doc"), "schedule")
            self.assertEqual(ktp_import.classify_file(folder / "Календарне планування 9 клас.doc"), "ktp")


class BulkImportTests(TkCase):
    def editor(self, config, plans):
        self.root.state, self.root.google_courses, self.root.update_day = {}, [], lambda: None
        with mock.patch.object(editor_ui, "deep_copy_data", return_value=(config, plans)):
            editor = editor_ui.SchoolEditor(self.root, lambda: None)
        editor.deiconify()
        editor.update()

        def close():
            try:
                editor.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        return editor

    @unittest.skipUnless(SOURCES.is_dir() and len(list(SOURCES.glob("*.docx"))) >= 15, "немає реальних КТП")
    def test_all_real_files_at_once_without_a_single_question(self):
        config, plans = config_with(ALL_STREAMS)
        editor = self.editor(config, plans)
        files = sorted(SOURCES.glob("*.docx"))
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "Навантаження_2026-2027.jpg"
            image.write_bytes(b"\xff\xd8\xff")
            note = Path(folder) / "нотатки.txt"
            note.write_text("x", encoding="utf-8")
            summaries = []
            with mock.patch.object(editor_ui.messagebox, "askyesno", side_effect=AssertionError("запитання!")), \
                    mock.patch.object(editor_ui.messagebox, "askyesnocancel", side_effect=AssertionError("запитання!")), \
                    mock.patch.object(editor, "_ask_choice", side_effect=AssertionError("вибір!")), \
                    mock.patch.object(editor_ui.messagebox, "showwarning",
                                      side_effect=lambda *a, **k: summaries.append(a[1])), \
                    mock.patch.object(editor_ui.messagebox, "showinfo",
                                      side_effect=lambda *a, **k: summaries.append(a[1])):
                editor.import_files(files + [image, note])
        self.assertEqual(len(summaries), 1)                                    # один підсумок, жодних питань
        self.assertIn(f"Імпортовано: {len(files)} з {len(files) + 2}.", summaries[0])
        self.assertIn("Навантаження_2026-2027.jpg — зображення", summaries[0])
        self.assertIn("нотатки.txt — формат не підтримується", summaries[0])
        cmap = editor.cfg["course_map"]
        empty = [s for s in cmap if not editor.plans[cmap[s]["plan"]]["lessons"]]
        self.assertEqual(empty, [])                                            # усі 25 потоків мають КТП
        same = lambda a, b: cmap[a]["plan"] == cmap[b]["plan"]
        self.assertTrue(same("9-Б ВІ", "9-Г ВІ") and same("8-Б ІУ", "8-Г ІУ") and same("11-А ВІ", "11-В ВІ"))
        self.assertFalse(same("9-Б ІУ", "9-Г ІУ"))
        self.assertIn("ІУ_9-Б", editor.plans[cmap["9-Б ІУ"]["plan"]]["filename"])
        self.assertIn("ВІ_9-Б", editor.plans[cmap["9-Б ВІ"]["plan"]]["filename"])
        editor.undo()                                                           # одним кроком — назад
        self.assertTrue(all(not editor.plans[cmap[s]["plan"]]["lessons"] for s in editor.cfg["course_map"]))

    def test_unreadable_single_file_falls_back_to_the_column_preview(self):
        config, plans = config_with(["8-Б ІУ"])
        editor = self.editor(config, plans)
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "Календарне_8_клас_ІУ.docx"
            Document().save(str(broken))                                       # документ без таблиці
            with mock.patch.object(editor_ui, "ImportPreview") as preview:
                editor.import_files([broken])
        preview.assert_called_once()

    def test_single_file_gives_a_note_without_any_window(self):
        config, plans = config_with(["8-Б ІУ", "8-В ІУ"])
        editor = self.editor(config, plans)
        with tempfile.TemporaryDirectory() as folder:
            ktp = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б", "8-В"])
            with mock.patch.object(editor_ui.messagebox, "showinfo", side_effect=AssertionError("вікно!")), \
                    mock.patch.object(editor_ui.messagebox, "askyesno", side_effect=AssertionError("запитання!")):
                editor.import_files([ktp])
        self.assertTrue(editor.history_note.cget("text").startswith("✓ Календарне_8_клас_ІУ.docx → 8-Б ІУ, 8-В ІУ"))

    def test_file_with_no_clear_class_is_reported_not_guessed_in_bulk(self):
        config, plans = config_with(["8-Б ІУ", "9-Б ІУ"])
        editor = self.editor(config, plans)
        with tempfile.TemporaryDirectory() as folder:
            vague = make_ktp(Path(folder) / "план.docx", "Календарний план", [])
            good = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б"])
            shown = []
            with mock.patch.object(editor_ui.messagebox, "showwarning", side_effect=lambda *a, **k: shown.append(a[1])):
                editor.import_files([vague, good])
        self.assertIn("✗ план.docx — не вдалося визначити клас і предмет", shown[0])
        self.assertIn("✓ Календарне_8_клас_ІУ.docx → 8-Б ІУ", shown[0])

    def test_file_dialog_accepts_many_files(self):
        config, plans = config_with(["8-Б ІУ"])
        editor = self.editor(config, plans)
        with mock.patch.object(editor_ui.filedialog, "askopenfilenames", return_value=("/a/1.docx", "/a/2.docx")), \
                mock.patch.object(editor, "import_files") as importer:
            editor.import_plan()
        self.assertEqual(importer.call_args.args[0], [Path("/a/1.docx"), Path("/a/2.docx")])

    def test_schedule_dropped_with_ktp_is_recognised_and_loaded_quietly(self):
        editor = self.editor(*(data_tools.blank_config(), {}))
        with tempfile.TemporaryDirectory() as folder:
            schedule = Path(folder) / "щось.docx"
            samples_ui.build_sample_workload(schedule)
            ktp = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б", "8-В"])
            summaries = []
            with mock.patch.object(editor_ui.messagebox, "askyesno", side_effect=AssertionError("запитання!")), \
                    mock.patch.object(editor_ui, "show_toast",
                                      side_effect=lambda parent, text, *a, **k: summaries.append(text)):
                editor.import_files([ktp, schedule])                           # розклад обробляється першим
        self.assertIn("8-Б ІУ", editor.cfg["course_map"])
        self.assertEqual(len(editor.cfg["holidays"]), 3)                       # канікули взято з першого рядка
        cmap = editor.cfg["course_map"]
        self.assertEqual(len(editor.plans[cmap["8-Б ІУ"]["plan"]]["lessons"]), 5)
        self.assertEqual(cmap["8-Б ІУ"]["plan"], cmap["8-В ІУ"]["plan"])
        self.assertIn("Імпортовано: 2 з 2", summaries[0])


class WindowWideDropTests(TkCase):
    def editor(self):
        config, plans = config_with(["8-Б ІУ"])
        self.root.state, self.root.google_courses, self.root.update_day = {}, [], lambda: None
        with mock.patch.object(editor_ui, "deep_copy_data", return_value=(config, plans)):
            editor = editor_ui.SchoolEditor(self.root, lambda: None)
        editor.deiconify()
        editor.update()
        def close():
            try:
                editor.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        return editor

    def test_every_part_of_the_window_accepts_files_and_shows_a_hint(self):
        editor = self.editor()
        for widget in (editor, editor.notebook, editor.tab_year, editor.tab_streams, editor.history_note,
                       editor.undo_button):
            registered = editor.tk.call("bind", str(widget), "<<DropTargetTypes>>")
            self.assertTrue(registered, widget)                                 # drop дозволено скрізь
        editor._highlight_ktp_drop(None, "window")
        editor.update()
        self.assertEqual(editor.drop_hint.winfo_manager(), "place")
        editor._clear_ktp_drop()
        self.assertEqual(editor.drop_hint.winfo_manager(), "")

    def test_drop_anywhere_hands_all_files_to_the_importer(self):
        editor = self.editor()
        event = type("E", (), {"data": "{/tmp/Календарне планування 9 клас.docx} /tmp/b.docx"})()
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "Календарне планування 9 клас.docx"
            second = Path(folder) / "b.docx"
            first.write_text("x")
            second.write_text("x")
            event.data = "{" + str(first) + "} " + str(second)
            with mock.patch.object(editor, "import_files") as importer:
                editor._drop_ktp_file(event, "window")
        self.assertEqual(importer.call_args.args[0], [first, second])
        self.assertIsNone(importer.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
