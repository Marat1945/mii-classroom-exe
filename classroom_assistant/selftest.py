"""Самоперевірка зібраної програми: «--self-test файл» запускається на GitHub одразу після збірки.

Перевіряє, що в .exe справді потрапили всі потрібні бібліотеки й модулі програми (інакше програма не стартує, як було б
без python-docx), і пише звіт у файл. Код виходу 0 — усе гаразд; 1 — чогось бракує (збірка на GitHub стає червоною).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REQUIRED_LIBRARIES = ("docx", "PIL", "googleapiclient", "google_auth_oauthlib", "google_auth_httplib2", "openai",
                      "keyring", "tkinterdnd2", "tkinter")
PROGRAM_MODULES = ("classroom_assistant.engine", "classroom_assistant.documents", "classroom_assistant.gui",
                   "classroom_assistant.materials", "classroom_assistant.app_icon_data", "classroom_assistant.bell_data")
EXPECTED_BOOKS = 6


def checks() -> list:
    """[(статус, текст)]: OK / FAIL (збірка зламана) / WARN (варто глянути)."""
    results = []
    for name in REQUIRED_LIBRARIES + PROGRAM_MODULES:
        try:
            importlib.import_module(name)
            results.append(("OK", f"імпорт {name}"))
        except Exception as error:                                                  # будь-яка помилка = модуля фактично немає
            results.append(("FAIL", f"імпорт {name}: {type(error).__name__}: {error}"))
    try:
        from classroom_assistant import materials
        books = len(list(materials.bundled_dir().glob("*.pdf")))
        results.append(("OK" if books >= EXPECTED_BOOKS else "WARN",
                        f"довідників PDF у збірці: {books} (очікується {EXPECTED_BOOKS})"))
    except Exception as error:
        results.append(("WARN", f"довідники не перевірено: {error}"))
    return results


def run(report_path=None) -> int:
    results = checks()
    failed = [text for status, text in results if status == "FAIL"]
    lines = [f"{status}  {text}" for status, text in results]
    lines.append("ПІДСУМОК: " + ("ПОМИЛКА, не вистачає: " + "; ".join(failed) if failed else "УСПІХ"))
    text = "\n".join(lines)
    if report_path:
        try:
            Path(report_path).write_text(text, encoding="utf-8")
        except OSError:
            pass
    else:
        print(text)
    return 1 if failed else 0


def requested(argv=None) -> bool:
    argv = sys.argv if argv is None else argv
    return len(argv) >= 2 and argv[1] == "--self-test"
