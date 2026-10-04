"""4.9: «старий прилад» — деталі, живий циліндр шапки (стрілка, лампочка, відблиск), зв'язок з інтернетом, тема."""
import random
import threading
import time
import tkinter as tk
import unittest
from unittest import mock

from test_update36 import TkCase
from test_update44 import TempProgram

from classroom_assistant import connectivity, gui, retro_assets as assets, retro_header as rh, theme
from classroom_assistant.ui_kit import AccentButton
from classroom_assistant.window_ui import fit_work_window


class AssetTests(unittest.TestCase):
    def test_pillow_is_available_and_parts_have_the_expected_sizes(self):
        self.assertTrue(assets.available())
        self.assertEqual(assets.metal_image(300, 100).size, (300, 100))
        self.assertEqual(assets.dial_image(96).size, (96, 96))
        self.assertEqual(assets.button_image("normal").size, (48, 34))
        self.assertEqual(assets.rivet_image(12).size, (12, 12))
        self.assertEqual(assets.lamp_bezel_image(44).size, (44, 44))

    def test_metal_is_the_same_every_time_so_the_look_does_not_flicker(self):
        a, b = assets.metal_image(200, 80), assets.metal_image(200, 80)
        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertNotEqual(a.tobytes(), assets.metal_image(200, 80, seed=99).tobytes())

    def test_button_states_look_different_and_corners_are_transparent(self):
        normal, pressed = assets.button_image("normal"), assets.button_image("pressed")
        self.assertNotEqual(normal.tobytes(), pressed.tobytes())
        self.assertEqual(normal.getpixel((0, 0))[3], 0)                               # заокруглений кут
        self.assertGreater(normal.getpixel((24, 17))[3], 250)
        self.assertEqual(assets.plate_image(200, 60).getpixel((0, 0))[3], 0)


class InstrumentLogicTests(unittest.TestCase):
    def test_the_needle_points_right_with_internet_left_without_and_to_the_middle_when_unknown(self):
        self.assertGreater(rh.needle_target(True), 40)
        self.assertLess(rh.needle_target(False), -40)
        self.assertEqual(rh.needle_target(None), 0)

    def test_the_needle_wobbles_a_little_but_stays_on_its_side(self):
        for t in [i * 0.137 for i in range(200)]:
            self.assertLess(abs(rh.needle_wobble(True, t)), 6)
            self.assertLess(abs(rh.needle_wobble(False, t)), 2.5)                       # без зв'язку — дрібне тремтіння
            self.assertGreater(rh.needle_target(True) + rh.needle_wobble(True, t), 40)
            self.assertLess(rh.needle_target(False) + rh.needle_wobble(False, t), -40)

    def test_the_lamp_is_green_with_internet_red_without_and_flickers_only_slightly(self):
        values = [rh.lamp_intensity(i * 0.11) for i in range(300)]
        self.assertGreaterEqual(min(values), 0.72)
        self.assertLessEqual(max(values), 1.0)
        self.assertGreater(max(values) - min(values), 0.04)                             # мерехтить, а не стоїть
        self.assertLess(max(values) - min(values), 0.3)                                 # але ледь помітно
        for t in (0, 1.3, 4.2):
            ring, middle, core = rh.lamp_layers(True, t)[:3]
            self.assertGreater(core[1], core[0] + 40)                                   # зелений
            red = rh.lamp_layers(False, t)[-1]
            self.assertGreater(red[0], red[1] + 80)                                     # червоний
            amber = rh.lamp_layers(None, t)[-1]
            self.assertGreater(amber[0], amber[2])                                      # бурштиновий, поки не знаємо

    def test_the_glint_runs_left_to_right_and_leaves_the_title_as_it_was(self):
        width = 500
        self.assertEqual(rh.glint_color(250, 0.0, width), rh.BASE_TITLE)
        self.assertEqual(rh.glint_color(250, 1.0, width), rh.BASE_TITLE)
        early = [rh.glint_color(x, 0.25, width) for x in (50, 250, 450)]
        late = [rh.glint_color(x, 0.75, width) for x in (50, 250, 450)]
        brightness = lambda c: sum(c)
        self.assertEqual(max(range(3), key=lambda i: brightness(early[i])), 0)          # відблиск ліворуч
        self.assertEqual(max(range(3), key=lambda i: brightness(late[i])), 2)           # потім праворуч

    def test_the_glint_comes_every_ten_to_fifteen_seconds(self):
        delays = [rh.next_glint_delay_ms(random.Random(seed)) for seed in range(200)]
        self.assertTrue(all(10000 <= d <= 15000 for d in delays))
        self.assertGreater(len(set(delays)), 50)                                         # не один і той самий інтервал


