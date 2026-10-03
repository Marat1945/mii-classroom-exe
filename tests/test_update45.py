"""4.8: «Тема» — найширший стовпець; меню й виділення мишею в усіх полях таблиці; обробка виділених уроків."""
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from unittest import mock

from test_update44 import TempProgram

from classroom_assistant import chatgpt_ui, dragselect, gui


class Ev:
    def __init__(self, widget=None, x=0, y=0, state=0):
        self.widget, self.x, self.y, self.state = widget, x, y, state
        self.x_root, self.y_root = x, y


class TableTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.app.geometry("1500x900")
        self.app.datevar.set("06.10.2026")
        self.app.update_day()
        self.pump()
        self.grid = self.app.grid
        self.rows = list(self.grid.get_children())
        self.assertGreaterEqual(len(self.rows), 7)

    def pump(self, n=15):
        for _ in range(n):
            self.app.update()
            time.sleep(0.01)

    def widths(self):
        return {c: int(self.grid.column(c, "width")) for c in self.app.grid_columns}

    def cell(self, row, column):
        x, y, w, h = self.grid.bbox(row, column)
        return Ev(self.grid, x + w // 2, y + h // 2)

    def popup(self, event):
        shown = []
        with mock.patch.object(tk.Menu, "tk_popup", lambda menu, x, y, entry="": shown.append(menu)):
            self.app._open_lesson_menu(event)
        return shown[-1]

    @staticmethod
    def labels(menu):
        return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) in ("command", "cascade")]

    # ---------- ширина стовпців ----------
    def test_topic_is_the_widest_column_and_the_only_one_that_stretches(self):
        self.app._fit_columns()
        widths = self.widths()
        self.assertEqual(max(widths, key=widths.get), "Тема")
        for column in self.app.grid_columns:
            self.assertEqual(bool(int(self.grid.column(column, "stretch"))), column == "Тема", column)
        self.assertLessEqual(sum(widths.values()), self.grid.winfo_width() + 2)

    def test_topic_takes_the_bulk_of_the_row_but_the_status_stays_readable(self):
        self.app._fit_columns()
        widths = self.widths()
        available = self.grid.winfo_width() - 6
        self.assertGreaterEqual(widths["Тема"], 0.45 * available)
        self.assertGreaterEqual(widths["Стан"], 150)
        self.app.geometry("1900x900")                                    # ширше вікно — «Тема» ще ширша
        self.pump()
        before = widths["Тема"]
        self.app._fit_columns()
        self.assertGreaterEqual(self.widths()["Тема"], before)

    def test_short_columns_never_cut_their_own_text_even_when_topics_are_long(self):
        self.app._fit_columns()
        style_font = ttk.Style().lookup("Treeview", "font") or "TkDefaultFont"
        try:
            font = tkfont.nametofont(style_font)
        except tk.TclError:
            font = tkfont.Font(font=style_font)
        widths = self.widths()
        for index, column in enumerate(self.app.grid_columns):
            if column in ("Тема", "Стан"):
                continue
            texts = [column] + [str(self.grid.item(r, "values")[index]) for r in self.rows]
            need = max(font.measure(x) for x in texts)
            self.assertGreaterEqual(widths[column], need + 8, column)           # «11 ІУ профіль» і заголовки видно повністю

    def test_a_long_status_keeps_its_width_before_the_topic_gets_the_rest(self):
        row = self.app.rows[0]
        self.app.state.setdefault("drafts", {})[row.unique_key] = {"id": "x", "created_at": 1.0}
        self.app.state["course_ids"][row.course_title] = "555"
        self.app.remote_classroom_entries["555"] = []
        self.app._last_sync_ts = time.time()
        self.app.update_day()
        self.app._fit_columns()
        status = self.grid.item(self.rows[0], "values")[6]
        self.assertIn("не знайдено", status)
        style_font = ttk.Style().lookup("Treeview", "font") or "TkDefaultFont"
        try:
            font = tkfont.nametofont(style_font)
        except tk.TclError:
            font = tkfont.Font(font=style_font)
        self.assertGreaterEqual(self.widths()["Стан"], min(font.measure(status) + 28, 260))

    def test_topic_stays_the_widest_even_in_a_narrow_window(self):
        self.app.geometry("1100x800")
        self.pump()
        self.app._fit_columns()
        widths = self.widths()
        self.assertEqual(max(widths, key=widths.get), "Тема")
        self.assertGreaterEqual(widths["Тема"], 260)

    def test_widths_follow_the_content_of_the_narrow_columns(self):
        self.app._fit_columns()
        widths = self.widths()
        self.assertLess(widths["№"], 80)
        self.assertLess(widths["КТП"], 90)
        self.assertGreaterEqual(widths["Потік"], 96)

    def test_manual_widths_are_remembered_and_can_be_reset_from_the_header_menu(self):
        with mock.patch.object(self.grid, "identify_region", return_value="separator"):
            self.app._column_drag_start(Ev(self.grid, 10, 8))
            self.grid.column("Курс Classroom", width=321)                       # вчитель потягнув межу
            self.app._column_drag_end(Ev(self.grid, 60, 8))
        saved = self.app.state["column_widths"]
        self.assertEqual(saved["Курс Classroom"], 321)
        self.grid.column("Тема", width=100)
        self.app._fit_columns()                                                 # збережене не перетирається автопідбором
        self.assertEqual(int(self.grid.column("Курс Classroom", "width")), 321)
        self.assertEqual(int(self.grid.column("Тема", "width")), saved["Тема"])
        self.app.reset_column_widths()
        self.assertNotIn("column_widths", self.app.state)
        widths = self.widths()
        self.assertEqual(max(widths, key=widths.get), "Тема")
        self.assertIn("тема найширша", self.toasts[-1])

    # ---------- права кнопка миші в усіх полях ----------
    def test_right_click_in_every_column_opens_the_lesson_menu_and_selects_the_row(self):
        for column in self.app.grid_columns:
            self.grid.selection_set(())
            menu = self.popup(self.cell(self.rows[1], column))
            self.assertEqual(self.grid.selection(), (self.rows[1],), column)
            labels = self.labels(menu)
            self.assertIn("Копіювати таблицю виділених уроків (Ctrl+C)", labels)
            self.assertIn("Лекції GPT для виділених уроків (1)…", labels)
            self.assertIn("Створити чернетки для виділених уроків (1)…", labels)
            self.assertIn("Прибрати ЛОКАЛЬНІ матеріали (Delete)", labels)

    def test_right_click_inside_a_multi_selection_keeps_it(self):
        self.grid.selection_set(self.rows[0:4])
        menu = self.popup(self.cell(self.rows[2], "Час"))
        self.assertEqual(self.grid.selection(), tuple(self.rows[0:4]))
        self.assertIn("Лекції GPT для виділених уроків (4)…", self.labels(menu))
        self.assertIn("Вставити копію у виділені уроки (4)", self.labels(menu))

    def test_right_click_on_the_header_gives_selection_columns_and_day_actions(self):
        x = self.cell(self.rows[0], "Потік").x
        self.assertEqual(self.grid.identify_region(x, 8), "heading")
        self.grid.selection_set(())
        menu = self.popup(Ev(self.grid, x, 8))
        labels = self.labels(menu)
        self.assertIn(f"Виділити всі уроки дня ({len(self.rows)}) — Ctrl+A", labels)
        self.assertIn("Ширину стовпців — автоматично (Тема найширша)", labels)
        self.assertIn("Порядок стовпців — за замовчуванням", labels)
        self.assertIn("Лекції GPT на весь день…", labels)
        self.assertFalse(any(x.startswith("Дії над виділеними") for x in labels))     # нічого не виділено
        self.grid.selection_set(self.rows[0:3])
        labels = self.labels(self.popup(Ev(self.grid, x, 8)))
        self.assertIn("Дії над виділеними уроками (3)", labels)

    def test_header_cascade_holds_the_same_actions_as_the_row_menu(self):
        self.grid.selection_set(self.rows[0:2])
        menu = self.popup(Ev(self.grid, self.cell(self.rows[0], "Тема").x, 8))
        index = next(i for i in range(menu.index("end") + 1)
                     if menu.type(i) == "cascade" and "Дії над виділеними" in menu.entrycget(i, "label"))
        sub = menu.nametowidget(menu.entrycget(index, "menu"))
        self.assertIn("Створити чернетки для виділених уроків (2)…", self.labels(sub))
        self.assertIn("Лекції GPT для виділених уроків (2)…", self.labels(sub))

    def test_empty_area_menu_offers_select_all_and_day_actions(self):
        self.app.geometry("1500x900")
        self.pump()
        blank_y = self.grid.winfo_height() - 4
        event = Ev(self.grid, 50, blank_y)
        if self.grid.identify_row(blank_y):
            self.skipTest("вікно замале: порожнього місця під рядками немає")
        labels = self.labels(self.popup(event))
        self.assertTrue(any(x.startswith("Виділити всі уроки дня") for x in labels))
        self.assertIn("Створити чернетки для всього дня…", labels)

    # ---------- виділення лівою кнопкою ----------
    def test_click_on_a_header_selects_the_whole_day_and_a_drag_still_moves_the_column(self):
        x = self.cell(self.rows[0], "Потік").x
        self.grid.selection_set(())
        self.app._column_drag_start(Ev(self.grid, x, 8))
        self.app._column_drag_end(Ev(self.grid, x + 2, 8))
        self.assertEqual(self.grid.selection(), tuple(self.rows))
        self.assertIn(f"Виділено всі уроки дня: {len(self.rows)}", self.toasts[-1])
        before = list(self.grid["displaycolumns"])
        self.grid.selection_set(self.rows[0:1])
        source_x, destination_x = self.cell(self.rows[0], "Час").x, self.cell(self.rows[0], "Тема").x
        self.app._column_drag_start(Ev(self.grid, source_x, 8))
        self.app._column_drag_end(Ev(self.grid, destination_x, 8))
        self.assertNotEqual(list(self.grid["displaycolumns"]), before)                  # перетягування — переставляє
        self.assertEqual(self.grid.selection(), (self.rows[0],))                         # і не виділяє все

    def test_holding_the_left_button_in_any_column_selects_a_range_of_rows(self):
        for column in self.app.grid_columns:
            self.grid.selection_set(())
            start, end = self.cell(self.rows[1], column), self.cell(self.rows[4], column)
            dragselect._press(start)
            dragselect._motion(end)
            self.assertEqual(self.grid.selection(), tuple(self.rows[1:5]), column)
            dragselect._motion(self.cell(self.rows[2], column))                          # тягнемо назад — діапазон зменшується
            self.assertEqual(self.grid.selection(), tuple(self.rows[1:3]), column)

    def test_holding_the_left_button_on_the_empty_area_draws_a_selection_band(self):
        last = self.grid.bbox(self.rows[-1])
        blank_y = last[1] + last[3] + 12
        if blank_y >= self.grid.winfo_height() or self.grid.identify_region(60, blank_y) != "nothing":
            self.skipTest("порожнього місця під рядками немає")
        self.grid.selection_set(())
        dragselect._press(Ev(self.grid, 60, blank_y))
        target = self.grid.bbox(self.rows[2])
        dragselect._motion(Ev(self.grid, 60, target[1] + target[3] // 2))
        self.assertEqual(self.grid.selection(), tuple(self.rows[2:]))                    # гумка від порожнього місця вгору

    def test_ctrl_a_selects_the_whole_day(self):
        self.assertTrue(self.grid.bind("<Control-a>"))
        self.grid.selection_set(())
        self.app._select_all_rows(announce=False)
        self.assertEqual(len(self.grid.selection()), len(self.rows))

    # ---------- обробка виділених ----------
    def test_gpt_lectures_for_the_selected_lessons_only(self):
        opened = []
        a, b = self.app.rows[0], self.app.rows[3]                                       # різні групи паралелей
        self.grid.selection_set((self.rows[0], self.rows[3]))
        with mock.patch("classroom_assistant.chatgpt_ui.open_day_dialog", side_effect=lambda app, lessons: opened.append(lessons)):
            self.app.chatgpt_batch(only=self.app.selected_rows())
            self.assertEqual([x.unique_key for x in opened[-1]], [a.unique_key, b.unique_key])
            self.grid.selection_set(self.rows[0:3])                                      # три паралелі однієї теми → одна задача
            self.app.chatgpt_batch(only=self.app.selected_rows())
            self.assertEqual(len(opened[-1]), 1)
            self.app.chatgpt_batch()                                                     # без вибору — увесь день, як і було
            self.assertGreater(len(opened[-1]), 2)

    def test_drafts_for_the_selected_lessons_only(self):
        for row in self.app.rows:
            self.app.state["course_ids"][row.course_title] = "1"
        asked = []
        self.grid.selection_set((self.rows[3], self.rows[4]))
        chosen = self.app.selected_rows()
        with mock.patch.object(gui.messagebox, "askyesno", side_effect=lambda t, m, **k: asked.append(m) or False):
            self.app.batch_drafts(only=chosen)
            self.assertIn("виділені уроки: 2", asked[-1])
            lines = [x for x in asked[-1].splitlines() if x.startswith("✓")]
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(row.stream in asked[-1] for row in chosen))
            self.assertNotIn(self.app.rows[0].stream + ":", asked[-1])
            self.app.batch_drafts()                                                      # увесь день
            self.assertGreater(len([x for x in asked[-1].splitlines() if x.startswith("✓")]), 2)
