"""Ярлик програми з логотипом на Робочому столі.

Іконка файла .exe вбудовується під час збірки на GitHub. Ярлик же зберігає СВОЮ іконку окремо від .exe, тому показує
логотип завжди, навіть якщо сам .exe ще зі стандартною іконкою. Створюється стандартними засобами Windows (PowerShell).
"""
from __future__ import annotations

import base64
import io
import subprocess
import sys
from pathlib import Path

NAME = "Помічник учителя Classroom"
ICON_NAME = "app_icon.ico"
NO_WINDOW = 0x08000000                                    # не показувати чорне вікно PowerShell


def ico_bytes() -> bytes:
    """Багаторозмірний .ico із вбудованого логотипу (той самий, що й іконка вікна)."""
    from PIL import Image
    from . import icon_builder
    from .app_icon_data import png_bytes
    return icon_builder.build_ico(Image.open(io.BytesIO(png_bytes())))


def write_icon(folder) -> Path:
    """Зберегти .ico у стабільне місце (папка програми): ярлик посилається на цей файл, тож він не має зникати."""
    target = Path(folder) / ICON_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ico_bytes())
    return target


def _quote(text) -> str:
    """Рядок для PowerShell в одинарних лапках (апостроф подвоюється)."""
    return "'" + str(text).replace("'", "''") + "'"


def powershell_script(exe, icon) -> str:
    exe = Path(exe)
    return "\n".join([
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "$shell = New-Object -ComObject WScript.Shell",
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$link = Join-Path $desktop {_quote(NAME + '.lnk')}",
        "$s = $shell.CreateShortcut($link)",
        f"$s.TargetPath = {_quote(exe)}",
        f"$s.WorkingDirectory = {_quote(exe.parent)}",
        f"$s.IconLocation = {_quote(str(icon) + ',0')}",
        f"$s.Description = {_quote(NAME)}",
        "$s.Save()",
        "Write-Output $link",
    ])


def encoded(script: str) -> str:
    """-EncodedCommand: UTF-16LE у base64, щоб кирилиця й лапки в шляхах не ламали команду."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def create_desktop_shortcut(folder, run=subprocess.run, platform=None, frozen=None, exe=None):
    """Створити ярлик на Робочому столі. Повертає (успіх, повідомлення для вчителя)."""
    platform = sys.platform if platform is None else platform
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if platform != "win32":
        return False, "Ярлик створюється лише у Windows."
    if not frozen:
        return False, "Ярлик створюється лише для готової програми (файл .exe), а не для запуску з вихідних кодів."
    try:
        icon = write_icon(folder)
        command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
                   encoded(powershell_script(exe or sys.executable, icon))]
        result = run(command, capture_output=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"Не вдалося створити ярлик: {error}"
    if result.returncode != 0:
        details = (result.stderr or b"").decode("utf-8", "replace").strip()[:300]
        return False, "Не вдалося створити ярлик. " + (details or "Windows не дозволила створити файл на Робочому столі.")
    where = (result.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    return True, f"Ярлик «{NAME}» створено на Робочому столі" + (f":\n{where[-1]}" if where else ".")