class InstrumentWidgetTests(TkCase):
    def make(self, animate=False, rng=None):
        host = tk.Toplevel(self.root)
        host.geometry("1300x200+0+0")
        header = rh.InstrumentHeader(host, "Помічник учителя Classroom", "розклад • плани", "Розробник програми — тест",
                                     rng=rng, animate=animate)
        header.pack(fill="x")
        host.update()
        header.layout()

        def close():
            try:
                host.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        return header

    def test_the_header_draws_title_letter_by_letter_and_keeps_the_whole_title_for_readers(self):
        header = self.make()
        self.assertEqual(len(header._char_items), len("Помічник учителя Classroom"))
        full = [header.itemcget(i, "text") for i in header.find_withtag("title_full")]
        self.assertEqual(full, ["Помічник учителя Classroom"])
        author = [header.itemcget(i, "text") for i in header.find_withtag("author_text")]
        self.assertEqual(" ".join(author[0].split()), "Розробник програми — тест")

    def test_needle_and_lamp_follow_the_connection(self):
        header = self.make()
        header.set_online(True)
        for i in range(80):
            header.step(i * 0.07)
        self.assertGreater(header.angle, 35)
        green = {header.itemcget(item, "fill") for item in header._lamp}
        header._apply_lamp(1.0)
        online_core = header.itemcget(header._lamp[-1], "fill")
        header.set_online(False)
        for i in range(80):
            header.step(6 + i * 0.07)
        self.assertLess(header.angle, -35)
        header._apply_lamp(1.0)
        offline_core = header.itemcget(header._lamp[-1], "fill")
        self.assertNotEqual(online_core, offline_core)
        self.assertGreater(int(online_core[3:5], 16), int(online_core[1:3], 16))        # зелений канал сильніший
        self.assertGreater(int(offline_core[1:3], 16), int(offline_core[3:5], 16))      # червоний канал сильніший

    def test_the_needle_actually_moves_on_the_canvas(self):
        header = self.make()
        header.set_online(True)
        header.angle = 0
        header._apply_needle()
        straight = header.coords(header._needle)
        for i in range(60):
            header.step(i * 0.07)
        header._apply_needle()
        self.assertGreater(header.coords(header._needle)[2], straight[2] + 15)          # кінчик стрілки поїхав праворуч

    def test_glint_changes_letter_colours_and_then_restores_them(self):
        header = self.make()
        base = {header.itemcget(i, "fill") for i in header._char_items}
        self.assertEqual(len(base), 1)
        header._glint_start = 100.0
        header._apply_glint(100.6)                                                       # посеред відблиску
        self.assertGreater(len({header.itemcget(i, "fill") for i in header._char_items}), 1)
        header._apply_glint(102.0)                                                       # кінець
        self.assertEqual({header.itemcget(i, "fill") for i in header._char_items}, base)
        self.assertIsNone(header._glint_start)

    def test_glint_is_scheduled_within_ten_to_fifteen_seconds_after_each_run(self):
        scheduled = []
        header = self.make(animate=True, rng=random.Random(5))
        with mock.patch.object(header, "after", side_effect=lambda ms, fn=None: scheduled.append(ms) or "job"):
            header._start_glint()
        self.assertEqual(len(scheduled), 1)
        self.assertTrue(10000 <= scheduled[0] <= 15000, scheduled)
        self.assertIsNotNone(header._glint_start)


class ConnectivityTests(unittest.TestCase):
    def test_check_is_true_if_any_host_answers_and_false_otherwise(self):
        calls = []

        def connect(address, timeout=None):
            calls.append(address[0])
            if address[0] == "second.example":
                return mock.Mock()
            raise OSError("немає")
        with mock.patch.object(connectivity.socket, "create_connection", side_effect=connect):
            self.assertTrue(connectivity.check(0.1, hosts=(("first.example", 443), ("second.example", 443))))
            self.assertEqual(calls, ["first.example", "second.example"])
            self.assertFalse(connectivity.check(0.1, hosts=(("first.example", 443),)))

    def test_monitor_follows_changes_and_can_be_woken_at_once(self):
        answers = iter([True, False, True, True, True, True])
        seen = []
        monitor = connectivity.Monitor(probe=lambda: seen.append(1) or next(answers), interval=30)
        monitor.start()
        deadline = time.time() + 3
        while monitor.online is None and time.time() < deadline:
            time.sleep(0.01)
        self.assertIs(monitor.online, True)
        monitor.refresh_soon()                                                           # не чекати 30 с
        deadline = time.time() + 3
        while monitor.online is True and time.time() < deadline:
            time.sleep(0.01)
        self.assertIs(monitor.online, False)
        monitor.stop()

    def test_a_crashing_probe_means_offline_not_a_dead_thread(self):
        monitor = connectivity.Monitor(probe=lambda: 1 / 0, interval=30).start()
        deadline = time.time() + 3
        while monitor.online is None and time.time() < deadline:
            time.sleep(0.01)
        self.assertIs(monitor.online, False)
        monitor.stop()


