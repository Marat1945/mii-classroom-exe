"""5.0: жива інфографіка (композиція за темою, деталі лекції), автоприйом файлів у папку програми."""
import json
import tempfile
import time
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from docx import Document

from test_update44 import TempProgram
from test_update36 import TkCase

from classroom_assistant import browser_downloads as bd
from classroom_assistant import chatgpt_ui, download_setup_ui, engine, gui, lecture_inbox
from classroom_assistant.chatgpt_bridge import (PALETTES, build_prompt, choose_composition, palette_for)


def lesson_with(topic, stream="10-Б ВІ", key=None):
    base = engine.day_lessons("2026-10-01", engine.read_json("Налаштування.json"))[0]
    return replace(base, topic=topic, stream=stream)


class LivelyInfographicTests(unittest.TestCase):
    def test_the_prompt_demands_a_living_illustrated_picture_built_from_the_lecture(self):
        text = build_prompt(lesson_with("Консульство та Імперія у Франції. Наполеон Бонапарт."))
        for needle in ("ЖИВА ІЛЮСТРОВАНА інфографіка, а не таблиця й не сітка", "випиши з неї 8–10 конкретних фактів",
                       "«зліпком» цієї лекції", "ВЕЛИКА центральна ілюстрація конкретної сцени з лекції",
                       "3–5 менших малюнків із підписами", "СТРІЛКИ ТА ЗВ'ЯЗКИ", "«тому що», «призвело до»",
                       "ЗАБОРОНЕНО: сітка однакових прямокутних карток", "Цікаво знати", "ТОЧНІСТЬ — найважливіше"):
            self.assertIn(needle, text, needle)

    def test_the_composition_follows_the_topic(self):
        cases = (("Історія України", "Причини, рушійні сили та періодизація Української революції 1917–1921 рр.", "cause"),
                 ("Історія України", "Берестейська церковна унія 1596 року та її наслідки", "cause"),
                 ("Історія України", "Минуле світу в археологічних пам’ятках. Трипільська культура", "exhibits"),
                 ("Всесвітня історія", "Консульство та Імперія у Франції. Наполеон Бонапарт.", "road"),
                 ("Всесвітня історія", "Німеччина: від «економічного дива» до об’єднання країни", "process"),
                 ("Правознавство", "Поняття та ознаки права. Джерела права", "system"),
                 ("Громадянська освіта", "Як вести діалог і обстоювати свою думку.", "system"))
        for subject, topic, expected in cases:
            self.assertEqual(choose_composition(topic, subject), expected, topic)

    def test_each_composition_reaches_the_prompt_with_its_own_wording(self):
        names = {"cause": "ПРИЧИНИ → ПЕРЕБІГ → НАСЛІДКИ", "road": "ДОРОГА ПОДІЙ", "exhibits": "ГАЛЕРЕЯ ЕКСПОНАТІВ",
                 "process": "ПРОЦЕС СТРІЛКАМИ"}
        samples = {"cause": "Причини та наслідки війни", "road": "Наполеон Бонапарт",
                   "exhibits": "Трипільська культура", "process": "Економічні реформи"}
        for kind, topic in samples.items():
            text = build_prompt(lesson_with(topic))
            self.assertIn(f"КОМПОЗИЦІЯ — «{names[kind]}»", text, kind)
            others = [v for k, v in names.items() if k != kind]
            self.assertFalse(any(f"КОМПОЗИЦІЯ — «{o}»" in text for o in others), kind)
        civic = build_prompt(lesson_with("Поняття права", stream="9-Г Право"))
        self.assertIn("ЖИВА СХЕМА З ПРИКЛАДАМИ", civic)
        self.assertIn("героями-підлітками", civic)

    def test_a_practical_work_gets_a_working_poster_with_steps_and_arrows(self):
        text = build_prompt(lesson_with("Практична робота. Аналіз літературних творів"))
        for needle in ("РОБОЧИЙ ПЛАКАТ", "«Мета роботи»", "«Що повторити»", "«Обсяг роботи»", "«Важливо!»",
                       "«Що прикріпити в Classroom?»", "натиснути «Здати»", "крок 1 → крок 2 → крок 3",
                       "ЗАБОРОНЕНО: сітка однакових", "ТОЧНІСТЬ — найважливіше"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("ДОРОГА ПОДІЙ", text)

    def test_palette_is_stable_for_a_lesson_but_differs_between_lessons(self):
        lessons = [lesson_with(f"Тема {i}") for i in range(12)]
        keyed = [replace(l, topic=f"Тема {i}") for i, l in enumerate(lessons)]
        first = [palette_for(l) for l in keyed]
        self.assertEqual(first, [palette_for(l) for l in keyed])
        self.assertGreaterEqual(len(set(first)), 1)
        by_topic = {palette_for(type("L", (), {"topic": f"Тема {i}"})()) for i in range(40)}
        self.assertGreaterEqual(len(by_topic), 3)                                   # картинки не схожі колір у колір
        self.assertTrue(by_topic <= set(PALETTES))
        self.assertIn("Палітра цього уроку:", build_prompt(lesson_with("Тема")))

    def test_the_example_picture_note_describes_the_lively_style(self):
        from classroom_assistant import samples_ui
        self.assertIn("ЖИВОГО стилю", samples_ui.INFOGRAPHIC_NOTE)
        self.assertNotIn("карток із заокругленими", samples_ui.INFOGRAPHIC_NOTE)


class BrowserSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def prefs(self, relative, profile, download_dir=None, raw=None):
        folder = self.base / relative / profile
        folder.mkdir(parents=True)
        data = raw if raw is not None else json.dumps({"download": {"default_directory": download_dir}} if download_dir
                                                      else {"profile": {}})
        (folder / "Preferences").write_text(data, encoding="utf-8")

    def test_reads_the_download_folder_of_every_installed_browser(self):
        self.prefs("Google/Chrome/User Data", "Default", "D:\\GPT")
        self.prefs("Microsoft/Edge/User Data", "Default")
        found = bd.detect(self.base)
        by_name = {f.browser: f for f in found}
        self.assertEqual(set(by_name), {"Chrome", "Edge"})                           # Brave не встановлено
        self.assertEqual(str(by_name["Chrome"].folder), "D:\\GPT")
        self.assertIsNone(by_name["Edge"].folder)                                    # власної папки немає = «Завантаження»

    def test_broken_or_missing_settings_never_crash(self):
        self.prefs("Google/Chrome/User Data", "Default", raw="{ не json")
        self.assertIsNone(bd.read_download_dir(self.base / "Google/Chrome/User Data/Default/Preferences"))
        self.assertIsNone(bd.read_download_dir(self.base / "немає.json"))
        self.assertEqual([f.folder for f in bd.detect(self.base)], [None])
        self.assertEqual(bd.detect(self.base / "порожньо"), [])

    def test_several_profiles_are_all_seen(self):
        self.prefs("Google/Chrome/User Data", "Default", "C:\\A")
        self.prefs("Google/Chrome/User Data", "Profile 1", "C:\\B")
        self.assertEqual(sorted(str(f.folder) for f in bd.detect(self.base)), ["C:\\A", "C:\\B"])

    def test_direct_other_and_default_are_told_apart(self):
        inbox, downloads = self.base / "Вхідні", self.base / "Завантаження"
        inbox.mkdir(); downloads.mkdir()
        direct = bd.Found("Chrome", inbox, "Default", self.base)
        slash = bd.Found("Chrome", Path(str(inbox) + "/"), "Default", self.base)
        other = bd.Found("Edge", self.base / "Десь", "Default", self.base)
        plain = bd.Found("Brave", None, "Default", self.base)
        self.assertEqual(bd.classify(direct, inbox, downloads), "direct")
        self.assertEqual(bd.classify(slash, inbox, downloads), "direct")             # слеш у кінці не заважає
        self.assertEqual(bd.classify(other, inbox, downloads), "other")
        self.assertEqual(bd.classify(plain, inbox, downloads), "default")
        self.assertTrue(bd.any_direct([plain, direct], inbox, downloads))
        self.assertFalse(bd.any_direct([plain, other], inbox, downloads))

    def test_only_new_existing_folders_are_watched_without_duplicates(self):
        inbox, downloads, extra = self.base / "in", self.base / "dl", self.base / "extra"
        for folder in (inbox, downloads, extra):
            folder.mkdir()
        found = [bd.Found("Chrome", extra, "Default", self.base), bd.Found("Edge", extra, "Default", self.base),
                 bd.Found("Brave", downloads, "Default", self.base), bd.Found("X", inbox, "Default", self.base),
                 bd.Found("Y", self.base / "нема", "Default", self.base), bd.Found("Z", None, "Default", self.base)]
        self.assertEqual(bd.watch_folders(found, skip=(inbox, downloads)), [extra])

    def test_opening_the_settings_page_starts_the_browser_or_falls_back(self):
        with mock.patch.object(bd, "executable", return_value=Path("C:/chrome.exe")), \
                mock.patch.object(bd.subprocess, "Popen") as popen:
            self.assertTrue(bd.open_settings("Chrome"))
        self.assertEqual(popen.call_args[0][0][1], "chrome://settings/downloads")
        with mock.patch.object(bd, "executable", return_value=None), \
                mock.patch.object(bd.webbrowser, "open", return_value=True) as web:
            self.assertTrue(bd.open_settings("Edge"))
        web.assert_called_once_with("edge://settings/downloads")
        with mock.patch.object(bd, "executable", return_value=None), \
                mock.patch.object(bd.webbrowser, "open", return_value=False):
            self.assertFalse(bd.open_settings("Brave"))


class InboxRulesTests(unittest.TestCase):
    def test_an_archive_name_may_carry_extra_words_around_the_date(self):
        for name in ("05.10.26.zip", "Лекції 05.10.26.zip", "lectures_05.10.2026.zip", "05-10-26.zip"):
            self.assertTrue(lecture_inbox.is_zip_for_day(name), name)
        for name in ("фото.zip", "архів.zip", "05.10.26.docx"):
            self.assertFalse(lecture_inbox.is_zip_for_day(name), name)

    def test_own_folder_takes_small_foreign_archives_but_not_huge_ones(self):
        with tempfile.TemporaryDirectory() as folder:
            small = Path(folder) / "щось.zip"
            small.write_bytes(b"PK")
            self.assertTrue(lecture_inbox.is_candidate(small, strict=False))
            self.assertFalse(lecture_inbox.is_candidate(small, strict=True))        # у «Завантаженнях» — лише архів дня
            with mock.patch.object(Path, "stat") as stat:
                stat.return_value = mock.Mock(st_size=lecture_inbox.MAX_LOOSE_ZIP + 1)
                self.assertFalse(lecture_inbox.is_candidate(small, strict=False))

    def test_strict_folders_still_take_only_lesson_named_files(self):
        with tempfile.TemporaryDirectory() as folder:
            lesson = Path(folder) / "9-Б ВІ, Урок 05.10 — Тема.docx"
            stray = Path(folder) / "звіт.docx"
            lesson.write_bytes(b"x"); stray.write_bytes(b"x")
            self.assertTrue(lecture_inbox.is_candidate(lesson, strict=True))
            self.assertFalse(lecture_inbox.is_candidate(stray, strict=True))


class AutoReceiveTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.app.geometry("1400x900")
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        self.app.update()

    def test_the_watcher_also_follows_the_folder_the_browser_really_uses(self):
        extra = Path(self.tmp.name) / "БраузерСам"
        extra.mkdir()
        found = [bd.Found("Chrome", extra, "Default", extra)]
        with mock.patch.object(bd, "detect", return_value=found):
            self.app._bf_ts = -999
            sources = self.app._watch_sources()
        self.assertIn((extra, True), sources)                                        # суворо: лише файли з назвою уроку
        self.assertIn((lecture_inbox.inbox_dir(gui.ROOT), False), sources)

    def test_browser_folders_are_not_added_when_watching_downloads_is_off(self):
        extra = Path(self.tmp.name) / "БраузерСам2"
        extra.mkdir()
        self.app.state["watch_downloads"] = False
        with mock.patch.object(bd, "detect", return_value=[bd.Found("Chrome", extra, "Default", extra)]):
            self.app._bf_ts = -999
            self.assertNotIn((extra, True), self.app._watch_sources())

    def test_stray_images_and_archives_in_the_inbox_are_left_quietly_but_a_stray_docx_is_reported(self):
        inbox = lecture_inbox.inbox_dir(gui.ROOT)
        picture, archive, word = inbox / "котик.jpg", inbox / "чужий.zip", inbox / "резюме.docx"
        picture.write_bytes(b"\xff\xd8x")
        archive.write_bytes(b"PK")
        document = Document()
        document.add_paragraph("Моє резюме")
        document.save(word)
        toasts_before = len(self.toasts)
        self.app._process_inbox([(picture, False), (archive, False)])
        self.assertEqual(len(self.toasts), toasts_before)                              # без повідомлень
        self.assertTrue(picture.exists() and archive.exists())                          # нічого не переносимо й не видаляємо
        self.app._process_inbox([(word, False)])
        self.assertTrue(any("Не вдалося визначити урок" in t and "резюме.docx" in t for t in self.toasts))
        self.assertTrue(word.exists())

    def test_lessons_with_a_word_and_no_draft_are_painted_ready(self):
        rows = self.app.grid.get_children()
        lessons = self.app.rows
        have, drafted, empty = lessons[0], lessons[1], lessons[2]
        self.app.state.setdefault("files", {})[have.unique_key] = {"path": "x.docx", "validated": True, "complete": True}
        self.app.state["files"][drafted.unique_key] = {"path": "y.docx", "validated": True, "complete": True}
        self.app.state.setdefault("drafts", {})[drafted.unique_key] = {"id": "1", "created_at": time.time()}
        self.app.update_day()
        tags = {lessons[i].unique_key: self.app.grid.item(str(i), "tags") for i in range(len(lessons))}
        self.assertIn("ready", tags[have.unique_key])
        self.assertNotIn("ready", tags[drafted.unique_key])                             # чернетка вже є
        self.assertNotIn("ready", tags[empty.unique_key])                               # Word ще немає
        self.assertEqual(str(self.app.grid.tag_configure("ready", "background")), "#DCE8B8")

    def test_the_arrival_toast_tells_what_to_do_next(self):
        word = self.make_lecture_for(self.app.rows[0])
        self.app.import_lecture_files([word])
        self.assertIn("зелені рядки готові до чернеток", self.toasts[-1])

    def make_lecture_for(self, lesson):
        from test_update42 import make_lecture
        folder = Path(self.tmp.name) / "прийшло"
        folder.mkdir(exist_ok=True)
        name = engine.lesson_base_name(lesson, label=None) + ".docx"
        return make_lecture(folder / name, f"{lesson.stream}, Урок")

    def test_the_main_button_opens_the_setup_window_not_just_the_folder(self):
        with mock.patch.object(download_setup_ui, "show_download_setup") as show:
            self.app.open_inbox()
        show.assert_called_once_with(self.app)
        labels = []
        stack = [self.app]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if widget.winfo_class() == "TButton":
                labels.append(str(widget.cget("text")))
        self.assertIn("Автоприйом файлів GPT…", labels)


class SetupWindowTests(TempProgram):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(download_setup_ui, "ROOT", gui.ROOT),
                        mock.patch.object(download_setup_ui, "show_toast",
                                          side_effect=lambda parent, text, *a, **k: self.toasts.append(text))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make(self, found):
        with mock.patch.object(bd, "detect", return_value=found):
            window = download_setup_ui.show_download_setup(self.app)
            window.update()
        self.addCleanup(lambda: window.winfo_exists() and window.destroy())
        return window

    @staticmethod
    def texts(window):
        result, stack = [], [window]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if widget.winfo_class() in ("TLabel", "TButton", "TLabelframe"):
                result.append(str(widget.cget("text")))
        return result

    def test_it_shows_each_browser_with_what_is_set_and_what_to_do(self):
        inbox = lecture_inbox.inbox_dir(gui.ROOT)
        other = Path(self.tmp.name) / "Інша"
        found = [bd.Found("Chrome", inbox, "Default", inbox), bd.Found("Edge", other, "Default", other),
                 bd.Found("Brave", None, "Default", other)]
        texts = self.texts(self.make(found))
        self.assertTrue(any("Chrome: зберігає в" in t for t in texts))
        self.assertIn("✓ Файли від GPT потрапляють прямо в програму", texts)
        self.assertTrue(any(t.startswith("⚠ Інша папка") for t in texts))
        self.assertTrue(any(t.startswith("Звичайні «Завантаження»") for t in texts))
        self.assertTrue(any("Відкрити налаштування Edge" == t for t in texts))
        self.assertTrue(any("Куди браузер зберігає завантажене" in t for t in texts))
        self.assertTrue(any(t.startswith("1. Натисніть «Копіювати шлях»") for t in texts))

    def test_the_folder_path_is_really_shown_in_the_field(self):
        window = self.make([])
        window.update()
        self.assertEqual(window.path_entry.get(), str(lecture_inbox.inbox_dir(gui.ROOT)))      # а не порожнє поле
        self.assertEqual(str(window.path_entry.cget("state")), "readonly")
        style = __import__("tkinter.ttk").ttk.Style(window)
        self.assertEqual(style.lookup("TEntry", "foreground", ("readonly",)), "#2A2118")        # читається на пергаменті

    def test_copy_puts_the_program_folder_on_the_clipboard(self):
        window = self.make([])
        buttons = [w for w in self.walk(window) if w.winfo_class() == "TButton" and w.cget("text") == "Копіювати шлях"]
        buttons[0].invoke()
        self.assertEqual(window.clipboard_get(), str(lecture_inbox.inbox_dir(gui.ROOT)))
        self.assertIn("Шлях скопійовано", self.toasts[-1])

    @staticmethod
    def walk(window):
        out, stack = [], [window]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            out.append(widget)
        return out

    def test_the_settings_button_opens_the_browser_page_and_reports_a_failure(self):
        inbox = lecture_inbox.inbox_dir(gui.ROOT)
        window = self.make([bd.Found("Chrome", None, "Default", inbox)])
        button = next(w for w in self.walk(window) if w.winfo_class() == "TButton"
                      and w.cget("text") == "Відкрити налаштування Chrome")
        with mock.patch.object(bd, "open_settings", return_value=True) as ok:
            button.invoke()
        ok.assert_called_once_with("Chrome")
        self.assertIn("Відкриваю налаштування Chrome", self.toasts[-1])
        with mock.patch.object(bd, "open_settings", return_value=False):
            button.invoke()
        self.assertIn("chrome://settings/downloads", self.toasts[-1])

    def test_no_known_browser_still_gives_a_manual_way(self):
        texts = self.texts(self.make([]))
        self.assertTrue(any("Chrome, Edge чи Brave не знайдено" in t for t in texts))

    def test_check_again_reads_the_settings_anew(self):
        inbox = lecture_inbox.inbox_dir(gui.ROOT)
        window = self.make([bd.Found("Chrome", None, "Default", inbox)])
        self.assertTrue(any(t.startswith("Звичайні «Завантаження»") for t in self.texts(window)))
        with mock.patch.object(bd, "detect", return_value=[bd.Found("Chrome", inbox, "Default", inbox)]):
            next(w for w in self.walk(window) if w.winfo_class() == "TButton" and w.cget("text") == "Перевірити ще раз").invoke()
        self.assertIn("✓ Файли від GPT потрапляють прямо в програму", self.texts(window))

    def test_summary_line_for_the_day_dialog(self):
        inbox, downloads = Path("/p/in"), Path("/p/dl")
        text, color = download_setup_ui.summary_line([bd.Found("Chrome", inbox, "Default", inbox)], inbox, downloads)
        self.assertTrue(text.startswith("✓ Автоприйом"))
        text, color = download_setup_ui.summary_line([bd.Found("Chrome", None, "Default", inbox)], inbox, downloads)
        self.assertIn("«Завантажень»", text)
        self.assertIn("Куди зберігати файли…", text)

    def test_day_dialog_shows_the_auto_receive_state_and_the_button(self):
        lessons = [l for l in self.app.rows][:1] or None
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        lessons = self.app.rows[:2]
        inbox = lecture_inbox.inbox_dir(gui.ROOT)
        with mock.patch.object(bd, "detect", return_value=[bd.Found("Chrome", inbox, "Default", inbox)]):
            dialog = chatgpt_ui.ChatGPTDayDialog(self.app, lessons)
            dialog.update()
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        self.assertTrue(str(dialog.auto_label.cget("text")).startswith("✓ Автоприйом"))
        with mock.patch.object(download_setup_ui, "show_download_setup") as show:
            next(w for w in self.walk(dialog) if w.winfo_class() == "TButton"
                 and w.cget("text") == "Куди зберігати файли…").invoke()
        show.assert_called_once_with(self.app)


if __name__ == "__main__":
    unittest.main()


class SingleLessonDialogTests(SetupWindowTests):
    """Вікно ОДНОГО уроку теж має рядок автоприйому (раніше його виклик не мав методу й вікно не відкрилось би)."""

    def test_the_single_lesson_dialog_opens_and_shows_the_auto_receive_state(self):
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        lesson = self.app.rows[3]
        inbox = lecture_inbox.inbox_dir(gui.ROOT)
        with mock.patch.object(bd, "detect", return_value=[bd.Found("Chrome", None, "Default", inbox)]):
            dialog = chatgpt_ui.open_chatgpt_dialog(self.app, [lesson])
            dialog.update()
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        self.assertIsInstance(dialog, chatgpt_ui.ChatGPTLectureDialog)
        self.assertIn("«Завантажень»", str(dialog.auto_label.cget("text")))
        with mock.patch.object(download_setup_ui, "show_download_setup") as show:
            next(w for w in self.walk(dialog) if w.winfo_class() == "TButton"
                 and w.cget("text") == "Куди зберігати файли…").invoke()
        show.assert_called_once_with(self.app)
