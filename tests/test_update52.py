"""5.5: оформлення як в оригіналі — вікна повідомлень, контекстні меню, рамка, таблички, заклепки, смугаста таблиця."""
import time
import tkinter as tk
import unittest
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from unittest import mock

from test_update36 import TkCase
from test_update44 import TempProgram

from classroom_assistant import lesson_marks, materials_ui, retro_menu, theme, themed_dialogs


def pump(widget, n=10):
    for _ in range(n):
        widget.update()
        time.sleep(0.01)


BOX = {name: themed_dialogs._make(name) for name in themed_dialogs.KIND_FOR}        # самі вікна програми, а не заглушки тестів


def dialogs(root):
    return [w for w in root.winfo_children() if w.winfo_class() == "Toplevel" and hasattr(w, "finish")]


class ThemedMessageBoxTests(TkCase):
    def setUp(self):
        super().setUp()
        theme.apply_theme(self.root)

    def answer(self, call, press=None, key=None):
        """Показати вікно, у момент показу натиснути кнопку чи клавішу; повернути результат функції."""
        outcome = {}

        def act():
            window = dialogs(self.root)[0]
            outcome["window"] = window
            outcome["text"] = window.message_widget.cget("text") if isinstance(window.message_widget, ttk.Label) else None
            outcome["buttons"] = list(window.buttons)
            outcome["long_text"] = window.message_widget.get("1.0", "end") if isinstance(window.message_widget, tk.Text) else None
            outcome["kind"] = type(window.message_widget)
            outcome["title"] = window.title()
            outcome["plate"] = bool(getattr(window, "_plate_images", None))
            outcome["icon"] = hasattr(window, "_icon_image")
            if press:
                window.buttons[press].invoke()
            else:
                window.focus_force()                                                  # без оконного менеджера фокус треба дати самому
                window.update()
                window.event_generate(key)

        def watchdog():                                                               # зависле вікно не повинне блокувати весь прогін
            for window in dialogs(self.root):
                window.finish("ЗАВИСЛО")
        self.root.after(120, act)
        self.root.after(2500, watchdog)
        value = call()
        self.assertNotEqual(value, "ЗАВИСЛО", "вікно не закрилось від натискання")
        return value, outcome

    def test_the_standard_windows_are_replaced_by_the_programs_own(self):
        originals = {n: themed_dialogs._ORIGINAL[n] for n in themed_dialogs.KIND_FOR}
        with mock.patch.multiple(messagebox, **originals):
            themed_dialogs.install()
            for name in themed_dialogs.KIND_FOR:
                self.assertEqual(getattr(messagebox, name).__name__, name)
                self.assertIsNot(getattr(messagebox, name), originals[name])

    def test_yes_and_no_return_true_and_false_like_the_original(self):
        value, seen = self.answer(lambda: BOX['askyesno']("Питання", "Продовжити?", parent=self.root), press="✔  Так")
        self.assertIs(value, True)
        self.assertEqual(seen["buttons"], ["✔  Так", "✖  Ні"])
        self.assertEqual(seen["text"], "Продовжити?")
        value, _ = self.answer(lambda: BOX['askyesno']("Питання", "Продовжити?", parent=self.root), press="✖  Ні")
        self.assertIs(value, False)

    def test_every_kind_of_window_returns_what_the_standard_one_returns(self):
        cases = ((lambda: BOX['showinfo']("a", "b", parent=self.root), "OK", "ok"),
                 (lambda: BOX['showwarning']("a", "b", parent=self.root), "OK", "ok"),
                 (lambda: BOX['showerror']("a", "b", parent=self.root), "OK", "ok"),
                 (lambda: BOX['askokcancel']("a", "b", parent=self.root), "OK", True),
                 (lambda: BOX['askokcancel']("a", "b", parent=self.root), "Скасувати", False),
                 (lambda: BOX['askretrycancel']("a", "b", parent=self.root), "Повторити", True),
                 (lambda: BOX['askquestion']("a", "b", parent=self.root), "✔  Так", "yes"),
                 (lambda: BOX['askquestion']("a", "b", parent=self.root), "✖  Ні", "no"),
                 (lambda: BOX['askyesnocancel']("a", "b", parent=self.root), "Скасувати", None),
                 (lambda: BOX['askyesnocancel']("a", "b", parent=self.root), "✖  Ні", False))
        for call, button, expected in cases:
            value, _ = self.answer(call, press=button)
            self.assertEqual(value, expected, button)

    def test_enter_accepts_the_default_and_escape_cancels(self):
        value, _ = self.answer(lambda: BOX['askyesno']("a", "b", parent=self.root), key="<Return>")
        self.assertIs(value, True)
        value, _ = self.answer(lambda: BOX['askyesno']("a", "b", parent=self.root), key="<Escape>")
        self.assertIs(value, False)
        value, _ = self.answer(lambda: BOX['askyesno']("a", "b", default="no", parent=self.root), key="<Return>")
        self.assertIs(value, False)                                                   # default="no" шанується

    def test_the_window_has_a_metal_title_plate_an_icon_and_a_modal_grab(self):
        _, seen = self.answer(lambda: BOX['askyesno']("Пакетна підготовка чернеток", "Текст", parent=self.root), press="✔  Так")
        self.assertEqual(seen["title"], "Пакетна підготовка чернеток")
        self.assertTrue(seen["plate"])
        self.assertTrue(seen["icon"])

    def test_a_long_report_goes_into_a_scrollable_field_and_is_never_cut(self):
        report = "\n".join(f"Рядок {k}: курс прочитано" for k in range(40))
        _, seen = self.answer(lambda: BOX['showinfo']("Звіт", report, parent=self.root), press="OK")
        self.assertIs(seen["kind"], tk.Text)
        self.assertIn("Рядок 39", seen["long_text"])
        self.assertIsNone(seen["text"])

    def test_the_detail_is_appended_and_without_a_window_the_original_is_used(self):
        _, seen = self.answer(lambda: BOX['showinfo']("a", "Головне", detail="Подробиці", parent=self.root), press="OK")
        self.assertIn("Подробиці", seen["text"])
        with mock.patch.object(tk, "_default_root", None), \
                mock.patch.dict(themed_dialogs._ORIGINAL, {"showinfo": mock.Mock(return_value="ok")}):
            self.assertEqual(themed_dialogs._show("showinfo", "a", "b"), "ok")


