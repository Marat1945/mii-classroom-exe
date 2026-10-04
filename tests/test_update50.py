"""5.3: одне вікно замість дублікатів, пошук будь-якого населеного пункту, повний листок, Друга світова й історія України."""
import json
import time
import tkinter as tk
import unittest
import urllib.error
from datetime import date
from unittest import mock

from test_update44 import TempProgram
from test_update48 import FakeResponse, TREE, alert, location

from classroom_assistant import air_alerts as aa
from classroom_assistant import alert_ui, calendar_leaf, day_facts, download_setup_ui, engine, geocode, gui, lecture_inbox

LUBNY = {"name": "Лубни", "oblast": "Полтавська область", "raion": "Лубенський район", "lat": 50.0186, "lon": 32.996}
NOMINATIM = [
    {"name": "Лубни", "lat": "50.0186", "lon": "32.9960",
     "address": {"city": "Лубни", "county": "Лубенський район", "state": "Полтавська область", "country_code": "ua"}},
    {"name": "Лубни", "lat": "49.5", "lon": "24.1",
     "address": {"village": "Лубни", "county": "Львівський район", "state": "Львівська область", "country_code": "ua"}},
    {"name": "Лубни", "lat": "50.0186", "lon": "32.9960",                                   # той самий — дубль
     "address": {"city": "Лубни", "county": "Лубенський район", "state": "Полтавська область", "country_code": "ua"}},
    {"name": "Lubny", "lat": "52", "lon": "21", "address": {"state": "Мазовецьке", "country_code": "pl"}},      # не Україна
    {"name": "Без координат", "lat": "x", "lon": "y", "address": {"state": "Київська область", "country_code": "ua"}},
    {"name": "Київ", "lat": "50.45", "lon": "30.52", "address": {"city": "Київ", "state": "Київ", "country_code": "ua"}},
]


def pump(app, n=15):
    for _ in range(n):
        app.update()
        time.sleep(0.01)


class GeocodeTests(unittest.TestCase):
    def test_the_request_asks_only_for_ukrainian_settlements_in_ukrainian(self):
        url = geocode.build_url("Лубни")
        for part in ("countrycodes=ua", "accept-language=uk", "featuretype=settlement", "addressdetails=1", "format=jsonv2"):
            self.assertIn(part, url)
        self.assertTrue(url.startswith("https://nominatim.openstreetmap.org/search?"))

    def test_results_become_places_without_duplicates_foreign_or_broken_entries(self):
        found = geocode.parse(NOMINATIM)
        self.assertEqual([item["label"] for item in found],
                         ["Лубни — Лубенський район, Полтавська область", "Лубни — Львівський район, Львівська область",
                          "Київ"])
        lubny = found[0]
        self.assertEqual((lubny["name"], lubny["oblast"], lubny["raion"]), ("Лубни", "Полтавська область", "Лубенський район"))
        self.assertEqual((lubny["lat"], lubny["lon"]), (50.0186, 32.996))
        self.assertEqual(found[2]["oblast"], "м. Київ")                              # Київ у довіднику програми — «м. Київ»
        self.assertEqual(geocode.parse(None), [])
        self.assertEqual(geocode.parse(["рядок", None, {}]), [])

    def test_search_returns_places_and_respects_the_service_rate_limit(self):
        sleeps, clock = [], [100.0]
        calls = []

        def opener(request, timeout=None):
            calls.append(request.get_header("User-agent"))
            return FakeResponse(NOMINATIM)
        geocode._last_request[0] = 99.8                                                # попередній запит був щойно
        found = geocode.search("Лубни", opener=opener, sleep=sleeps.append, now=lambda: clock[0])
        self.assertEqual(len(found), 3)
        self.assertTrue(sleeps and 0.8 < sleeps[0] <= geocode.MIN_INTERVAL)            # зачекали, щоб не частіше разу на секунду
        self.assertTrue(calls[0].startswith("PomichnykUchytelia/"))                    # назвалися, як вимагають правила сервісу

    def test_every_failure_is_explained_in_plain_words(self):
        def failing(error):
            def opener(request, timeout=None):
                raise error
            return opener
        geocode._last_request[0] = 0
        cases = ((failing(urllib.error.URLError("x")), "немає зв'язку"),
                 (failing(urllib.error.HTTPError("u", 429, "x", {}, None)), "помилкою 429"),
                 (lambda r, timeout=None: FakeResponse(b"<html>"), "незрозумілу"))
        for opener, expected in cases:
            with self.assertRaises(geocode.GeocodeError) as raised:
                geocode.search("Лубни", opener=opener, sleep=lambda s: None, now=lambda: 1e9)
            self.assertIn(expected, str(raised.exception))
        with self.assertRaises(geocode.GeocodeError):
            geocode.search("Л", opener=lambda *a, **k: None)                           # надто коротко: запиту не робимо


