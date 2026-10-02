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

from pathlib import Path

from .chatgpt_bridge import (DEFAULT_CHATGPT_URL, best_lesson_for_file, build_prompt,
                             lesson_code, looks_like_answer, match_score, parse_answer,
                             safe_chatgpt_url)
from .ui_kit import AccentButton
from . import autopaste
try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES = None

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
from .engine import read_json, save_state
from .window_ui import fit_work_window

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
        self.escape_closes = True
        self.dropped_docx = None
        self.dropped_images = []
        self.dropped_extra = []
        self.title("Лекція через мій ChatGPT — безкоштовно")
        fit_work_window(self,"normal")
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.show_current()
        self._poll_job = self.after(self.POLL_MS, self._poll_clipboard)

    # ---------- побудова ----------
    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        self.header = ttk.Label(outer, font=("Segoe UI", 12, "bold"), foreground="#1F4E79", wraplength=940)
        self.header.pack(anchor="w")
        self.topic_label = ttk.Label(outer, font=("Segoe UI", 11), wraplength=940, justify="left")
        self.topic_label.pack(anchor="w", pady=(2, 6))
        self.previous = ttk.Label(outer, foreground="#2E6B30")
        if self.batch:
            self.previous.pack(anchor="w")
        steps = ("1) «Відкрити ChatGPT»  →  2) запит вставиться сам, натисніть Enter  →  "
                 "3) коли ChatGPT створить файли, завантажте їх (Word і ОДНУ картинку)  →  "
                 "4) перетягніть файли з Провідника в рамку нижче (або вставте текст відповіді)  →  "
                 "5) «Прикріпити до уроку».")
        ttk.Label(outer, text=steps, wraplength=940, justify="left",
                  foreground="#33475B").pack(anchor="w", pady=(4, 8))
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(0, 6))
        AccentButton(bar, "🌐 Відкрити ChatGPT",
                     self.open_chatgpt).pack(side="left")
        ttk.Button(bar, text="📋 Копіювати запит", command=self.copy_prompt).pack(side="left", padx=8)
        self.mode = "file"
        self.mode_button = ttk.Button(bar, text="Запасний запит: текстом", command=self.toggle_mode)
        self.mode_button.pack(side="left")
        self.auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Підхоплювати текстову відповідь з буфера",
                        variable=self.auto).pack(side="left", padx=10)
        bar2 = ttk.Frame(outer)
        bar2.pack(fill="x", pady=(0, 6))
        self.url = tk.StringVar(value=safe_chatgpt_url(
            self.app.state.get("chatgpt_url", DEFAULT_CHATGPT_URL)))
        self.url.trace_add("write", lambda *_: self._save_url_if_valid())
        ttk.Label(bar2, text="Адреса ChatGPT (можна посилання на свій проєкт):").pack(side="left")
        ttk.Entry(bar2, textvariable=self.url).pack(side="left", fill="x", expand=True, padx=6)
        autopaste.build_controls(outer, self.app.state, save_state).pack(fill="x", pady=(0, 6))

        panes = ttk.PanedWindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True)
        top, bottom = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(top, weight=2)
        panes.add(bottom, weight=3)
        ttk.Label(top, text="Запит для ChatGPT (за бажанням допишіть, напр., автора підручника):"
                  ).pack(anchor="w")
        self.prompt = ScrolledText(top, wrap="word", height=5, font=("Segoe UI", 10))
        self.prompt.pack(fill="both", expand=True)
        self.drop_label = tk.Label(
            bottom, bg="#EAF2FA", fg="#164F82", relief="groove", bd=2, pady=12,
            font=("Segoe UI", 10, "bold"),
            text=("⬇  Перетягніть сюди з Провідника файли від ChatGPT: Word (.docx) та інфографіку (PNG/JPG)"
                  if DND_FILES else "Файли від ChatGPT додайте кнопкою «Додати файли…» нижче"))
        self.drop_label.pack(fill="x", pady=(6, 2))
        row = ttk.Frame(bottom)
        row.pack(fill="x")
        self.files_label = ttk.Label(row, text="", foreground="#2E6B30", wraplength=600)
        self.files_label.pack(side="left")
        ttk.Button(row, text="Додати файли…", command=self.pick_files).pack(side="right")
        ttk.Button(row, text="Очистити файли", command=self.clear_files).pack(side="right", padx=6)
        ttk.Label(bottom, text="…або відповідь ChatGPT текстом (якщо файли не створено):"
                  ).pack(anchor="w", pady=(4, 0))
        self.answer = ScrolledText(bottom, wrap="word", height=4, font=("Segoe UI", 10))
        self.answer.pack(fill="both", expand=True)
        self._setup_drop()
        for widget in (self.prompt, self.answer):
            self._text_tools(widget)
        self.answer.bind("<<Modified>>", self._answer_changed)

        self.status = ttk.Label(outer, text="", wraplength=940, justify="left")
        self.status.pack(anchor="w", pady=(8, 4))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        self.create_button = ttk.Button(buttons, text="✅ Прикріпити до уроку",
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
        self._plan_lessons = plan_lessons
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", build_prompt(lesson, plan_lessons, self.mode))
        self.answer.delete("1.0", "end")
        self.answer.edit_modified(False)
        self.clear_files()
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

    def toggle_mode(self):
        """Основний запит — готові файли; запасний — відповідь текстом (якщо файли не вдаються)."""
        self.mode = "text" if self.mode == "file" else "file"
        self.mode_button.config(text="Основний запит: файли" if self.mode == "text"
                                else "Запасний запит: текстом")
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", build_prompt(self.lesson, getattr(self, "_plan_lessons", None), self.mode))
        self._set_status("Запасний запит: ChatGPT відповість ТЕКСТОМ; скопіюйте відповідь — "
                         "вона з'явиться нижче сама." if self.mode == "text" else
                         "Основний запит: ChatGPT має видати готовий Word і одну картинку.", "#1F4E79")

    def _copy_prompt_text(self):
        text = self.prompt.get("1.0", "end-1c").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        self._last_clipboard = text

    def copy_prompt(self):
        self._copy_prompt_text()
        message = "Запит скопійовано. У ChatGPT вставте його (Ctrl+V) і надішліть."
        if not self._opened_browser:
            self.open_chatgpt(copy=False)
            message += " ChatGPT відкрито в браузері."
        self._set_status(message, "#1F4E79")

    def open_chatgpt(self, copy=True):
        if copy:
            self._copy_prompt_text()
        url = self._remember_url()
        self._opened_browser = True
        try:
            webbrowser.open(url)
            if copy:
                self._set_status("ChatGPT відкрито, запит УЖЕ скопійовано.", "#1F4E79")
            self._auto = autopaste.start_autopaste(
                self, self.app.state, self._copy_prompt_text,
                lambda text: self._set_status(text, "#1F4E79"))
        except Exception as ex:   # браузер недоступний — запит усе одно в буфері
            messagebox.showwarning("ChatGPT", f"Не вдалося відкрити браузер: {ex}\n"
                                   f"Відкрийте вручну: {url}", parent=self)

    def _save_url_if_valid(self):
        value = self.url.get().strip()
        if value.startswith("https://") and " " not in value \
                and self.app.state.get("chatgpt_url") != value:
            self.app.state["chatgpt_url"] = value
            try:
                save_state(self.app.state)
            except Exception:
                pass

    # ---------- файли від ChatGPT ----------
    def _setup_drop(self):
        if not DND_FILES:
            return
        for widget in (self.drop_label, self.answer):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<DropEnter>>", self._drop_enter)
            widget.dnd_bind("<<DropLeave>>", self._drop_leave)
            widget.dnd_bind("<<Drop>>", self._drop_files)

    def _drop_enter(self, _event=None):
        self.drop_label.config(bg="#FFE49A")
        return "copy"

    def _drop_leave(self, _event=None):
        self.drop_label.config(bg="#EAF2FA")
        return "copy"

    def _drop_files(self, event):
        self._drop_leave()
        try:
            names = list(self.tk.splitlist(event.data))
        except tk.TclError:
            return "copy"
        self.receive_files(names)
        return "copy"

    def pick_files(self):
        from tkinter import filedialog
        names = filedialog.askopenfilenames(parent=self, title="Файли від ChatGPT (Word, зображення)")
        if names:
            self.receive_files(list(names))

    def clear_files(self):
        self.dropped_docx = None
        self.dropped_images = []
        self.dropped_extra = []
        if hasattr(self, "files_label"):
            self.files_label.config(text="")

    def receive_files(self, names):
        from .material_library import check_real_docx
        problems = []
        for raw in names:
            path = Path(raw)
            if not path.is_file():
                continue
            suffix = path.suffix.casefold()
            if suffix == ".docx":
                try:
                    check_real_docx(path)
                except ValueError as ex:
                    problems.append(f"{path.name}: {ex}")
                    continue
                self.dropped_docx = path
            elif suffix in IMAGE_SUFFIXES:
                if path not in self.dropped_images:
                    self.dropped_images.append(path)
            elif suffix in (".txt", ".md"):
                try:
                    self.answer.delete("1.0", "end")
                    self.answer.insert("1.0", path.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeDecodeError) as ex:
                    problems.append(f"{path.name}: {ex}")
            else:
                if path not in self.dropped_extra:
                    self.dropped_extra.append(path)
        self._refresh_files_status(problems)

    def _docx_text(self, path):
        try:
            from docx import Document
            return "\n".join(p.text for p in Document(path).paragraphs[:40])
        except Exception:
            return ""

    def _refresh_files_status(self, problems=()):
        parts = []
        warning = ""
        if self.dropped_docx:
            parts.append(f"Word: {self.dropped_docx.name}")
            if match_score(self.lesson, self.dropped_docx.name, self._docx_text(self.dropped_docx)) < 2:
                warning = (" ⚠ У назві чи тексті Word не знайдено теми цього уроку — "
                           "переконайтеся, що це лекція саме для нього.")
        if self.dropped_images:
            parts.append("зображень: " + str(len(self.dropped_images)))
        if self.dropped_extra:
            parts.append("інших файлів: " + str(len(self.dropped_extra)))
        self.files_label.config(
            text=("✅ " + "; ".join(parts) + warning) if parts else "",
            foreground="#9B6A00" if warning else "#2E6B30")
        if problems:
            messagebox.showwarning("Файли", "\n".join(problems), parent=self)
        if self.dropped_docx:
            self.create_button.config(state="normal")
            self._set_status("Файли отримано. Натисніть «Прикріпити до уроку»: Word потрапить у "
                             "програму й у чернетку Classroom, зображення — у вкладення.",
                             "#2E6B30")
        elif not self.answer.get("1.0", "end-1c").strip():
            self.create_button.config(state="disabled")

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

    def _create_from_files(self):
        lesson = self.lesson
        extras = list(self.dropped_images) + list(self.dropped_extra)
        try:
            path, attached, skipped = self.app.save_dropped_lecture(
                lesson, self.dropped_docx, extras, replace_existing=self.replace_existing)
        except PermissionError:
            messagebox.showerror("Word", "Не вдалося записати Word: файл, імовірно, відкритий у Word.\n"
                                 "Закрийте його й спробуйте ще раз.", parent=self)
            return
        except Exception as ex:
            messagebox.showerror("Word", str(ex), parent=self)
            return
        self.created.append((lesson, attached, path))
        own = any(x.unique_key == lesson.unique_key for x in attached)
        note = (f"✅ {lesson.stream}: Word і файли прикріплено, уроків: {len(attached)}."
                if own else
                f"⚠ {lesson.stream}: Word збережено в бібліотеці, але до цього уроку НЕ прив’язано "
                "(для нього вже є чернетка Google або підтверджений Word).")
        if skipped:
            note += "\nДеякі вкладення не додано: " + skipped
        if self.batch:
            self.previous.config(text="Попередній урок — " + note)
            self.position += 1
            self.show_current()
        else:
            messagebox.showinfo("Лекцію прикріплено", note + "\n\nУ Classroom нічого не створено. "
                                "Відкрийте Word і перевірте факти перед чернеткою.", parent=self)
            self.close()

    def create_word(self):
        lesson = self.lesson
        if lesson is None:
            return
        if self.dropped_docx and not self.answer.get("1.0", "end-1c").strip():
            self._create_from_files()
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
        auto = getattr(self, "_auto", None)
        if auto is not None:
            auto.finished = True
        self._save_url_if_valid()
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


def _plan_lessons_of(lesson):
    try:
        from .engine import read_json
        return read_json("Календарні плани.json").get(lesson.plan_id, {}).get("lessons")
    except Exception:
        return None


def build_day_prompt(lessons):
    """Один спільний запит на всі уроки дня: кожен урок — окреме завдання з власними файлами."""
    from .chatgpt_bridge import PROMPT_MARKER
    total = len(lessons)
    lines = [
        f"{PROMPT_MARKER} — лекції на весь день ({total} " + ("урок" if total == 1 else "уроків") + ")",
        "",
        "Нижче "+str(total)+" окремих завдань — по одному на кожен урок. НЕ став уточнювальних "
        "запитань і не чекай підтвердження: виконай їх ПІДРЯД. "
        "Для КОЖНОГО уроку створи його власні два файли (справжній Word з текстом — НЕ картинку — і "
        "PNG-інфографіку) з ТОЧНИМИ іменами, вказаними в завданні. Після всіх завдань напиши в чаті "
        "по одному рядку на урок: «Готово. КОД УРОКУ: …» — і дай посилання на всі файли. "
        "Лекції в чат не переписуй.",
        "",
    ]
    for number, lesson in enumerate(lessons, 1):
        lines.append(f"==================== ЗАВДАННЯ {number} з {total} ====================")
        lines.append(build_prompt(lesson, _plan_lessons_of(lesson)))
        lines.append("")
    return "\n".join(lines)


class ChatGPTDayDialog(tk.Toplevel):
    """Усі лекції дня одним запитом. Галочками можна зняти клас, для якого Word не потрібен."""

    def __init__(self, app, lessons):
        super().__init__(app)
        self.app = app
        self.lessons = list(lessons)
        self.checked = set(range(len(self.lessons)))
        self.docx = {}            # індекс уроку → шлях до Word
        self.images = {}          # індекс уроку → список зображень
        self.unassigned = []
        self.escape_closes = True
        day = self.lessons[0].day
        self.title(f"Лекції ГПТ на весь день — {day[8:10]}.{day[5:7]}.{day[:4]}")
        fit_work_window(self, "normal")
        self.transient(app)
        self._build()
        self.refresh()
        self._rebuild_prompt()

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        self.counter = ttk.Label(outer, font=("Segoe UI", 12, "bold"), foreground="#1F4E79")
        self.counter.pack(anchor="w")
        ttk.Label(outer, wraplength=1000, justify="left", foreground="#33475B", text=(
            "Галочка = для цього класу готуємо Word. Зніміть її там, де лекція не потрібна. "
            "Далі: «Відкрити ChatGPT»  →  Enter  →  завантажте створені файли "
            "(Word і PNG)  →  перетягніть УСІ файли разом у рамку нижче  →  «Прикріпити всі».")
        ).pack(anchor="w", pady=(2, 6))
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(0, 4))
        AccentButton(bar, "🌐 Відкрити ChatGPT", self.open_chatgpt,
                     color="#2E8B57", hover="#3AA36B").pack(side="left")
        ttk.Button(bar, text="📋 Копіювати запит", command=self.copy_prompt).pack(side="left", padx=8)
        ttk.Button(bar, text="☑ Усі", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bar, text="☐ Жодного", command=lambda: self._set_all(False)).pack(side="left", padx=4)
        bar2 = ttk.Frame(outer)
        bar2.pack(fill="x", pady=(0, 4))
        self.url = tk.StringVar(value=safe_chatgpt_url(
            self.app.state.get("chatgpt_url", DEFAULT_CHATGPT_URL)))
        self.url.trace_add("write", lambda *_: self._save_url())
        ttk.Label(bar2, text="Адреса ChatGPT:").pack(side="left")
        ttk.Entry(bar2, textvariable=self.url).pack(side="left", fill="x", expand=True, padx=6)
        autopaste.build_controls(outer, self.app.state, save_state).pack(fill="x", pady=(0, 6))

        columns = ("use", "num", "stream", "topic", "spread", "word", "pictures")
        self.table = ttk.Treeview(outer, columns=columns, show="headings", height=5,
                                  selectmode="browse")
        for name, title, width in (("use", "Word?", 60), ("num", "КТП №", 60), ("stream", "Потік", 150),
                                   ("topic", "Тема", 400), ("spread", "Охоплює (уроків)", 130),
                                   ("word", "Word", 70), ("pictures", "Зображення", 90)):
            self.table.heading(name, text=title)
            self.table.column(name, width=width, anchor="w" if name == "topic" else "center")
        self.table.pack(fill="x")
        self.table.bind("<Button-1>", self._click)
        self.table.bind("<space>", self._space)
        self.table.bind("<Double-1>", self._double)
        panes = ttk.PanedWindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(8, 0))
        top, bottom = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(top, weight=2)
        panes.add(bottom, weight=2)
        self.prompt = ScrolledText(top, wrap="word", height=3, font=("Segoe UI", 9))
        self.prompt.pack(fill="both", expand=True)
        self.drop_label = tk.Label(
            bottom, bg="#EAF2FA", fg="#164F82", relief="groove", bd=2, pady=14,
            font=("Segoe UI", 10, "bold"),
            text=("⬇  Перетягніть сюди ВСІ файли від ChatGPT (Word і картинки) разом"
                  if DND_FILES else "Файли від ChatGPT додайте кнопкою «Додати файли…»"))
        self.drop_label.pack(fill="x")
        row = ttk.Frame(bottom)
        row.pack(fill="x", pady=4)
        self.note = ttk.Label(row, text="", wraplength=800, foreground="#2E6B30")
        self.note.pack(side="left")
        ttk.Button(row, text="Додати файли…", command=self.pick_files).pack(side="right")
        ttk.Label(bottom, text="Файли, які не вдалося розпізнати (двічі клацніть, щоб вибрати урок):"
                  ).pack(anchor="w")
        self.unknown = tk.Listbox(bottom, height=2)
        self.unknown.pack(fill="both", expand=True)
        self.unknown.bind("<Double-1>", self._assign_menu)
        if DND_FILES:
            for widget in (self.drop_label, self.unknown):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>", lambda e: (self.drop_label.config(bg="#FFE49A"), "copy")[1])
                widget.dnd_bind("<<DropLeave>>", lambda e: (self.drop_label.config(bg="#EAF2FA"), "copy")[1])
                widget.dnd_bind("<<Drop>>", self._drop)
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(8, 0))
        AccentButton(buttons, "✅ Прикріпити всі", self.attach_all).pack(side="left")
        ttk.Button(buttons, text="Закрити", command=self.close).pack(side="right")

    # ---- вибір уроків ----
    def active_lessons(self):
        return [self.lessons[i] for i in sorted(self.checked)]

    def _toggle(self, index):
        if index in self.checked:
            self.checked.discard(index)
        else:
            self.checked.add(index)
        self.refresh()
        self._rebuild_prompt()

    def _set_all(self, value):
        self.checked = set(range(len(self.lessons))) if value else set()
        self.refresh()
        self._rebuild_prompt()

    def _click(self, event):
        if self.table.identify_region(event.x, event.y) != "cell":
            return None
        row = self.table.identify_row(event.y)
        if row and self.table.identify_column(event.x) == "#1":
            self._toggle(int(row))
            return "break"
        return None

    def _double(self, event):
        row = self.table.identify_row(event.y)
        if row and self.table.identify_column(event.x) != "#1":
            self._toggle(int(row))
        return "break"

    def _space(self, _event=None):
        selected = self.table.selection()
        if selected:
            self._toggle(int(selected[0]))
        return "break"

    def _rebuild_prompt(self):
        active = self.active_lessons()
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", build_day_prompt(active) if active else
                           "Не вибрано жодного класу: поставте галочку «Word?» біля потрібних уроків.")

    # ---- запит ----
    def _save_url(self):
        value = self.url.get().strip()
        if value.startswith("https://") and " " not in value \
                and self.app.state.get("chatgpt_url") != value:
            self.app.state["chatgpt_url"] = value
            try:
                save_state(self.app.state)
            except Exception:
                pass

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.prompt.get("1.0", "end-1c").strip())
        self.update_idletasks()

    def _say(self, text):
        self.note.config(text=text, foreground="#1F4E79")

    def copy_prompt(self):
        if not self.checked:
            messagebox.showinfo("Лекції", "Не вибрано жодного класу.", parent=self)
            return
        self._copy()
        self._say("Запит скопійовано. У ChatGPT натисніть Ctrl+V і Enter.")

    def open_chatgpt(self):
        if not self.checked:
            messagebox.showinfo("Лекції", "Не вибрано жодного класу: поставте галочку «Word?».", parent=self)
            return
        self._copy()
        url = safe_chatgpt_url(self.url.get())
        try:
            webbrowser.open(url)
            self._say("ChatGPT відкрито, запит УЖЕ скопійовано.")
            self._auto = autopaste.start_autopaste(self, self.app.state, self._copy, self._say)
        except Exception as ex:
            messagebox.showwarning("ChatGPT", f"Не вдалося відкрити браузер: {ex}\n{url}", parent=self)

    # ---- файли ----
    def _drop(self, event):
        self.drop_label.config(bg="#EAF2FA")
        try:
            names = list(self.tk.splitlist(event.data))
        except tk.TclError:
            return "copy"
        self.receive_files(names)
        return "copy"

    def pick_files(self):
        from tkinter import filedialog
        names = filedialog.askopenfilenames(parent=self, title="Файли від ChatGPT")
        if names:
            self.receive_files(list(names))

    def _docx_text(self, path):
        try:
            from docx import Document
            return "\n".join(p.text for p in Document(path).paragraphs[:40])
        except Exception:
            return ""

    def receive_files(self, names):
        from .material_library import check_real_docx
        problems = []
        for raw in names:
            path = Path(raw)
            if not path.is_file():
                continue
            suffix = path.suffix.casefold()
            text = ""
            if suffix == ".docx":
                try:
                    check_real_docx(path)
                except ValueError as ex:
                    problems.append(f"{path.name}: {ex}")
                    continue
                text = self._docx_text(path)
            elif suffix not in IMAGE_SUFFIXES:
                problems.append(f"{path.name}: очікується Word або зображення.")
                continue
            lesson = best_lesson_for_file(self.lessons, path.name, text)
            if lesson is None:
                if path not in self.unassigned:
                    self.unassigned.append(path)
                continue
            self._assign(self.lessons.index(lesson), path)
        self.refresh()
        if problems:
            messagebox.showwarning("Файли", "\n".join(problems), parent=self)

    def _assign(self, index, path):
        if path.suffix.casefold() == ".docx":
            self.docx[index] = path
        else:
            bucket = self.images.setdefault(index, [])
            if path not in bucket:
                bucket.append(path)
        if path in self.unassigned:
            self.unassigned.remove(path)

    def _assign_menu(self, event):
        picked = self.unknown.nearest(event.y)
        if picked < 0 or picked >= len(self.unassigned):
            return
        path = self.unassigned[picked]
        menu = tk.Menu(self, tearoff=False)
        for index, lesson in enumerate(self.lessons):
            menu.add_command(label=f"{lesson.stream}: {lesson.topic[:70]}",
                             command=lambda i=index: (self._assign(i, path), self.refresh()))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def refresh(self):
        selected = self.table.selection()
        for item in self.table.get_children():
            self.table.delete(item)
        for index, lesson in enumerate(self.lessons):
            try:
                spread = len(self.app._parallel(lesson))
            except Exception:
                spread = "—"
            self.table.insert("", "end", iid=str(index), values=(
                "☑" if index in self.checked else "☐", lesson.lesson_number, lesson.stream,
                lesson.topic[:110], spread, "✅" if index in self.docx else "—",
                len(self.images.get(index, [])) or "—"))
        if selected and self.table.exists(selected[0]):
            self.table.selection_set(selected[0])
        self.unknown.delete(0, "end")
        for path in self.unassigned:
            self.unknown.insert("end", path.name)
        self.counter.config(text=f"Вибрано для лекції: {len(self.checked)} з {len(self.lessons)}")
        ready = len(self.docx)
        self.note.config(text=f"Розпізнано Word: {ready}."
                         + (f" Нерозпізнаних файлів: {len(self.unassigned)}." if self.unassigned else ""),
                         foreground="#2E6B30" if ready else "#33475B")

    def attach_all(self):
        if not self.docx:
            messagebox.showinfo("Лекції", "Спершу додайте файли Word від ChatGPT.", parent=self)
            return
        done, warnings = 0, []
        for index, path in sorted(self.docx.items()):
            lesson = self.lessons[index]
            try:
                _, attached, skipped = self.app.save_dropped_lecture(
                    lesson, path, self.images.get(index, []))
            except Exception as ex:
                warnings.append(f"{lesson.stream}: {ex}")
                continue
            done += 1
            if not any(x.unique_key == lesson.unique_key for x in attached):
                warnings.append(f"{lesson.stream}: Word збережено в бібліотеці, але урок уже має чернетку "
                                "або підтверджений Word.")
            if skipped:
                warnings.append(f"{lesson.stream}: {skipped}")
        text = f"Прикріплено лекцій: {done}."
        waiting = [self.lessons[i].stream for i in sorted(self.checked) if i not in self.docx]
        if waiting:
            text += "\nЗалишились без Word (позначені, але файлу немає): " + ", ".join(waiting[:8])
        if warnings:
            text += "\n\n" + "\n".join(warnings[:6])
        messagebox.showinfo("Лекції за день", text + "\n\nУ Classroom нічого не створено. "
                            "Перевірте Word перед чернетками.", parent=self)
        self.close()

    def close(self):
        auto = getattr(self, "_auto", None)
        if auto is not None:
            auto.finished = True
        self._save_url()
        try:
            self.destroy()
        except tk.TclError:
            pass


def open_day_dialog(app, lessons):
    return ChatGPTDayDialog(app, lessons)
