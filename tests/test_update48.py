"""5.1: листочок календаря (сонце, Місяць, свята й події), панель повітряної тривоги, вужче поле повідомлення."""
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_update36 import TkCase
from test_update44 import TempProgram

from classroom_assistant import air_alerts as aa
from classroom_assistant import alert_ui, calendar_leaf, data_tools, day_facts, engine, gui, retro_assets as assets
from classroom_assistant import sun_moon as sm

KYIV = (50.45, 30.52)


class FakeResponse:
    def __init__(self, payload):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def minutes(text):
    hours, mins = text.split(":")
    return int(hours) * 60 + int(mins)


class SunAndMoonTests(unittest.TestCase):
    def test_kyiv_sun_times_match_the_astronomy(self):
        rise, sunset, length = sm.sun_summary(date(2026, 10, 4), *KYIV)
        self.assertTrue(minutes("06:55") <= minutes(rise) <= minutes("07:15"), rise)
        self.assertTrue(minutes("18:20") <= minutes(sunset) <= minutes("18:45"), sunset)
        self.assertTrue(minutes("11:15") <= minutes(length) <= minutes("11:40"), length)
        self.assertTrue(minutes("16:15") <= minutes(sm.sun_summary(date(2026, 6, 21), *KYIV)[2]) <= minutes("16:40"))
        self.assertTrue(minutes("07:50") <= minutes(sm.sun_summary(date(2026, 12, 21), *KYIV)[2]) <= minutes("08:10"))
        self.assertTrue(minutes("12:05") <= minutes(sm.sun_summary(date(2026, 3, 20), *KYIV)[2]) <= minutes("12:20"))

    def test_the_east_sees_the_sun_earlier_than_the_west(self):
        east = sm.sun_times(date(2026, 10, 4), 49.99, 36.23)[0]                 # Харків
        west = sm.sun_times(date(2026, 10, 4), 49.84, 24.03)[0]                 # Львів
        self.assertTrue(2400 < (west - east).total_seconds() < 3400)            # ≈ 12° довготи = ≈ 49 хвилин

    def test_polar_day_has_no_sunrise(self):
        self.assertIsNone(sm.sun_summary(date(2026, 6, 21), 80.0, 30.0))

    def test_ukraine_switches_to_summer_time_on_the_last_sunday_of_march_and_back_in_october(self):
        utc = lambda y, m, d, h, mi: datetime(y, m, d, h, mi, tzinfo=timezone.utc)
        self.assertEqual(sm.ukraine_offset(utc(2026, 3, 29, 0, 59)), timedelta(hours=2))
        self.assertEqual(sm.ukraine_offset(utc(2026, 3, 29, 1, 0)), timedelta(hours=3))
        self.assertEqual(sm.ukraine_offset(utc(2026, 10, 25, 0, 59)), timedelta(hours=3))
        self.assertEqual(sm.ukraine_offset(utc(2026, 10, 25, 1, 0)), timedelta(hours=2))
        self.assertEqual(sm.ukraine_offset(utc(2026, 1, 10, 12, 0)), timedelta(hours=2))

SAMPLE = """Подій
== Події ==
=== До XIX століття ===
1582 — у Римі після 4 жовтня одразу настало 15 жовтня: запроваджено григоріанський календар[1].
1648 року — гетьман Богдан Хмельницький розпочав боротьбу під Жовтими Водами.
44 до н. е. — давня подія, що не має значення.
=== XX століття ===
1957 — запущено перший штучний супутник Землі «Спутник-1».
== Народились ==
1970 — Ім'я Прізвище, письменник.
== Свята та пам'ятні дні ==
=== Національні ===
Україна: День ветеринарної служби[2]
=== Міжнародні ===
Всесвітній день тварин
Всесвітній тиждень космосу
=== Релігійні ===
Православна церква вшановує пам'ять апостола Кодрата.
=== Іменини ===
Хтось, Хтось
== Примітки ==
1. Щось.
"""


