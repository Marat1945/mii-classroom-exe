"""Повітряна тривога для вчителя: рівні «червоний / жовтий / немає / немає даних».

ДЖЕРЕЛА (обидва офіційні й обидва вимагають ключ, який видають за заявкою на їхніх сайтах):
  • Ukraine Alarm (api.ukrainealarm.com) — державна система, дерево областей/районів/громад;
  • alerts.in.ua — дані з офіційних каналів («Повітряна тривога», ОВА, ДСНС), персональний токен.
ПРАВИЛО РІВНІВ (поки державні жовтий/червоний рівні не віддаються відкритим API, це правило програми):
  • ЧЕРВОНИЙ — повітряна тривога діє у вашому місці (або в області/районі/громаді, що його включає);
  • ЖОВТИЙ — у вашому місці інша загроза (обстріл, вуличні бої, хімічна, радіаційна), або повітряна
    тривога є в іншій частині вашої ОБЛАСТІ;
  • НЕМАЄ — дані свіжі, і тривоги немає;
  • НЕМАЄ ДАНИХ — немає ключа, мережі або дані застаріли. «Тривоги немає» тоді НЕ показуємо ніколи.
Програма не замінює сирену та офіційні сповіщення.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

RED, YELLOW, NONE, UNKNOWN = "red", "yellow", "none", "unknown"
MAX_AGE = 180.0                                   # дані старші за 3 хвилини вважаємо застарілими
SETTINGS_NAME = "air_alert.json"
REGIONS_NAME = "air_alert_regions.json"
USER_AGENT = "PomichnykUchytelia/5.1 (github.com/Marat1945/mii-classroom-exe)"
UKRAINE_ALARM = "ukrainealarm"
ALERTS_IN_UA = "alertsinua"
KEY_FORMS = {UKRAINE_ALARM: "https://api.ukrainealarm.com", ALERTS_IN_UA: "https://alerts.in.ua/api-request"}
PROVIDER_NAMES = {UKRAINE_ALARM: "Ukraine Alarm (державна система)", ALERTS_IN_UA: "alerts.in.ua"}

DEFAULT_PLACE = {"name": "Київ", "oblast": "м. Київ"}

# Область (або м. Київ) → координати центру: для схід/захід сонця й швидкого вибору місця без інтернету.
OBLASTS = {
    "Автономна Республіка Крим": (44.95, 34.10), "Вінницька область": (49.23, 28.47),
    "Волинська область": (50.75, 25.33), "Дніпропетровська область": (48.46, 35.04),
    "Донецька область": (48.02, 37.80), "Житомирська область": (50.25, 28.66),
    "Закарпатська область": (48.62, 22.29), "Запорізька область": (47.84, 35.14),
    "Івано-Франківська область": (48.92, 24.71), "Київська область": (50.45, 30.52), "м. Київ": (50.45, 30.52),
    "Кіровоградська область": (48.51, 32.26), "Луганська область": (48.57, 39.31),
    "Львівська область": (49.84, 24.03), "Миколаївська область": (46.97, 32.00),
    "Одеська область": (46.48, 30.73), "Полтавська область": (49.59, 34.55),
    "Рівненська область": (50.62, 26.25), "Сумська область": (50.91, 34.80),
    "Тернопільська область": (49.55, 25.59), "Харківська область": (49.99, 36.23),
    "Херсонська область": (46.64, 32.62), "Хмельницька область": (49.42, 26.99),
    "Черкаська область": (49.44, 32.06), "Чернівецька область": (48.29, 25.94),
    "Чернігівська область": (51.49, 31.29),
}


@dataclass
class Status:
    level: str
    title: str
    detail: str = ""
    checked_at: float | None = None
    source: str = ""


class SourceError(Exception):
    """Зрозуміла причина, чому дані не отримано (показується вчителю)."""


def norm(name) -> str:
    """Порівняння назв: без «м.», «область», «район», «територіальна громада», апострофів, регістру."""
    text = str(name or "").casefold().replace("’", "'").replace("ʼ", "'").replace("`", "'")
    text = re.sub(r"\b(м\.|місто|область|обл\.|район|р-н|територіальна громада|тг|громада|селище|смт|с\.)", " ", text)
    return re.sub(r"[^а-яіїєґa-z0-9']+", "", text)


def place_text(place: dict) -> str:
    return (place or {}).get("name") or DEFAULT_PLACE["name"]


def place_coordinates(place: dict):
    """Координати для сонця: за областю обраного місця (за замовчуванням — Київ)."""
    target = norm((place or {}).get("oblast") or DEFAULT_PLACE["oblast"])
    for oblast, coordinates in OBLASTS.items():
        if norm(oblast) == target:
            return coordinates
    return OBLASTS["м. Київ"]


# ---------- налаштування (ключ не потрапляє в резервні копії: див. SECRET_NAMES) ----------
def load_settings(data_dir) -> dict:
    try:
        data = json.loads((Path(data_dir) / SETTINGS_NAME).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError):
        data = {}
    place = data.get("place") if isinstance(data.get("place"), dict) else {}
    return {"provider": data.get("provider") if data.get("provider") in PROVIDER_NAMES else UKRAINE_ALARM,
            "key": str(data.get("key") or "").strip(),
            "place": {"name": place.get("name") or DEFAULT_PLACE["name"],
                      "oblast": place.get("oblast") or DEFAULT_PLACE["oblast"]}}


def save_settings(data_dir, settings: dict) -> None:
    path = Path(data_dir) / SETTINGS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


# ---------- HTTP ----------
def http_json(url, headers, opener=urllib.request.urlopen, timeout=7.0):
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT, **headers})
    try:
        with opener(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise SourceError("ключ не прийнято (перевірте ключ або запросіть новий)") from error
        if error.code == 429:
            raise SourceError("забагато запитів: спробую пізніше") from error
        raise SourceError(f"джерело відповіло помилкою {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SourceError("немає зв'язку з джерелом") from error
    except ValueError as error:
        raise SourceError("джерело повернуло незрозумілу відповідь") from error


# ---------- Ukraine Alarm ----------
def walk_tree(tree):
    """Дерево областей → {id: {name, type, owner, chain}}; терпимо до різних форм відповіді."""
    index = {}
    roots = tree.get("states") if isinstance(tree, dict) else tree
    for root in roots or []:
        _walk(root, [], index, None)
    return index


def _walk(node, chain, index, owner):
    if not isinstance(node, dict):
        return
    rid = str(node.get("regionId", ""))
    if not rid:
        return
    owner = owner or rid
    path = chain + [rid]
    index[rid] = {"name": node.get("regionName", ""), "type": node.get("regionType", ""), "owner": owner,
                  "chain": path}
    for child in node.get("regionChildIds") or node.get("children") or []:
        _walk(child, path, index, owner)


def find_region(index, place) -> str | None:
    """Знайти регіон за назвою місця й області; запасний варіант — сама область."""
    name, oblast = norm(place.get("name")), norm(place.get("oblast"))
    best = None
    for rid, node in index.items():
        if norm(node["name"]) != name:
            continue
        owner_name = norm(index.get(node["owner"], {}).get("name"))
        if oblast and owner_name == oblast:
            return rid
        best = best or rid
    if best:
        return best
    for rid, node in index.items():
        if node["owner"] == rid and norm(node["name"]) == oblast:
            return rid
    return None


def region_alert_types(entry) -> list:
    return [str(a.get("type", "")).upper() for a in (entry.get("activeAlerts") or []) if isinstance(a, dict)]


def evaluate_ukrainealarm(active, index, region_id) -> Status:
    """active — відповідь /alerts (регіони з активними загрозами), index — дерево, region_id — обране місце."""
    node = index.get(region_id) or {}
    chain, owner = set(node.get("chain", [])), node.get("owner")
    mine, nearby_air = [], False
    for entry in active or []:
        rid = str(entry.get("regionId", ""))
        types = region_alert_types(entry)
        if not types:
            continue
        if rid in chain:
            mine.append(types)
        elif owner and index.get(rid, {}).get("owner") == owner and "AIR" in types:
            nearby_air = True
    if any("AIR" in types for types in mine):
        return Status(RED, "Повітряна тривога", "Терміново пройдіть до найближчого укриття.")
    if mine:
        return Status(YELLOW, "Жовтий рівень", "У вашому місці діє інша загроза: будьте готові до укриття.")
    if nearby_air:
        return Status(YELLOW, "Жовтий рівень", "Тривога в іншій частині вашої області: будьте готові.")
    return Status(NONE, "Тривоги немає", "")


# ---------- alerts.in.ua ----------
def evaluate_alerts_in_ua(alerts, place) -> Status:
    name, oblast = norm(place.get("name")), norm(place.get("oblast"))
    mine, nearby_air = [], False
    for alert in alerts or []:
        if not isinstance(alert, dict) or alert.get("finished_at"):
            continue
        kind = str(alert.get("alert_type", "")).lower()
        title = norm(alert.get("location_title"))
        alert_oblast = norm(alert.get("location_oblast")) or (title if alert.get("location_type") == "oblast" else "")
        whole_oblast = alert.get("location_type") == "oblast" and alert_oblast == oblast
        if whole_oblast or (name and title == name):
            mine.append(kind)
        elif alert_oblast == oblast and kind == "air_raid":
            nearby_air = True
    if "air_raid" in mine:
        return Status(RED, "Повітряна тривога", "Терміново пройдіть до найближчого укриття.")
    if mine:
        return Status(YELLOW, "Жовтий рівень", "У вашому місці діє інша загроза: будьте готові до укриття.")
    if nearby_air:
        return Status(YELLOW, "Жовтий рівень", "Тривога в іншій частині вашої області: будьте готові.")
    return Status(NONE, "Тривоги немає", "")


# ---------- загальний запит ----------
def regions_index(key, data_dir, opener=urllib.request.urlopen, max_age_days=7):
    cache = Path(data_dir) / REGIONS_NAME
    try:
        if time.time() - cache.stat().st_mtime < max_age_days * 86400:
            return walk_tree(json.loads(cache.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    tree = http_json("https://api.ukrainealarm.com/api/v3/regions", {"Authorization": key}, opener)
    try:
        cache.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return walk_tree(tree)


def fetch_status(settings: dict, data_dir, opener=urllib.request.urlopen, now=time.time) -> Status:
    """Один запит до обраного джерела. Помилка або відсутній ключ — НІКОЛИ не «тривоги немає», а «немає даних»."""
    provider, key, place = settings["provider"], settings.get("key", ""), settings["place"]
    if not key:
        return Status(UNKNOWN, "Немає даних про тривогу", "Підключіть джерело: потрібен ключ API.", None)
    try:
        if provider == ALERTS_IN_UA:
            data = http_json("https://api.alerts.in.ua/v1/alerts/active.json", {"Authorization": f"Bearer {key}"}, opener)
            status = evaluate_alerts_in_ua(data.get("alerts", []) if isinstance(data, dict) else data, place)
        else:
            index = regions_index(key, data_dir, opener)
            region = find_region(index, place)
            if region is None:
                raise SourceError("місце не знайдено в списку джерела: оберіть його заново")
            active = http_json("https://api.ukrainealarm.com/api/v3/alerts", {"Authorization": key}, opener)
            status = evaluate_ukrainealarm(active, index, region)
    except SourceError as error:
        return Status(UNKNOWN, "Немає даних про тривогу", str(error).capitalize() + ".", None)
    status.checked_at = now()
    status.source = PROVIDER_NAMES[provider]
    return status


def effective_status(status: Status | None, now: float | None = None, max_age: float = MAX_AGE) -> Status:
    """Застарілі дані = «немає даних»: так програма не заспокоїть учителя, коли зв'язок зник."""
    now = time.time() if now is None else now
    if status is None:
        return Status(UNKNOWN, "Немає даних про тривогу", "Перевіряю…", None)
    if status.level != UNKNOWN and (status.checked_at is None or now - status.checked_at > max_age):
        return Status(UNKNOWN, "Немає даних про тривогу", "Дані застаріли: перевірте зв'язок.", None)
    return status