class PlaceModelTests(unittest.TestCase):
    def test_a_settlement_remembers_its_district_and_exact_coordinates(self):
        place = aa.clean_place(LUBNY)
        self.assertEqual((place["raion"], place["lat"], place["lon"]), ("Лубенський район", 50.0186, 32.996))
        self.assertEqual(aa.place_coordinates(place), (50.0186, 32.996))              # сонце — для самого міста, не для області
        self.assertEqual(aa.place_label(place), "Лубни (Лубенський район, Полтавська область)")
        self.assertEqual(aa.place_text(place), "Лубни")
        self.assertEqual(aa.place_label(aa.DEFAULT_PLACE), "Київ")

    def test_coordinates_outside_ukraine_or_garbage_are_ignored(self):
        self.assertNotIn("lat", aa.clean_place({"name": "X", "oblast": "Y", "lat": 10, "lon": 10}))
        self.assertNotIn("lat", aa.clean_place({"name": "X", "oblast": "Y", "lat": "а", "lon": None}))
        self.assertEqual(aa.clean_place("рядок"), aa.DEFAULT_PLACE)
        self.assertEqual(aa.clean_place(None)["name"], "Київ")


def tree_with_raions():
    return {"states": [
        {"regionId": "17", "regionName": "Полтавська область", "regionType": "State", "regionChildIds": [
            {"regionId": "171", "regionName": "Лубенський район", "regionType": "District", "regionChildIds": [
                {"regionId": "1711", "regionName": "Лубенська територіальна громада", "regionType": "Community"}]},
            {"regionId": "172", "regionName": "Кременчуцький район", "regionType": "District", "regionChildIds": []}]},
        {"regionId": "5", "regionName": "Львівська область", "regionType": "State", "regionChildIds": []}]}


class DistrictAlertTests(unittest.TestCase):
    def setUp(self):
        self.index = aa.walk_tree(tree_with_raions())

    def level(self, active, place=LUBNY):
        region = aa.find_region(self.index, aa.clean_place(place))
        return aa.evaluate_ukrainealarm(active, self.index, region).level

    def test_a_town_without_its_own_entry_is_placed_into_its_district(self):
        self.assertEqual(aa.find_region(self.index, aa.clean_place(LUBNY)), "171")

    def test_oblast_and_district_alerts_cover_the_town_while_a_neighbouring_district_is_only_yellow(self):
        self.assertEqual(self.level([alert("17")]), aa.RED)                           # на всю область
        self.assertEqual(self.level([alert("171")]), aa.RED)                          # на район
        self.assertEqual(self.level([alert("172")]), aa.YELLOW)                       # інший район тієї ж області
        self.assertEqual(self.level([alert("5")]), aa.NONE)                           # інша область
        self.assertEqual(self.level([]), aa.NONE)

    def test_without_the_district_the_oblast_is_used_and_alerts_in_ua_also_knows_the_district(self):
        bare = {"name": "Хутір", "oblast": "Полтавська область"}
        self.assertEqual(aa.find_region(self.index, aa.clean_place(bare)), "17")
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Лубенський район", "raion", "Полтавська область")], LUBNY).level,
                         aa.RED)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Кременчуцький район", "raion", "Полтавська область")], LUBNY).level,
                         aa.YELLOW)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Полтавська область")], LUBNY).level, aa.RED)


