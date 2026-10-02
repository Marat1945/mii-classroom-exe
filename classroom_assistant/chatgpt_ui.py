"""Вікно «Лекція через мій ChatGPT»: запит → ваш ChatGPT → відповідь → Word.

Нічого не надсилає в інтернет самостійно: лише копіює запит у буфер обміну
й за бажанням відкриває сторінку ChatGPT у браузері. Google Classroom не змінюється.
"""
from __future__ import annotations

import sys
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from .chatgpt_bridge import (DEFAULT_CHATGPT_URL, build_prompt, lesson_code,
                             looks_like_answer, parse_answer, safe_chatgpt_url)
from .engine import read_json, save_state
from .window_ui import maximize_work_window

WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "п’ятниця", "субота", "неділя")
# Фізичні клавіші для Ctrl+… навіть за української розкладки.
if sys.platform == "win32":
    KEY_V, KEY_A, KEY_C, KEY_X = 86, 65, 67, 88
else:
    KEY_V, KEY_A, KEY_C, KEY_X = 55, 38, 54, 53


class ChatGPTLectureDialog(tk.Toplevel):
    POLL_MS = 800

    def __init__(self, app, lessons, batch=False, replace_existing=False):
        super().__init__(app)
        self.app = app
        self.queue = list(lessons)
        self.batch = batch
        self.replace_existing = replace_existing
        self.position = 0
        self.created = []
        self.skipped = []
        self.lesson = None
        self.code = ""
        self._opened_browser = False
        self._last_clipboard = None
        self._parse_job = None
        self._poll_job = None
        self._closing = False
        self.title("Лекція через мій ChatGPT — безкоштовно")
        maximize_work_window(self)
        self.minsize(900, 620)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.show_current()
        self._poll_job = self.after(self.POLL_MS, self._poll_clipboard)

    # ---------- побудова ----------
    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        self.header = ttk.Label(outer, font=("Segoe UI", 12, "bold"), foreground="#1F4E79")
        self.header.pack(anchor="w")
        self.topic_label = ttk.Label(outer, font=("Segoe UI", 11), wraplength=1150, justify="left")
        self.topic_label.pack(anchor="w", pady=(2, 6))
        self.previous = ttk.Label(outer, foreground="#2E6B30")
        if self.batch:
            self.previous.pack(anchor="w")
        steps = ("1) «Копіювати запит»  →  2) у ChatGPT вставте (Ctrl+V) і надішліть  →  "
                 "3) під відповіддю ChatGPT натисніть «Копіювати»  →  4) поверніться сюди: "
                 "відповідь з’явиться в нижньому полі сама (або вставте її)  →  "
                 "5) «Створити Word».")
        ttk.Label(outer, text=steps, wraplength=1150, justify="left",
                  foreground="#33475B").pack(anchor="w", pady=(4, 8))
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="📋 Копіювати запит", command=self.copy_prompt).pack(side="left")
        ttk.Button(bar, text="🌐 Відкрити ChatGPT", command=self.open_chatgpt).pack(side="left", padx=6)
        self.auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Підхоплювати відповідь із буфера обміну автоматично",
                        variable=self.auto).pack(side="left", padx=10)
        self.url = tk.StringVar(value=safe_chatgpt_url(
            self.app.state.get("chatgpt_url", DEFAULT_CHATGPT_URL)))
        ttk.Entry(bar, textvariable=self.url, width=34).pack(side="right")
        ttk.Label(bar, text="Адреса ChatGPT (можна посилання на свій проєкт):").pack(side="right", padx=4)

        panes = ttk.PanedWindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True)
        top, bottom = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(top, weight=2)
        panes.add(bottom, weight=3)
        ttk.Label(top, text="Запит для ChatGPT (за бажанням допишіть, напр., автора підручника):"
                  ).pack(anchor="w")
        self.prompt = ScrolledText(top, wrap="word", height=10, font=("Segoe UI", 10))
        self.prompt.pack(fill="both", expand=True)
        ttk.Label(bottom, text="Відповідь ChatGPT:").pack(anchor="w", pady=(6, 0))
        self.answer = ScrolledText(bottom, wrap="word", height=14, font=("Segoe UI", 10))
        self.answer.pack(fill="both", expand=True)
        for widget in (self.prompt, self.answer):
            self._text_tools(widget)
        self.answer.bind("<<Modified>>", self._answer_changed)

        self.status = ttk.Label(outer, text="", wraplength=1150, justify="left")
        self.status.pack(anchor="w", pady=(8, 4))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        self.create_button = ttk.Button(buttons, text="✅ Створити Word для уроку",
                                        command=self.create_word, state="disabled")
        self.create_button.pack(side="left")
        if self.batch:
            ttk.Button(buttons, text="Пропустити цей урок", command=self.skip).pack(side="left", padx=8)
        ttk.Button(buttons, text="Закрити", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Платно через OpenAI API…",
                   command=self.use_api).pack(side="right", padx=8)

    def _text_tools(self, widget):
        def paste(_event=None):
            try:
                text = self.clipboard_get()
            except tk.TclError:
                return "break"
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            widget.insert("insert", text)
            return "break"

        def select_all(_event=None):
            widget.tag_add("sel", "1.0", "end-1c")
            return "break"

        def by_keycode(event):
            if event.keycode == KEY_V:
                return paste()
            if event.keycode == KEY_A:
                return select_all()
            if event.keycode == KEY_C:
                widget.event_generate("<<Copy>>")
                return "break"
            if event.keycode == KEY_X:
                widget.event_generate("<<Cut>>")
                return "break"
            return None

        for sequence in ("<Control-v>", "<Control-V>", "<Shift-Insert>"):
            widget.bind(sequence, paste)
        widget.bind("<Control-a>", select_all)
        widget.bind("<Control-KeyPress>", by_keycode, add=True)
        menu = tk.Menu(widget, tearoff=False)
        menu.add_command(label="Вирізати", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Копіювати", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Вставити", command=paste)
        menu.add_command(label="Виділити все", command=select_all)
        menu.add_separator()
        menu.add_command(label="Очистити поле", command=lambda: widget.delete("1.0", "end"))

        def show(event):
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
            menu.grab_release()
        widget.bind("<Button-3>", show)

    # ---------- поточний урок ----------
    def show_current(self):
        files = self.app.state.get("files", {})
        while (self.batch and self.position < len(self.queue)
               and files.get(self.queue[self.position].unique_key, {}).get("complete")):
            self.position += 1          # уже отримав готовий Word від сумісної паралелі
        if self.position >= len(self.queue):
            self.finish()
            return
        lesson = self.queue[self.position]
        self.lesson = lesson
        self.code = lesson_code(lesson)
        day = f"{lesson.day[8:10]}.{lesson.day[5:7]}.{lesson.day[:4]}"
        weekday = WEEKDAYS[int(lesson.weekday)] if str(lesson.weekday).isdigit() else ""
        counter = f"Урок {self.position + 1} з {len(self.queue)} • " if self.batch else ""
        self.header.config(text=f"{counter}{day}, {weekday} • {lesson.period}-й урок • "
                                f"{lesson.stream} • КТП №{lesson.lesson_number} • код {self.code}")
        self.topic_label.config(text="Тема: " + lesson.topic)
        try:
            plan_lessons = read_json("Календарні плани.json").get(lesson.plan_id, {}).get("lessons")
        except Exception:
            plan_lessons = None
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", build_prompt(lesson, plan_lessons))
        self.answer.delete("1.0", "end")
        self.answer.edit_modified(False)
        try:
            self._last_clipboard = self.clipboard_get()
        except tk.TclError:
            self._last_clipboard = None
        self._set_status("Натисніть «Копіювати запит». Відповідь ChatGPT для цього уроку "
                         "буде підхоплено з буфера обміну, щойно ви її скопіюєте.", "#33475B")
        self.create_button.config(state="disabled")

    def _set_status(self, text, color):
        self.status.config(text=text, foreground=color)

    # ---------- дії ----------
    def _remember_url(self):
        url = safe_chatgpt_url(self.url.get())
        self.url.set(url)
        if self.app.state.get("chatgpt_url") != url:
            self.app.state["chatgpt_url"] = url
            save_state(self.app.state)
        return url

    def copy_prompt(self):
        text = self.prompt.get("1.0", "end-1c").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        self._last_clipboard = text
        message = "Запит скопійовано. У ChatGPT вставте його (Ctrl+V) і надішліть."
        if not self._opened_browser:
            self.open_chatgpt()
            message += " ChatGPT відкрито в браузері."
        self._set_status(message, "#1F4E79")

    def open_chatgpt(self):
        url = self._remember_url()
        self._opened_browser = True
        try:
            webbrowser.open(url)
        except Exception as ex:   # браузер недоступний — запит усе одно в буфері
            messagebox.showwarning("ChatGPT", f"Не вдалося відкрити браузер: {ex}\n"
                                   f"Відкрийте вручну: {url}", parent=self)

    def _answer_changed(self, _event=None):
        if not self.answer.edit_modified():
            return
        self.answer.edit_modified(False)
        if self._parse_job:
            self.after_cancel(self._parse_job)
        self._parse_job = self.after(350, self.evaluate)

    def evaluate(self):
        self._parse_job = None
        text = self.answer.get("1.0", "end-1c")
        if not text.strip():
            self.create_button.config(state="disabled")
            self._set_status("Очікую відповідь ChatGPT…", "#33475B")
            return None
        result = parse_answer(text, self.code)
        if result["errors"]:
            self.create_button.config(state="disabled")
            self._set_status("❌ " + " ".join(result["errors"]), "#9B251F")
            return result
        material = result["material"]
        message = (f"✅ Розпізнано: розділів — {len(material['sections'])}, пунктів плану-конспекту — "
                   f"{len(material['notebook'])}, ≈{result['words']} слів.")
        if result["code_ok"]:
            message += " Код уроку збігається."
        if result["warnings"]:
            message += " ⚠ " + " ".join(result["warnings"])
        self.create_button.config(state="normal")
        self._set_status(message + " Можна створювати Word.", "#2E6B30")
        return result

    def _poll_clipboard(self):
        self._poll_job = None
        if self._closing or not self.winfo_exists():
            return
        try:
            if self.auto.get() and self.lesson is not None:
                try:
                    text = self.clipboard_get()
                except tk.TclError:
                    text = None
                if text and text != self._last_clipboard:
                    self._last_clipboard = text
                    if (looks_like_answer(text, self.code)
                            and self.answer.get("1.0", "end-1c").strip() != text.strip()):
                        self.answer.delete("1.0", "end")
                        self.answer.insert("1.0", text)
                        self.answer.edit_modified(False)
                        self.evaluate()
        finally:
            if not self._closing:
                self._poll_job = self.after(self.POLL_MS, self._poll_clipboard)

    def create_word(self):
        lesson = self.lesson
        if lesson is None:
            return
        result = parse_answer(self.answer.get("1.0", "end-1c"), self.code)
        if result["errors"]:
            messagebox.showerror("Відповідь ChatGPT", "\n".join(result["errors"]), parent=self)
            return
        if result["code"] is None and not messagebox.askyesno(
                "Перевірте відповідність",
                "У відповіді немає коду уроку.\n\nВи впевнені, що це відповідь саме для "
                f"«{lesson.stream}», тема «{lesson.topic}»?", parent=self):
            return
        try:
            path, attached = self.app.save_chatgpt_lecture(
                lesson, result["material"], replace_existing=self.replace_existing)
        except PermissionError:
            messagebox.showerror("Word", "Не вдалося записати Word: файл, імовірно, відкритий у Word.\n"
                                 "Закрийте його й натисніть «Створити Word» ще раз — "
                                 "відповідь залишилася в цьому вікні.", parent=self)
            return
        except Exception as ex:
            messagebox.showerror("Word", str(ex), parent=self)
            return
        self.created.append((lesson, attached, path))
        own = any(x.unique_key == lesson.unique_key for x in attached)
        note = (f"✅ {lesson.stream}: Word створено, прив’язано уроків: {len(attached)}."
                if own else
                f"⚠ {lesson.stream}: Word збережено в бібліотеці, але до цього уроку НЕ прив’язано "
                "(для нього вже є чернетка Google або підтверджений Word).")
        if self.batch:
            self.previous.config(text="Попередній урок — " + note)
            self.position += 1
            self.show_current()
        else:
            messagebox.showinfo("Лекцію створено", note + "\n\nУ Classroom нічого не створено. "
                                "Відкрийте Word і перевірте факти, дату та Д/з перед чернеткою.",
                                parent=self)
            self.close()

    def skip(self):
        if self.lesson is not None:
            self.skipped.append(self.lesson)
        self.position += 1
        self.show_current()

    def use_api(self):
        if not messagebox.askyesno(
                "OpenAI API", "Це ПЛАТНИЙ автоматичний режим: потрібен ваш OpenAI API-ключ, "
                "оплата окремо від підписки ChatGPT.\n\nПерейти до нього?", parent=self):
            return
        batch = self.batch
        self.close()
        if batch:
            self.app.batch_ai()
        else:
            self.app.make_word(True)

    def finish(self):
        if self.batch and (self.created or self.skipped):
            linked = sum(len(item[1]) for item in self.created)
            text = (f"Створено лекцій: {len(self.created)}. Прив’язано до уроків: {linked}.")
            if self.skipped:
                text += "\nПропущено: " + ", ".join(x.stream for x in self.skipped) + "."
            messagebox.showinfo("Лекції за день", text + "\n\nУ Classroom нічого не створено. "
                                "Перевірте Word перед чернетками.", parent=self.app)
        self.close()

    def close(self):
        self._closing = True
        for job in (self._poll_job, self._parse_job):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        if self.winfo_exists():
            self.destroy()


def open_chatgpt_dialog(app, lessons, batch=False, replace_existing=False):
    return ChatGPTLectureDialog(app, lessons, batch=batch, replace_existing=replace_existing)