def search_places(query: str, index=None, limit: int = 40) -> list:
    """Варіанти місця для вибору: [(підпис, {'name', 'oblast'})]. Без дерева — області; з деревом — і райони/громади."""
    wanted = norm(query)
    found = []
    if index:
        for rid, node in index.items():
            if wanted and wanted not in norm(node["name"]):
                continue
            oblast = index.get(node["owner"], {}).get("name", node["name"])
            label = node["name"] if node["owner"] == rid else f"{node['name']} — {oblast}"
            found.append((label, {"name": node["name"], "oblast": oblast}))
    else:
        for oblast in OBLASTS:
            if not wanted or wanted in norm(oblast):
                name = "Київ" if oblast == "м. Київ" else oblast
                found.append((name, {"name": name, "oblast": oblast}))
    found.sort(key=lambda item: 0 if norm(item[1]["name"]) == wanted else 1)     # точний збіг («Київ») — першим
    return found[:limit]


class Monitor:
    """Фоновий потік: раз на interval секунд оновлює status."""

    def __init__(self, settings_loader, data_dir, fetcher=fetch_status, interval: float = 45.0):
        self._loader, self._data_dir, self._fetcher, self._interval = settings_loader, data_dir, fetcher, interval
        self.status = None
        self._wake, self._stop, self._thread = threading.Event(), threading.Event(), None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="air-alerts", daemon=True)
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            try:
                self.status = self._fetcher(self._loader(), self._data_dir)
            except Exception:
                self.status = Status(UNKNOWN, "Немає даних про тривогу", "Несподівана помилка джерела.", None)
            self._wake.wait(self._interval)
            self._wake.clear()

    def refresh_soon(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
