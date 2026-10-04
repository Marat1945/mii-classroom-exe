"""Чи є інтернет: фоновий «пульс» для приладу на шапці (зелена лампочка / червона)."""
from __future__ import annotations

import socket
import threading

HOSTS = (("classroom.googleapis.com", 443), ("www.google.com", 443))


def check(timeout: float = 2.0, hosts=HOSTS) -> bool:
    """Швидка перевірка: чи вдається відкрити з'єднання до сервісів Google."""
    for host, port in hosts:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


class Monitor:
    """Фоновий потік, що кожні interval секунд оновлює online (True / False / None — ще не знаємо)."""

    def __init__(self, probe=check, interval: float = 12.0):
        self._probe = probe
        self._interval = interval
        self.online = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="net-monitor", daemon=True)
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            try:
                self.online = bool(self._probe())
            except Exception:
                self.online = False
            self._wake.wait(self._interval)
            self._wake.clear()

    def refresh_soon(self):
        """Перевірити негайно (наприклад, після невдалої синхронізації)."""
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