class DayFactsTests(unittest.TestCase):
    def test_the_page_title_and_request_use_the_ukrainian_wikipedia(self):
        self.assertEqual(day_facts.page_title(10, 4), "4 жовтня")
        self.assertEqual(day_facts.page_title(3, 9), "9 березня")
        url = day_facts.build_url(10, 4)
        self.assertTrue(url.startswith("https://uk.wikipedia.org/w/api.php?"))
        for part in ("explaintext=1", "exsectionformat=wiki", "redirects=1", "formatversion=2"):
            self.assertIn(part, url)

    def test_events_and_holidays_are_read_and_religious_or_birth_sections_are_skipped(self):
        facts = day_facts.parse_extract(SAMPLE)
        years = [year for year, _ in facts.events]
        self.assertEqual(years, [1582, 1648, 44, 1957])                          # «Народились» не потрапили
        self.assertNotIn("[1]", facts.events[0][1])
        self.assertEqual(facts.holidays, ["Україна: День ветеринарної служби", "Всесвітній день тварин",
                                          "Всесвітній тиждень космосу"])            # без церковних і іменин

    def test_unexpected_pages_give_empty_results_not_errors(self):
        self.assertEqual(day_facts.parse_extract("").events, [])
        self.assertEqual(day_facts.parse_extract("просто текст без розділів").holidays, [])
        self.assertEqual(day_facts.parse_extract(None).events, [])

    def test_long_items_are_shortened_at_a_word(self):
        text = day_facts.shorten("слово " * 40, 30)
        self.assertLessEqual(len(text), 31)
        self.assertTrue(text.endswith("…"))
        self.assertNotIn("сл…", text)

    def test_the_leaf_gets_ukrainian_holidays_first_and_ukraine_related_events_first(self):
        lines = day_facts.compose(day_facts.parse_extract(SAMPLE), 10, 5)
        holidays = [text for kind, text in lines if kind == "holiday"]
        events = [text for kind, text in lines if kind == "event"]
        self.assertEqual(holidays[0], "Всесвітній день учителів")                    # вбудований список
        self.assertLessEqual(len(holidays), 3)
        self.assertEqual(len(events), 4)                                              # на великому листку їх більше
        self.assertIn("Хмельницький", events[0])                                      # українське — першим
        self.assertTrue(events[0].startswith("1648 р. — "))
    def test_holidays_and_events_alternate_so_both_fit_on_the_leaf(self):
        lines = day_facts.compose(day_facts.parse_extract(SAMPLE), 10, 5)
        kinds = [kind for kind, _ in lines]
        self.assertEqual(kinds[:6], ["holiday", "event", "holiday", "event", "holiday", "event"])
        self.assertEqual([kind for kind, _ in day_facts.compose(None, 10, 5)], ["holiday"])
        only_events = day_facts.compose(day_facts.Facts(events=[(1648, "гетьман х")]), 4, 4)
        self.assertEqual([kind for kind, _ in only_events], ["event"])
    def test_built_in_dates_work_without_any_internet(self):
        for month, day, expected in ((8, 24, "День Незалежності України"), (1, 22, "День Соборності України"),
                                     (9, 1, "День знань"), (10, 1, "День захисників і захисниць України")):
            self.assertEqual(day_facts.compose(None, month, day)[0], ("holiday", expected))
        self.assertEqual(day_facts.compose(None, 4, 4), [])

    def test_duplicates_between_the_built_in_list_and_wikipedia_are_not_repeated(self):
        facts = day_facts.Facts(holidays=["Всесвітній день учителів", "День учителів в Україні"])
        holidays = [t for k, t in day_facts.compose(facts, 10, 5) if k == "holiday"]
        self.assertEqual(holidays.count("Всесвітній день учителів"), 1)

    def test_cache_round_trip_and_loader_never_blocks_or_crashes(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(day_facts.cached(folder, 10, 4))
            day_facts.store(folder, 10, 4, day_facts.parse_extract(SAMPLE))
            again = day_facts.cached(folder, 10, 4)
            self.assertEqual(len(again.events), 4)
            self.assertTrue(json.loads((Path(folder) / day_facts.CACHE_NAME).read_text(encoding="utf-8")))
            (Path(folder) / day_facts.CACHE_NAME).write_text("{ зіпсовано", encoding="utf-8")
            self.assertEqual(day_facts.read_cache(folder), {})                       # зіпсований кеш — не катастрофа

    def test_fetch_parses_the_api_answer_and_the_loader_caches_it_once(self):
        payload = {"query": {"pages": [{"title": "4 жовтня", "extract": SAMPLE}]}}
        calls = []

        def opener(request, timeout=None):
            calls.append(request.full_url)
            return FakeResponse(payload)
        with tempfile.TemporaryDirectory() as folder:
            loader = day_facts.Loader(folder, opener=opener)
            thread = loader.refresh_async(10, 4)
            thread.join(5)
            self.assertIn((10, 4), loader.updated)
            self.assertTrue(any("гетьман" in t.casefold() for _, t in loader.lookup(10, 4) if t))
            self.assertIsNone(loader.refresh_async(10, 4))                           # уже в кеші: удруге не качаємо
            self.assertEqual(len(calls), 1)

    def test_network_failures_leave_the_built_in_list(self):
        def broken(request, timeout=None):
            raise urllib.error.URLError("немає мережі")
        with tempfile.TemporaryDirectory() as folder:
            loader = day_facts.Loader(folder, opener=broken)
            loader.refresh_async(10, 5).join(5)
            self.assertFalse(loader.updated)
            self.assertEqual(loader.lookup(10, 5)[0], ("holiday", "Всесвітній день учителів"))
            self.assertIsNone(day_facts.Loader(folder, network=False).refresh_async(10, 6))

    def test_an_empty_page_is_not_cached_as_success(self):
        payload = {"query": {"pages": [{"title": "x", "missing": True}]}}
        with self.assertRaises(ValueError):
            day_facts.fetch(10, 4, opener=lambda r, timeout=None: FakeResponse(payload))


TREE = {"states": [
    {"regionId": "31", "regionName": "м. Київ", "regionType": "State", "regionChildIds": []},
    {"regionId": "14", "regionName": "Київська область", "regionType": "State", "regionChildIds": [
        {"regionId": "141", "regionName": "Бучанський район", "regionType": "District", "regionChildIds": [
            {"regionId": "1411", "regionName": "Бучанська територіальна громада", "regionType": "Community"}]},
        {"regionId": "142", "regionName": "Вишгородський район", "regionType": "District", "regionChildIds": []}]},
    {"regionId": "5", "regionName": "Львівська область", "regionType": "State", "regionChildIds": []}]}


def alert(region_id, kind="AIR"):
    return {"regionId": region_id, "activeAlerts": [{"regionId": region_id, "type": kind}]}


class UkraineAlarmLogicTests(unittest.TestCase):
    def setUp(self):
        self.index = aa.walk_tree(TREE)

    def level(self, active, place):
        region = aa.find_region(self.index, place)
        return aa.evaluate_ukrainealarm(active, self.index, region).level

    def test_names_are_compared_without_decorations(self):
        self.assertEqual(aa.norm("м. Київ"), aa.norm("Київ"))
        self.assertEqual(aa.norm("Київська область"), aa.norm("Київська обл."))
        self.assertEqual(aa.norm("Бучанська територіальна громада"), aa.norm("бучанська громада"))
        self.assertEqual(aa.norm("Нові Санжари"), aa.norm("нові санжари"))

    def test_kyiv_city_is_found_and_alert_in_it_is_red(self):
        kyiv = aa.DEFAULT_PLACE
        self.assertEqual(aa.find_region(self.index, kyiv), "31")
        self.assertEqual(self.level([alert("31")], kyiv), aa.RED)
        self.assertEqual(self.level([], kyiv), aa.NONE)
        self.assertEqual(self.level([alert("5")], kyiv), aa.NONE)                  # тривога у Львівській області Києва не стосується

    def test_an_alert_declared_for_the_whole_oblast_covers_every_community_in_it(self):
        place = {"name": "Бучанська територіальна громада", "oblast": "Київська область"}
        self.assertEqual(aa.find_region(self.index, place), "1411")
        self.assertEqual(self.level([alert("14")], place), aa.RED)                  # на рівні області
        self.assertEqual(self.level([alert("141")], place), aa.RED)                 # на рівні району
        self.assertEqual(self.level([alert("1411")], place), aa.RED)                # саме в громаді

    def test_other_threats_and_neighbouring_alerts_are_yellow_not_red(self):
        place = {"name": "Бучанська територіальна громада", "oblast": "Київська область"}
        self.assertEqual(self.level([alert("1411", "ARTILLERY")], place), aa.YELLOW)
        self.assertEqual(self.level([alert("1411", "URBAN_FIGHTS")], place), aa.YELLOW)
        self.assertEqual(self.level([alert("142")], place), aa.YELLOW)              # тривога в іншому районі тієї ж області
        self.assertEqual(self.level([alert("142", "ARTILLERY")], place), aa.NONE)   # чужа не повітряна загроза не лякає
        self.assertEqual(self.level([alert("142"), alert("1411")], place), aa.RED)  # власна важливіша за сусідню

    def test_unknown_place_falls_back_to_the_oblast_or_is_reported(self):
        self.assertEqual(aa.find_region(self.index, {"name": "Невідомий пункт", "oblast": "Львівська область"}), "5")
        self.assertIsNone(aa.find_region(self.index, {"name": "Nowhere", "oblast": "Atlantis"}))

    def test_broken_tree_shapes_do_not_crash(self):
        self.assertEqual(aa.walk_tree({}), {})
        self.assertEqual(aa.walk_tree([{"x": 1}, "рядок", None]), {})
        self.assertEqual(len(aa.walk_tree([TREE["states"][0]])), 1)


def location(title, kind="oblast", oblast=None, alert_type="air_raid", finished=None):
    return {"location_title": title, "location_type": kind, "location_oblast": oblast or title,
            "alert_type": alert_type, "finished_at": finished}


class AlertsInUaLogicTests(unittest.TestCase):
    def test_levels(self):
        kyiv, oblast = aa.DEFAULT_PLACE, {"name": "Бучанський район", "oblast": "Київська область"}
        self.assertEqual(aa.evaluate_alerts_in_ua([location("м. Київ")], kyiv).level, aa.RED)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Київська область")], kyiv).level, aa.NONE)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Київська область")], oblast).level, aa.RED)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Бучанський район", "raion", "Київська область")], oblast).level, aa.RED)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("Вишгородський район", "raion", "Київська область")], oblast).level,
                         aa.YELLOW)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("м. Київ", alert_type="chemical")], kyiv).level, aa.YELLOW)
        self.assertEqual(aa.evaluate_alerts_in_ua([location("м. Київ", finished="2026-10-04T10:00:00Z")], kyiv).level, aa.NONE)
        self.assertEqual(aa.evaluate_alerts_in_ua([], kyiv).level, aa.NONE)
        self.assertEqual(aa.evaluate_alerts_in_ua([None, "x", {}], kyiv).level, aa.NONE)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def settings(self, provider=aa.UKRAINE_ALARM, key="секрет-123", place=None):
        return {"provider": provider, "key": key, "place": place or dict(aa.DEFAULT_PLACE)}

    def opener(self, alerts, calls=None, tree=TREE):
        def open_(request, timeout=None):
            if calls is not None:
                calls.append((request.full_url, request.get_header("Authorization")))
            if request.full_url.endswith("/regions"):
                return FakeResponse(tree)
            if "alerts.in.ua" in request.full_url:
                return FakeResponse({"alerts": alerts})
            return FakeResponse(alerts)
        return open_

    def test_without_a_key_it_says_there_is_no_data_and_touches_no_network(self):
        called = []
        status = aa.fetch_status(self.settings(key=""), self.folder, opener=lambda *a, **k: called.append(1))
        self.assertEqual(status.level, aa.UNKNOWN)
        self.assertIn("ключ", status.detail)
        self.assertEqual(called, [])

    def test_ukraine_alarm_flow_sends_the_key_and_reuses_the_regions_cache(self):
        calls = []
        status = aa.fetch_status(self.settings(), self.folder, opener=self.opener([alert("31")], calls))
        self.assertEqual((status.level, status.source), (aa.RED, "Ukraine Alarm (державна система)"))
        self.assertTrue(status.checked_at)
        self.assertTrue(all(auth == "секрет-123" for _, auth in calls))
        self.assertEqual([u.rsplit("/", 1)[-1] for u, _ in calls], ["regions", "alerts"])
        aa.fetch_status(self.settings(), self.folder, opener=self.opener([], calls))
        self.assertEqual([u.rsplit("/", 1)[-1] for u, _ in calls].count("regions"), 1)    # дерево з кешу, а не знову
        self.assertTrue((self.folder / aa.REGIONS_NAME).exists())

    def test_alerts_in_ua_flow_uses_a_bearer_token(self):
        calls = []
        status = aa.fetch_status(self.settings(aa.ALERTS_IN_UA), self.folder,
                                 opener=self.opener([location("м. Київ")], calls))
        self.assertEqual(status.level, aa.RED)
        self.assertEqual(calls[0][1], "Bearer секрет-123")

    def test_every_failure_means_no_data_and_never_no_alert(self):
        def http_error(code):
            def open_(request, timeout=None):
                raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)
            return open_

        def offline(request, timeout=None):
            raise urllib.error.URLError("немає мережі")
        cases = ((http_error(401), "ключ не прийнято"), (http_error(403), "ключ не прийнято"),
                 (http_error(429), "забагато запитів"), (http_error(500), "помилкою 500"),
                 (offline, "немає зв'язку"), (lambda r, timeout=None: FakeResponse(b"<html>"), "незрозумілу"))
        for opener, expected in cases:
            for provider in (aa.UKRAINE_ALARM, aa.ALERTS_IN_UA):
                status = aa.fetch_status(self.settings(provider), tempfile.mkdtemp(), opener=opener)
                self.assertEqual(status.level, aa.UNKNOWN, (provider, expected))
                self.assertIn(expected, status.detail.casefold())

    def test_a_place_the_source_does_not_know_is_reported_not_guessed(self):
        place = {"name": "Nowhere", "oblast": "Atlantis"}
        status = aa.fetch_status(self.settings(place=place), self.folder, opener=self.opener([]))
        self.assertEqual(status.level, aa.UNKNOWN)
        self.assertIn("оберіть його заново", status.detail)

    def test_stale_or_missing_data_never_shows_no_alert(self):
        fresh = aa.Status(aa.NONE, "Тривоги немає", "", checked_at=1000.0)
        self.assertEqual(aa.effective_status(fresh, now=1100.0).level, aa.NONE)
        self.assertEqual(aa.effective_status(fresh, now=1000.0 + aa.MAX_AGE + 1).level, aa.UNKNOWN)   # застаріло
        self.assertEqual(aa.effective_status(None).level, aa.UNKNOWN)
        self.assertEqual(aa.effective_status(aa.Status(aa.NONE, "x", "", None)).level, aa.UNKNOWN)
        red = aa.Status(aa.RED, "Повітряна тривога", "", checked_at=1000.0)
        self.assertEqual(aa.effective_status(red, now=1000.0 + aa.MAX_AGE + 1).level, aa.UNKNOWN)      # навіть червоне не «висить»

    def test_settings_round_trip_and_defaults(self):
        self.assertEqual(aa.load_settings(self.folder), {"provider": aa.UKRAINE_ALARM, "key": "", "place": aa.DEFAULT_PLACE})
        aa.save_settings(self.folder, self.settings(aa.ALERTS_IN_UA, key="  abc  ", place={"name": "Львів", "oblast": "Львівська область"}))
        loaded = aa.load_settings(self.folder)
        self.assertEqual((loaded["provider"], loaded["key"], loaded["place"]["name"]), (aa.ALERTS_IN_UA, "abc", "Львів"))
        (self.folder / aa.SETTINGS_NAME).write_text("не json", encoding="utf-8")
        self.assertEqual(aa.load_settings(self.folder)["place"], aa.DEFAULT_PLACE)
        (self.folder / aa.SETTINGS_NAME).write_text(json.dumps({"provider": "чужий", "place": "рядок"}), encoding="utf-8")
        self.assertEqual(aa.load_settings(self.folder)["provider"], aa.UKRAINE_ALARM)

    def test_the_key_and_caches_never_go_into_backups(self):
        for name in (aa.SETTINGS_NAME, aa.REGIONS_NAME, day_facts.CACHE_NAME):
            self.assertTrue(data_tools.is_secret(Path(name)), name)
        root = self.folder / "root"
        (root / "data").mkdir(parents=True)
        (root / "data" / aa.SETTINGS_NAME).write_text('{"key": "секрет"}', encoding="utf-8")
        (root / "data" / "Налаштування.json").write_text("{}", encoding="utf-8")
        names = {Path(p).name if not isinstance(p, tuple) else Path(p[0]).name for p in data_tools.data_files(root)}
        self.assertIn("Налаштування.json", names)
        self.assertNotIn(aa.SETTINGS_NAME, names)

    def test_place_search_offline_and_with_the_region_tree(self):
        offline = aa.search_places("Льв")
        self.assertEqual([place["name"] for _, place in offline], ["Львівська область"])
        self.assertEqual(aa.search_places("київ")[0][1], {"name": "Київ", "oblast": "м. Київ"})
        self.assertGreaterEqual(len(aa.search_places("")), 25)
        online = dict(aa.search_places("бучан", aa.walk_tree(TREE)))
        self.assertIn("Бучанська територіальна громада — Київська область", online)
        self.assertEqual(online["Бучанський район — Київська область"]["oblast"], "Київська область")

    def test_coordinates_follow_the_chosen_oblast(self):
        self.assertEqual(aa.place_coordinates(aa.DEFAULT_PLACE), (50.45, 30.52))
        self.assertEqual(aa.place_coordinates({"name": "Львів", "oblast": "Львівська область"})[0], 49.84)
        self.assertEqual(aa.place_coordinates({"name": "?", "oblast": "щось"}), (50.45, 30.52))

    def test_monitor_refreshes_on_request_and_survives_crashes(self):
        results = iter([aa.Status(aa.NONE, "a", "", 1.0), aa.Status(aa.RED, "b", "", 2.0)])
        monitor = aa.Monitor(lambda: {}, self.folder, fetcher=lambda s, d: next(results), interval=30).start()
        deadline = time.time() + 3
        while monitor.status is None and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(monitor.status.level, aa.NONE)
        monitor.refresh_soon()
        while monitor.status.level == aa.NONE and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(monitor.status.level, aa.RED)
        monitor.stop()
        crashing = aa.Monitor(lambda: {}, self.folder, fetcher=lambda s, d: 1 / 0, interval=30).start()
        deadline = time.time() + 3
        while crashing.status is None and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(crashing.status.level, aa.UNKNOWN)
        crashing.stop()


