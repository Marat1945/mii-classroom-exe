"""Вікна повідомлень у стилі програми (замість стандартних Windows): металева табличка з назвою, круглий значок,
пергаментний фон і латунні кнопки. Підмінюють tkinter.messagebox: решта коду програми не змінюється."""
from __future__ import annotations

import importlib.util
import tkinter as tk
from tkinter import messagebox as _mb
from tkinter import ttk

from . import retro_assets

_ORIGINAL = {}
KIND_FOR = {"showinfo": "info", "showwarning": "warning", "showerror": "error", "askyesno": "question",
            "askokcancel": "question", "askretrycancel": "warning", "askquestion": "question", "askyesnocancel": "question"}
BUTTONS = {
    "showinfo": ((("OK", "ok"),), "ok", "ok"), "showwarning": ((("OK", "ok"),), "ok", "ok"),
    "showerror": ((("OK", "ok"),), "ok", "ok"),
    "askyesno": ((("✔  Так", True), ("✖  Ні", False)), True, False),
    "askokcancel": ((("OK", True), ("Скасувати", False)), True, False),
    "askretrycancel": ((("Повторити", True), ("Скасувати", False)), True, False),
    "askquestion": ((("✔  Так", "yes"), ("✖  Ні", "no")), "yes", "no"),
    "askyesnocancel": ((("✔  Так", True), ("✖  Ні", False), ("Скасувати", None)), True, None),
}
LONG_TEXT = 700


def _parent(options):
    parent = options.get("parent")
    root = tk._default_root
    return parent.winfo_toplevel() if parent is not None else root


def _plate(window, title, before=None):
    """Металева табличка з назвою угорі вікна (як у вашому оригіналі)."""
    from .retro_header import BASE_TITLE, TITLE_FONT_FAMILY, hexcolor
    height = 46
    canvas = tk.Canvas(window, height=height, highlightthickness=0, bd=0, bg="#2f3631")
    if before is not None:
        canvas.pack(side="top", fill="x", before=before)
    else:
        canvas.pack(side="top", fill="x")
    window._plate_images = []

    def draw(_event=None):
        canvas.delete("all")
        width = max(canvas.winfo_width(), 300)
        if retro_assets.available():
            image = retro_assets.photo(retro_assets.plate_image(width - 8, height - 8, radius=8), canvas)
            window._plate_images = [image]
            canvas.create_image(4, 4, anchor="nw", image=image)
        canvas.create_text(width / 2, height / 2, text=title, fill=hexcolor(BASE_TITLE),
                           font=(TITLE_FONT_FAMILY, 15, "bold"))
    canvas.bind("<Configure>", draw)
    draw()
    return canvas


def _show(name, title=None, message=None, **options):
    root = _parent(options)
    custom = options.pop("choices", None)
    if root is None:
        if custom:
            return options.get("cancel_value", custom[-1][1])
        return _ORIGINAL[name](title, message, **options)
    kind = options.get("icon") if options.get("icon") in ("info", "warning", "error", "question") else KIND_FOR[name]
    choices, default_value, cancel_value = BUTTONS[name]
    if custom:                                                          # власні підписи кнопок (ask_choice)
        choices = tuple(custom)
        default_value = options.get("default_value", choices[0][1])
        cancel_value = options.get("cancel_value", choices[-1][1])
    if "default" in options:
        wanted = {"yes": True, "no": False, "ok": True, "cancel": False, "retry": True}.get(str(options["default"]))
        if wanted is not None and any(v == wanted for _, v in choices):
            default_value = wanted
    text = "" if message is None else str(message)
    if options.get("detail"):
        text += "\n\n" + str(options["detail"])
    window = tk.Toplevel(root)
    window.title(title or "")
    window.withdraw()
    window.resizable(False, False)
    window.transient(root)
    result = {"value": cancel_value}
    _plate(window, title or "")
    body = ttk.Frame(window, padding=(20, 16))
    body.pack(fill="both", expand=True)
    icon = None
    if retro_assets.available():
        icon = retro_assets.photo(retro_assets.dialog_icon(kind, 64), window)
        window._icon_image = icon
        ttk.Label(body, image=icon).grid(row=0, column=0, sticky="n", padx=(0, 16))
    if len(text) > LONG_TEXT or text.count("\n") > 14:                       # довгий звіт: прокручуване поле
        box = tk.Text(body, width=64, height=min(18, max(8, text.count("\n") + 2)), wrap="word", font=("Segoe UI", 10),
                      relief="solid", bd=1)
        box.insert("1.0", text)
        box.configure(state="disabled")
        scroll = ttk.Scrollbar(body, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        box.grid(row=0, column=1, sticky="nsew")
        scroll.grid(row=0, column=2, sticky="ns")
        window.message_widget = box
    else:
        label = ttk.Label(body, text=text, wraplength=440, justify="left", font=("Segoe UI", 10))
        label.grid(row=0, column=1, sticky="w")
        window.message_widget = label
    buttons = ttk.Frame(body)
    buttons.grid(row=1, column=0, columnspan=3, pady=(16, 0))
    window.buttons = {}

    def finish(value):
        result["value"] = value
        try:
            window.grab_release()
        except tk.TclError:
            pass
        window.destroy()
    for label_text, value in choices:
        button = ttk.Button(buttons, text=label_text, command=lambda v=value: finish(v), width=12)
        button.pack(side="left", padx=8)
        window.buttons[label_text] = button
        if value == default_value:
            window.default_button = button
    window.finish = finish
    window.bind("<Return>", lambda _e: finish(default_value))
    window.bind("<Escape>", lambda _e: finish(cancel_value))
    window.protocol("WM_DELETE_WINDOW", lambda: finish(cancel_value))
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
    y = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 3)
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
    window.deiconify()
    try:
        window.grab_set()
    except tk.TclError:
        pass
    getattr(window, "default_button", buttons).focus_set()
    window.wait_window()
    return result["value"]


def ask_choice(title, message, choices, **options):
    """Вікно у стилі програми з власними кнопками: choices = ((підпис, значення), ...). Перша — за замовчуванням (Enter),
    остання — скасування (Esc, закриття вікна). Повертає значення обраної кнопки."""
    return _show("askyesno", title, message, choices=choices, **options)


def _make(name):
    def dialog(title=None, message=None, **options):
        return _show(name, title, message, **options)
    dialog.__name__ = name
    return dialog


def _pristine() -> dict:
    """Справжні стандартні функції tkinter.messagebox (свіжа копія модуля: не залежить від того, що хтось уже підмінив)."""
    spec = importlib.util.find_spec("tkinter.messagebox")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: getattr(module, name) for name in KIND_FOR}


def install():
    """Підмінити стандартні вікна повідомлень на вікна у стилі програми. Чужі підміни (наприклад, заглушки в тестах)
    не чіпаємо: замінюються лише стандартні функції та наші власні."""
    if not _ORIGINAL:
        _ORIGINAL.update(_pristine())
    for name in KIND_FOR:
        current = getattr(_mb, name)
        if current is _ORIGINAL[name] or getattr(current, "__module__", None) in ("tkinter.messagebox", __name__):
            setattr(_mb, name, _make(name))


def uninstall():
    for name, function in list(_ORIGINAL.items()):
        setattr(_mb, name, function)
    _ORIGINAL.clear()
