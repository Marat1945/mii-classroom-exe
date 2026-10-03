"""Майстер першого підключення Google Classroom (для будь-якого вчителя).

Показується, поки вхід ще не виконано. Далі кнопка «Підключити Google»
працює лише як оновлення. Програма не бачить пароль: вхід відбувається на сторінці Google.
"""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import google_client
from .ui_kit import AccentButton
from .window_ui import fit_work_window

CLOUD = "https://console.cloud.google.com/"
LINKS = {
    "project": "https://console.cloud.google.com/projectcreate",
    "classroom": "https://console.cloud.google.com/apis/library/classroom.googleapis.com",
    "drive": "https://console.cloud.google.com/apis/library/drive.googleapis.com",
    "consent": "https://console.cloud.google.com/auth/overview",
    "clients": "https://console.cloud.google.com/auth/clients",
}

# (стиль, текст[, посилання]) — «h» заголовок, «p» абзац, «l» клікабельне посилання.
INSTRUCTION = [
    ("h", "ЯК ПІДКЛЮЧИТИ ВАШ GOOGLE CLASSROOM (один раз, приблизно 10 хвилин)"),
    ("p", "Щоб програма бачила ваші класи та створювала ЧЕРНЕТКИ, Google вимагає власний «ключ доступу» "
          "для вашого облікового запису. Він безкоштовний. Програма НЕ бачить ваш пароль: вхід "
          "відбувається на сторінці Google. Нічого не публікується учням без вашої команди."),
    ("h", "Крок 1. Увійдіть у Google Cloud"),
    ("p", "Відкрийте сторінку й увійдіть тим акаунтом, у якому ваші класи Classroom:"),
    ("l", CLOUD, CLOUD),
    ("p", "Якщо шкільний акаунт не дозволяє користуватися Google Cloud, створіть проєкт під особистим "
          "Gmail, а на кроці 6 при вході в програмі оберіть шкільний акаунт (де класи). Якщо школа "
          "блокує сторонні програми, попросіть адміністратора Google Workspace дозволити доступ."),
    ("h", "Крок 2. Створіть проєкт"),
    ("l", LINKS["project"], LINKS["project"]),
    ("p", "Назва — будь-яка, наприклад «Помічник учителя». Натисніть «Створити» й зачекайте кілька секунд. "
          "Угорі сторінки має бути вибрано саме цей проєкт."),
    ("h", "Крок 3. Увімкніть дві служби (кнопка «Увімкнути» / «Enable» на кожній сторінці)"),
    ("l", "Google Classroom API", LINKS["classroom"]),
    ("l", "Google Drive API", LINKS["drive"]),
    ("h", "Крок 4. Налаштуйте екран згоди"),
    ("l", LINKS["consent"], LINKS["consent"]),
    ("p", "Натисніть «Розпочати» («Get started»). Назва застосунку — «Помічник учителя»; електронна "
          "пошта підтримки — ваша; аудиторія («Audience») — «Зовнішня» («External»); контактна пошта — "
          "ваша; прийміть умови й «Створити». Потім у розділі «Аудиторія» («Audience») знайдіть "
          "«Тестові користувачі» («Test users»), натисніть «Додати користувачів» і впишіть адресу "
          "акаунта, у якому ваші класи. Збережіть."),
    ("p", "Порада: щоб вхід не доводилося повторювати щотижня, у тому ж розділі натисніть "
          "«Опублікувати застосунок» («Publish app»). Google покаже, що застосунок «не перевірений»: "
          "це нормально, бо він ваш власний."),
    ("h", "Крок 5. Створіть і завантажте ключ"),
    ("l", LINKS["clients"], LINKS["clients"]),
    ("p", "«Створити клієнта» («Create client») → тип застосунку «Комп'ютерний застосунок» («Desktop app») "
          "→ назва → «Створити» → «Завантажити JSON» («Download JSON»). Файл збережеться у «Завантаження»."),
    ("h", "Крок 6. Поверніться сюди"),
    ("p", "1) Натисніть «Вибрати завантажений JSON…» і виберіть цей файл.\n"
          "2) Натисніть «Увійти через Google». Відкриється браузер: оберіть акаунт, де ваші класи. Якщо "
          "Google пише «Цей застосунок не перевірено», натисніть «Додатково» → «Перейти до … (небезпечно)» "
          "— це ваш власний застосунок. Поставте всі галочки доступу й «Продовжити». Коли сторінка "
          "напише, що можна закрити вкладку, поверніться в програму."),
    ("p", "Після входу програма сама підтягне ваші класи в порядку Classroom і оновлюватиме їх при кожному "
          "запуску. Далі кнопка «Підключити Google» працює лише як ручне оновлення."),
    ("h", "Якщо щось не виходить"),
    ("p", "• «Помилка доступу» / «access_denied»: на кроці 4 не додано вашу адресу в «Тестові користувачі».\n"
          "• Просить входити щотижня: на кроці 4 натисніть «Опублікувати застосунок».\n"
          "• Файл не приймається: потрібен ключ типу «Комп'ютерний застосунок», не «Веб-застосунок».\n"
          "• Назви пунктів у Google можуть відрізнятися від цих: шукайте за змістом або надішліть "
          "скриншот розробникові програми."),
]


