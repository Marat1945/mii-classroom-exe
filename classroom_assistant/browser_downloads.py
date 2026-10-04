"""Куди браузер зберігає завантажене. Програма лише ЧИТАЄ налаштування Chrome / Edge / Brave.

Змінити папку завантажень може тільки сам браузер (так захищено від сайтів і програм), тому програма:
  • бачить, чи збігається папка завантажень браузера з її папкою «Вхідні файли GPT» («прямий запис»);
  • стежить і за тією папкою, яку справді вибрав браузер (лише файли з назвою уроку);
  • відкриває сторінку налаштувань браузера й веде вчителя по кроках.
Нічого в налаштуваннях браузера програма не пише.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

BROWSERS = {
    "Chrome": ("Google/Chrome/User Data", "chrome://settings/downloads",
               ("Google/Chrome/Application/chrome.exe",)),
    "Edge": ("Microsoft/Edge/User Data", "edge://settings/downloads",
             ("Microsoft/Edge/Application/msedge.exe",)),
    "Brave": ("BraveSoftware/Brave-Browser/User Data", "brave://settings/downloads",
              ("BraveSoftware/Brave-Browser/Application/brave.exe",)),
}


@dataclass
class Found:
    browser: str
    folder: Path | None          # None — у налаштуваннях немає власної папки, тобто звичайні «Завантаження»
    profile: str
    prefs: Path


def local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def read_download_dir(prefs_path) -> str | None:
    """download.default_directory із файла налаштувань браузера (Preferences). Немає або не читається — None."""
    try:
        data = json.loads(Path(prefs_path).read_text(encoding="utf-8"))
        value = (data.get("download") or {}).get("default_directory")
        return str(value) if value else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def detect(base=None) -> list:
    """Знайдені браузери (за профілем Default та Profile N). base — корінь «AppData\\Local» (для тестів)."""
    root = Path(base) if base else local_app_data()
    found = []
    for name, (relative, _url, _exe) in BROWSERS.items():
        user_data = root / Path(relative)
        if not user_data.is_dir():
            continue
        profiles = [p for p in sorted(user_data.iterdir()) if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))
                    and (p / "Preferences").is_file()]
        if not profiles:
            found.append(Found(name, None, "—", user_data / "Preferences"))
            continue
        for profile in profiles:
            value = read_download_dir(profile / "Preferences")
            found.append(Found(name, Path(value) if value else None, profile.name, profile / "Preferences"))
    return found


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")


def same_folder(a, b) -> bool:
    return bool(a) and bool(b) and _norm(a) == _norm(b)


def classify(item: Found, inbox, downloads) -> str:
    """direct — браузер пише прямо в папку програми; default — у звичайні «Завантаження»; other — в іншу папку."""
    if item.folder is None:
        return "direct" if same_folder(downloads, inbox) else "default"
    if same_folder(item.folder, inbox):
        return "direct"
    if same_folder(item.folder, downloads):
        return "default"
    return "other"


def watch_folders(found, skip=()) -> list:
    """Папки браузерів, за якими варто стежити додатково (без дублів і без тих, що вже відстежуються)."""
    seen = {_norm(p) for p in skip}
    folders = []
    for item in found:
        if item.folder is None or _norm(item.folder) in seen:
            continue
        seen.add(_norm(item.folder))
        if item.folder.is_dir():
            folders.append(item.folder)
    return folders


def any_direct(found, inbox, downloads) -> bool:
    return any(classify(item, inbox, downloads) == "direct" for item in found)


def settings_url(browser: str) -> str:
    return BROWSERS[browser][1]


def executable(browser: str):
    """Шлях до браузера (стандартні місця встановлення Windows) або None."""
    relatives = BROWSERS[browser][2]
    bases = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for base in filter(None, bases):
        for relative in relatives:
            candidate = Path(base) / Path(relative)
            if candidate.is_file():
                return candidate
    return None


def open_settings(browser: str) -> bool:
    """Відкрити сторінку «Завантаження» в налаштуваннях браузера. True — вдалося запустити."""
    url = settings_url(browser)
    exe = executable(browser)
    try:
        if exe:
            subprocess.Popen([str(exe), url])
            return True
    except OSError:
        pass
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False