class SingleWindowTests(TempProgram):
    def setUp(self):
        super().setUp()
        for target, name in ((alert_ui, "show_toast"), (download_setup_ui, "show_toast")):
            patcher = mock.patch.object(target, name, side_effect=lambda p, text, *a, **k: self.toasts.append(text))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(download_setup_ui, "ROOT", gui.ROOT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def toplevels(self, title):
        return [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == title]

    def test_clicking_the_alert_picture_many_times_opens_the_window_only_once(self):
        for _ in range(5):
            self.app.alert_panel.event_generate("<Button-1>", x=30, y=30)
            self.app.update()
        self.assertEqual(len(self.toplevels("Повітряна тривога: місце й джерело даних")), 1)
        first = alert_ui.show_alert_setup(self.app)
        self.assertIs(first, alert_ui.show_alert_setup(self.app))                      # та сама, лише виноситься наперед

    def test_after_closing_the_window_can_be_opened_again(self):
        first = alert_ui.show_alert_setup(self.app)
        first.destroy()
        self.app.update()
        second = alert_ui.show_alert_setup(self.app)
        self.assertIsNot(first, second)
        self.assertEqual(len(self.toplevels("Повітряна тривога: місце й джерело даних")), 1)

    def test_the_other_new_windows_are_single_too(self):
        a, b = download_setup_ui.show_download_setup(self.app), download_setup_ui.show_download_setup(self.app)
        self.assertIs(a, b)
        self.assertEqual(len(self.toplevels("Куди зберігати файли від GPT")), 1)
        c, d = calendar_leaf.show_leaf_window(self.app), calendar_leaf.show_leaf_window(self.app)
        self.assertIs(c, d)
        self.assertEqual(len(self.toplevels("Листочок календаря")), 1)

    def test_a_second_click_brings_the_open_window_to_the_front(self):
        window = alert_ui.show_alert_setup(self.app)
        with mock.patch.object(window, "lift") as lift, mock.patch.object(window, "focus_force") as focus:
            self.assertIs(alert_ui.show_alert_setup(self.app), window)
        lift.assert_called_once()
        focus.assert_called_once()


class LeafWindowTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.app.geometry("1500x900")
        self.app.datevar.set("06.11.2026")
        self.app.update_day()
        pump(self.app)

    def test_a_click_on_the_small_leaf_opens_the_full_one_with_everything_on_it(self):
        self.app.leaf.event_generate("<Button-1>", x=20, y=20)
        pump(self.app)
        windows = [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == "Листочок календаря"]
        self.assertEqual(len(windows), 1)
        big = windows[0].leaf
        self.assertEqual(big.day, date(2026, 11, 6))
        self.assertEqual(big.shown, self.app.leaf.shown)                               # той самий вміст
        self.assertGreater(int(big.cget("height")), int(self.app.leaf.cget("height")))   # але крупніше
        self.assertIn(("event", "1943 р. — Радянські війська визволили Київ від німецької окупації"), big.shown)

    def test_changing_the_day_refreshes_the_open_big_leaf_too(self):
        window = calendar_leaf.show_leaf_window(self.app)
        self.app.datevar.set("22.06.2026")
        self.app.update_day()
        self.assertEqual(window.leaf.day, date(2026, 6, 22))
        self.assertTrue(any("німецько-радянської війни" in text for _, text in window.leaf.shown))

    def test_the_small_leaf_and_the_alert_are_completely_visible_above_the_bottom_row(self):
        app = self.app
        app.geometry("1500x1000")                                                        # програмі потрібно ≈960 пікселів висоти
        pump(app)
        buttons = [w for w in self._walk(app) if w.winfo_class() == "Button" and "СКИНУТИ ВСЕ" in str(w.cget("text"))]
        bottom_row_top = buttons[0].winfo_rooty()
        for widget in (app.leaf, app.alert_panel):
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom_row_top + 2, widget)
            self.assertGreaterEqual(widget.winfo_height(), int(widget.cget("height")) - 1)      # не підрізані
        app.geometry("1500x1020")                                                        # і на вищому: нічого не змінюється
        pump(app)
        for widget in (app.leaf, app.alert_panel):
            self.assertGreaterEqual(widget.winfo_height(), int(widget.cget("height")) - 1)

    @staticmethod
    def _walk(widget):
        out, stack = [], [widget]
        while stack:
            current = stack.pop()
            stack.extend(current.winfo_children())
            out.append(current)
        return out