class IconTests(unittest.TestCase):
    def test_the_bomb_sits_in_a_red_or_a_yellow_circle(self):
        red, yellow = assets.alert_icon(alert_ui.LEVEL_COLORS[aa.RED]), assets.alert_icon(alert_ui.LEVEL_COLORS[aa.YELLOW])
        self.assertEqual(red.size, (112, 112))
        self.assertEqual(red.getpixel((4, 56))[:3], alert_ui.LEVEL_COLORS[aa.RED])
        self.assertEqual(yellow.getpixel((4, 56))[:3], alert_ui.LEVEL_COLORS[aa.YELLOW])
        self.assertEqual(red.getpixel((1, 1))[3], 0)                                   # поза колом прозоро
        dark = sum(1 for x in range(112) for y in range(112)
                   if red.getpixel((x, y))[3] > 200 and sum(red.getpixel((x, y))[:3]) < 120)
        self.assertGreater(dark, 700)                                                  # чорний силует бомби є
        self.assertNotEqual(red.tobytes(), yellow.tobytes())


class LeafTests(TkCase):
    def make(self, scale=0.47):
        host = tk.Toplevel(self.root)
        leaf = calendar_leaf.CalendarLeaf(host, scale=scale)
        leaf.pack()

        def close():
            try:
                host.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        return leaf

    def test_the_leaf_shows_number_month_weekday_sun_and_the_chronicle_without_the_moon(self):
        leaf = self.make(1.0)
        lines = [("holiday", "Всесвітній день учителів"), ("event", "1957 р. — Запущено «Спутник-1»")]
        leaf.show(date(2026, 10, 5), *KYIV, lines)
        texts = leaf.text_items()
        self.assertTrue("ПОНЕДІЛОК" in texts or "П О Н Е Д І Л О К" in texts)
        for expected in ("5", "2 0 2 6", "Ж О В Т Е Н Ь", "Схід сонця", "Захід сонця", "Тривалість", "дня", "День року", "278-й",
                         "Свято", "1957", "Запущено «Спутник-1»"):
            self.assertIn(expected, texts, expected)
        self.assertEqual(texts.count("2 0 2 6"), 2)                                   # рік і ліворуч, і праворуч, як у зразку
        self.assertEqual(leaf.shown, [("holiday", "Всесвітній день учителів"), ("event", "1957 р. — Запущено «Спутник-1»")])
        for time_text in (leaf.data["sunrise"], leaf.data["sunset"]):
            self.assertRegex(time_text, r"^\d{1,2}\.\d{2}$")                          # «7.12», як у зразку
        self.assertRegex(leaf.data["hours"], r"^\d+ год\.$")
        self.assertRegex(leaf.data["minutes"], r"^\d{2} хв\.$")
        joined = " ".join(texts)
        for gone in ("Місяць", "Повня", "Новомісяччя", "чверть", "високос", "Схід місяця", "Тривалість ночі"):
            self.assertNotIn(gone, joined, gone)                                      # Місяця, високосного року й ночі на листку немає
    def test_without_facts_it_says_when_they_will_appear(self):
        leaf = self.make(1.0)
        leaf.show(date(2026, 10, 4), *KYIV, [])
        self.assertIn("з'являться, коли буде зв'язок", " ".join(leaf.text_items()))

    def test_the_source_line_names_wikipedia_only_when_the_text_really_came_from_it(self):
        leaf = self.make()
        leaf.show(date(2026, 10, 5), *KYIV, [("holiday", "x")], "вбудований список пам'ятних дат")
        self.assertIn("вбудований список пам'ятних дат", leaf.text_items())
        self.assertFalse(any("Вікіпедії" in t for t in leaf.text_items()))
        leaf.show(date(2026, 10, 5), *KYIV, [("holiday", "x")], "за матеріалами Вікіпедії (CC BY-SA)")
        self.assertIn("за матеріалами Вікіпедії (CC BY-SA)", leaf.text_items())
        leaf.show(date(2026, 10, 5), *KYIV, [("holiday", "x")])
        self.assertFalse(any("Вікіпедії" in t or "вбудований" in t for t in leaf.text_items()))

    def test_month_number_and_weekday_are_red_like_on_the_sample_and_weekends_stay_red(self):
        leaf = self.make(1.0)
        leaf.show(date(2026, 9, 18), *KYIV, [])                                        # п'ятниця
        by_text = {leaf.itemcget(i, "text"): leaf.itemcget(i, "fill") for i in leaf.find_all() if leaf.type(i) == "text"}
        self.assertEqual(by_text["18"], calendar_leaf.RED)                             # число червоне
        self.assertEqual(by_text["В Е Р Е С Е Н Ь"], calendar_leaf.RED)                # місяць червоний
        weekday = next(v for k, v in by_text.items() if k in ("П'ЯТНИЦЯ", "П ' Я Т Н И Ц Я"))
        self.assertEqual(weekday, calendar_leaf.RED)
        self.assertEqual(by_text["Схід сонця"], calendar_leaf.INK)                     # решта — чорнилом
        leaf.show(date(2026, 10, 4), *KYIV, [])                                        # неділя
        sunday = next(i for i in leaf.find_all() if leaf.type(i) == "text"
                      and leaf.itemcget(i, "text") in ("НЕДІЛЯ", "Н Е Д І Л Я"))
        self.assertEqual(leaf.itemcget(sunday, "fill"), calendar_leaf.RED)

    def test_every_month_name_stays_between_the_two_side_columns(self):
        for scale in (1.0, 0.47):
            leaf = self.make(scale)
            for month in range(1, 13):
                leaf.show(date(2026, month, 15), *KYIV, [])
                name = next(i for i in leaf.find_all() if leaf.type(i) == "text"
                            and leaf.itemcget(i, "text") == calendar_leaf.spaced(calendar_leaf.MONTHS[month - 1]))
                box = leaf.bbox(name)
                self.assertGreaterEqual(box[0], 112 * scale - 2, (scale, month))
                self.assertLessEqual(box[2], 308 * scale + 2, (scale, month))

    def test_the_text_is_left_aligned_in_a_chronicle_with_years_in_their_own_column(self):
        leaf = self.make(1.0)
        leaf.show(date(2026, 6, 22), *KYIV, [("event", "1941 р. — Напад нацистської Німеччини на СРСР: початок війни"),
                                              ("holiday", "День скорботи")])
        items = {leaf.itemcget(i, "text"): leaf.coords(i) for i in leaf.find_all() if leaf.type(i) == "text"}
        year_x, text_x = items["1941"][0], items["Свято"][0]
        self.assertEqual(year_x, text_x)                                               # і роки, і «Свято» — в одному стовпчику
        body_x = next(v[0] for k, v in items.items() if k.startswith("Напад"))
        self.assertGreater(body_x, year_x + 30)                                        # а текст — правіше
        self.assertLess(body_x, calendar_leaf.DESIGN_W / 2)                            # і не по центру
        anchors = {leaf.itemcget(i, "anchor") for i in leaf.find_all()
                   if leaf.type(i) == "text" and leaf.itemcget(i, "text").startswith("Напад")}
        self.assertEqual(anchors, {"nw"})

    def test_the_paper_is_an_aged_texture_and_there_is_no_engraving(self):
        leaf = self.make(1.0)
        leaf.show(date(2026, 10, 5), *KYIV, [("holiday", "x")])
        images = [i for i in leaf.find_all() if leaf.type(i) == "image"]
        self.assertEqual(len(images), 1)                                               # лише папір
        self.assertFalse(hasattr(calendar_leaf, "leaf_art"))
    def test_the_leaf_keeps_whole_items_only_and_never_runs_past_the_paper(self):
        lines = [("holiday", f"Свято {i} " + "слово " * 8) for i in range(3)] + \
                [("event", f"{1900 + i} р. — подія " + "слово " * 14) for i in range(8)]
        for scale in (1.0, 0.47):
            leaf = self.make(scale)
            leaf.show(date(2026, 10, 5), *KYIV, lines, "вбудований список пам'ятних дат")
            self.assertGreaterEqual(len(leaf.shown), 3)
            self.assertLess(len(leaf.shown), len(lines))                                # решта не вмістилась — пропущена цілком
            self.assertEqual(leaf.shown, lines[:len(leaf.shown)])                       # порядок збережено, без «дір»
            paper = (calendar_leaf.DESIGN_W - 12) * scale + 2
            for item in leaf.find_all():
                if leaf.type(item) == "text":
                    box = leaf.bbox(item)
                    self.assertLessEqual(box[2], paper, leaf.itemcget(item, "text"))
                    self.assertLessEqual(box[3], (calendar_leaf.DESIGN_H - 14) * scale + 2)

    def test_the_small_leaf_is_an_exact_reduced_copy_of_the_big_one(self):
        lines = [("holiday", "Всесвітній день учителів"), ("event", "1943 р. — Радянські війська визволили Київ від німецької окупації")]
        small, big = self.make(0.47), self.make(1.0)
        for leaf in (small, big):
            leaf.show(date(2026, 11, 6), *KYIV, lines, "вбудований список пам'ятних дат")
        self.assertEqual(small.shown, big.shown)                                       # той самий вміст, нічого не обрізано
        ratio = lambda leaf: int(leaf.cget("width")) / int(leaf.cget("height"))
        self.assertAlmostEqual(ratio(small), ratio(big), delta=0.01)                    # ті самі пропорції
        self.assertAlmostEqual(ratio(big), calendar_leaf.DESIGN_W / calendar_leaf.DESIGN_H, delta=0.01)
        rows = lambda leaf: sum(1 for t in leaf.text_items() if "Київ" in t or "окупац" in t)
        self.assertEqual(rows(small), rows(big))                                       # однакові переноси рядків

    def test_the_big_leaf_is_larger_than_life_but_fits_any_screen(self):
        self.assertEqual(calendar_leaf.full_scale(1440), 1.2)
        self.assertEqual(calendar_leaf.full_scale(1080), 1.2)
        self.assertLess(calendar_leaf.full_scale(768), 1.2)
        self.assertGreaterEqual(calendar_leaf.full_scale(400), 0.55)
        self.assertLessEqual(calendar_leaf.DESIGN_H * calendar_leaf.full_scale(1080) + 80, 1080)