class MainWindowWiringTests(TempProgram):
    def test_the_header_shows_the_state_that_the_monitor_reports(self):
        self.assertIsNone(self.app.header.online)
        self.app.net.online = True
        self.app._net_poll()
        self.assertIs(self.app.header.online, True)
        self.app.net.online = False
        self.app._net_poll()
        self.assertIs(self.app.header.online, False)

    def test_closing_the_program_stops_the_monitor(self):
        with mock.patch.object(self.app.net, "stop") as stop, mock.patch.object(self.app, "destroy"):
            self.app.on_close()
        stop.assert_called_once()

    def test_tests_never_touch_the_real_network(self):
        self.assertIsNone(self.app.net._thread)                                          # POMICHNYK_NO_OFFERS: потік не запущено


class ThemeTests(TkCase):
    def test_the_whole_program_gets_the_retro_look(self):
        self.assertTrue(theme.apply_theme(self.root))
        style = tk.ttk.Style(self.root) if hasattr(tk, "ttk") else __import__("tkinter.ttk").ttk.Style(self.root)
        layout = str(style.layout("TButton"))
        self.assertIn("Retro.Button.plate", layout)                                      # латунна пластина замість плоскої кнопки
        self.assertEqual(self.root.cget("bg"), theme.METAL)
        self.assertEqual(int(str(self.root.cget("bd"))), theme.BORDER_WIDTH)
        text = tk.Text(self.root)
        self.assertEqual(text.cget("bg"), theme.PARCH_LIGHT)                             # поля — пергамент
        self.assertEqual(tk.Listbox(self.root).cget("bg"), theme.PARCH_LIGHT)
        dialog = tk.Toplevel(self.root)
        self.assertEqual(dialog.cget("bg"), theme.METAL)                                 # усі вікна мають металеву рамку
        self.assertEqual(int(str(dialog.cget("bd"))), theme.BORDER_WIDTH)
        dialog.destroy()

    def test_every_sized_dialog_gets_four_rivets_without_breaking_its_layout(self):
        theme.apply_theme(self.root)
        dialog = tk.Toplevel(self.root)
        body = tk.ttk.Frame(dialog) if hasattr(tk, "ttk") else __import__("tkinter.ttk").ttk.Frame(dialog)
        body.pack(fill="both", expand=True)
        fit_work_window(dialog, "small")
        dialog.update()
        image, labels = dialog._rivets
        self.assertEqual(len(labels), 4)
        self.assertTrue(body.winfo_ismapped())
        dialog.destroy()

    def test_accent_buttons_are_raised_metal_plates(self):
        button = AccentButton(self.root, "Дія")
        self.assertEqual(str(button.cget("relief")), "raised")
        self.assertEqual(int(str(button.cget("bd"))), 3)
        button.destroy()

    def test_old_colour_names_still_exist_for_other_modules(self):
        for name in ("BG", "CARD", "INK", "MUTED", "BORDER", "BUTTON", "ACCENT", "SELECT", "HEADING", "FONT"):
            self.assertTrue(hasattr(theme, name), name)


if __name__ == "__main__":
    unittest.main()


class InfographicSampleTests(TkCase):
    def test_the_sample_is_a_real_picture_of_the_expected_size(self):
        import io
        from PIL import Image
        from classroom_assistant.infographic_sample_data import sample_bytes
        image = Image.open(io.BytesIO(sample_bytes()))
        self.assertEqual(image.size, (1536, 1024))
        self.assertEqual(image.format, "JPEG")

    def test_samples_window_has_the_infographic_tab_with_preview_and_save(self):
        from classroom_assistant import samples_ui
        window = samples_ui.show_samples(self.root)

        def close():
            try:
                window.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        window.update()
        book = next(w for w in window.winfo_children() if w.winfo_class() == "TNotebook")
        tabs = [book.tab(i, "text") for i in range(book.index("end"))]
        self.assertIn("Зразок інфографіки", tabs)
        frame = book.nametowidget(book.tabs()[tabs.index("Зразок інфографіки")])
        previews = [w for w in frame.winfo_children() if w.winfo_class() == "TLabel" and w.cget("image")]
        self.assertTrue(previews)                                                          # є мініатюра зразка
        self.assertIn("перейме стиль виконання", samples_ui.INFOGRAPHIC_NOTE)
        saved = []
        buttons = [w for w in frame.winfo_children()[1].winfo_children()]
        with mock.patch.object(samples_ui.filedialog, "asksaveasfilename", return_value=str(__import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "s.jpg")) as ask, \
                mock.patch.object(samples_ui.messagebox, "showinfo"):
            buttons[0].invoke()
        self.assertTrue(ask.called)