class WarAndUkraineFirstTests(unittest.TestCase):
    def test_built_in_dates_are_real_dates_with_texts_and_sensible_years(self):
        seen = set()
        for (month, day), events in day_facts.BUILTIN_EVENTS.items():
            date(2000, month, day)                                                        # існуюча дата
            for year, text in events:
                self.assertTrue(1500 < year <= 2025 and len(text) > 15, (month, day, year))
                self.assertNotIn(text, seen)
                seen.add(text)
        self.assertGreaterEqual(len(seen), 90)                                         # вбудовано близько ста подій

    def test_the_key_dates_of_the_second_world_war_and_of_ukraine_are_there(self):
        wanted = {(6, 22): (1941, "німецько-радянської війни"), (9, 1): (1939, "Другої світової війни"),
                  (5, 8): (1945, "капітуляцію"), (11, 6): (1943, "визволили Київ"), (9, 19): (1941, "вступили до Києва"),
                  (10, 28): (1944, "вигнання німецьких військ"), (1, 22): (1918, "незалежність"),
                  (8, 24): (1991, "Акт незалежності"), (6, 30): (1941, "Акт відновлення"), (9, 29): (1941, "Бабиному Яру")}
        for key, (year, word) in wanted.items():
            self.assertTrue(any(y == year and word in text for y, text in day_facts.BUILTIN_EVENTS[key]), key)

    def test_second_world_war_and_ukrainian_history_come_before_other_events(self):
        facts = day_facts.Facts(events=[(1990, "відкрито торговий центр у далекому місті"),
                                        (1943, "розпочалась оборона міста під час німецько-радянської війни"),
                                        (1700, "у Києві відбулась подія, важлива для історії України"),
                                        (1975, "футбольний матч")])
        events = [text for kind, text in day_facts.compose(facts, 4, 5) if kind == "event"]
        self.assertTrue(events[0].startswith("1943 р."))                               # війна — першою
        self.assertTrue(events[1].startswith("1700 р."))                               # потім історія України
        self.assertTrue(events[-1].startswith(("1975 р.", "1990 р.")))                 # решта — наприкінці
        self.assertGreater(day_facts.event_score(1941, "бої", False), day_facts.event_score(1980, "бої", False))
        self.assertGreater(day_facts.event_score(1980, "x", True), day_facts.event_score(1980, "x", False))
        general_builtin = day_facts.event_score(1940, "Франція підписала перемир'я з Німеччиною", True)
        ukraine_wiki = day_facts.event_score(1941, "бої на західних рубежах України: німецько-радянська війна", False)
        self.assertGreater(ukraine_wiki, general_builtin)                              # українське з Вікіпедії — вище за загальне вбудоване
        self.assertGreater(day_facts.event_score(1941, "Напад на СРСР", True), general_builtin)
    def test_a_built_in_event_is_not_repeated_when_wikipedia_has_the_same_one(self):
        facts = day_facts.Facts(events=[(1943, "Радянські війська визволили Київ від німецької окупації (бої тривали)")])
        events = [text for kind, text in day_facts.compose(facts, 11, 6) if kind == "event"]
        self.assertEqual(len([t for t in events if "визволили Київ" in t]), 1)

    def test_events_start_with_a_capital_letter_and_the_year(self):
        facts = day_facts.parse_extract("== Події ==\n1941 — запеклі бої на підступах до міста.\n")
        self.assertEqual(day_facts.compose(facts, 4, 4)[0], ("event", "1941 р. — Запеклі бої на підступах до міста."))
        self.assertEqual(day_facts.capfirst("гетьман"), "Гетьман")
        self.assertEqual(day_facts.capfirst(""), "")

    def test_most_built_in_events_are_the_second_world_war_and_the_history_of_ukraine(self):
        events = [(year, text) for items in day_facts.BUILTIN_EVENTS.values() for year, text in items]
        relevant = [e for e in events if e[0] in day_facts.WWII_YEARS or any(w in e[1].casefold() for w in day_facts.UA_HISTORY_WORDS)]
        self.assertGreaterEqual(len(relevant) / len(events), 0.85)                      # переважна більшість — за темою
        self.assertGreaterEqual(sum(1 for y, _ in events if y in day_facts.WWII_YEARS), 40)

    def test_events_are_shown_in_full_up_to_150_characters_for_the_big_leaf(self):
        long_text = "Подія, що має досить довгий опис, який розповідає про кілька важливих обставин того дня, " \
                    "про учасників, місце й наслідки, а також про те, що було далі після цього"
        parsed = day_facts.parse_extract(f"== Події ==\n1648 — {long_text}\n")
        self.assertGreater(len(parsed.events[0][1]), 100)
        self.assertLessEqual(len(parsed.events[0][1]), 151)