class PanelTests(TkCase):
    def make(self, clicks=None):
        host = tk.Toplevel(self.root)
        panel = alert_ui.AlertPanel(host, (lambda: clicks.append(1)) if clicks is not None else (lambda: None))
        panel.pack()
        host.update()

        def close():
            try:
                host.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        return panel

    @staticmethod
    def images(panel):
        return [i for i in panel.find_all() if panel.type(i) == "image"]

    def test_red_and_yellow_show_the_bomb_in_a_circle_while_the_others_show_only_words(self):
        panel = self.make()
        for level, with_bomb in ((aa.RED, True), (aa.YELLOW, True), (aa.NONE, False), (aa.UNKNOWN, False)):
            panel.show(aa.Status(level, alert_ui.TITLES[level], "", time.time()), "Київ")
            self.assertEqual(len(self.images(panel)), 2 if with_bomb else 1, level)       # плашка (+ значок)
            self.assertIn(alert_ui.TITLES[level], panel.text_items(), level)

    def test_red_has_the_official_wording_and_none_has_no_circle(self):
        panel = self.make()
        panel.show(aa.Status(aa.RED, "Повітряна тривога", "Терміново пройдіть до найближчого укриття.", time.time()), "Київ")
        self.assertIn("Повітряна тривога", panel.text_items())
        self.assertIn("Терміново пройдіть до найближчого укриття.", panel.text_items())
        panel.show(aa.Status(aa.NONE, "Тривоги немає", "", time.time()), "Київ")
        self.assertIn("Тривоги немає", panel.text_items())
        self.assertTrue(any(t.startswith("Станом на ") for t in panel.text_items()))

    def test_the_caption_explains_that_any_place_can_be_chosen_and_names_the_current_one(self):
        panel = self.make()
        panel.show(aa.Status(aa.UNKNOWN, "x", "", None), "Київ")
        caption = next(t for t in panel.text_items() if "Натисніть на малюнок" in t)
        self.assertIn("будь-який населений пункт України", caption)
        self.assertIn("Зараз обрано: Київ", caption)
        panel.show(aa.Status(aa.UNKNOWN, "x", "", None), "Львівська область")
        self.assertTrue(any("Зараз обрано: Львівська область" in t for t in panel.text_items()))

    def test_a_click_opens_the_setup(self):
        clicks = []
        panel = self.make(clicks)
        panel.event_generate("<Button-1>", x=20, y=20)
        panel.update()
        self.assertEqual(clicks, [1])