class ThemedMenuTests(TkCase):
    def setUp(self):
        super().setUp()
        theme.apply_theme(self.root)
        self.addCleanup(retro_menu.close_all)
        self.calls = []
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Створити чернетку", command=lambda: self.calls.append("draft"))
        self.menu.add_command(label="Відкрити Word", command=lambda: self.calls.append("word"))
        self.menu.add_separator()
        self.menu.add_command(label="Властивості уроку", state="disabled", command=lambda: self.calls.append("props"))
        self.sub = tk.Menu(self.menu, tearoff=0)
        self.sub.add_command(label="Усі готові", command=lambda: self.calls.append("all"))
        self.menu.add_cascade(label="Дії над виділеними (2)", menu=self.sub)

    def popup(self):
        self.menu.tk_popup(200, 150)
        self.root.update()
        return retro_menu._open[0]

    def test_all_menus_of_the_program_use_the_themed_popup(self):
        self.assertIs(tk.Menu.tk_popup, retro_menu.popup)
        self.assertIsNot(tk.Menu.tk_popup, retro_menu._original_tk_popup)

    def test_the_popup_shows_every_entry_with_icons_and_a_brass_separator(self):
        window = self.popup()
        self.assertEqual([r["item"]["label"] for r in window.rows],
                         ["Створити чернетку", "Відкрити Word", "Властивості уроку", "Дії над виділеними (2)"])
        self.assertEqual(len(retro_menu._open), 1)
        self.assertEqual(window.cget("bg"), retro_menu.METAL)
        seps = [w for w in window.winfo_children()[0].winfo_children() if w.winfo_class() == "Frame" and int(w.cget("height")) == 2]
        self.assertEqual(len(seps), 1)
        self.assertEqual(retro_menu.icon_for("Відкрити Word")[0], "W")
        self.assertEqual(retro_menu.icon_for("Скасувати")[1], "#C4342C")
        self.assertEqual(retro_menu.icon_for("щось нове")[0], "•")

    def test_clicking_an_entry_closes_the_menu_and_then_runs_its_command(self):
        window = self.popup()
        retro_menu._activate(window, window.rows[0])
        self.assertEqual(retro_menu._open, [])
        self.assertEqual(self.calls, [])                                                # команда — вже після закриття
        pump(self.root, 8)
        self.assertEqual(self.calls, ["draft"])

    def test_a_disabled_entry_does_nothing(self):
        window = self.popup()
        retro_menu._activate(window, window.rows[2])
        pump(self.root, 8)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(retro_menu._open), 1)

    def test_a_submenu_opens_beside_the_row_and_its_command_works(self):
        window = self.popup()
        cascade = window.rows[3]
        retro_menu._hover(window, cascade)
        self.root.update()
        self.assertEqual(len(retro_menu._open), 2)
        child = retro_menu._open[1]
        self.assertGreaterEqual(child.winfo_rootx(), window.winfo_rootx() + window.winfo_width() - 14)     # трохи перекриває край батька
        self.assertLessEqual(child.winfo_rootx(), window.winfo_rootx() + window.winfo_width() + 2)
        retro_menu._hover(window, window.rows[0])                                       # курсор пішов на інший пункт
        self.assertEqual(len(retro_menu._open), 1)
        retro_menu._hover(window, cascade)
        retro_menu._activate(retro_menu._open[1], retro_menu._open[1].rows[0])
        pump(self.root, 8)
        self.assertEqual(self.calls, ["all"])
        self.assertEqual(retro_menu._open, [])

    def test_hover_highlights_one_row_and_escape_closes_everything(self):
        window = self.popup()
        retro_menu._hover(window, window.rows[1])
        self.assertEqual(window.rows[1]["row"].cget("bg"), retro_menu.PARCH_HOVER)
        self.assertEqual(window.rows[0]["row"].cget("bg"), retro_menu.PARCH)
        window.focus_force()                                                              # без оконного менеджера фокус дає тест
        window.update()
        window.event_generate("<Escape>")
        self.root.update()
        self.assertEqual(retro_menu._open, [])

    def test_an_empty_menu_shows_nothing_and_inside_detects_the_popup_area(self):
        empty = tk.Menu(self.root, tearoff=0)
        empty.tk_popup(10, 10)
        self.assertEqual(retro_menu._open, [])
        window = self.popup()
        self.assertTrue(retro_menu._inside(window, window.winfo_rootx() + 5, window.winfo_rooty() + 5))
        self.assertFalse(retro_menu._inside(window, window.winfo_rootx() + 9999, window.winfo_rooty()))

    def test_the_menu_stays_inside_the_screen(self):
        self.menu.tk_popup(self.root.winfo_screenwidth() - 3, self.root.winfo_screenheight() - 3)
        self.root.update()
        window = retro_menu._open[0]
        self.assertLessEqual(window.winfo_rootx() + window.winfo_width(), self.root.winfo_screenwidth() + 1)
        self.assertLessEqual(window.winfo_rooty() + window.winfo_height(), self.root.winfo_screenheight() + 1)


class FrameAndPlatesTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.app.geometry("1500x1000")
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        pump(self.app)

    def test_the_main_window_has_a_rusty_frame_with_rivets_in_the_border_zone(self):
        images, strips = self.app._frame_strips
        self.assertEqual(len(strips), 4)
        top, bottom, left, right = strips
        self.assertEqual(top.winfo_y(), 0)
        self.assertEqual(top.winfo_height(), theme.BORDER_WIDTH)
        self.assertEqual(left.winfo_width(), theme.BORDER_WIDTH)
        self.assertEqual(bottom.winfo_y() + bottom.winfo_height(), self.app.winfo_height())
        self.assertEqual(right.winfo_x() + right.winfo_width(), self.app.winfo_width())
        self.assertEqual(len(self.app._rivets[1]), 4)

    def test_the_frame_images_are_shared_between_windows_of_one_program(self):
        first = theme._strip_images(self.app)
        second = theme._strip_images(self.app)
        self.assertIs(first, second)

    def test_the_table_and_the_message_field_sit_in_riveted_metal_insets(self):
        for widget in (self.app.grid.master, self.app.desc.master):
            self.assertEqual(widget.winfo_class(), "Frame")
            self.assertEqual(len(widget._rivets), 4)
            self.assertEqual(str(widget.cget("bg")), "#4F5A50")

    def test_table_rows_are_striped_like_a_paper_ledger(self):
        children = self.app.grid.get_children()
        tags = [self.app.grid.item(i, "tags")[0] for i in children]
        for position, tag in enumerate(tags):
            if tag in ("odd", "even"):
                self.assertEqual(tag, "odd" if position % 2 else "even", position)
        odd = str(self.app.grid.tag_configure("odd", "background"))
        even = str(self.app.grid.tag_configure("even", "background"))
        self.assertNotEqual(odd, even)

    def test_dialogs_get_a_title_plate_above_their_content_and_the_same_frame(self):
        window = materials_ui.show_materials(self.app)
        window.update()
        plate = window._title_plate
        self.assertIs(window.pack_slaves()[0], plate)
        self.assertTrue(window._frame_strips)
        self.assertEqual(len(window._rivets[1]), 4)
        self.assertEqual(window.title(), "Навчальні матеріали")

    def test_windows_that_lay_out_with_grid_are_left_alone(self):
        window = tk.Toplevel(self.app)
        window.title("Сітка")
        ttk.Label(window, text="x").grid(row=0, column=0)
        theme.add_title_plate(window)
        self.assertIsNone(getattr(window, "_title_plate", None))

    def test_the_bell_is_never_taller_than_its_row(self):
        self.app.clock = lambda: datetime(2026, 10, 5, 11, 26)
        self.app.lesson_marks.refresh()
        pump(self.app, 6)
        label = self.app.lesson_marks.labels[0]
        box = self.app.grid.bbox("3")
        self.assertLessEqual(label.winfo_height(), box[3] - 1)
        self.assertGreaterEqual(label.winfo_height(), 16)


if __name__ == "__main__":
    unittest.main()