class SettlementPickerTests(TempProgram):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(alert_ui, "show_toast", side_effect=lambda p, text, *a, **k: self.toasts.append(text))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = alert_ui.show_alert_setup(self.app)
        self.window.update()

    def wait_for(self, predicate, seconds=3):
        deadline = time.time() + seconds
        while not predicate() and time.time() < deadline:
            self.window.update()
            time.sleep(0.02)
        return predicate()

    def test_any_settlement_can_be_found_in_the_internet_and_chosen(self):
        window = self.window
        window.query.set("Лубни")
        with mock.patch.object(geocode, "search", return_value=geocode.parse(NOMINATIM)) as search:
            window.search_online()
            self.assertTrue(self.wait_for(lambda: window.search_status.get().startswith("Знайдено")))
        search.assert_called_once_with("Лубни")
        labels = list(window.places_box.get(0, "end"))
        self.assertEqual(labels[0], "Лубни — Лубенський район, Полтавська область")
        self.assertIn("Лубни — Львівський район, Львівська область", labels)
        window.places_box.selection_set(0)
        window.places_box.event_generate("<<ListboxSelect>>")
        window.update()
        self.assertEqual(window.chosen_var.get(), "Обрано: Лубни (Лубенський район, Полтавська область)")

    def test_the_chosen_town_is_saved_shown_under_the_picture_and_used_for_the_sun(self):
        kyiv_sun = self.app.leaf.data["sunrise"]
        window = self.window
        window.query.set("Лубни")
        with mock.patch.object(geocode, "search", return_value=geocode.parse(NOMINATIM)):
            window.search_online()
            self.wait_for(lambda: window.search_status.get().startswith("Знайдено"))
        window.places_box.selection_set(0)
        window.places_box.event_generate("<<ListboxSelect>>")
        window.save()
        saved = aa.load_settings(engine.DATA)["place"]
        self.assertEqual((saved["name"], saved["oblast"], saved["raion"]), ("Лубни", "Полтавська область", "Лубенський район"))
        self.assertEqual((saved["lat"], saved["lon"]), (50.0186, 32.996))
        self.assertTrue(any("Зараз обрано: Лубни" in t for t in self.app.alert_panel.text_items()))     # під малюнком
        self.assertNotEqual(self.app.leaf.data["sunrise"], kyiv_sun)
    def test_a_search_failure_is_explained_and_the_oblast_list_stays(self):
        window = self.window
        window.query.set("Лубни")
        with mock.patch.object(geocode, "search", side_effect=geocode.GeocodeError("немає зв'язку із сервісом пошуку")):
            window.search_online()
            self.assertTrue(self.wait_for(lambda: "Немає зв'язку" in window.search_status.get()))
        self.assertIn("області зі списку програми", window.search_status.get())

    def test_an_unknown_name_says_so(self):
        window = self.window
        window.query.set("Ґґґґґ")
        with mock.patch.object(geocode, "search", return_value=[]):
            window.search_online()
            self.assertTrue(self.wait_for(lambda: "не знайдено" in window.search_status.get()))

    def test_enter_runs_the_search_and_typing_alone_never_hits_the_internet(self):
        window = self.window
        window.query.set("Лубни")
        with mock.patch.object(geocode, "search", return_value=[]) as search:
            window.update()
            self.assertFalse(search.called)                                               # набір тексту не робить запитів
            entry = next(w for w in self._walk(window) if w.winfo_class() == "TEntry" and str(w.cget("show")) != "•")
            entry.focus_force()                                                           # клавіші Tk віддає віджету з фокусом
            window.update()
            entry.event_generate("<Return>")
            self.wait_for(lambda: search.called)
            self.assertTrue(search.called)

    @staticmethod
    def _walk(widget):
        out, stack = [], [widget]
        while stack:
            current = stack.pop()
            stack.extend(current.winfo_children())
            out.append(current)
        return out


class ExplorerIconBuildTests(unittest.TestCase):
    def test_a_visible_copy_of_the_build_file_is_shipped_for_manual_upload(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        copy = root / "Windows_EXE.yml"
        self.assertTrue(copy.is_file())
        self.assertEqual(copy.read_text(encoding="utf-8").split("\n", 1)[1],
                         (root / ".github" / "workflows" / "Windows_EXE.yml").read_text(encoding="utf-8"))
        self.assertIn('--icon "app_icon.ico"', copy.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