class MainWindowTests(TempProgram):
    def setUp(self):
        super().setUp()
        self.app.geometry("1500x900")
        self.app.datevar.set("05.10.2026")
        self.app.update_day()
        for _ in range(10):
            self.app.update()
            time.sleep(0.01)

    def test_the_message_field_is_narrower_and_the_alert_and_the_leaf_sit_to_its_right_symmetrically(self):
        app = self.app
        alert, leaf, desc = app.alert_panel, app.leaf, app.desc
        self.assertLess(desc.winfo_width(), app.winfo_width() - 400)
        self.assertLess(desc.winfo_rootx(), alert.winfo_rootx())
        self.assertLess(alert.winfo_rootx(), leaf.winfo_rootx())                     # тривога зліва від листочка
        self.assertEqual(alert.winfo_height(), leaf.winfo_height())                  # однакова висота
        self.assertEqual(alert.winfo_rooty(), leaf.winfo_rooty())                    # на одному рівні
        self.assertLessEqual(leaf.winfo_rootx() + leaf.winfo_width(), app.winfo_rootx() + app.winfo_width())
    def test_the_bottom_row_never_disappears_even_on_a_low_window(self):
        self.app.geometry("1500x820")
        for _ in range(10):
            self.app.update()
            time.sleep(0.01)
        buttons = [w for w in self._walk(self.app) if w.winfo_class() == "Button" and "СКИНУТИ ВСЕ" in str(w.cget("text"))]
        self.assertTrue(buttons)
        bottom = buttons[0].winfo_rooty() + buttons[0].winfo_height()
        self.assertLessEqual(bottom, self.app.winfo_rooty() + self.app.winfo_height())

    @staticmethod
    def _walk(widget):
        out, stack = [], [widget]
        while stack:
            current = stack.pop()
            stack.extend(current.winfo_children())
            out.append(current)
        return out

    def test_the_leaf_follows_the_selected_day_and_shows_holidays_without_internet(self):
        self.assertEqual(self.app.leaf.day, date(2026, 10, 5))
        self.assertIn(("holiday", "Всесвітній день учителів"), self.app.leaf.shown)
        self.app.datevar.set("24.08.2026")
        self.app.update_day()
        self.assertEqual(self.app.leaf.day, date(2026, 8, 24))
        self.assertIn(("holiday", "День Незалежності України"), self.app.leaf.shown)
    def test_the_main_leaf_credits_wikipedia_only_after_a_wikipedia_page_is_cached(self):
        self.assertIn("вбудований список пам'ятних дат", self.app.leaf.text_items())
        day_facts.store(engine.DATA, 10, 5, day_facts.parse_extract(SAMPLE))
        self.app._refresh_leaf()
        self.assertIn("за матеріалами Вікіпедії (CC BY-SA)", self.app.leaf.text_items())
        self.assertTrue(any(text.startswith("1648 р.") for kind, text in self.app.leaf.shown))
    def test_sun_times_follow_the_chosen_oblast(self):
        minutes_of = lambda text: int(text.split(".")[0]) * 60 + int(text.split(".")[1])
        kyiv = self.app.leaf.data["sunrise"]
        aa.save_settings(engine.DATA, {"provider": aa.UKRAINE_ALARM, "key": "",
                                       "place": {"name": "Львів", "oblast": "Львівська область"}})
        self.app.alert_settings_changed()
        lviv = self.app.leaf.data["sunrise"]
        self.assertNotEqual(kyiv, lviv)
        self.assertGreater(minutes_of(lviv), minutes_of(kyiv))                       # на заході сонце сходить пізніше
        self.assertTrue(any("Зараз обрано: Львів" in t for t in self.app.alert_panel.text_items()))
    def test_without_a_key_the_panel_says_there_is_no_data_never_no_alert(self):
        self.app._apply_alert_status()
        self.assertEqual(self.app.alert_panel.level, aa.UNKNOWN)
        self.assertIn("Немає даних про тривогу", self.app.alert_panel.text_items())

    def test_the_panel_shows_what_the_monitor_reports_and_drops_stale_data(self):
        aa.save_settings(engine.DATA, {"provider": aa.UKRAINE_ALARM, "key": "k", "place": dict(aa.DEFAULT_PLACE)})
        self.app.alerts.status = aa.Status(aa.RED, "Повітряна тривога", "", time.time())
        self.app._apply_alert_status()
        self.assertEqual(self.app.alert_panel.level, aa.RED)
        self.app.alerts.status = aa.Status(aa.YELLOW, "Жовтий рівень", "", time.time())
        self.app._apply_alert_status()
        self.assertEqual(self.app.alert_panel.level, aa.YELLOW)
        self.app.alerts.status = aa.Status(aa.NONE, "Тривоги немає", "", time.time())
        self.app._apply_alert_status()
        self.assertEqual(self.app.alert_panel.level, aa.NONE)
        self.app.alerts.status = aa.Status(aa.NONE, "Тривоги немає", "", time.time() - aa.MAX_AGE - 5)
        self.app._apply_alert_status()
        self.assertEqual(self.app.alert_panel.level, aa.UNKNOWN)                     # дані застаріли

    def test_no_threads_or_network_in_tests_and_closing_stops_the_monitors(self):
        self.assertIsNone(self.app.alerts._thread)
        self.assertIsNone(self.app.facts.refresh_async(10, 5))
        with mock.patch.object(self.app.alerts, "stop") as alerts_stop, mock.patch.object(self.app.net, "stop") as net_stop, \
                mock.patch.object(self.app, "destroy"):
            self.app.on_close()
        alerts_stop.assert_called_once()
        net_stop.assert_called_once()

    def test_facts_that_arrive_later_refresh_the_leaf(self):
        calls = []
        self.app._refresh_leaf = lambda: calls.append(1)
        self.app.facts.updated.add((10, 5))
        self.app._facts_poll()
        self.assertEqual(calls, [1])
        self.assertFalse(self.app.facts.updated)


