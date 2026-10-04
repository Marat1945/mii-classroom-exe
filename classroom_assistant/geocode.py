"""Пошук будь-якого населеного пункту України (місто, селище, село) за назвою: сервіс OpenStreetMap Nominatim.

Повертає назву, район, область і координати. Запит робиться лише за натисканням «Знайти» (правила сервісу: без
автодоповнення, не частіше разу на секунду, з «User-Agent»). Дані © учасники OpenStreetMap (ліцензія ODbL).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "PomichnykUchytelia/5.3 (teacher assistant; github.com/Marat1945/mii-classroom-exe)"
MIN_INTERVAL = 1.1
_last_request = [0.0]


class GeocodeError(Exception):
    """Зрозуміла причина невдачі (показується вчителю)."""


def build_url(query: str, limit: int = 10) -> str:
    params = {"q": query, "countrycodes": "ua", "format": "jsonv2", "addressdetails": 1,
              "accept-language": "uk", "limit": limit, "featuretype": "settlement"}
    return URL + "?" + urllib.parse.urlencode(params)


def normalize_oblast(state: str) -> str:
    """У довіднику програми Київ — «м. Київ»; решта областей — як є."""
    state = (state or "").strip()
    return "м. Київ" if state.casefold() in ("київ", "м. київ", "місто київ") else state


def parse(results) -> list:
    """Відповідь Nominatim → [{'label','name','oblast','raion','lat','lon'}]; без дублів і лише Україна."""
    found, seen = [], set()
    for item in results or []:
        if not isinstance(item, dict):
            continue
        address = item.get("address") or {}
        if str(address.get("country_code", "ua")).lower() != "ua":
            continue
        name = (item.get("name") or address.get("city") or address.get("town") or address.get("village")
                or address.get("hamlet") or "").strip()
        oblast = normalize_oblast(address.get("state", ""))
        raion = (address.get("county") or address.get("state_district") or "").strip()
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name or not oblast:
            continue
        key = (name.casefold(), raion.casefold(), oblast.casefold())
        if key in seen:
            continue
        seen.add(key)
        where = ", ".join(part for part in (raion, oblast) if part and part not in (name, "м. " + name))
        found.append({"label": f"{name} — {where}" if where else name, "name": name, "oblast": oblast,
                      "raion": raion, "lat": round(lat, 4), "lon": round(lon, 4)})
    return found


def search(query: str, opener=urllib.request.urlopen, timeout: float = 8.0, sleep=time.sleep, now=time.monotonic) -> list:
    """Знайти населені пункти за назвою. Помилка мережі чи сервісу — GeocodeError із зрозумілим текстом."""
    query = (query or "").strip()
    if len(query) < 2:
        raise GeocodeError("введіть щонайменше дві літери")
    wait = MIN_INTERVAL - (now() - _last_request[0])
    if wait > 0:
        sleep(wait)                                        # правила сервісу: не частіше разу на секунду
    _last_request[0] = now()
    request = urllib.request.Request(build_url(query), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            return parse(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as error:
        raise GeocodeError(f"сервіс пошуку відповів помилкою {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GeocodeError("немає зв'язку із сервісом пошуку") from error
    except ValueError as error:
        raise GeocodeError("сервіс пошуку повернув незрозумілу відповідь") from error