class GoogleWizard(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Підключення Google Classroom — перший раз")
        fit_work_window(self, "large")
        self.transient(app)
        self.escape_closes = True
        self._busy = False

        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        self.json_status = ttk.Label(top, font=("Segoe UI", 10, "bold"))
        self.json_status.pack(anchor="w")
        self.login_status = ttk.Label(top, font=("Segoe UI", 10, "bold"))
        self.login_status.pack(anchor="w")

        self.text = ScrolledText(self, wrap="word", font=("Segoe UI", 10), padx=12, pady=8,
                                 relief="flat", height=10)
        self.text.pack(fill="both", expand=True, padx=12, pady=4)
        self._fill_text()

        bar = ttk.Frame(self, padding=(12, 6, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="🌐 Відкрити Google Cloud", command=lambda: webbrowser.open(CLOUD)).pack(side="left")
        ttk.Button(bar, text="📁 Вибрати завантажений JSON…", command=self.choose_json).pack(side="left", padx=8)
        self.login_button = AccentButton(bar, "🔑 Увійти через Google", self.login)
        self.login_button.pack(side="left")
        ttk.Button(bar, text="Закрити", command=self.destroy).pack(side="right")
        self.refresh_status()

    def _fill_text(self):
        widget = self.text
        widget.tag_configure("h", font=("Segoe UI", 11, "bold"), foreground="#1F4E79", spacing1=10, spacing3=3)
        widget.tag_configure("link", foreground="#1F6FB2", underline=True)
        for item in INSTRUCTION:
            kind, text = item[0], item[1]
            if kind == "h":
                widget.insert("end", text + "\n", "h")
            elif kind == "p":
                widget.insert("end", text + "\n")
            else:
                url = item[2]
                tag = f"link{len(url)}{abs(hash(url)) % 100000}"
                widget.tag_configure(tag, foreground="#1F6FB2", underline=True)
                widget.tag_bind(tag, "<Button-1>", lambda _e, u=url: webbrowser.open(u))
                widget.tag_bind(tag, "<Enter>", lambda _e: widget.config(cursor="hand2"))
                widget.tag_bind(tag, "<Leave>", lambda _e: widget.config(cursor=""))
                widget.insert("end", "   ➜ " + text + "\n", tag)
        widget.config(state="disabled")

    def refresh_status(self):
        have_json = google_client.credentials_present()
        logged_in = google_client.token_ready()
        self.json_status.config(
            text=("✅ Файл ключа вибрано" if have_json else "⬜ Файл ключа ще не вибрано (крок 5–6)"),
            foreground="#2E6B30" if have_json else "#9B6A00")
        self.login_status.config(
            text=("✅ Вхід у Google виконано" if logged_in else "⬜ Вхід у Google ще не виконано"),
            foreground="#2E6B30" if logged_in else "#9B6A00")

    def choose_json(self):
        path = filedialog.askopenfilename(
            parent=self, title="Виберіть JSON, завантажений із Google Cloud",
            filetypes=[("JSON", "*.json"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            google_client.import_credentials_file(path)
        except ValueError as ex:
            messagebox.showerror("Файл ключа", str(ex), parent=self)
            return
        self.refresh_status()
        messagebox.showinfo("Файл ключа", "Ключ прийнято. Тепер натисніть «Увійти через Google».", parent=self)

    def login(self):
        if self._busy:
            return
        if not google_client.credentials_present():
            messagebox.showinfo("Спершу ключ", "Спершу виберіть файл JSON (кнопка «Вибрати завантажений JSON…»).",
                                parent=self)
            return
        self._busy = True
        self.login_button.config(state="disabled")
        self.login_status.config(text="⏳ Відкрито браузер: завершіть вхід на сторінці Google…",
                                 foreground="#1F4E79")

        self._outcome = None

        def run():
            try:
                google_client.authenticate()
                self._outcome = ("ok", "")
            except Exception as ex:                       # мережа, скасований вхід, помилка доступу
                self._outcome = ("error", str(ex))
        threading.Thread(target=run, daemon=True).start()
        self.after(300, self._poll_login)

    def _poll_login(self):
        """Результат входу забираємо з головного потоку (безпечно для Tk)."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self._outcome is None:
            self.after(300, self._poll_login)
            return
        kind, message = self._outcome
        if kind == "ok":
            self._done()
        else:
            self._failed(message)

    def _failed(self, message):
        self._busy = False
        try:
            self.login_button.config(state="normal")
            self.refresh_status()
        except tk.TclError:
            return
        messagebox.showerror(
            "Вхід не виконано",
            f"{message}\n\nПеревірте крок 4 (ваша адреса в «Тестових користувачах») і спробуйте ще раз.",
            parent=self)

    def _done(self):
        self._busy = False
        try:
            self.refresh_status()
            messagebox.showinfo("Готово", "Google підключено. Зараз програма підтягне ваші класи.", parent=self)
            self.destroy()
        except tk.TclError:
            pass
        self.app.sync_classroom(interactive=True)


def show_google_wizard(app):
    return GoogleWizard(app)