class SetupWindowTests(TempProgram):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(alert_ui, "show_toast",
                                    side_effect=lambda parent, text, *a, **k: self.toasts.append(text))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self):
        window = alert_ui.show_alert_setup(self.app)
        window.update()
        self.addCleanup(lambda: window.winfo_exists() and window.destroy())
        return window

    @staticmethod
    def labels(window):
        out, stack = [], [window]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if widget.winfo_class() in ("TLabel", "TButton", "TLabelframe", "TRadiobutton"):
                out.append(str(widget.cget("text")))
        return out

    def test_kyiv_is_chosen_by_default_and_there_is_no_clutter(self):
        window = self.make()
        self.assertEqual(window.chosen_var.get(), "Обрано: Київ")
        text = "\n".join(self.labels(window))
        for needle in ("не замінює сирену", "Отримати ключ (відкрити сайт)", "Ukraine Alarm (державна система)",
                       "alerts.in.ua", "оберіть будь-який населений пункт України", "© учасники OpenStreetMap"):
            self.assertIn(needle, text, needle)
        for gone in ("Що означають кольори", "Показати вигляд", "ЧЕРВОНИЙ (бомбочка", "Державні жовтий"):
            self.assertNotIn(gone, text, gone)                                        # зайвих блоків і кнопок немає
        buttons = {w.cget("text") for w in self.walk(window) if w.winfo_class() == "TButton"}
        self.assertFalse(buttons & {"Червоний", "Жовтий", "Тривоги немає", "Немає даних"})
    def test_search_filters_places_and_a_click_chooses_one(self):
        window = self.make()
        self.assertGreaterEqual(window.places_box.size(), 25)
        window.query.set("Льв")
        window.update()
        self.assertEqual(window.places_box.size(), 1)
        window.places_box.selection_set(0)
        window.places_box.event_generate("<<ListboxSelect>>")
        window.update()
        self.assertEqual(window.chosen_var.get(), "Обрано: Львівська область")

    def test_saving_writes_the_settings_and_tells_the_app(self):
        window = self.make()
        window.query.set("Харків")
        window.update()
        window.places_box.selection_set(0)
        window.places_box.event_generate("<<ListboxSelect>>")
        window.provider.set(aa.ALERTS_IN_UA)
        window.key.set("  мій-токен  ")
        with mock.patch.object(self.app, "alert_settings_changed") as changed:
            window.save()
        saved = aa.load_settings(engine.DATA)
        self.assertEqual((saved["provider"], saved["key"], saved["place"]["oblast"]),
                         (aa.ALERTS_IN_UA, "мій-токен", "Харківська область"))
        changed.assert_called_once()
        self.assertIn("Налаштування тривоги збережено", self.toasts[-1])

    def test_the_key_is_masked_on_screen(self):
        window = self.make()
        entries = [w for w in self.walk(window) if w.winfo_class() == "TEntry" and str(w.cget("show")) == "•"]
        self.assertEqual(len(entries), 1)

    @staticmethod
    def walk(window):
        out, stack = [], [window]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            out.append(widget)
        return out

    def test_check_now_reports_the_result_of_a_real_request_without_freezing(self):
        window = self.make()
        window.key.set("k")
        done = threading.Event()

        def fake(settings, data_dir, *a, **k):
            done.set()
            return aa.Status(aa.RED, "Повітряна тривога", "Терміново пройдіть до найближчого укриття.", time.time(),
                             "alerts.in.ua")
        with mock.patch.object(aa, "fetch_status", side_effect=fake):
            window.check()
            self.assertTrue(done.wait(3))
            deadline = time.time() + 3
            while "Повітряна тривога" not in window.result.get() and time.time() < deadline:
                window.update()
                time.sleep(0.02)
        self.assertIn("Повітряна тривога. Терміново пройдіть", window.result.get())
        self.assertIn("alerts.in.ua", window.result.get())

    def test_the_key_site_buttons_open_the_right_pages(self):
        window = self.make()
        button = next(w for w in self.walk(window) if w.winfo_class() == "TButton"
                      and w.cget("text") == "Отримати ключ (відкрити сайт)")
        with mock.patch.object(alert_ui.webbrowser, "open") as opened:
            button.invoke()
            window.provider.set(aa.ALERTS_IN_UA)
            button.invoke()
        self.assertEqual([c.args[0] for c in opened.call_args_list],
                         ["https://api.ukrainealarm.com", "https://alerts.in.ua/api-request"])


if __name__ == "__main__":
    unittest.main()
