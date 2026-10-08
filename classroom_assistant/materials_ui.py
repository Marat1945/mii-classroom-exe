"""Вікно «Навчальні матеріали»: вбудовані довідники й власні файли вчителя; відкрити чи зберегти в «Завантаження»."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import lecture_inbox, materials
from .toast import show_toast
from .window_ui import fit_work_window, remember_window, reuse_window

INTRO = ("Тут зібрано довідники й навчальні матеріали, які завжди під рукою: вони вшиті в програму й працюють без "
         "інтернету. Відкрийте файл або збережіть його в папку «Завантаження». Свої матеріали (для будь-якого предмета) "
         "можна додати: вони лишаються в програмі назавжди.")


def show_materials(app):
    """Відкривається ОДИН раз: повторний клац лише виносить вікно наперед."""
    existing = reuse_window(app, "materials")
    if existing:
        return existing
    from .engine import ROOT
    win = tk.Toplevel(app)
    remember_window(app, "materials", win)
    win.title("Навчальні матеріали")
    fit_work_window(win, "normal")
    win.transient(app)
    win.escape_closes = True
    outer = ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text=INTRO, wraplength=820, justify="left").pack(anchor="w")

    box = ttk.Frame(outer)
    box.pack(fill="both", expand=True, pady=(10, 6))
    columns = ("Назва", "Розділ", "Розмір")
    tree = ttk.Treeview(box, columns=columns, show="headings", selectmode="extended", height=9)
    for name, width in zip(columns, (520, 170, 90)):
        tree.heading(name, text=name)
        tree.column(name, width=width, stretch=(name == "Назва"))
    scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    tree.tag_configure("builtin", background="#EEE2C4")
    win.tree = tree
    items = {}
    status = tk.StringVar(master=win, value="")
    win.status = status

    def refresh(select=None):
        items.clear()
        tree.delete(*tree.get_children())
        for k, item in enumerate(materials.catalog(ROOT)):
            iid = str(k)
            items[iid] = item
            tree.insert("", "end", iid=iid, values=(item.title, item.section,
                                                    materials.human_size(item.size)), tags=("builtin",) if item.builtin else ())
        if select:
            for iid, item in items.items():
                if item.path == select:
                    tree.selection_set(iid)
                    tree.see(iid)
    win.refresh = refresh

    def chosen():
        return [items[i] for i in tree.selection() if i in items]

    def need_selection():
        picked = chosen()
        if not picked:
            status.set("Спершу оберіть матеріал у списку.")
        return picked

    def open_selected(_event=None):
        for item in need_selection()[:1]:
            try:
                materials.open_file(materials.local_copy(item, ROOT))
                status.set(f"Відкриваю: {item.title}")
            except Exception as error:
                messagebox.showerror("Навчальні матеріали", f"Не вдалося відкрити файл:\n{error}", parent=win)

    def save_selected():
        saved = []
        for item in need_selection():
            try:
                saved.append(materials.save_to_downloads(item, ROOT, lecture_inbox.downloads_dir()))
            except OSError as error:
                messagebox.showerror("Навчальні матеріали", f"Не вдалося зберегти:\n{error}", parent=win)
                return
        if saved:
            status.set(f"Збережено в «Завантаження»: {len(saved)}")
            show_toast(app, f"✓ Збережено в «Завантаження»: {saved[0].name}" + (f" і ще {len(saved) - 1}" if len(saved) > 1 else ""), 3200)

    def save_all_references():
        saved = []
        for item in (i for i in materials.catalog(ROOT) if i.builtin):
            saved.append(materials.save_to_downloads(item, ROOT, lecture_inbox.downloads_dir()))
        status.set(f"Збережено довідників у «Завантаження»: {len(saved)}")
        show_toast(app, f"✓ У «Завантаження» збережено довідників: {len(saved)}", 3200)

    def add_files():
        paths = filedialog.askopenfilenames(parent=win, title="Додати навчальні матеріали",
                                            filetypes=[("Документи, таблиці, презентації, зображення",
                                                        "*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.png *.jpg *.jpeg *.txt"),
                                                       ("Усі файли", "*.*")])
        if not paths:
            return
        copies = materials.add_files(ROOT, paths, section_var.get())
        refresh(copies[0] if copies else None)
        status.set(f"Додано матеріалів: {len(copies)}")
        show_toast(app, f"✓ Додано до навчальних матеріалів: {len(copies)}", 2800)

    def delete_selected():
        removed = 0
        for item in need_selection():
            if item.builtin:
                status.set("Вбудовані довідники видалити не можна: вони завжди лишаються в програмі.")
                continue
            if messagebox.askyesno("Навчальні матеріали", f"Видалити «{item.title}» зі своїх матеріалів?", parent=win):
                removed += materials.remove(item)
        if removed:
            refresh()
            status.set(f"Видалено: {removed}")

    def open_folder():
        folder = materials.user_dir(ROOT)
        folder.mkdir(parents=True, exist_ok=True)
        materials.open_file(folder)

    tree.bind("<Double-Button-1>", open_selected)
    row1 = ttk.Frame(outer)
    row1.pack(fill="x", pady=(0, 4))
    ttk.Button(row1, text="📖 Відкрити", command=open_selected).pack(side="left")
    ttk.Button(row1, text="⬇ Зберегти в «Завантаження»", command=save_selected).pack(side="left", padx=8)
    ttk.Button(row1, text="⬇ Усі довідники в «Завантаження»", command=save_all_references).pack(side="left")
    row2 = ttk.LabelFrame(outer, text=" Додати свої матеріали ", padding=8)
    row2.pack(fill="x", pady=(4, 4))
    section_var = tk.StringVar(master=win, value=materials.USER_SECTION)
    win.section_var = section_var
    ttk.Label(row2, text="Розділ (наприклад, назва предмета):").pack(side="left")
    ttk.Entry(row2, textvariable=section_var, width=26).pack(side="left", padx=6)
    ttk.Button(row2, text="➕ Додати файли…", command=add_files).pack(side="left")
    ttk.Button(row2, text="🗑 Видалити свій матеріал", command=delete_selected).pack(side="left", padx=8)
    ttk.Button(row2, text="📂 Папка матеріалів", command=open_folder).pack(side="left")
    ttk.Label(outer, textvariable=status, foreground="#5E5039").pack(anchor="w", pady=(4, 0))
    ttk.Button(outer, text="Закрити", command=win.destroy).pack(anchor="e", pady=(6, 0))
    win.open_selected, win.save_selected, win.add_files, win.delete_selected = open_selected, save_selected, add_files, delete_selected
    win.save_all_references = save_all_references
    refresh()
    return win
