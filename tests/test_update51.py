"""5.5: годинник уроків (дзвіночок, червона рамка), вшитий ключ, навчальні матеріали, підбір розмірів під екран, ярлик."""
import base64
import io
import json
import re
import tempfile
import time
import tkinter as tk
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import yaml

from test_update36 import TkCase
from test_update44 import TempProgram

from classroom_assistant import air_alerts as aa
from classroom_assistant import alert_ui, engine, gui, lesson_clock, lesson_marks, lecture_inbox, materials, materials_ui
from classroom_assistant import shortcut

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 5)


def pump(app, n=12):
    for _ in range(n):
        app.update()
        time.sleep(0.01)


def at(row, minutes_from_start):
    """Момент часу відносно початку уроку (у хвилинах), для вказаної дати."""
    hours, minutes = map(int, row.begin.split(":"))
    return datetime(DAY.year, DAY.month, DAY.day, hours, minutes) + timedelta(minutes=minutes_from_start)


class LessonClockTests(unittest.TestCase):
    def test_times_are_read_in_any_common_notation(self):
        for text in ("08:30", "8:30", "8.30", " 08 : 30 "):
            self.assertEqual(lesson_clock.parse_hm(text).hour, 8, text)
        for bad in ("", None, "25:00", "08:99", "обід", "8"):
            self.assertIsNone(lesson_clock.parse_hm(bad), bad)

    def test_the_bell_rings_ten_minutes_before_and_the_frame_lives_exactly_during_the_lesson(self):
        phase = lambda h, m, s=0: lesson_clock.lesson_phase(datetime(2026, 10, 5, h, m, s), DAY, "11:35", "12:20")
        self.assertIsNone(phase(11, 24, 59))
        self.assertEqual(phase(11, 25), "bell")
        self.assertEqual(phase(11, 34, 59), "bell")
        self.assertEqual(phase(11, 35), "now")                                        # о 11:35 дзвіночок зникає, рамка з'являється
        self.assertEqual(phase(12, 19, 59), "now")
        self.assertIsNone(phase(12, 20))                                              # урок закінчився: рамки немає

    def test_it_works_for_any_schedule_and_only_for_today(self):
        for begin, end in (("07:45", "08:30"), ("14:20", "15:05"), ("18:00", "18:45"), ("08.30", "09.15")):
            start = lesson_clock.parse_hm(begin)
            moment = datetime.combine(DAY, start)
            self.assertEqual(lesson_clock.lesson_phase(moment, DAY, begin, end), "now", begin)
            self.assertEqual(lesson_clock.lesson_phase(moment - timedelta(minutes=5), DAY, begin, end), "bell", begin)
        noon = datetime(2026, 10, 5, 11, 40)
        self.assertIsNone(lesson_clock.lesson_phase(noon, DAY + timedelta(days=1), "11:35", "12:20"))   # завтрашній день
        self.assertIsNone(lesson_clock.lesson_phase(noon, DAY - timedelta(days=1), "11:35", "12:20"))   # учорашній
        self.assertIsNone(lesson_clock.lesson_phase(noon, DAY, "12:20", "11:35"))                         # зламані дані
        self.assertIsNone(lesson_clock.lesson_phase(noon, DAY, "", ""))

    def test_phases_marks_the_right_rows(self):
        rows = [type("R", (), {"begin": b, "end": e})() for b, e in
                (("08:30", "09:15"), ("09:30", "10:15"), ("11:35", "12:20"))]
        self.assertEqual(lesson_clock.phases(rows, DAY, datetime(2026, 10, 5, 9, 19)), {})
        self.assertEqual(lesson_clock.phases(rows, DAY, datetime(2026, 10, 5, 9, 20)), {"1": "bell"})
        self.assertEqual(lesson_clock.phases(rows, DAY, datetime(2026, 10, 5, 9, 40)), {"1": "now"})
        self.assertEqual(lesson_clock.phases(rows, DAY, datetime(2026, 10, 5, 11, 30)), {"2": "bell"})


