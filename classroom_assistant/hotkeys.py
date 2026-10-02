"""Гарячі клавіші й контекстні меню, що працюють у будь-якій розкладці.

Tk сам обробляє Ctrl+C/V/X/A лише при ЛАТИНСЬКІЙ розкладці. Для української
(та російської) розкладки ловимо фізичну клавішу за кодом і викликаємо ті самі
дії. Якщо розкладка латинська, нічого не робимо, щоб не вставити текст двічі.
"""
from __future__ import annotations
import sys
import tkinter as tk

# Windows: коди клавіш (не залежать від розкладки).
WIN_CODES={86:"v",67:"c",88:"x",65:"a",90:"z",89:"y",83:"s"}
# Інші системи: кириличні символи тих самих фізичних клавіш.
CYR_KEYSYMS={"Cyrillic_em":"v","Cyrillic_es":"c","Cyrillic_che":"x","Cyrillic_ef":"a",
             "Cyrillic_ya":"z","Cyrillic_en":"y","Cyrillic_yeru":"s",
             "Cyrillic_EM":"v","Cyrillic_ES":"c","Cyrillic_CHE":"x","Cyrillic_EF":"a",
             "Cyrillic_YA":"z","Cyrillic_EN":"y","Cyrillic_YERU":"s"}
TEXTLIKE=("Text","Entry","TEntry","TCombobox","Spinbox","TSpinbox")


def physical_letter(event):
    """Літера фізичної клавіші: 'v','c',... або '' (+ ознака латинської розкладки)."""
    keysym=str(event.keysym)
    latin=len(keysym)==1 and keysym.isascii()
    if sys.platform=="win32":
        return WIN_CODES.get(event.keycode,""),latin
    return (keysym.lower() if latin else CYR_KEYSYMS.get(keysym,"")),latin


def _on_control_key(event):
    letter,latin=physical_letter(event)
    if not letter:return None
    widget=event.widget
    if not hasattr(widget,"winfo_toplevel"):return None
    top=widget.winfo_toplevel()
    if letter=="s":
        # Ctrl+S: «зберегти» у вікні, де це підтримано (редактор року).
        top.event_generate("<<SaveAll>>")
        return "break" if getattr(top,"handles_save",False) else None
    if latin:
        return None   # латинську розкладку обробляє сам Tk
    cls=widget.winfo_class()
    try:
        if cls in TEXTLIKE:
            event_name={"v":"<<Paste>>","c":"<<Copy>>","x":"<<Cut>>",
                        "a":"<<SelectAll>>","z":"<<Undo>>","y":"<<Redo>>"}.get(letter)
            if event_name:
                widget.event_generate(event_name)
                return "break"
        elif cls in ("Treeview","Listbox"):
            if letter=="a":
                if cls=="Treeview":
                    widget.selection_set(widget.get_children())
                else:
                    widget.selection_set(0,"end")
                return "break"
            if letter=="c":
                widget.event_generate("<Control-Key-c>")
                return "break"
    except tk.TclError:
        return None
    return None


def _on_escape(event):
    if not hasattr(event.widget,"winfo_toplevel"):return None
    top=event.widget.winfo_toplevel()
    if not getattr(top,"escape_closes",False):return None
    try:
        handler=top.wm_protocol("WM_DELETE_WINDOW")
        if handler:top.tk.call(handler)
        else:top.destroy()
    except tk.TclError:
        return None
    return "break"


def _show_text_menu(event):
    widget=event.widget
    if not hasattr(widget,"bind"):return
    if widget.bind("<Button-3>"):return   # власне меню віджета має перевагу
    cls=widget.winfo_class()
    readonly=False
    try:
        readonly=(cls=="TCombobox" and str(widget.cget("state"))=="readonly")
        readonly=readonly or (cls=="Text" and str(widget.cget("state"))=="disabled")
    except tk.TclError:pass
    widget.focus_set()
    menu=tk.Menu(widget,tearoff=False)
    if not readonly:
        menu.add_command(label="Вирізати (Ctrl+X)",command=lambda:widget.event_generate("<<Cut>>"))
    menu.add_command(label="Копіювати (Ctrl+C)",command=lambda:widget.event_generate("<<Copy>>"))
    if not readonly:
        menu.add_command(label="Вставити (Ctrl+V)",command=lambda:widget.event_generate("<<Paste>>"))
    menu.add_command(label="Виділити все (Ctrl+A)",command=lambda:widget.event_generate("<<SelectAll>>"))
    try:menu.tk_popup(event.x_root,event.y_root)
    finally:menu.grab_release()


def install_hotkeys(root):
    """Один раз на програму: гарячі клавіші, Esc для діалогів, меню для полів."""
    root.bind_all("<Control-KeyPress>",_on_control_key,add="+")
    root.bind_all("<Escape>",_on_escape,add="+")
    for cls in ("Entry","TEntry","TCombobox","Text","Spinbox"):
        root.bind_class(cls,"<Button-3>",_show_text_menu,add="+")
    try:root.option_add("*Text.undo",True)
    except tk.TclError:pass
