"""Історія дій: «Назад» і «Вперед» як у Word."""
from __future__ import annotations

import json

STATE_LABELS = {"files": "Word-файли", "attachments": "вкладення",
                "description_overrides": "текст повідомлення", "lesson_models": "перенесення уроку",
                "parallel_templates": "шаблон для паралелі"}


class History:
    def __init__(self, limit=60):
        self.limit = limit
        self.items = []
        self.index = -1
        self.step_meta = None          # додаткові відомості про крок, який щойно скасовано / повернуто

    def reset(self, snapshot, label="Початковий стан", meta=None):
        self.items = [(snapshot, label, meta)]
        self.index = 0
        self.step_meta = None

    @property
    def current(self):
        return self.items[self.index][0] if 0 <= self.index < len(self.items) else None

    def record(self, snapshot, label="Зміна", meta=None):
        if self.current == snapshot:
            return False
        del self.items[self.index + 1:]
        self.items.append((snapshot, label, meta))
        self.index = len(self.items) - 1
        if len(self.items) > self.limit:
            self.items.pop(0)
            self.index -= 1
        return True

    def replace_current(self, snapshot):
        if self.index >= 0:
            self.items[self.index] = (snapshot, self.items[self.index][1], self.items[self.index][2])

    def can_undo(self):
        return self.index > 0

    def can_redo(self):
        return 0 <= self.index < len(self.items) - 1

    def undo(self):
        """(знімок_до, назва_скасованої_дії) або None."""
        if not self.can_undo():
            return None
        label = self.items[self.index][1]
        self.step_meta = self.items[self.index][2]
        self.index -= 1
        return self.items[self.index][0], label

    def redo(self):
        if not self.can_redo():
            return None
        self.index += 1
        snapshot, label, self.step_meta = self.items[self.index]
        return snapshot, label

    def undo_label(self):
        return self.items[self.index][1] if self.can_undo() else ""

    def redo_label(self):
        return self.items[self.index + 1][1] if self.can_redo() else ""


def describe_change(old_json, new_json) -> str:
    """Коротка назва зміни за різницею двох знімків (для підказок «Скасовано: …»)."""
    try:
        old, new = json.loads(old_json), json.loads(new_json)
    except (TypeError, ValueError):
        return "зміну даних"
    parts = []
    if old.get("cfg") != new.get("cfg"):
        parts.append("розклад / налаштування")
    if old.get("plans") != new.get("plans"):
        parts.append("календарні плани")
    old_state, new_state = old.get("state", {}), new.get("state", {})
    for key in sorted(set(old_state) | set(new_state)):
        if old_state.get(key) != new_state.get(key):
            parts.append(STATE_LABELS.get(key, "дані"))
    unique = list(dict.fromkeys(parts))
    return ", ".join(unique[:3]) if unique else "зміну даних"