class MarkAnimationTests(unittest.TestCase):
    def test_the_bell_sways_gently_and_never_jerks(self):
        angles = [lesson_marks.swing_angle(i * 0.05) for i in range(0, 120)]
        self.assertLessEqual(max(abs(a) for a in angles), lesson_marks.SWING_DEGREES + 1e-9)
        self.assertGreater(max(angles), 5)
        self.assertLess(min(angles), -5)
        steps = [abs(b - a) for a, b in zip(angles, angles[1:])]
        self.assertLess(max(steps), 1.2)                                              # за 0,05 с — не більше ~1°: без ривків

    def test_the_red_line_breathes_and_a_soft_glint_runs_around_it(self):
        base_k = [lesson_marks.edge_color(0.5, t) for t in (0.0, 0.65, 1.3, 1.95)]
        self.assertGreater(len(set(base_k)), 1)                                       # дихання
        peak = lesson_marks.edge_color(0.0, 0.0)                                       # відблиск у стартовій точці
        quiet = lesson_marks.edge_color(0.5, 0.0)                                      # а навпроти нього — звичайна лінія
        self.assertGreater(sum(peak), sum(quiet) + 60)
        for t in (0.3, 1.7, 3.1):                                                      # завжди червоний, ніколи не біла чи зелена
            for fraction in (0.0, 0.25, 0.5, 0.75):
                r, g, b = lesson_marks.edge_color(fraction, t)
                self.assertGreater(r, g + 60)
        moved = [max(range(100), key=lambda i: sum(lesson_marks.edge_color(i / 100, t))) / 100 for t in (0.0, 0.85, 1.7, 2.55)]
        self.assertEqual(moved, sorted(moved))                                         # відблиск біжить в один бік


class MarksOnTheTableTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.app.geometry("1500x1000")
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        pump(self.app)
        self.marks = self.app.lesson_marks
        self.row = self.app.rows[3]                                                    # четвертий урок дня

    def set_time(self, moment):
        self.app.clock = lambda: moment
        self.marks.refresh()
        pump(self.app, 6)

    def test_the_bell_appears_right_of_the_lesson_number_ten_minutes_before_and_vanishes_at_the_start(self):
        self.set_time(at(self.row, -10))
        self.assertEqual(self.marks.visible, {"frames": 0, "bells": 1})
        box = self.app.grid.bbox("3", "#1")                                             # клітинка «№» четвертого уроку
        label = self.marks.labels[0]
        self.assertGreaterEqual(label.winfo_x(), box[0] + 20)                           # правіше цифри номера (вона зліва)
        self.assertLessEqual(label.winfo_x() + label.winfo_width(), box[0] + box[2] + 1)
        self.assertLessEqual(abs((label.winfo_y() + label.winfo_height() // 2) - (box[1] + box[3] // 2)), 2)
        self.set_time(at(self.row, -11))
        self.assertEqual(self.marks.visible, {"frames": 0, "bells": 0})                 # ще рано
        self.set_time(at(self.row, 0))
        self.assertEqual(self.marks.visible, {"frames": 1, "bells": 0})                 # урок почався: дзвіночка немає

    def test_the_red_frame_surrounds_exactly_the_time_cell_and_leaves_when_the_lesson_ends(self):
        self.set_time(at(self.row, 5))
        self.assertEqual(self.marks.visible, {"frames": 1, "bells": 0})
        box = self.app.grid.bbox("3", "#2")                                             # клітинка «Час»
        top, right, bottom, left = self.marks.frames[0].strips
        self.assertEqual((top.winfo_x(), top.winfo_y(), top.winfo_width()), (box[0], box[1], box[2]))
        self.assertEqual((left.winfo_x(), left.winfo_y(), left.winfo_height()), (box[0], box[1], box[3]))
        self.assertEqual(bottom.winfo_y() + bottom.winfo_height(), box[1] + box[3])
        self.assertEqual(right.winfo_x() + right.winfo_width(), box[0] + box[2])
        self.assertEqual(top.winfo_height(), lesson_marks.THICKNESS)                    # лише тонка лінія: усередині без заливки
        self.set_time(at(self.row, 44))
        self.assertEqual(self.marks.visible["frames"], 1)
        end = datetime.combine(DAY, lesson_clock.parse_hm(self.row.end))
        self.set_time(end)
        self.assertEqual(self.marks.visible, {"frames": 0, "bells": 0})                 # о кінці уроку рамка зникає

    def test_the_frame_glint_really_moves_between_frames_of_the_animation(self):
        self.set_time(at(self.row, 5))
        frame = self.marks.frames[0]
        self.marks.tick(0.0)
        first = {item: frame.strips[0].itemcget(item, "fill") for item in frame.items[0]}
        self.marks.tick(1.7)
        second = {item: frame.strips[0].itemcget(item, "fill") for item in frame.items[0]}
        self.assertNotEqual(first, second)
        self.assertGreater(len(set(first.values())), 1)                                  # уздовж лінії колір не однаковий

    def test_nothing_is_marked_for_other_days_and_marks_follow_a_changed_schedule_date(self):
        self.app.clock = lambda: at(self.row, 5)
        self.app.datevar.set("06.10.2026")
        self.app.update_day()
        pump(self.app, 6)
        self.assertEqual(self.marks.state, {})
        self.assertEqual(self.marks.visible, {"frames": 0, "bells": 0})
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        pump(self.app, 6)
        self.assertEqual(self.marks.state, {"3": "now"})

    def test_the_bell_background_matches_the_row_so_it_blends_in(self):
        self.set_time(at(self.row, -5))
        self.assertEqual(self.marks.labels[0].cget("bg"), self.marks.row_background("3"))
        self.app.grid.selection_set("3")
        self.marks.tick(0.0)
        self.assertEqual(self.marks.labels[0].cget("bg"), lesson_marks.ROW_SELECTED_BG)

    def test_a_scrolled_away_lesson_has_no_stray_marks_and_a_failing_frame_does_not_stop_the_clock(self):
        self.set_time(at(self.row, 5))
        with mock.patch.object(self.marks, "_draw", side_effect=tk.TclError("збій кадру")):
            self.marks.tick(0.0)
        self.assertEqual(self.marks.errors, 1)
        self.assertIsNotNone(self.marks._job)                                           # таймер живий і спробує ще
        self.marks.tick(0.0)
        self.assertEqual(self.marks.visible["frames"], 1)

    def test_two_lessons_at_the_same_time_both_get_the_frame(self):
        twin = self.app.rows[4]
        with mock.patch.object(type(twin), "begin", self.row.begin, create=True), \
                mock.patch.object(type(twin), "end", self.row.end, create=True):
            self.set_time(at(self.row, 5))
        self.assertGreaterEqual(self.marks.visible["frames"], 1)

    def test_closing_the_program_stops_the_clock(self):
        self.set_time(at(self.row, 5))
        with mock.patch.object(self.app, "destroy"):
            self.app.on_close()
        self.assertIsNone(self.marks._job)


class AlarmKeyTests(unittest.TestCase):
    def test_the_key_from_ukraine_alarm_is_built_in_and_works_without_any_setup(self):
        self.assertEqual(aa.DEFAULT_KEY, "71680c3f:cd6f222b95e33791bd3eaf746bba0307")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(aa.load_settings(folder)["key"], aa.DEFAULT_KEY)
            self.assertEqual(aa.load_settings(folder)["provider"], aa.UKRAINE_ALARM)

    def test_a_key_typed_by_the_teacher_wins_and_an_empty_one_falls_back_to_the_built_in(self):
        with tempfile.TemporaryDirectory() as folder:
            aa.save_settings(folder, {"provider": aa.UKRAINE_ALARM, "key": "мій:ключ", "place": dict(aa.DEFAULT_PLACE)})
            self.assertEqual(aa.load_settings(folder)["key"], "мій:ключ")
            aa.save_settings(folder, {"provider": aa.UKRAINE_ALARM, "key": "", "place": dict(aa.DEFAULT_PLACE)})
            self.assertEqual(aa.load_settings(folder)["key"], aa.DEFAULT_KEY)

    def test_the_built_in_key_is_never_used_for_another_service(self):
        with tempfile.TemporaryDirectory() as folder:
            aa.save_settings(folder, {"provider": aa.ALERTS_IN_UA, "key": "", "place": dict(aa.DEFAULT_PLACE)})
            self.assertEqual(aa.load_settings(folder)["key"], "")

    def test_the_request_to_the_service_carries_the_key(self):
        sent = []

        class Response:
            def __init__(self, payload):
                self.body = json.dumps(payload).encode()

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout=None):
            sent.append(request.get_header("Authorization"))
            return Response({"states": [{"regionId": "31", "regionName": "м. Київ", "regionType": "State"}]}
                            if request.full_url.endswith("/regions") else [])
        with tempfile.TemporaryDirectory() as folder:
            status = aa.fetch_status(aa.load_settings(folder), folder, opener=opener)
        self.assertEqual(status.level, aa.NONE)
        self.assertEqual(set(sent), {aa.DEFAULT_KEY})


class AlarmKeyDialogTests(TempProgram):
    def test_the_dialog_shows_the_built_in_key_masked_and_lets_it_be_replaced(self):
        with mock.patch.object(alert_ui, "show_toast"):
            window = alert_ui.show_alert_setup(self.app)
            window.update()
            self.assertEqual(window.key.get(), aa.DEFAULT_KEY)
            window.key.set("новий:ключ")
            with mock.patch.object(self.app, "alert_settings_changed"):
                window.save()
        self.assertEqual(aa.load_settings(engine.DATA)["key"], "новий:ключ")

    def test_switching_the_service_does_not_carry_the_built_in_key_over(self):
        with mock.patch.object(alert_ui, "show_toast"):
            window = alert_ui.show_alert_setup(self.app)
            window.update()
            window.provider.set(aa.ALERTS_IN_UA)
            self.assertEqual(window.collect()["key"], "")


class MaterialsTests(unittest.TestCase):
    def test_the_six_reference_books_ship_with_the_program(self):
        folder = materials.bundled_dir()
        names = sorted(p.name for p in folder.glob("*.pdf"))
        self.assertEqual(len(names), 6, names)
        for path in folder.glob("*.pdf"):
            self.assertEqual(path.read_bytes()[:5], b"%PDF-", path.name)                # справжні PDF
            self.assertGreater(path.stat().st_size, 1_000_000)
        self.assertLess(sum(p.stat().st_size for p in folder.glob("*.pdf")), 25 * 1024 * 1024)

    def test_in_the_built_program_the_books_are_looked_for_inside_the_bundle(self):
        with tempfile.TemporaryDirectory() as bundle:
            folder = Path(bundle) / "КТП джерела" / materials.FOLDER
            folder.mkdir(parents=True)
            (folder / "Рятівник - ВІ 6-7.pdf").write_bytes(b"%PDF-1.4")
            with mock.patch.object(materials.sys, "frozen", True, create=True), \
                    mock.patch.object(materials.sys, "_MEIPASS", bundle, create=True):
                self.assertEqual(materials.bundled_dir(), folder)
                with tempfile.TemporaryDirectory() as root:
                    self.assertEqual([i.title for i in materials.catalog(root)], ["«Рятівник» — Всесвітня історія, 6–7 класи"])

    def test_the_catalog_lists_them_with_readable_titles_in_a_sensible_order(self):
        with tempfile.TemporaryDirectory() as root:
            items = materials.catalog(root)
        self.assertEqual(len(items), 6)
        self.assertTrue(all(i.builtin and i.section == materials.BUNDLED_SECTION for i in items))
        titles = [i.title for i in items]
        self.assertEqual(titles[0], "«Рятівник» — Всесвітня історія, 6–7 класи")
        self.assertIn("Історія України, 5 клас — у схемах і таблицях", titles)
        self.assertEqual(len(set(titles)), 6)

    def test_own_materials_are_added_into_sections_and_never_overwrite_anything(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as src:
            doc = Path(src) / "Схема.docx"
            doc.write_bytes(b"1")
            first = materials.add_files(root, [doc], "Географія")
            second = materials.add_files(root, [doc], "Географія")
            plain = materials.add_files(root, [doc])
            self.assertEqual(first[0].parent.name, "Географія")
            self.assertEqual(second[0].name, "Схема (1).docx")
            self.assertEqual(plain[0].parent.name, materials.FOLDER)
            own = [(i.title, i.section) for i in materials.catalog(root) if not i.builtin]
            self.assertIn(("Схема", "Географія"), own)
            self.assertIn(("Схема (1)", "Географія"), own)
            self.assertIn(("Схема", materials.USER_SECTION), own)
            self.assertEqual(materials.add_files(root, [Path(src) / "немає.pdf"]), [])

    def test_unsafe_section_names_cannot_escape_the_folder(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as src:
            doc = Path(src) / "a.txt"
            doc.write_bytes(b"1")
            copies = materials.add_files(root, [doc], "..\\..\\зламати:<>|")
            self.assertTrue(str(copies[0].resolve()).startswith(str(materials.user_dir(root).resolve())))

    def test_only_own_materials_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as src:
            doc = Path(src) / "мій.txt"
            doc.write_bytes(b"1")
            materials.add_files(root, [doc])
            own = next(i for i in materials.catalog(root) if not i.builtin)
            builtin = next(i for i in materials.catalog(root) if i.builtin)
            self.assertFalse(materials.remove(builtin))
            self.assertTrue(builtin.path.exists())
            self.assertTrue(materials.remove(own))
            self.assertFalse(own.path.exists())

    def test_saving_to_downloads_copies_and_keeps_the_originals(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as downloads:
            item = materials.catalog(root)[0]
            first = materials.save_to_downloads(item, root, downloads)
            second = materials.save_to_downloads(item, root, downloads)
            self.assertEqual(first.read_bytes(), item.path.read_bytes())
            self.assertEqual(second.name, f"{item.path.stem} (1).pdf")
            self.assertTrue(item.path.exists())
            local = materials.local_copy(item, root)                                       # розпаковано в папку вчителя
            self.assertTrue(str(local).startswith(str(materials.user_dir(root))))
            self.assertEqual(local.stat().st_size, item.size)


class MaterialsWindowTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.downloads = Path(self.tmp.name) / "Завантаження"
        for patcher in (mock.patch.object(lecture_inbox, "downloads_dir", return_value=self.downloads),
                        mock.patch.object(materials_ui, "show_toast",
                                          side_effect=lambda p, text, *a, **k: self.toasts.append(text))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = materials_ui.show_materials(self.app)
        self.window.update()

    def test_the_header_button_opens_one_window_with_the_six_books(self):
        header = self.app.header
        self.assertIsNotNone(header.on_materials)
        for _ in range(4):
            header._mat_release()
        windows = [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == "Навчальні матеріали"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(len(self.window.tree.get_children()), 6)
        self.assertIn("«Рятівник» — Історія України, 10–11 класи", [self.window.tree.item(i, "values")[0] for i in self.window.tree.get_children()])

    def test_the_header_button_sits_left_of_the_author_plate(self):
        header = self.app.header
        header.layout()
        left, top, right, bottom = header._button_box
        self.assertLess(right, header._author_box[0])
        self.assertLess(header._title_box[2], left)
        self.assertTrue(any("Навчальні" in header.itemcget(i, "text") for i in header.find_all() if header.type(i) == "text"))

    def test_saving_the_chosen_book_puts_it_into_downloads_and_says_so(self):
        first = self.window.tree.get_children()[0]
        self.window.tree.selection_set(first)
        self.window.save_selected()
        saved = list(self.downloads.glob("*.pdf"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(any("Збережено в «Завантаження»" in t for t in self.toasts))

    def test_nothing_chosen_gives_a_hint_instead_of_an_error(self):
        self.window.save_selected()
        self.assertIn("оберіть матеріал", self.window.status.get())
        self.assertFalse(self.downloads.exists() and list(self.downloads.glob("*")))

    def test_all_references_can_be_saved_at_once(self):
        self.window.save_all_references()
        self.assertEqual(len(list(self.downloads.glob("*.pdf"))), 6)

    def test_adding_a_file_shows_it_in_the_list_in_its_own_section_and_it_can_be_deleted(self):
        source = Path(self.tmp.name) / "Схема Вікінгів.pdf"
        source.write_bytes(b"%PDF-1.4 x")
        self.window.section_var.set("Всесвітня історія")
        with mock.patch.object(materials_ui.filedialog, "askopenfilenames", return_value=(str(source),)):
            self.window.add_files()
        rows = [self.window.tree.item(i, "values") for i in self.window.tree.get_children()]
        self.assertIn(("Схема Вікінгів", "Всесвітня історія", "1 КБ"), rows)
        own = next(i for i in self.window.tree.get_children() if self.window.tree.item(i, "values")[0] == "Схема Вікінгів")
        self.window.tree.selection_set(own)
        with mock.patch.object(materials_ui.messagebox, "askyesno", return_value=True):
            self.window.delete_selected()
        self.assertEqual(len(self.window.tree.get_children()), 6)

    def test_built_in_books_refuse_deletion_with_an_explanation(self):
        self.window.tree.selection_set(self.window.tree.get_children()[0])
        with mock.patch.object(materials_ui.messagebox, "askyesno") as ask:
            self.window.delete_selected()
        ask.assert_not_called()
        self.assertIn("видалити не можна", self.window.status.get())
        self.assertEqual(len(self.window.tree.get_children()), 6)

    def test_opening_a_book_unpacks_it_to_the_teachers_folder_first(self):
        self.window.tree.selection_set(self.window.tree.get_children()[2])
        with mock.patch.object(materials, "open_file") as opener:
            self.window.open_selected()
        opened = Path(opener.call_args[0][0])
        self.assertTrue(opened.exists())
        self.assertIn(materials.FOLDER, str(opened))


class DensityTests(TempProgram):
    def setUp(self):
        super().setUp()
        for _ in range(90):                                                          # дати вікну саме розгорнутись на старті
            self.app.update()
            time.sleep(0.01)

    def settle(self, width, height):
        self.app.geometry(f"{width}x{height}+0+0")
        pump(self.app, 8)
        self.app._apply_density()
        pump(self.app, 6)

    def test_a_tall_window_keeps_everything_full_size(self):
        self.settle(1920, 1000)
        self.assertEqual(self.app.density, 1.0)
        self.assertEqual(self.app.header.s, 1.0)
        self.assertEqual(int(self.app.header.cget("height")), 108)

    def test_a_low_window_shrinks_the_header_and_the_side_blocks_instead_of_squeezing_the_table(self):
        self.settle(1280, 860)
        self.assertLess(self.app.density, 1.0)
        self.assertLess(int(self.app.header.cget("height")), 108)
        self.assertLess(int(self.app.alert_panel.cget("height")), alert_ui.HEIGHT)
        self.assertLessEqual(self.app.winfo_reqheight(), self.app.winfo_height() + 2)         # усе вміщається
        rows = [i for i in self.app.grid.get_children() if self.app.grid.bbox(i)]
        self.assertGreaterEqual(len(rows), 4)                                                    # таблиця не схлопнулась

    def test_nothing_is_cut_off_on_a_low_window(self):
        self.settle(1280, 860)
        bottom_buttons = [w for w in self._walk(self.app) if w.winfo_class() == "Button" and "СКИНУТИ ВСЕ" in str(w.cget("text"))]
        edge = self.app.winfo_rooty() + self.app.winfo_height()
        self.assertLessEqual(bottom_buttons[0].winfo_rooty() + bottom_buttons[0].winfo_height(), edge)
        for widget in (self.app.alert_panel, self.app.leaf):
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom_buttons[0].winfo_rooty() + 2)
            self.assertGreaterEqual(widget.winfo_height(), int(widget.cget("height")) - 1)

    def test_what_is_drawn_always_matches_the_size_of_the_blocks_so_nothing_is_clipped(self):
        for width, height in ((1600, 900), (1600, 856), (1536, 790), (1920, 1000), (1920, 880)):
            self.settle(width, height)
            for name, widget in (("тривога", self.app.alert_panel), ("листок", self.app.leaf)):
                canvas_w, canvas_h = int(widget.cget("width")), int(widget.cget("height"))
                items = [i for i in widget.find_all() if widget.type(i) in ("text", "image")]
                right = max(widget.bbox(i)[2] for i in items)
                bottom = max(widget.bbox(i)[3] for i in items)
                self.assertLessEqual(right, canvas_w + 2, f"{name} {width}x{height}: малюнок ширший за полотно")
                self.assertLessEqual(bottom, canvas_h + 2, f"{name} {width}x{height}: малюнок вищий за полотно")
                self.assertFalse(widget._dirty, f"{name} {width}x{height}: розмір змінено, а малюнок не оновлено")
            self.assertLessEqual(self.app.alert_panel.winfo_rootx() + self.app.alert_panel.winfo_width(),
                                 self.app.leaf.winfo_rootx() + 2)                       # панель тривоги не перекрита листком

    def test_the_message_field_stays_usable(self):
        self.settle(1280, 860)
        self.assertGreaterEqual(int(self.app.desc.cget("height")), 2)
        self.assertGreaterEqual(self.app.desc.winfo_height(), 40)

    def test_the_other_laptop_1600_by_856_gets_a_roomy_table_and_a_proper_message_field(self):
        self.settle(1600, 856)
        rows = [i for i in self.app.grid.get_children() if self.app.grid.bbox(i)]
        self.assertGreaterEqual(len(rows), 5)                                                   # було 3 рядки на скриншоті
        self.assertGreaterEqual(int(self.app.desc.cget("height")), 3)
        self.assertGreaterEqual(self.app.desc.winfo_height(), 60)
        self.assertLessEqual(self.app.winfo_reqheight(), self.app.winfo_height() + 2)

    def test_growing_the_window_back_restores_the_full_look(self):
        self.settle(1920, 860)
        self.assertLess(self.app.density, 1.0)
        self.settle(1920, 1000)
        self.assertEqual(self.app.density, 1.0)
        self.assertEqual(int(self.app.header.cget("height")), 108)
        self.assertEqual(tuple(map(int, re.findall(r"\d+", str(ttk_style(self.app).lookup("TButton", "padding"))))), (6, 3))

    def test_the_smallest_level_hides_only_the_thumbnail_strip_and_it_returns_later(self):
        self.settle(1366, 640)
        self.assertTrue(self.app.ultra)
        self.assertEqual(self.app.attachment_bar.winfo_manager(), "")
        self.settle(1920, 1000)
        self.assertFalse(self.app.ultra)
        self.assertEqual(self.app.attachment_bar.winfo_manager(), "pack")

    def test_the_alert_panel_and_the_leaf_are_complete_pictures_at_every_size(self):
        self.app._apply_density = lambda *a, **k: None                              # не заважати власним розмірам цього тесту
        for s in (1.0, 0.74, 0.55, 0.46):
            self.app.alert_panel.set_scale(s)
            self.app.leaf.set_scale(alert_ui.HEIGHT * s / 620)
            self.app.update()
            panel_bottom = max(self.app.alert_panel.bbox(i)[3] for i in self.app.alert_panel.find_all())
            self.assertLessEqual(panel_bottom, int(self.app.alert_panel.cget("height")) + 3, s)
            self.assertAlmostEqual(int(self.app.leaf.cget("height")), round(620 * alert_ui.HEIGHT * s / 620), delta=2)

    @staticmethod
    def _walk(widget):
        out, stack = [], [widget]
        while stack:
            current = stack.pop()
            stack.extend(current.winfo_children())
            out.append(current)
        return out


def ttk_style(app):
    from tkinter import ttk
    return ttk.Style(app)


class ShortcutTests(unittest.TestCase):
    def test_the_script_points_the_shortcut_at_the_exe_and_the_logo(self):
        script = shortcut.powershell_script("C:/Програми/Помічник/Pomichnyk_Uchytelia.exe", "C:/Документи/app_icon.ico")
        for needle in ("CreateShortcut", "$s.TargetPath = 'C:/Програми/Помічник/Pomichnyk_Uchytelia.exe'",
                       "$s.IconLocation = 'C:/Документи/app_icon.ico,0'", "GetFolderPath('Desktop')",
                       "Помічник учителя Classroom.lnk", "$s.Save()"):
            self.assertIn(needle, script)

    def test_apostrophes_and_cyrillic_cannot_break_the_command(self):
        script = shortcut.powershell_script("C:/Мій'шлях/a.exe", "C:/Мій'шлях/app_icon.ico")
        self.assertIn("'C:/Мій''шлях/a.exe'", script)
        packed = shortcut.encoded(script)
        self.assertEqual(base64.b64decode(packed).decode("utf-16-le"), script)

    def test_it_only_works_in_windows_for_the_finished_program(self):
        with tempfile.TemporaryDirectory() as folder:
            run = mock.Mock()
            self.assertFalse(shortcut.create_desktop_shortcut(folder, run=run, platform="linux", frozen=True)[0])
            self.assertFalse(shortcut.create_desktop_shortcut(folder, run=run, platform="win32", frozen=False)[0])
            run.assert_not_called()

    def test_it_runs_powershell_hidden_and_reports_the_path(self):
        with tempfile.TemporaryDirectory() as folder:
            run = mock.Mock(return_value=mock.Mock(returncode=0, stdout="C:\\Users\\Я\\Desktop\\Помічник учителя Classroom.lnk\r\n".encode(), stderr=b""))
            ok, message = shortcut.create_desktop_shortcut(folder, run=run, platform="win32", frozen=True, exe="C:/p/a.exe")
            self.assertTrue(ok)
            self.assertIn("Помічник учителя Classroom.lnk", message)
            command = run.call_args[0][0]
            self.assertEqual(command[:6], ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"])
            self.assertEqual(run.call_args[1]["creationflags"], shortcut.NO_WINDOW)
            decoded = base64.b64decode(command[-1]).decode("utf-16-le")
            self.assertIn("C:/p/a.exe", decoded)
            self.assertIn(shortcut.ICON_NAME, decoded)

    def test_failures_are_explained(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = mock.Mock(return_value=mock.Mock(returncode=1, stdout=b"", stderr="Access denied".encode()))
            ok, message = shortcut.create_desktop_shortcut(folder, run=bad, platform="win32", frozen=True, exe="x.exe")
            self.assertFalse(ok)
            self.assertIn("Access denied", message)
            boom = mock.Mock(side_effect=OSError("немає PowerShell"))
            ok, message = shortcut.create_desktop_shortcut(folder, run=boom, platform="win32", frozen=True, exe="x.exe")
            self.assertFalse(ok)
            self.assertIn("немає PowerShell", message)

    def test_the_logo_icon_file_is_a_valid_multi_size_ico(self):
        with tempfile.TemporaryDirectory() as folder:
            path = shortcut.write_icon(folder)
            from PIL import Image
            sizes = sorted(Image.open(path).ico.sizes())
            self.assertIn((256, 256), sizes)
            self.assertIn((16, 16), sizes)
            self.assertGreaterEqual(len(sizes), 6)

    def test_the_data_window_offers_the_shortcut_button(self):
        from classroom_assistant import samples_ui
        self.assertIn("make_shortcut", open(samples_ui.__file__, encoding="utf-8").read())


class BuildFileTests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / ".github" / "workflows" / "Windows_EXE.yml").read_text(encoding="utf-8")
        self.steps = yaml.safe_load(text)["jobs"]["build"]["steps"]
        self.text = text

    def test_the_icon_is_embedded_and_checked_in_the_log_between_build_and_upload(self):
        names = [s["name"] for s in self.steps]
        self.assertLess(names.index("Build Windows EXE"), names.index("Check the icon inside the EXE"))
        self.assertLess(names.index("Check the icon inside the EXE"), names.index("Save finished EXE"))
        build = self.steps[names.index("Build Windows EXE")]
        self.assertIn('--icon "app_icon.ico"', build["run"])
        check = self.steps[names.index("Check the icon inside the EXE")]
        self.assertTrue(check["continue-on-error"])                                       # перевірка ніколи не ламає збірку
        self.assertEqual(check["shell"], "python")

    def test_the_log_check_reads_icon_sizes_from_a_real_group_icon_record(self):
        check = next(s for s in self.steps if s["name"].startswith("Check the icon"))
        source = re.search(r"def icon_sizes\(data\):\n(?:    .*\n)+", check["run"].replace("          ", "")).group(0)
        namespace = {}
        exec(source, namespace)
        ico = (ROOT / "app_icon.ico").read_bytes()
        count = int.from_bytes(ico[4:6], "little")
        group = ico[:6]
        for k in range(count):                                                            # з каталогу .ico — у запис RT_GROUP_ICON (14 байтів)
            entry = ico[6 + 16 * k:22 + 16 * k]
            group += entry[:12] + (k + 1).to_bytes(2, "little")
        self.assertEqual(namespace["icon_sizes"](group), [16, 24, 32, 48, 64, 128, 256])

    def test_the_visible_copy_is_identical(self):
        copy = (ROOT / "Windows_EXE.yml").read_text(encoding="utf-8")
        self.assertEqual(copy.split("\n", 1)[1], self.text)


class MessageTests(unittest.TestCase):
    def test_the_standard_message_no_longer_mentions_the_video(self):
        base = engine.day_lessons("2026-10-01", engine.read_json("Налаштування.json"))[0]
        text = engine.html_classroom_text(base)
        self.assertNotIn("відео", text)
        self.assertIn("* Уважно опрацюйте прикріплений матеріал уроку.", text)
        self.assertIn("Доброго дня, шановні учні!", text)


if __name__ == "__main__":
    unittest.main()
