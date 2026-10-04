"""«Цей день в історії»: події й свята з української Вікіпедії + вбудований список головних українських дат.

Мережа не обов'язкова: результат кешується у файлі, а без інтернету лишається вбудований список.
Джерело тексту — українська Вікіпедія (ліцензія CC BY-SA 4.0), про що зазначено на листочку.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MONTHS_GEN = ("січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня",
              "жовтня", "листопада", "грудня")
API = "https://uk.wikipedia.org/w/api.php"
USER_AGENT = "PomichnykUchytelia/5.1 (teacher assistant for Google Classroom; github.com/Marat1945/mii-classroom-exe)"
CACHE_NAME = "day_facts_cache.json"
MAX_CACHE_DAYS = 400
UA_WORDS = ("україн", "київ", "львів", "козац", "гетьман", "харків", "одес", "дніпр", "запоріж", "чорнобил", "шевченк")
RELIGIOUS = ("релігій", "православ", "католиц", "церковн", "іменин", "християн", "ісламськ", "іудей")

# Лише певні, незмінні за датою українські свята й пам'ятні дні.
BUILTIN = {
    (1, 1): "Новий рік",
    (1, 22): "День Соборності України",
    (1, 29): "День пам'яті героїв Крут",
    (2, 20): "День Героїв Небесної Сотні",
    (3, 8): "Міжнародний жіночий день",
    (3, 9): "День народження Тараса Шевченка (1814)",
    (4, 26): "Річниця Чорнобильської катастрофи (1986)",
    (5, 8): "День пам'яті та перемоги над нацизмом у Другій світовій війні",
    (5, 9): "День Європи",
    (5, 18): "День пам'яті жертв геноциду кримськотатарського народу",
    (6, 28): "День Конституції України",
    (7, 15): "День Української Державності",
    (8, 23): "День Державного Прапора України",
    (8, 24): "День Незалежності України",
    (8, 29): "День пам'яті захисників України",
    (9, 1): "День знань",
    (9, 21): "Міжнародний день миру",
    (10, 1): "День захисників і захисниць України",
    (10, 5): "Всесвітній день учителів",
    (11, 21): "День Гідності та Свободи",
    (12, 6): "День Збройних сил України",
    (12, 25): "Різдво Христове",
}


@dataclass
class Facts:
    events: list = field(default_factory=list)      # [(рік, текст)]
    holidays: list = field(default_factory=list)    # [текст]
    source: str = ""


def page_title(month: int, day: int) -> str:
    return f"{day} {MONTHS_GEN[month - 1]}"


def build_url(month: int, day: int) -> str:
    query = {"action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "wiki", "redirects": 1,
             "titles": page_title(month, day), "format": "json", "formatversion": 2}
    return API + "?" + urllib.parse.urlencode(query)


def clean(text: str) -> str:
    text = re.sub(r"\[\d+\]|\[[а-яa-z]\]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \u00a0;,")
    return text


def shorten(text: str, limit: int = 84) -> str:
    text = clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return cut + "…"


HEAD2 = re.compile(r"^==\s*([^=].*?)\s*==\s*$")
HEAD3 = re.compile(r"^===+\s*(.*?)\s*=+\s*$")
EVENT = re.compile(r"^(\d{1,4})(?:\s*(?:рік|року|р\.|до н\.\s?е\.))?\s*[—–-]\s*(.+)$")


def parse_extract(text: str) -> Facts:
    """Розбір простого тексту сторінки дня («== Події ==», «== Свята та пам'ятні дні ==»). Терпимий до відмінностей."""
    facts = Facts(source="Вікіпедія")
    section, skip = None, False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        two = HEAD2.match(line)
        if two:
            title = two.group(1).casefold()
            section = "events" if "поді" in title else ("holidays" if "свят" in title else None)
            skip = False
            continue
        three = HEAD3.match(line)
        if three:
            skip = section == "holidays" and any(word in three.group(1).casefold() for word in RELIGIOUS)
            continue
        if section == "events":
            found = EVENT.match(line)
            if found:
                facts.events.append((int(found.group(1)), shorten(found.group(2))))
        elif section == "holidays" and not skip:
            if any(word in line.casefold() for word in RELIGIOUS):
                continue
            item = shorten(line)
            if len(item) >= 6:
                facts.holidays.append(item)
    return facts


def compose(facts: Facts | None, month: int, day: int, holidays_limit: int = 2, events_limit: int = 2) -> list:
    """Короткий перелік для листочка: [('holiday'|'event', текст)]. Українське — першим, а свята й події чергуються
    (свято, подія, свято, подія), щоб у трьох рядках листочка було і те, і те."""
    holidays, seen = [], []

    def add_holiday(text):
        key = text.casefold()
        if text and len(holidays) < holidays_limit and not any(key in s or s in key for s in seen):
            seen.append(key)
            holidays.append(("holiday", text))
    builtin = BUILTIN.get((month, day))
    if builtin:
        add_holiday(builtin)
    for text in sorted(facts.holidays if facts else [], key=lambda t: 0 if "україн" in t.casefold() else 1):
        add_holiday(text)
    events = list(facts.events) if facts else []
    events.sort(key=lambda e: (0 if any(w in e[1].casefold() for w in UA_WORDS) else 1, -e[0]))
    events = [("event", f"{year} р. — {text}") for year, text in events[:events_limit]]
    result = []
    for k in range(max(len(holidays), len(events))):
        result += holidays[k:k + 1] + events[k:k + 1]
    return result


# ---------- кеш і мережа ----------
def cache_path(data_dir) -> Path:
    return Path(data_dir) / CACHE_NAME


def read_cache(data_dir) -> dict:
    try:
        data = json.loads(cache_path(data_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def store(data_dir, month: int, day: int, facts: Facts) -> None:
    cache = read_cache(data_dir)
    cache[f"{month:02d}-{day:02d}"] = {"events": [[y, t] for y, t in facts.events], "holidays": facts.holidays,
                                       "fetched": time.time()}
    for key in sorted(cache, key=lambda k: cache[k].get("fetched", 0))[:-MAX_CACHE_DAYS]:
        cache.pop(key, None)
    try:
        cache_path(data_dir).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def cached(data_dir, month: int, day: int):
    entry = read_cache(data_dir).get(f"{month:02d}-{day:02d}")
    if not entry:
        return None
    return Facts([(int(y), t) for y, t in entry.get("events", [])], list(entry.get("holidays", [])), "Вікіпедія")


def fetch(month: int, day: int, opener=urllib.request.urlopen, timeout: float = 8.0) -> Facts:
    """Завантажити й розібрати сторінку дня. Помилка мережі або порожня сторінка — виняток."""
    request = urllib.request.Request(build_url(month, day), headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    pages = (payload.get("query") or {}).get("pages") or []
    text = pages[0].get("extract", "") if pages else ""
    facts = parse_extract(text)
    if not facts.events and not facts.holidays:
        raise ValueError("на сторінці дня не знайдено подій і свят")
    return facts


class Loader:
    """Дає факти дня миттєво (кеш + вбудований список) і в фоні оновлює їх із Вікіпедії."""

    def __init__(self, data_dir, opener=urllib.request.urlopen, network: bool = True):
        self.data_dir, self.opener, self.network = Path(data_dir), opener, network
        self._busy = set()
        self.updated = set()

    def lookup(self, month: int, day: int) -> list:
        return compose(cached(self.data_dir, month, day), month, day)

    def refresh_async(self, month: int, day: int):
        key = (month, day)
        if not self.network or key in self._busy or cached(self.data_dir, month, day):
            return None
        self._busy.add(key)

        def work():
            try:
                store(self.data_dir, month, day, fetch(month, day, self.opener))
                self.updated.add(key)
            except Exception:
                pass
            finally:
                self._busy.discard(key)
        thread = threading.Thread(target=work, name="day-facts", daemon=True)
        thread.start()
        return thread
