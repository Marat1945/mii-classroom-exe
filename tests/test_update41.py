"""4.1: КТП підв'язується до класів із Classroom; потоки, яких ще немає, створюються самі."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from test_update36 import TkCase
from test_update38 import make_ktp

from classroom_assistant import data_tools, editor_ui, samples_ui

SOURCES = Path(__file__).resolve().parents[1] / "КТП джерела"
CLASSROOM = ["5-Г історія", "8-Б ІУ", "8-Б ВI", "8-Б ГО", "8-В ІУ", "8-В ВІ", "8-В ГО", "8-Г ІУ", "8-Г ВІ", "8-Г ГО",
             "9-Б ІУ", "9-Б ВІ", "9-Б Право + ГО", "9-Г ІУ", "9-Г ВІ", "9-Г Право + ГО", "10 ІУ профіль", "10-Б ВІ",
             "10-Б ГО", "11 ІУ Профіль", "11 ІУ Стандарт", "11-А ВІ", "11-В ВІ", "11 класи СІМЕЙНЕ НАВЧАННЯ"]


class ClassroomDrivenImportTests(TkCase):
    def editor(self, courses=CLASSROOM, streams=()):
        config = data_tools.blank_config()
        plans = {}
        for stream in streams:
            plans[stream] = {"filename": "Очікує файл КТП", "lessons": [], "needs_review": True}
            config["course_map"][stream] = {"plan": stream, "course_title": stream}
        self.root.state = {"classroom_order": list(courses)}
        self.root.google_courses = [{"name": n, "id": str(i)} for i, n in enumerate(courses)]
        self.root.update_day = lambda: None
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

    def no_questions(self, editor):
        return (mock.patch.object(editor_ui.messagebox, "askyesno", side_effect=AssertionError("запитання!")),
                mock.patch.object(editor_ui.messagebox, "askyesnocancel", side_effect=AssertionError("запитання!")),
                mock.patch.object(editor, "_ask_choice", side_effect=AssertionError("вибір!")))

    @unittest.skipUnless(SOURCES.is_dir() and len(list(SOURCES.glob("*.docx"))) >= 15, "немає реальних КТП")
    def test_program_knows_only_classroom_yet_every_ktp_lands_on_its_classes(self):
        editor = self.editor()                                      # жодного потоку, розкладу ще немає
        self.assertEqual(editor.cfg["course_map"], {})
        files = sorted(SOURCES.glob("*.docx"))
        shown = []
        a, b, c = self.no_questions(editor)
        with a, b, c, mock.patch.object(editor_ui.messagebox, "showinfo", side_effect=lambda *x, **k: shown.append(x[1])), \
                mock.patch.object(editor_ui.messagebox, "showwarning", side_effect=lambda *x, **k: shown.append(x[1])):
            editor.import_files(files)
        self.assertIn(f"Імпортовано: {len(files)} з {len(files)}.", shown[0])
        cmap = editor.cfg["course_map"]
        # потоки створено з канонічними назвами, але прив'язано до ТОЧНИХ назв курсів Classroom
        self.assertEqual(cmap["8-Б ВІ"]["course_title"], "8-Б ВI")                  # латинська I з Classroom
        self.assertEqual(cmap["9-Б Право"]["course_title"], "9-Б Право + ГО")
        self.assertEqual(cmap["9-Б ГО"]["course_title"], "9-Б Право + ГО")
        self.assertEqual(cmap["11 ІУ профіль"]["course_title"], "11 ІУ Профіль")
        self.assertEqual(cmap["11 ІУ стандарт"]["course_title"], "11 ІУ Стандарт")
        self.assertIn("5-Г історія", cmap)
        # кожен із 23 класів Classroom має КТП (клас «Сімейне навчання» — не предмет, лишається порожнім)
        for entry in editor.list_entries:
            if entry["course"] and "СІМЕЙНЕ" not in entry["course"]:
                self.assertTrue(entry["filled"], entry["course"])
                self.assertNotIn("без КТП", entry["label"], entry["label"])
        same = lambda x, y: cmap[x]["plan"] == cmap[y]["plan"]
        self.assertTrue(same("8-Б ІУ", "8-В ІУ") and same("8-Б ІУ", "8-Г ІУ"))
        self.assertTrue(same("9-Б ВІ", "9-Г ВІ") and same("11-А ВІ", "11-В ВІ"))
        self.assertFalse(same("9-Б ІУ", "9-Г ІУ"))
        self.assertFalse(same("9-Б Право", "9-Б ГО"))                               # два предмети — два КТП
        self.assertIn("ІУ_9-Б", editor.plans[cmap["9-Б ІУ"]["plan"]]["filename"])

    def test_schedule_loaded_afterwards_attaches_to_the_streams_that_ktp_created(self):
        editor = self.editor()
        with tempfile.TemporaryDirectory() as folder:
            ktp = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б", "8-В", "8-Г"])
            editor.import_files([ktp])
            before = {s: i["plan"] for s, i in editor.cfg["course_map"].items()}
            schedule = Path(folder) / "n.docx"
            samples_ui.build_sample_workload(schedule)
            a, b, c = self.no_questions(editor)
            with a, b, c, mock.patch.object(editor_ui.messagebox, "showinfo"):
                self.assertTrue(editor.import_schedule(path=schedule, quiet=True))
        for stream, plan in before.items():                                       # КТП не загубились і не задубльовані
            self.assertEqual(editor.cfg["course_map"][stream]["plan"], plan)
            self.assertEqual(len(editor.plans[plan]["lessons"]), 5)
        self.assertEqual(sum(1 for s in editor.cfg["course_map"] if s.startswith("8-Б ІУ")), 1)
        self.assertEqual(editor.cfg["days"]["0"][0], ["8-Б ІУ", "8-Б ГО"])

    def test_another_subject_of_the_same_class_is_never_mistaken_for_the_only_stream(self):
        from classroom_assistant.schedule_io import resolve_stream
        self.assertTrue(resolve_stream("8-Б ГО", ["8-Б ІУ"]).startswith("? "))          # було: «8-Б ІУ»
        self.assertTrue(resolve_stream("8-Б ВІ", ["8-Б ІУ", "8-Б ГО"]).startswith("? "))
        self.assertEqual(resolve_stream("5-Г ІУ", ["5-Г історія"]), "5-Г історія")        # той самий предмет
        self.assertEqual(resolve_stream("9-Б Право", ["9-Б Право + ГО"]), "9-Б Право + ГО")

    def test_missing_parallels_are_created_for_a_class_that_already_has_a_stream(self):
        editor = self.editor(streams=["8-Б ІУ"])
        with tempfile.TemporaryDirectory() as folder:
            ktp = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б", "8-В", "8-Г"])
            editor.import_files([ktp])
        cmap = editor.cfg["course_map"]
        self.assertEqual(sorted(s for s in cmap if s.endswith("ІУ")), ["8-Б ІУ", "8-В ІУ", "8-Г ІУ"])
        self.assertTrue(cmap["8-Б ІУ"]["plan"] == cmap["8-В ІУ"]["plan"] == cmap["8-Г ІУ"]["plan"])

    def test_combined_course_gets_only_the_subject_of_the_file(self):
        editor = self.editor(courses=["9-Б Право + ГО"])
        with tempfile.TemporaryDirectory() as folder:
            law = make_ktp(Path(folder) / "Календарне_Правознавство_9.docx", "Правознавство, 9 клас", ["9-Б"])
            editor.import_files([law])
            self.assertEqual(sorted(editor.cfg["course_map"]), ["9-Б Право"])
            civics = make_ktp(Path(folder) / "Календарне_ГО_9.docx", "Громадянська освіта, 9 клас", ["9-Б"])
            editor.import_files([civics])
        self.assertEqual(sorted(editor.cfg["course_map"]), ["9-Б ГО", "9-Б Право"])
        self.assertEqual({i["course_title"] for i in editor.cfg["course_map"].values()}, {"9-Б Право + ГО"})

    def test_profile_or_standard_is_not_guessed_but_named_files_are_clear(self):
        editor = self.editor(courses=["11 ІУ Профіль", "11 ІУ Стандарт"])
        shown = []
        with tempfile.TemporaryDirectory() as folder:
            vague = make_ktp(Path(folder) / "Історія України 11 клас.docx", "Історія України, 11 клас", [])
            clear = make_ktp(Path(folder) / "Історія України 11 клас 1,5 год.docx", "Історія України, 11 клас", [])
            with mock.patch.object(editor_ui.messagebox, "showwarning", side_effect=lambda *x, **k: shown.append(x[1])):
                editor.import_files([vague, clear])
        self.assertIn("✓ Історія України 11 клас 1,5 год.docx → 11 ІУ стандарт", shown[0])
        self.assertIn("✗ Історія України 11 клас.docx", shown[0])
        self.assertEqual(sorted(editor.cfg["course_map"]), ["11 ІУ стандарт"])

    def test_without_classroom_and_schedule_the_message_says_what_to_do(self):
        editor = self.editor(courses=[])
        shown = []
        with tempfile.TemporaryDirectory() as folder:
            ktp = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б"])
            with mock.patch.object(editor_ui.messagebox, "showwarning", side_effect=lambda *x, **k: shown.append(x[1])):
                editor.import_files([ktp])
        self.assertIn("підключіть Google", shown[0])

    def test_class_not_in_classroom_is_reported_with_the_reason(self):
        editor = self.editor(courses=["8-Б ІУ", "10 ІУ профіль"])
        shown = []
        with tempfile.TemporaryDirectory() as folder:
            ktp = make_ktp(Path(folder) / "Календарне_7_клас_ІУ.docx", "Історія України, 7 клас", ["7-А"])
            ok = make_ktp(Path(folder) / "Календарне_8_клас_ІУ.docx", "Історія України, 8 клас", ["8-Б"])
            with mock.patch.object(editor_ui.messagebox, "showwarning", side_effect=lambda *x, **k: shown.append(x[1])):
                editor.import_files([ktp, ok])
        self.assertIn("у Classroom і в програмі немає відповідного класу", shown[0])
        self.assertIn("7 клас", shown[0])


if __name__ == "__main__":
    unittest.main()
