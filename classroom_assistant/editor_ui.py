"""Tkinter-редактор КТП/розкладу/класів/року, повністю локальний."""
from __future__ import annotations
import copy
import json
import re
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from .editor_core import (deep_copy_data, guess_columns, extract_lessons,
    docx_table_rows, csv_rows, persist, validate_working, tidy, migrate_stream_keys,
    import_source_dates, source_date_for_stream, parse_source_dates, import_notes)
from .engine import ROOT, save_state, build_calendar
from .window_ui import fit_work_window
from .material_library import stream_subject
from .datepicker import DateField, pick_date
from .history import History, describe_change
from .course_match import (assign_streams, best_match, link_streams, norm as match_norm, parse as match_parse,
                           _expand as expand_subjects)
from . import ktp_detect, ktp_import
try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES=None



def friendly_plan_id(code):
    """Українська позначка в інтерфейсі; старий ідентифікатор залишається в базі."""
    variants={"iu":"ІУ","vi":"ВІ","go":"ГО","law":"Право","hist":"Історія",
              "profile":"профіль","standard":"стандарт"}
    bits=re.split(r"[_\s]+",str(code))
    if not bits:return str(code)
    letter={"B":"Б","G":"Г","A":"А","V":"В"}
    m=re.fullmatch(r"(\d+)([ABGV])",bits[0],re.I)
    if m:
        grade=m.group(1)
        group=letter.get(m.group(2).upper(),m.group(2))
        first=f"{grade}-{group}"
    else:first=bits[0]
    other=[variants.get(v.casefold(),v) for v in bits[1:]]
    return " ".join([first]+other)

def display_ui_date(iso):
    return date.fromisoformat(iso).strftime("%d.%m.%Y")

def parse_ui_date(value):
    value=str(value).strip()
    if "." in value:
        return datetime.strptime(value,"%d.%m.%Y").date().isoformat()
    return date.fromisoformat(value).isoformat()

def attach_paste(widget, host):
    """Вставлення навіть тоді, коли системні прив'язки Ctrl+V не працюють."""
    def paste(_event=None):
        try:
            text=host.clipboard_get()
            if isinstance(widget,tk.Text):
                widget.insert("insert",text)
            else:
                widget.insert(tk.INSERT,text)
        except tk.TclError:
            messagebox.showwarning("Буфер обміну","У буфері обміну немає тексту.",parent=host)
        return "break"
    for sequence in ("<Control-v>","<Control-V>","<Shift-Insert>"):
        widget.bind(sequence,paste,add=False)
    menu=tk.Menu(widget,tearoff=0)
    menu.add_command(label="Вставити",command=paste)
    def show_menu(e):
        menu.tk_popup(e.x_root,e.y_root)
        menu.grab_release()
    widget.bind("<Button-3>",show_menu,add=True)
    return paste


def api_key_dialog(parent):
    """Окремий діалог замість simpledialog.askstring(show='*') із кнопкою вставлення."""
    window=tk.Toplevel(parent)
    window.title("OpenAI API — безпечне введення")
    fit_work_window(window,"small")
    window.resizable(False,False)
    window.transient(parent)
    window.grab_set()
    box=ttk.Frame(window,padding=16);box.pack(fill="both",expand=True)
    ttk.Label(box,text="Скопіюйте свій API-ключ на сайті OpenAI та вставте його сюди.",
              wraplength=570).pack(anchor="w",pady=(0,8))
    keyvar=tk.StringVar()
    field=ttk.Entry(box,textvariable=keyvar,show="•",width=80)
    field.pack(fill="x",pady=5)
    paste=attach_paste(field,window)
    visible=tk.BooleanVar(value=False)
    def toggle():
        field.configure(show="" if visible.get() else "•")
    ttk.Checkbutton(box,text="Тимчасово показати введений ключ",variable=visible,command=toggle).pack(anchor="w")
    ttk.Label(box,text="Ключ не записується у Word, ZIP, GitHub чи текстові налаштування.",
              foreground="#3d566a").pack(anchor="w",pady=6)
    controls=ttk.Frame(box);controls.pack(fill="x",pady=(9,0))
    ttk.Button(controls,text="Вставити з буфера",command=paste).pack(side="left")
    ttk.Button(controls,text="Скасувати",command=window.destroy).pack(side="right")
    def save():
        key=keyvar.get().strip()
        if not key:
            messagebox.showwarning("OpenAI","Спочатку вставте ключ.",parent=window);return
        if not key.startswith("sk-"):
            if not messagebox.askyesno("Перевірте ключ","Ключ зазвичай починається на sk-. Все одно зберегти?",parent=window):
                return
        try:
            import keyring
            keyring.set_password("Помічник учителя Classroom","OPENAI_API_KEY",key)
        except Exception as ex:
            messagebox.showerror("Сховище Windows",str(ex),parent=window)
            return
        keyvar.set("")
        messagebox.showinfo("Готово","Ключ збережено у сховищі облікових даних Windows.",parent=window)
        window.destroy()
    ttk.Button(controls,text="Зберегти ключ",command=save).pack(side="right",padx=8)
    window.bind("<Return>",lambda _:save())
    field.focus_set()
    parent.wait_window(window)


class ImportPreview(tk.Toplevel):
    """Імпорт документа лише ПІСЛЯ попереднього перегляду, без автоматичного перезаписування."""
    def __init__(self,parent,path,on_accept):
        super().__init__(parent)
        self.title("Попередній перегляд імпорту КТП")
        fit_work_window(self,"large")
        self.transient(parent);self.grab_set()
        self.path=Path(path);self.on_accept=on_accept
        self._excluded_indices=set()
        self.rows=docx_table_rows(path) if self.path.suffix.lower() in (".docx",".doc") else csv_rows(path)
        longest=max((len(row) for row in self.rows),default=0)
        if longest<2: raise ValueError("Не знайдено таблицю зі стовпцями тем і домашніх завдань")
        samples=next((r for r in self.rows[:8] if any("тема" in c.casefold() or "зміст" in c.casefold() for c in r)),self.rows[0])
        topic,home,number=guess_columns(samples)
        self.topicvar=tk.IntVar(value=topic+1)
        self.hwvar=tk.IntVar(value=home+1)
        self.numvar=tk.IntVar(value=number+1)
        outer=ttk.Frame(self,padding=10);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Перевірте стовпці: дати й назви класів імпортуємо, якщо вони є у файлі. Нічого не збережено.",
                  font=("Segoe UI",10,"bold")).pack(anchor="w",pady=6)
        fields=ttk.Frame(outer);fields.pack(fill="x",pady=8)
        for label,var in [("№ уроку (стовпець)",self.numvar),("Тема (стовпець)",self.topicvar),("Д/з (стовпець)",self.hwvar)]:
            block=ttk.Frame(fields);block.pack(side="left",padx=9)
            ttk.Label(block,text=label).pack(anchor="w")
            ttk.Spinbox(block,from_=1,to=longest,textvariable=var,width=6).pack()
        ttk.Button(fields,text="Переглянути розпізнане",command=self.refresh).pack(side="left",padx=12)
        ttk.Label(outer,text="Зверніть увагу: розділи без номера уроку не імпортуються. Після імпорту можна змінити будь-який пункт.").pack(anchor="w")
        table=ttk.Frame(outer);table.pack(fill="both",expand=True,pady=6)
        self.tree=ttk.Treeview(table,columns=("num","dates","topic","hw"),show="headings")
        for col,text,width in (("num","№",120),("dates","Дати за класами з файлу",300),
                               ("topic","Тема",530),("hw","Д/з",350)):
            self.tree.heading(col,text=text);self.tree.column(col,width=width,anchor="w")
        sb=ttk.Scrollbar(table,command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")
        self.tree.bind("<Delete>",lambda e:self.remove_preview_rows())
        self.tree.bind("<Control-c>",lambda e:self.copy_preview_rows())
        self.tree.bind("<Button-3>",self._preview_context_menu)
        bottom=ttk.Frame(outer);bottom.pack(fill="x")
        self.status=ttk.Label(bottom,text="");self.status.pack(side="left")
        ttk.Button(bottom,text="Скасувати",command=self.destroy).pack(side="right")
        ttk.Button(bottom,text="Замінити план після перевірки",command=self.commit).pack(side="right",padx=8)
        self.refresh()

    def refresh(self):
        try:
            self.parsed=extract_lessons(self.rows,self.topicvar.get()-1,
                 self.hwvar.get()-1,self.numvar.get()-1,True)
            self.parsed=import_source_dates(
                self.rows,self.parsed,self.topicvar.get()-1,
                self.numvar.get()-1,
                academic_start=int(self.master.cfg["year_start"][:4]))
        except (ValueError,tk.TclError) as e:
            messagebox.showerror("Стовпці",str(e),parent=self);return
        self.parsed=[row for row in self.parsed
                     if row["index"] not in self._excluded_indices]
        for item in self.tree.get_children():self.tree.delete(item)
        for row in self.parsed:
            dates=row.get("source_dates",{})
            preview=", ".join(f"{key}: {value[8:10]}.{value[5:7]}.{value[:4]}"
                               for key,value in dates.items())
            label=str(row["index"])
            original=row.get("source_number") or ""
            if original and original.rstrip(".)")!=label:
                label+=f" (у файлі {original})"
            self.tree.insert("","end",iid=str(row["index"]),
                             values=(label,preview,row["topic"],row["homework"]))
        empties=sum(not r["homework"] for r in self.parsed)
        with_dates=sum(bool(x.get("source_dates")) for x in self.parsed)
        classes=sorted({klass for row in self.parsed for klass in
                        row.get("source_dates",{}) if klass!="*"})
        notes=import_notes(self.parsed)
        self.status.config(text=f"Уроків: {len(self.parsed)}. Із датами: {with_dates}. "
           f"Класи: {', '.join(classes) or 'загальна дата'}. Без Д/з: {empties}."
           +(" ПЕРЕВІРТЕ: "+"; ".join(notes)+"." if notes else ""))

    def copy_preview_rows(self):
        choice=self.tree.selection()
        if not choice:return "break"
        lines=["\t".join(str(v) for v in self.tree.item(item,"values"))
               for item in choice]
        self.clipboard_clear();self.clipboard_append("\n".join(lines))
        return "break"

    def remove_preview_rows(self):
        choice=self.tree.selection()
        if not choice:return "break"
        if not messagebox.askyesno("Імпорт КТП",
              f"Виключити з майбутнього імпорту {len(choice)} рядків? "
              "Вихідний Word на диску залишиться без змін.",parent=self):
            return "break"
        self._excluded_indices.update(int(item) for item in choice)
        self.refresh()
        return "break"

    def _preview_context_menu(self,event):
        item=self.tree.identify_row(event.y)
        if item and item not in self.tree.selection():
            self.tree.selection_set(item)
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Копіювати рядки (Ctrl+C)",command=self.copy_preview_rows)
        menu.add_command(label="Виключити рядки з імпорту (Delete)",
                         command=self.remove_preview_rows)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def commit(self):
        self.refresh()
        if not self.parsed:
            messagebox.showerror("Імпорт","Не знайдено жодного уроку. Перевірте номери стовпців.",parent=self);return
        payload=copy.deepcopy(self.parsed)
        for ix,row in enumerate(payload,1):
            row["index"]=ix
        self.on_accept(payload,self.path.name)
        self.destroy()


SUBJECT_CODES=("ІУ","ВІ","ГО","Право","історія")


class SchoolEditor(tk.Toplevel):
    def __init__(self,parent,on_saved):
        super().__init__(parent)
        self.title("КЕРУВАННЯ НАВЧАЛЬНИМ РОКОМ • редагування КТП і розкладу")
        fit_work_window(self,"normal")
        self.transient(parent)
        self.cfg,self.plans=deep_copy_data()
        self.original_cfg,self.original_plans=copy.deepcopy(self.cfg),copy.deepcopy(self.plans)
        self.on_saved=on_saved
        self.parent=parent
        self.current_plan=None;self.lesson_row=None
        self.current_entry=None;self.list_entries=[];self.plan_keys=[]
        self._active_inline=None
        self.escape_closes=True;self.handles_save=True
        self.bind("<<SaveAll>>",lambda _:self.save())
        outer=ttk.Frame(self,padding=8);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Редагуйте та перевіряйте локально. До Google нічого не надсилається.",
                  foreground="#245471").pack(anchor="w")
        notebook=ttk.Notebook(outer);notebook.pack(fill="both",expand=True,pady=7)
        self.notebook=notebook
        self.tab_plans=ttk.Frame(notebook);self.tab_schedule=ttk.Frame(notebook)
        self.tab_streams=ttk.Frame(notebook);self.tab_year=ttk.Frame(notebook)
        notebook.add(self.tab_plans,text="КАЛЕНДАРНІ ПЛАНИ")
        notebook.add(self.tab_schedule,text="РОЗКЛАД")
        notebook.add(self.tab_streams,text="КЛАСИ / КУРСИ")
        notebook.add(self.tab_year,text="НАВЧАЛЬНИЙ РІК, КАНІКУЛИ")
        self._plans_ui();self._schedule_ui();self._streams_ui();self._year_ui()
        buttons=ttk.Frame(outer);buttons.pack(fill="x",pady=4)
        ttk.Button(buttons,text="ЗБЕРЕГТИ ВСІ ЗМІНИ (з резервною копією)",command=self.save).pack(side="left")
        self.undo_button=ttk.Button(buttons,text="↶ Назад",command=self.undo,state="disabled")
        self.undo_button.pack(side="left",padx=(12,2))
        self.redo_button=ttk.Button(buttons,text="↷ Вперед",command=self.redo,state="disabled")
        self.redo_button.pack(side="left",padx=2)
        self.history_note=ttk.Label(buttons,text="",foreground="#2E6B30")
        self.history_note.pack(side="left",padx=8)
        ttk.Button(buttons,text="Відкрити папку резервних копій",
                   command=self.open_backup).pack(side="left",padx=12)
        ttk.Button(buttons,text="Закрити",command=self.close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW",self.close)
        # Побудова вкладок сама оновлює похідні поля (напр. список курсів):
        # запам'ятати стан ПІСЛЯ цього, щоб «незбережені зміни» означали лише ваші правки.
        self.auto_link()
        self._setup_file_drop_targets()          # у кінці: щоб drop приймала і нижня смуга кнопок
        self.original_cfg=copy.deepcopy(self.cfg)
        self.original_plans=copy.deepcopy(self.plans)
        self.history=History()
        self.history.reset(self._history_snapshot())
        self.history_undo=self.undo;self.history_redo=self.redo      # Ctrl+Z / Ctrl+Y
        self._poll_job=self.after(700,self._history_poll)

    # ---------- Назад / Вперед ----------
    def _history_snapshot(self):
        return json.dumps({"cfg":self.cfg,"plans":self.plans},ensure_ascii=False,sort_keys=True)

    def _history_buttons(self):
        try:
            self.undo_button.config(state="normal" if self.history.can_undo() else "disabled")
            self.redo_button.config(state="normal" if self.history.can_redo() else "disabled")
        except tk.TclError:pass

    def _history_record(self):
        self._commit_pending_edit()
        snapshot=self._history_snapshot()
        if snapshot!=self.history.current:
            self.history.record(snapshot,describe_change(self.history.current,snapshot))
        self._history_buttons()

    def _history_poll(self):
        try:
            if not self.winfo_exists():return
            self._history_record()
        except tk.TclError:return
        self._poll_job=self.after(700,self._history_poll)

    def _restore_snapshot(self,snapshot):
        data=json.loads(snapshot)
        self.cfg,self.plans=data["cfg"],data["plans"]
        self.lesson_row=None;self.current_plan=None;self.current_entry=None
        self._refresh_planlist();self.refresh_slots();self.refresh_streams()
        self.refresh_holidays()
        self.history.replace_current(self._history_snapshot())   # похідні поля не вважаємо новою дією
        self._history_buttons()

    def undo(self):
        self._history_record()
        step=self.history.undo()
        if not step:
            self.history_note.config(text="Немає що скасовувати.",foreground="#9B6A00");return "break"
        self._restore_snapshot(step[0])
        self.history_note.config(text=f"Скасовано: {step[1]}",foreground="#2E6B30")
        return "break"

    def redo(self):
        self._history_record()
        step=self.history.redo()
        if not step:
            self.history_note.config(text="Немає що повертати.",foreground="#9B6A00");return "break"
        self._restore_snapshot(step[0])
        self.history_note.config(text=f"Повернуто: {step[1]}",foreground="#2E6B30")
        return "break"

    def destroy(self):
        job=getattr(self,"_poll_job",None)
        if job:
            try:self.after_cancel(job)
            except tk.TclError:pass
        super().destroy()

    def _setup_file_drop_targets(self):
        """Перетягування файлів: на клас, на таблиці — і в БУДЬ-ЯКЕ місце вікна (КТП чи розклад — сама)."""
        if not DND_FILES:return
        self._dnd_highlight=None
        self.lessons.tag_configure("drop-target",background="#FFE49A")
        self.slots.tag_configure("drop-target",background="#FFE49A")
        self.streamtree.tag_configure("drop-target",background="#FFE49A")
        specific=((self.planlist,"planlist"),(self.lessons,"lesson"),(self.slots,"schedule"),
                  (self.streamtree,"stream"))
        taken={id(widget) for widget,_ in specific}
        self.drop_hint=tk.Label(self,bg="#FFE49A",fg="#164F82",font=("Segoe UI",10,"bold"),
            text="⬇  Відпустіть файли: програма сама визначить, що це (КТП чи розклад) і кому призначити")
        everything=list(specific)
        stack=[self]
        while stack:
            widget=stack.pop()
            stack.extend(widget.winfo_children())
            if id(widget) not in taken and widget is not self.drop_hint:
                everything.append((widget,"window"))
        everything.append((self.drop_hint,"window"))
        for widget,kind in everything:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>",lambda e,k=kind:self._highlight_ktp_drop(e,k))
                widget.dnd_bind("<<DropPosition>>",lambda e,k=kind:self._highlight_ktp_drop(e,k))
                widget.dnd_bind("<<DropLeave>>",self._clear_ktp_drop)
                widget.dnd_bind("<<Drop>>",lambda e,k=kind:self._drop_ktp_file(e,k))
            except tk.TclError:pass

    def _show_drop_hint(self):
        try:self.drop_hint.place(x=0,y=0,relwidth=1,height=28);self.drop_hint.lift()
        except (AttributeError,tk.TclError):pass

    def _hide_drop_hint(self):
        try:self.drop_hint.place_forget()
        except (AttributeError,tk.TclError):pass

    def _planlist_item_at(self,y):
        """Рядок списку під вказівником; None, якщо вказівник поза рядками (порожнє місце)."""
        if not self.planlist.size() or y<0:return None
        index=self.planlist.nearest(y)
        box=self.planlist.bbox(index)
        if not box or y<box[1] or y>box[1]+box[3]:return None
        return index

    def _clear_ktp_drop(self,_event=None):
        old=getattr(self,"_dnd_highlight",None)
        if old:
            widget,index,kind=old
            try:
                if kind=="planlist":
                    widget.itemconfigure(index,background="")
                elif widget.exists(index):
                    tags=[x for x in widget.item(index,"tags") if x!="drop-target"]
                    widget.item(index,tags=tuple(tags))
            except tk.TclError:pass
        self._dnd_highlight=None
        self._hide_drop_hint()
        return "copy"

    def _highlight_ktp_drop(self,event,kind):
        if kind=="window":
            self._show_drop_hint();return "copy"
        self._hide_drop_hint()
        widget={"planlist":self.planlist,"lesson":self.lessons,
                "schedule":self.slots,"stream":self.streamtree}[kind]
        y=widget.winfo_pointery()-widget.winfo_rooty()
        item=(self._planlist_item_at(y) if kind=="planlist" else widget.identify_row(y))
        if item is not None and (widget,item,kind)!=getattr(self,"_dnd_highlight",None):
            self._clear_ktp_drop()
            if kind=="planlist":
                widget.itemconfigure(item,background="#FFE49A")
            elif item:
                tags=set(widget.item(item,"tags"));tags.add("drop-target")
                widget.item(item,tags=tuple(tags))
            self._dnd_highlight=(widget,item,kind)
        return "copy"

    def _drop_ktp_file(self,event,kind):
        """Один або кілька файлів, кинутих будь-куди у вікні: імпорт без запитань «Так/Ні»."""
        item=None
        if kind!="window":
            widget={"planlist":self.planlist,"lesson":self.lessons,
                    "schedule":self.slots,"stream":self.streamtree}[kind]
            y=widget.winfo_pointery()-widget.winfo_rooty()
            item=(self._planlist_item_at(y) if kind=="planlist" else widget.identify_row(y))
        self._clear_ktp_drop()
        try:
            files=[Path(x) for x in self.tk.splitlist(event.data)]
        except tk.TclError:
            return "copy"
        files=[f for f in files if f.is_file()]
        if not files:return "copy"
        entry=None
        if kind=="planlist":
            if item is not None and 0<=item<len(self.list_entries):
                self.planlist.selection_clear(0,"end")
                self.planlist.selection_set(item)
                self.plan_selected()
                entry=self.current_entry
            else:                       # повз клас: програма сама визначить клас за змістом файлу
                self.planlist.selection_clear(0,"end")
                self.current_entry=None;self.current_plan=None
        elif kind=="lesson":
            entry=self.current_entry
        elif kind=="stream" and item:
            name=widget.item(item,"values")[0]
            course=self.cfg["course_map"].get(name,{}).get("course_title")
            index=next((i for i,e in enumerate(self.list_entries) if e.get("course")==course),None)
            if index is not None:
                self.notebook.select(self.tab_plans)
                self.planlist.selection_clear(0,"end")
                self.planlist.selection_set(index)
                self.plan_selected()
                entry=self.current_entry
        self.import_files(files,entry)
        return "copy"

    def open_backup(self):
        import os
        folder=ROOT/"Архів навчальних даних"
        folder.mkdir(parents=True,exist_ok=True)
        if os.name=="nt":
            os.startfile(folder)
        else:
            messagebox.showinfo("Резервні копії",str(folder),parent=self)

    def _is_dirty(self):
        if self.cfg!=self.original_cfg or self.plans!=self.original_plans:return True
        try:values=self._year_values()
        except Exception:return False
        if any(self.cfg.get(k)!=v for k,v in values.items()):return True
        return (self.teacher_var.get().strip()!=str(self.cfg.get("workload_teacher","")).strip()
                or self.code_var.get().strip()!=str(self.cfg.get("workload_code","")).strip())

    def close(self):
        if self._is_dirty():
            answer=messagebox.askyesnocancel("Зберегти зміни?",
                "У редакторі є незбережені зміни.\n\nЗберегти їх перед закриттям?\n\n"
                "«Так» — зберегти (буде створено резервну копію)\n"
                "«Ні» — закрити без збереження\n«Скасувати» — повернутися",parent=self)
            if answer is None:return
            if answer and not self.save(confirm=False):return
        try:self.destroy()
        except tk.TclError:pass

    def _plans_ui(self):
        tab=self.tab_plans
        left=ttk.Frame(tab,padding=6);left.pack(side="left",fill="y")
        ttk.Label(left,text="Класи з вашого Classroom",
                  font=("Segoe UI",10,"bold")).pack(anchor="w")
        ttk.Label(left,foreground="#365777",wraplength=250,justify="left",
                  text=("Порядок як у Classroom. Перетягніть у будь-яке місце вікна ВСІ файли КТП "
                        "(і розклад) разом: програма сама визначить, кому вони. Або на клас." if DND_FILES else
                        "Порядок як у Classroom. Для КТП натисніть «Імпортувати файли…».")
                  ).pack(anchor="w",pady=(0,4))
        self.planlist=tk.Listbox(left,width=31,exportselection=False,height=11,
                                 activestyle="none",selectbackground="#2E7BC4",
                                 selectforeground="white")
        self.planlist.pack(fill="y",expand=True)
        self.planlist.bind("<<ListboxSelect>>",self.plan_selected)
        self.planlist.bind("<Button-3>",self._plan_context_menu)
        self.planlist.bind("<Delete>",lambda e:self.delete_ktp())
        self.planlist.bind("<F2>",lambda e:self.rename_subject())
        self.planlist.bind("<Control-c>",lambda e:self.copy_plan_data())
        ttk.Button(left,text="+ Додати курс",command=lambda:self.edit_course(True)).pack(fill="x",pady=(4,2))
        ttk.Button(left,text="✎ Редагувати курс",command=lambda:self.edit_course(False)).pack(fill="x",pady=2)
        ttk.Button(left,text="Імпортувати файли…",command=self.import_plan).pack(fill="x",pady=2)
        ttk.Button(left,text="Позначити КТП перевіреним",command=self.approve_plan).pack(fill="x",pady=2)
        ttk.Button(left,text="🗑 Видалити КТП",command=self.delete_ktp).pack(fill="x",pady=2)
        right=ttk.Frame(tab,padding=6);right.pack(side="left",fill="both",expand=True)
        self.plan_name=ttk.Label(right,text="Виберіть план",font=("Segoe UI",11,"bold"),
                                 wraplength=800)
        self.plan_name.pack(anchor="w")
        self.plan_count=ttk.Label(right,text="",wraplength=800,justify="left")
        self.plan_count.pack(anchor="w")
        datebar=ttk.Frame(right);datebar.pack(fill="x",pady=(2,3))
        ttk.Label(datebar,text="Дати уроків для класу:").pack(side="left",padx=(0,6))
        self.ktp_dates_stream=tk.StringVar()
        self.ktp_dates_combo=ttk.Combobox(datebar,textvariable=self.ktp_dates_stream,
                                              state="readonly",width=25)
        self.ktp_dates_combo.pack(side="left")
        self.ktp_dates_combo.bind("<<ComboboxSelected>>",self._stream_combo_changed)
        ttk.Label(datebar,text="Дати — за розкладом і канікулами; для іншого класу "
                       "виберіть його тут.",wraplength=330,justify="left",
                  foreground="#365777").pack(side="left",padx=9)
        frame=ttk.Frame(right);frame.pack(fill="both",expand=True,pady=6)
        self.lessons=ttk.Treeview(frame,columns=("num","date","topic","hw"),
                                   show="headings",height=6,selectmode="extended")
        for col,title,width in (("num","№",40),("date","Дата",96),
                                 ("topic","Тема",455),("hw","Домашнє завдання",285)):
            self.lessons.heading(col,text=title);self.lessons.column(col,width=width)
        vert=ttk.Scrollbar(frame,command=self.lessons.yview)
        self.lessons.configure(yscrollcommand=vert.set)
        self.lessons.pack(side="left",fill="both",expand=True);vert.pack(side="right",fill="y")
        self.lessons.bind("<<TreeviewSelect>>",self.lesson_selected)
        self.lessons.bind("<Button-3>",self._lesson_context_menu)
        self.lessons.bind("<Delete>",lambda e:self.delete_lesson())
        self.lessons.bind("<Control-c>",lambda e:self.copy_ktp_rows())
        self.lessons.bind("<Double-1>",lambda _:self.topictext.focus_set())
        form=ttk.Frame(right);form.pack(fill="x")
        ttk.Label(form,text="Тема вибраного уроку (можна редагувати)").pack(anchor="w")
        self.topictext=tk.Text(form,height=2,wrap="word")
        self.topictext.pack(fill="x")
        attach_paste(self.topictext,self)
        ttk.Label(form,text="Д/з (залишайте порожнім, якщо його немає у плані)").pack(anchor="w",pady=(4,0))
        self.hwtext=tk.Text(form,height=2,wrap="word")
        self.hwtext.pack(fill="x")
        attach_paste(self.hwtext,self)
        rowbuttons=ttk.Frame(right);rowbuttons.pack(fill="x",pady=5)
        for label,fn in [("Застосувати правку",self.apply_lesson),
                         ("+ Урок",self.add_lesson),("Видалити урок",self.delete_lesson),
                         ("Вгору",lambda:self.move_lesson(-1)),("Вниз",lambda:self.move_lesson(+1))]:
            ttk.Button(rowbuttons,text=label,command=fn).pack(side="left",padx=3)
        self._refresh_planlist()

    def _plan_context_menu(self,event):
        index=self._planlist_item_at(event.y)
        menu=tk.Menu(self,tearoff=False)
        if index is None:
            menu.add_command(label="Додати новий курс…",command=lambda:self.edit_course(True))
            menu.add_command(label="Імпортувати КТП (клас визначу за файлом)…",command=self.import_plan)
        else:
            self.planlist.selection_clear(0,"end");self.planlist.selection_set(index)
            self.plan_selected()
            menu.add_command(label="Імпортувати КТП для цього класу…",command=self.import_plan)
            menu.add_command(label="Редагувати курс…",command=lambda:self.edit_course(False))
            menu.add_command(label="Перейменувати предмет… (F2)",command=self.rename_subject)
            menu.add_command(label="Розклад: чисельник / знаменник…",command=self.edit_course_schedule)
            menu.add_command(label="Додати новий курс…",command=lambda:self.edit_course(True))
            menu.add_separator()
            menu.add_command(label="Позначити КТП перевіреним",command=self.approve_plan)
            menu.add_command(label="Копіювати назву",command=self.copy_plan_data)
            menu.add_command(label="Новий порожній план…",command=self.add_plan)
            menu.add_separator()
            menu.add_command(label="Видалити КТП цього класу (Delete)",command=self.delete_ktp)
            menu.add_command(label="Видалити курс із програми…",command=self.delete_course)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def _lesson_context_menu(self,event):
        item=self.lessons.identify_row(event.y)
        if item and item not in self.lessons.selection():
            self.lessons.selection_set(item);self.lesson_selected()   # правка попереднього рядка зберігається сама
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Копіювати вибрані рядки (Ctrl+C)",command=self.copy_ktp_rows)
        menu.add_separator()
        menu.add_command(label="Застосувати зміни з полів внизу",command=self.apply_lesson)
        menu.add_separator()
        menu.add_command(label="Додати наступний урок",command=self.add_lesson)
        menu.add_command(label="Видалити вибрані уроки (Delete)",command=self.delete_lesson)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def copy_plan_data(self):
        """Копіює назву КТП звичайним текстом."""
        if not self.current_plan:return "break"
        self.clipboard_clear()
        self.clipboard_append(friendly_plan_id(self.current_plan))
        return "break"

    def copy_ktp_rows(self):
        """Копіює вибрані рядки КТП як TSV, сумісний з Excel/Word."""
        selected=self.lessons.selection()
        if not selected:return "break"
        lines=["\\t".join(str(x) for x in self.lessons.item(item,"values"))
               for item in sorted(selected,key=int)]
        self.clipboard_clear()
        self.clipboard_append("\\n".join(lines).replace("\\t","\t").replace("\\n","\n"))
        return "break"

    def delete_plan(self):
        """КТП з прив'язаними потоками не видаляємо, щоб не пошкодити розклад."""
        plan=self.current_plan
        if not plan:return "break"
        streams=[key for key,info in self.cfg.get("course_map",{}).items()
                 if info.get("plan")==plan]
        if streams:
            messagebox.showwarning("КТП використовується",
                "План «"+friendly_plan_id(plan)+"» прив'язаний до класів: "
                +", ".join(streams)+".\nСпочатку призначте цим класам інший КТП "
                "у вкладці «КЛАСИ / КУРСИ». Розклад не змінено.",
                parent=self)
            return "break"
        count=len(self.plans[plan].get("lessons",[]))
        if messagebox.askyesno("Видалити КТП",
               f"ВИДАЛИТИ план «{friendly_plan_id(plan)}» і {count} уроків? "
               "До натискання «ЗБЕРЕГТИ ВСІ ЗМІНИ» видалення можна скасувати.",
               parent=self):
            del self.plans[plan]
            self.current_plan=None;self.lesson_row=None
            self._refresh_planlist()
        return "break"

    def _classroom_course_titles(self):
        """Назви курсів у порядку Classroom; власні, яких там немає, — в кінці."""
        google=[str(c.get("name","")).strip()
                for c in (getattr(self.parent,"google_courses",None) or []) if c.get("name")]
        saved=[x for x in self.parent.state.get("classroom_order",[]) if isinstance(x,str)]
        ordered=list(dict.fromkeys(google or saved))
        configured=sorted({info.get("course_title","") for info in self.cfg["course_map"].values()
                           if info.get("course_title")})
        for title in configured:
            if title not in ordered and best_match(title,ordered) is None:
                ordered.append(title)
        return ordered

    @staticmethod
    def _subject_label(stream):
        """«9-Б Право» → «Право» (клас уже видно з назви курсу)."""
        short=re.sub(r"^\s*\d{1,2}(?:\s*-\s*[А-Яа-яІіЇїЄєҐґA-Za-z])?\s+","",stream)
        return short or stream

    def _build_list_entries(self):
        entries=[];used=set()
        titles=self._classroom_course_titles()
        assigned=assign_streams({s:i.get("course_title","") for s,i in self.cfg["course_map"].items()},titles)
        for title in titles:
            streams=sorted(s for s,course in assigned.items() if course==title)
            plans=[self.cfg["course_map"][s]["plan"] for s in streams]
            used.update(plans)
            if len(streams)>1 and len(set(plans))>1:
                # Спільний курс («Право + ГО»): кожен предмет — окремий рядок зі своїм КТП
                for stream in streams:
                    key=self.cfg["course_map"][stream]["plan"]
                    has=bool(self.plans.get(key,{}).get("lessons"))
                    entries.append({"kind":"course","course":title,"streams":[stream],"course_streams":streams,
                        "plan":key if key in self.plans else None,"filled":has,
                        "label":f"{title}  ▸ {self._subject_label(stream)}"+("" if has else "   — без КТП")})
                continue
            filled=[p for p in plans if p in self.plans and self.plans[p].get("lessons")]
            plan=(filled or [p for p in plans if p in self.plans] or [None])[0]
            if streams and len(filled)==len({*plans}):label=title
            elif filled:label=title+"   — КТП частково"
            else:label=title+"   — без КТП"
            entries.append({"kind":"course","course":title,"streams":streams,"course_streams":streams,
                            "plan":plan,"filled":bool(filled),"label":label})
        for key in self.plans:
            if key not in used:
                entries.append({"kind":"plan","course":None,"streams":[],"plan":key,
                                "filled":True,"label":"КТП "+friendly_plan_id(key)+"   — без класу"})
        return entries

    def _refresh_planlist(self,chosen=None,course=None):
        previous=(self.current_entry or {}).get("course")
        self.list_entries=self._build_list_entries()
        self.plan_keys=[e.get("plan") for e in self.list_entries]
        self.planlist.delete(0,"end")
        for index,entry in enumerate(self.list_entries):
            self.planlist.insert("end",entry["label"])
            if not entry.get("filled") or entry["kind"]=="plan":
                self.planlist.itemconfigure(index,foreground="#7A8794")
        if not self.list_entries:
            self.current_plan=None;self.current_entry=None
            self.plan_name.config(text="Список класів порожній")
            self.plan_count.config(text=("Завантажте розклад (вкладка «Розклад»: «Завантажити навантаження / "
                "розклад» або перетягніть файл на таблицю) чи підключіть Google (кнопка вгорі головного "
                "вікна) — класи з'являться тут. Потім перетягніть файл КТП на потрібний клас."))
            for item in self.lessons.get_children():self.lessons.delete(item)
            return
        def find(test):
            return next((i for i,e in enumerate(self.list_entries) if test(e)),None)
        pick=None
        if course:pick=find(lambda e:e["course"]==course)
        if pick is None and chosen:pick=find(lambda e:e["plan"]==chosen)
        if pick is None and previous:pick=find(lambda e:e["course"]==previous)
        if pick is None and self.current_plan:pick=find(lambda e:e["plan"]==self.current_plan)
        pick=0 if pick is None else pick
        self.planlist.selection_clear(0,"end");self.planlist.selection_set(pick)
        self.planlist.see(pick)
        self.plan_selected()

    def plan_selected(self,_event=None):
        indexes=self.planlist.curselection()
        if not indexes:return
        entry=self.list_entries[indexes[0]]
        if entry.get("plan")!=self.current_plan:
            self._commit_pending_edit()
        self.current_entry=entry
        self.current_plan=entry.get("plan")
        if entry.get("streams"):
            self.ktp_dates_stream.set(entry["streams"][0])
        if self.current_plan and entry.get("filled"):
            self.refresh_lessons()
            sharing=sorted(s for s,i in self.cfg["course_map"].items()
                           if i.get("plan")==self.current_plan)
            if len(sharing)>1:
                self.plan_count.config(text=self.plan_count.cget("text")
                    +f"  КТП спільний для: {', '.join(sharing)}.")
        else:
            self._show_empty_entry(entry)

    def _show_empty_entry(self,entry):
        for item in self.lessons.get_children():self.lessons.delete(item)
        self.lesson_row=None
        for field in (self.topictext,self.hwtext):field.delete("1.0","end")
        self.ktp_dates_combo.configure(values=[])
        name=entry.get("course") or "клас"
        self.plan_name.config(text=f"{name}: КТП ще не підключено")
        self.plan_count.config(text=("Перетягніть сюди файл КТП (DOCX, DOC, CSV) — програма "
            "створить для цього класу план. Або натисніть «Імпортувати файли…»."))

    def focus_lesson(self,stream,number):
        """Відкрити КТП клітинки з головного вікна: клас → план → рядок уроку."""
        course=self.cfg["course_map"].get(stream,{}).get("course_title")
        ix=next((i for i,e in enumerate(self.list_entries) if stream in e.get("streams",[])),None)
        if ix is None:
            ix=next((i for i,e in enumerate(self.list_entries) if e.get("course")==course),None)
        if ix is None:return
        self.notebook.select(self.tab_plans)
        self.planlist.selection_clear(0,"end");self.planlist.selection_set(ix)
        self.planlist.see(ix)
        self.plan_selected()
        self.ktp_dates_stream.set(stream)
        self.refresh_lessons(max(0,int(number)-1))

    def _stream_combo_changed(self,_event=None):
        self._sync_plan_with_stream()
        self.refresh_lessons(self.lesson_row)

    def _sync_plan_with_stream(self):
        shared=(self.current_entry or {}).get("streams") or []
        stream=self.ktp_dates_stream.get()
        if stream in shared:
            plan=self.cfg["course_map"].get(stream,{}).get("plan")
            if plan in self.plans:self.current_plan=plan

    def _create_plan_for_course(self,course):
        base=re.sub(r"\s+","_",course.strip()) or "Новий_клас"
        key=base;number=2
        while key in self.plans:
            key=f"{base}_{number}";number+=1
        self.cfg["course_map"][course]={"plan":key,"course_title":course}
        return key

    def refresh_lessons(self,selected=None):
        if not self.current_plan:return
        self._sync_plan_with_stream()
        doc=self.plans[self.current_plan]
        entries=doc["lessons"]
        streams=sorted(name for name,info in self.cfg["course_map"].items()
                       if info.get("plan")==self.current_plan)
        shared=sorted((self.current_entry or {}).get("streams") or [])
        if len({self.cfg["course_map"][x]["plan"] for x in shared
                if x in self.cfg["course_map"]})>1:
            streams=shared      # об'єднаний курс (напр. Право + ГО)
        current=self.ktp_dates_stream.get()
        self.ktp_dates_combo.configure(values=streams)
        if current not in streams:
            self.ktp_dates_stream.set(streams[0] if streams else "")
        active=self.ktp_dates_stream.get()
        # Обидві дати в ISO: раніше ISO порівнювалося з «ДД.ММ.РРРР» і
        # попередження про розбіжність з'являлося для КОЖНОГО датованого уроку.
        dates={x.lesson_number:x.day
               for x in build_calendar(self.cfg,self.plans)
               if x.stream==active and x.plan_id==self.current_plan}
        for item in self.lessons.get_children():self.lessons.delete(item)
        conflicts=0
        for i,row in enumerate(entries):
            source=source_date_for_stream(row,active)
            calculated=dates.get(i+1)
            if source and calculated and source!=calculated:conflicts+=1
            # Imported class-specific dates are shown first; if absent use schedule.
            shown=source or calculated
            self.lessons.insert("","end",iid=str(i),
                     values=(i+1,display_ui_date(shown) if shown else "",
                             row["topic"],row.get("homework","")))
        extra=" ⚠ ПЕРЕВІРТЕ КТП НОВОГО РОКУ" if doc.get("needs_review") else ""
        self.plan_name.config(text=f"{friendly_plan_id(self.current_plan)} • {doc.get('filename','План без джерела')[:90]}{extra}")
        self.plan_count.config(text=f"{len(entries)} уроків. "
           f"Дати з джерела використано для відображення, якщо вони існують. "
           f"{'⚠ Різниця дат із розкладом: '+str(conflicts)+'; перевірте!' if conflicts else ''} "
           "Зміни збережуться лише після «ЗБЕРЕГТИ».")
        self.lesson_row=None
        if entries:
            i=selected if selected is not None and 0<=selected<len(entries) else 0
            self.lessons.selection_set(str(i));self.lesson_selected()

    def _pending_edit(self):
        if not self.current_plan or self.lesson_row is None:return None
        rows=self.plans.get(self.current_plan,{}).get("lessons",[])
        if not 0<=self.lesson_row<len(rows):return None
        topic=tidy(self.topictext.get("1.0","end"));homework=tidy(self.hwtext.get("1.0","end"))
        row=rows[self.lesson_row]
        if topic and (topic!=tidy(row["topic"]) or homework!=tidy(row.get("homework",""))):
            return row,topic,homework
        return None

    def _commit_pending_edit(self):
        """Правка в полях внизу застосовується сама, коли ви переходите до іншого рядка чи класу."""
        pending=self._pending_edit()
        if not pending:return False
        row,topic,homework=pending
        row["topic"]=topic;row["homework"]=homework
        item=str(self.lesson_row)
        try:
            if self.lessons.exists(item):
                values=list(self.lessons.item(item,"values"))
                values[2],values[3]=topic,homework
                self.lessons.item(item,values=values)
        except tk.TclError:pass
        return True

    def lesson_selected(self,_event=None):
        choice=self.lessons.selection()
        if not choice or not self.current_plan:return
        i=int(choice[0]);rows=self.plans[self.current_plan]["lessons"]
        if i>=len(rows):return
        if i==self.lesson_row:
            return                     # той самий рядок: поле з вашою правкою не перезаписуємо
        if self.lesson_row is not None:
            self._commit_pending_edit()
        self.lesson_row=i
        for field,val in ((self.topictext,rows[i]["topic"]),(self.hwtext,rows[i].get("homework",""))):
            field.delete("1.0","end");field.insert("1.0",val)

    def _read_lesson_form(self):
        topic=tidy(self.topictext.get("1.0","end"))
        homework=tidy(self.hwtext.get("1.0","end"))
        if not topic: raise ValueError("Тема уроку не може бути порожньою")
        return topic,homework

    def _renumber(self):
        for ix,row in enumerate(self.plans[self.current_plan]["lessons"],1):row["index"]=ix

    def apply_lesson(self):
        if self.current_plan is None or self.lesson_row is None:return
        try:topic,hw=self._read_lesson_form()
        except ValueError as ex:messagebox.showerror("Урок",str(ex),parent=self);return
        row=self.plans[self.current_plan]["lessons"][self.lesson_row]
        row["topic"]=topic;row["homework"]=hw
        self.refresh_lessons(self.lesson_row)

    def add_lesson(self):
        if not self.current_plan:return
        topic=tidy(self.topictext.get("1.0","end"))
        hw=tidy(self.hwtext.get("1.0","end"))
        if not topic:
            topic=simpledialog.askstring("Новий урок","Введіть тему нового уроку:",parent=self)
            if not topic:return
        entries=self.plans[self.current_plan]["lessons"]
        i=len(entries) if self.lesson_row is None else self.lesson_row+1
        entries.insert(i,{"index":i+1,"topic":topic,"homework":hw})
        self._renumber();self.refresh_lessons(i)

    def delete_lesson(self):
        if not self.current_plan:return "break"
        selected=sorted({int(item) for item in self.lessons.selection()
                         if item.isdigit()},reverse=True)
        if not selected and self.lesson_row is not None:selected=[self.lesson_row]
        if not selected:return "break"
        if not messagebox.askyesno("Видалити уроки",
              f"Видалити {len(selected)} вибраних уроків КТП? "
              "Номери наступних тем зсунуться. "
              "Зміни запишуться лише після «ЗБЕРЕГТИ ВСІ ЗМІНИ».",
              parent=self):return "break"
        rows=self.plans[self.current_plan]["lessons"]
        for ix in selected:
            if 0<=ix<len(rows):rows.pop(ix)
        self._renumber();self.refresh_lessons()
        return "break"

    def move_lesson(self,delta):
        if self.lesson_row is None:return
        entries=self.plans[self.current_plan]["lessons"]
        i=self.lesson_row;j=i+delta
        if j<0 or j>=len(entries):return
        entries[i],entries[j]=entries[j],entries[i]
        self._renumber();self.refresh_lessons(j)

    def delete_ktp(self):
        """Видаляє КТП класу (клас і розклад лишаються): КТП можна завантажити пізніше."""
        entry=self.current_entry
        if not entry:return "break"
        if entry.get("kind")!="course":
            return self.delete_plan()              # КТП без класу видаляється повністю
        streams=entry["streams"]
        course_map=self.cfg["course_map"]
        filled=[s for s in streams if self.plans.get(course_map[s]["plan"],{}).get("lessons")]
        if not filled:
            messagebox.showinfo("КТП","У цього класу ще немає КТП.",parent=self);return "break"
        shared={x for s in filled for x,i in course_map.items()
                if i["plan"]==course_map[s]["plan"] and x not in streams}
        count=sum(len(self.plans[course_map[s]["plan"]]["lessons"]) for s in filled)
        text=(f"Видалити КТП класу «{entry['course']}» ({count} уроків)?\n\n"
              "Клас і розклад залишаться, КТП можна завантажити пізніше.")
        if shared:
            text+=("\n\nЦей КТП був спільний ще для: "+", ".join(sorted(shared))
                   +". Вони його збережуть, відкріпиться лише цей клас.")
        if not messagebox.askyesno("Видалити КТП",text+"\nСкасувати: кнопка «Назад».",parent=self,default="no"):
            return "break"
        for stream in streams:
            key=course_map[stream]["plan"]
            users=[x for x,i in course_map.items() if i["plan"]==key]
            if all(u in streams for u in users):
                self.plans[key]={"filename":"Очікує файл КТП","lessons":[],"needs_review":True}
            else:
                new=stream;number=2
                while new in self.plans:
                    new=f"{stream} ({number})";number+=1
                self.plans[new]={"filename":"Очікує файл КТП","lessons":[],"needs_review":True}
                course_map[stream]["plan"]=new
        self.lesson_row=None
        self.refresh_streams();self._refresh_planlist(course=entry["course"])
        return "break"

    def _ask_text(self,title,prompt,initial="",parent=None):
        dialog=tk.Toplevel(parent or self);dialog.title(title);dialog.transient(parent or self)
        dialog.escape_closes=True;fit_work_window(dialog,"small")
        ttk.Label(dialog,text=prompt,wraplength=480).pack(anchor="w",padx=14,pady=(14,4))
        value=tk.StringVar(value=initial)
        entry=ttk.Entry(dialog,textvariable=value,width=48);entry.pack(padx=14,pady=4)
        entry.focus_set();entry.select_range(0,"end")
        result={"value":None}
        def ok():
            result["value"]=value.get().strip();dialog.destroy()
        row=ttk.Frame(dialog);row.pack(pady=12)
        ttk.Button(row,text="Гаразд",command=ok).pack(side="left",padx=6)
        ttk.Button(row,text="Скасувати",command=dialog.destroy).pack(side="left")
        dialog.bind("<Return>",lambda _e:ok())
        dialog.grab_set();(parent or self).wait_window(dialog)
        return result["value"]

    def rename_stream(self,old,new):
        """Перейменування предмета (потоку). Збережені Word, вкладення й чернетки переносяться при збереженні."""
        new=tidy(new)
        if not new or "|" in new:
            raise ValueError("Назва порожня або містить знак «|».")
        if new==old:return
        if any(match_norm(s)==match_norm(new) for s in self.cfg["course_map"] if s!=old):
            raise ValueError("Потік із такою назвою вже є.")
        self.cfg["course_map"]={(new if s==old else s):i for s,i in self.cfg["course_map"].items()}
        for pairs in self.cfg["days"].values():
            for pair in pairs:
                for k in (0,1):
                    if pair[k]==old:pair[k]=new
        aliases=self.cfg.get("schedule_aliases")
        if aliases:
            for key,value in list(aliases.items()):
                if value==old:aliases[key]=new
        renames=self.cfg.setdefault("pending_stream_renames",{})
        origin=next((o for o,n in renames.items() if n==old),old)
        if origin==new:renames.pop(origin,None)
        else:renames[origin]=new
        if not renames:self.cfg.pop("pending_stream_renames",None)
        self.refresh_streams();self.refresh_slots();self._refresh_planlist()

    def rename_subject(self):
        """F2 / меню: перейменувати вибраний предмет (потік) прямо зі списку класів."""
        entry=self.current_entry
        if not entry or entry.get("kind")!="course" or not entry["streams"]:
            messagebox.showinfo("Предмет","Виберіть клас або предмет у списку зліва.",parent=self);return "break"
        streams=entry["streams"]
        old=streams[0] if len(streams)==1 else self._ask_choice(
            "Який предмет перейменувати?",f"У курсі «{entry['course']}» кілька потоків:",sorted(streams))
        if not old:return "break"
        new=self._ask_text("Перейменувати предмет","Нова назва потоку (як у розкладі):",old)
        if not new or new==old:return "break"
        try:self.rename_stream(old,new)
        except ValueError as ex:messagebox.showerror("Предмет",str(ex),parent=self)
        return "break"

    def edit_course_schedule(self,entry=None,streams=None):
        """Предмети одного курсу, що чергуються по тижнях: окремо на чисельник і на знаменник."""
        entry=entry or self.current_entry
        if not entry or entry.get("kind")!="course":
            messagebox.showinfo("Розклад","Виберіть клас у списку зліва.",parent=self);return
        subjects=list(streams or entry.get("course_streams") or entry["streams"])
        if not subjects:
            messagebox.showinfo("Розклад","У цього курсу ще немає предметів: спершу «Редагувати курс».",parent=self);return
        names=("Понеділок","Вівторок","Середа","Четвер","П’ятниця")
        none="— немає —"
        dialog=tk.Toplevel(self);dialog.title(f"Розклад: {entry['course']}");dialog.transient(self)
        dialog.escape_closes=True;fit_work_window(dialog,"normal")
        ttk.Label(dialog,wraplength=700,justify="left",foreground="#365777",text=(
            "Предмети цього курсу можуть чергуватися по тижнях: наприклад, Право — у ЧИСЕЛЬНИК, ГО — у ЗНАМЕННИК "
            "(або один урок на два тижні: тоді другий тиждень лишіть «— немає —»). Оберіть день, номер уроку та "
            "предмет для кожного тижня.")).pack(anchor="w",padx=14,pady=(12,6))
        grid=ttk.Frame(dialog);grid.pack(anchor="w",padx=14)
        day=tk.StringVar(value=names[0]);number=tk.StringVar(value="1")
        top=tk.StringVar(value=subjects[0]);bottom=tk.StringVar(value=subjects[1] if len(subjects)>1 else none)
        count=len(self.cfg["period_times"])
        ttk.Label(grid,text="День:").grid(row=0,column=0,sticky="w",pady=4)
        ttk.Combobox(grid,textvariable=day,values=names,state="readonly",width=14).grid(row=0,column=1,padx=6)
        ttk.Label(grid,text="Урок №:").grid(row=0,column=2,sticky="w",padx=(14,0))
        ttk.Combobox(grid,textvariable=number,values=[str(i) for i in range(1,count+1)],state="readonly",
                     width=5).grid(row=0,column=3,padx=6)
        ttk.Label(grid,text="ЧИСЕЛЬНИК:").grid(row=1,column=0,sticky="w",pady=4)
        ttk.Combobox(grid,textvariable=top,values=[none]+subjects,state="readonly",width=28).grid(row=1,column=1,columnspan=3,padx=6,sticky="w")
        ttk.Label(grid,text="ЗНАМЕННИК:").grid(row=2,column=0,sticky="w",pady=4)
        ttk.Combobox(grid,textvariable=bottom,values=[none]+subjects,state="readonly",width=28).grid(row=2,column=1,columnspan=3,padx=6,sticky="w")
        ttk.Label(dialog,text="Вже в розкладі для цього курсу:").pack(anchor="w",padx=14,pady=(10,2))
        box=tk.Listbox(dialog,height=8,exportselection=False);box.pack(fill="both",expand=True,padx=14)
        places=[]

        def refresh():
            box.delete(0,"end");places.clear()
            for d in range(5):
                for i,pair in enumerate(self.cfg["days"].get(str(d),[])):
                    if pair[0] in subjects or pair[1] in subjects:
                        places.append((d,i))
                        box.insert("end",f"{names[d]}, урок {i+1}:  чисельник — {pair[0] or '—'};  знаменник — {pair[1] or '—'}")
        def assign():
            a=None if top.get()==none else top.get();b=None if bottom.get()==none else bottom.get()
            if a is None and b is None:
                messagebox.showwarning("Розклад","Оберіть предмет хоча б для одного тижня.",parent=dialog);return
            d=names.index(day.get());i=int(number.get())-1
            current=self.cfg["days"][str(d)][i]
            foreign=[x for x in current if x and x not in subjects and x not in (a,b)]
            if foreign and not messagebox.askyesno("Урок зайнятий",
                    f"У цьому уроці вже стоїть: {', '.join(foreign)}.\nЗамінити?",parent=dialog):return
            self.cfg["days"][str(d)][i]=[a,b]
            self.refresh_slots();refresh()
        def remove():
            picked=box.curselection()
            if not picked:return
            d,i=places[picked[0]]
            pair=self.cfg["days"][str(d)][i]
            self.cfg["days"][str(d)][i]=[None if x in subjects else x for x in pair]
            self.refresh_slots();refresh()
        buttons=ttk.Frame(dialog);buttons.pack(fill="x",padx=14,pady=10)
        ttk.Button(buttons,text="Призначити",command=assign).pack(side="left")
        ttk.Button(buttons,text="Прибрати вибраний рядок з розкладу",command=remove).pack(side="left",padx=8)
        ttk.Button(buttons,text="Закрити",command=dialog.destroy).pack(side="right")
        from types import SimpleNamespace
        dialog.api=SimpleNamespace(day=day,number=number,top=top,bottom=bottom,assign=assign,remove=remove,
                                   box=box,places=places,subjects=subjects)
        refresh();dialog.grab_set()

    def delete_course(self):
        entry=self.current_entry
        if not entry or entry.get("kind")!="course":return
        streams=entry.get("course_streams") or entry["streams"]
        if not streams:
            messagebox.showinfo("Курс","У цього курсу Classroom немає предметів у програмі.",parent=self);return
        self._remove_streams(streams,f"курс «{entry['course']}» (усі його предмети)")

    def edit_course(self,new=False):
        """Редагування курсу (напр. спільний «Право + ГО») та додавання нового курсу."""
        entry=None if new else self.current_entry
        if not new and (not entry or entry.get("kind")!="course"):
            messagebox.showinfo("Курс","Виберіть клас у списку зліва.",parent=self);return
        original=list(entry.get("course_streams") or entry["streams"]) if entry else []
        streams=list(original);created=[]
        dialog=tk.Toplevel(self);dialog.title("Додати курс" if new else "Редагувати курс")
        dialog.transient(self);dialog.escape_closes=True;fit_work_window(dialog,"normal")
        ttk.Label(dialog,wraplength=720,justify="left",foreground="#365777",text=(
            "Курс — це клас у Google Classroom. В одному курсі може бути кілька предметів, наприклад спільний "
            "«9-Б Право + ГО» (Право в чисельнику, ГО в знаменнику або по одному уроку на два тижні). "
            "Кожен предмет має свій КТП; чисельник і знаменник задаються у вкладці «Розклад»."
            )).pack(anchor="w",padx=14,pady=(12,6))
        ttk.Label(dialog,text="Назва курсу в Google Classroom:").pack(anchor="w",padx=14)
        title=tk.StringVar(value=entry["course"] if entry else "")
        free=list(dict.fromkeys(
            [e["course"] for e in self.list_entries if e.get("course") and not e["streams"]]
            +([entry["course"]] if entry else [])))
        ttk.Combobox(dialog,textvariable=title,values=free,width=60).pack(anchor="w",padx=14,pady=(2,8))
        ttk.Label(dialog,text="Предмети цього курсу (потоки):").pack(anchor="w",padx=14)
        box=tk.Listbox(dialog,height=6,exportselection=False)
        box.pack(fill="x",padx=14,pady=2)

        def render():
            box.delete(0,"end")
            for s in streams:
                info=self.cfg["course_map"].get(s)
                count=len(self.plans.get(info["plan"],{}).get("lessons",[])) if info else 0
                box.insert("end",f"{s}   —   "+(f"КТП: {count} уроків" if count else "КТП ще немає"))
        row=ttk.Frame(dialog);row.pack(fill="x",padx=14,pady=6)
        cls=tk.StringVar();subject=tk.StringVar(value=SUBJECT_CODES[0]);name=tk.StringVar()
        parsed=match_parse(title.get())
        if parsed:cls.set(f"{parsed.grade}-{parsed.letter.upper()}" if parsed.letter else str(parsed.grade))
        def compose(*_):
            name.set((cls.get().strip()+" "+subject.get()).strip())
        ttk.Label(row,text="Клас:").pack(side="left")
        ttk.Entry(row,textvariable=cls,width=7).pack(side="left",padx=(3,8))
        ttk.Label(row,text="Предмет:").pack(side="left")
        ttk.Combobox(row,textvariable=subject,values=SUBJECT_CODES,state="readonly",width=9).pack(side="left",padx=(3,8))
        ttk.Label(row,text="Назва потоку:").pack(side="left")
        ttk.Entry(row,textvariable=name,width=20).pack(side="left",padx=3)
        cls.trace_add("write",compose);subject.trace_add("write",compose);compose()
        def add_subject():
            stream=name.get().strip()
            if not stream:return
            if stream in streams or stream in self.cfg["course_map"]:
                messagebox.showerror("Предмет","Потік із такою назвою вже існує.",parent=dialog);return
            streams.append(stream);created.append(stream);render()
        def remove_subject():
            picked=box.curselection()
            if not picked:return
            stream=streams.pop(picked[0])
            if stream in created:created.remove(stream)
            render()
        buttons=ttk.Frame(dialog);buttons.pack(fill="x",padx=14)
        ttk.Button(buttons,text="+ Додати предмет",command=add_subject).pack(side="left")
        ttk.Button(buttons,text="− Прибрати вибраний",command=remove_subject).pack(side="left",padx=8)

        def rename_selected():
            picked=box.curselection()
            if not picked:
                messagebox.showinfo("Предмет","Виберіть предмет у списку.",parent=dialog);return
            old=streams[picked[0]]
            new=self._ask_text("Перейменувати предмет","Нова назва потоку (як у розкладі):",old,dialog)
            if not new or new==old:return
            try:
                if old in created:
                    if new in streams or new in self.cfg["course_map"]:raise ValueError("Потік із такою назвою вже існує")
                    created[created.index(old)]=new
                else:
                    self.rename_stream(old,new)
                    if old in original:original[original.index(old)]=new
            except ValueError as ex:
                messagebox.showerror("Предмет",str(ex),parent=dialog);return
            streams[picked[0]]=new;render()
        ttk.Button(buttons,text="✎ Перейменувати вибраний",command=rename_selected).pack(side="left")
        ttk.Button(buttons,text="Розклад: чисельник / знаменник…",
                   command=lambda:(self.edit_course_schedule(entry,streams) if entry else None)).pack(side="left",padx=8)
        def ok():
            course=title.get().strip()
            if not course:
                messagebox.showerror("Курс","Вкажіть назву курсу.",parent=dialog);return
            if not streams:
                messagebox.showerror("Курс","У курсі має бути хоча б один предмет.",parent=dialog);return
            own=match_norm(entry["course"]) if entry else None
            clash=[e for e in self.list_entries if e.get("course") and e["streams"]
                   and match_norm(e["course"])==match_norm(course) and match_norm(course)!=own]
            if clash:
                messagebox.showerror("Курс","Курс із такою назвою вже є.",parent=dialog);return
            for stream in created:
                key=stream;number=2
                while key in self.plans:
                    key=f"{stream} ({number})";number+=1
                self.plans[key]={"filename":"Очікує файл КТП","lessons":[],"needs_review":True}
                self.cfg["course_map"][stream]={"plan":key,"course_title":course}
            for stream in streams:
                self.cfg["course_map"][stream]["course_title"]=course
            dropped=[s for s in original if s not in streams]
            if dropped:self._remove_streams(dropped,"прибрані предмети",ask=False)
            self.refresh_streams();self.refresh_slots();self._refresh_planlist(course=course)
            dialog.destroy()
        foot=ttk.Frame(dialog);foot.pack(pady=14)
        ttk.Button(foot,text="Зберегти курс",command=ok).pack(side="left",padx=6)
        ttk.Button(foot,text="Скасувати",command=dialog.destroy).pack(side="left")
        from types import SimpleNamespace
        dialog.api=SimpleNamespace(title=title,cls=cls,subject=subject,name=name,add=add_subject,
                                   remove=remove_subject,ok=ok,box=box,streams=streams,rename=rename_selected)
        render();dialog.grab_set()

    def add_plan(self):
        planid=simpledialog.askstring("Новий КТП","Введіть назву плану, наприклад «8 ІУ 2027»:",
                                     parent=self)
        if not planid:return
        planid=planid.strip()
        if not planid:
            messagebox.showwarning("КТП","Назва не може бути порожньою.",parent=self);return
        if planid in self.plans:
            messagebox.showerror("КТП","Такий план уже є.",parent=self);return
        self.plans[planid]={"filename":"Створено вручну","lessons":[],"needs_review":True}
        self._refresh_planlist(planid)

    def approve_plan(self):
        if not self.current_plan:return
        p=self.plans[self.current_plan]
        if not p["lessons"]:
            messagebox.showwarning("КТП","Спочатку завантажте або впишіть теми.",parent=self);return
        if messagebox.askyesno("Перевірка",f"Ви перевірили тему й Д/з у плані {self.current_plan} для цього навчального року?",parent=self):
            p["needs_review"]=False
            self.refresh_lessons()

    def _ask_choice(self,title,prompt,options):
        dialog=tk.Toplevel(self);dialog.title(title);dialog.transient(self)
        dialog.escape_closes=True
        fit_work_window(dialog,"small")
        ttk.Label(dialog,text=prompt,wraplength=520,justify="left").pack(anchor="w",padx=14,pady=12)
        variable=tk.StringVar(value=options[0])
        for option in options:
            ttk.Radiobutton(dialog,text=option,value=option,variable=variable).pack(anchor="w",padx=24,pady=2)
        result={"value":None}
        def ok():
            result["value"]=variable.get();dialog.destroy()
        row=ttk.Frame(dialog);row.pack(pady=12)
        ttk.Button(row,text="Далі",command=ok).pack(side="left",padx=6)
        ttk.Button(row,text="Скасувати",command=dialog.destroy).pack(side="left")
        dialog.grab_set();self.wait_window(dialog)
        return result["value"]

    def import_plan(self,path=None):
        """Кнопка «Імпортувати…»: можна вибрати ОДИН чи КІЛЬКА файлів — решту програма робить сама."""
        if path is None:
            chosen=filedialog.askopenfilenames(parent=self,title="Календарні плани та розклад",
                    filetypes=[("Календарні плани й розклад","*.docx *.doc *.csv *.xlsx"),
                               ("Word DOCX","*.docx"),("Word DOC (через Word)","*.doc"),("CSV","*.csv")])
            paths=[Path(x) for x in chosen]
        else:
            paths=[Path(path)]
        if paths:self.import_files(paths,self.current_entry)

    def import_files(self,files,entry=None):
        """Файли (КТП, розклад) → призначення за змістом. Жодних запитань; підсумок і «Назад» для скасування."""
        files=[Path(f) for f in files]
        bulk=len(files)>1
        if bulk:entry=None
        kinds={f:ktp_import.classify_file(f) for f in files}
        results=[]
        for f in files:
            if kinds[f]=="schedule":
                before=set(self.cfg["course_map"])
                ok=bool(self.import_schedule(path=f,quiet=True))
                made=sorted(set(self.cfg["course_map"])-before)
                note="розклад завантажено" if ok else "розклад не завантажено"
                if ok and made:note+=f"; створено нових класів: {len(made)}"
                results.append({"name":f.name,"ok":ok,"note":note})
        for f in files:
            if kinds[f]=="ktp":results.append(self._auto_import_ktp(f,entry,bulk))
            elif kinds[f]=="image":
                results.append({"name":f.name,"ok":False,
                    "note":"зображення програма прочитати не може: завантажте Word- або Excel-файл"})
            elif kinds[f]=="unsupported":
                results.append({"name":f.name,"ok":False,"note":"формат не підтримується (потрібні DOCX, DOC, CSV, XLSX)"})
        if not bulk and results and results[0].get("needs_preview"):
            self._manual_preview(files[0],entry)            # автоматично не вийшло: показуємо таблицю
            return
        self._report_import(results,bulk)

    def _report_import(self,results,bulk):
        done=[r for r in results if r["ok"]];failed=[r for r in results if not r["ok"]]
        self._refresh_planlist()
        lines=[]
        for r in done:
            line="✓ "+r["name"]
            if r.get("targets"):line+=" → "+", ".join(r["targets"])
            if r.get("lessons"):line+=f" ({r['lessons']} уроків)"
            if r.get("note"):line+=" — "+r["note"]
            lines.append(line)
        lines+=[f"✗ {r['name']} — {r['note']}" for r in failed]
        if not bulk and results and results[0]["ok"]:
            self.history_note.config(text=lines[0],foreground="#2E6B30")      # без вікон
            return
        text=f"Імпортовано: {len(done)} з {len(results)}.\n\n"+"\n".join(lines[:30])
        if len(lines)>30:text+=f"\n… ще {len(lines)-30}"
        text+="\n\nУсе можна скасувати кнопкою «↶ Назад», доки редактор відкритий."
        (messagebox.showwarning if failed else messagebox.showinfo)("Імпорт файлів",text,parent=self)

    def _auto_import_ktp(self,path,entry,bulk):
        name=path.name
        try:
            lessons=ktp_import.load_ktp(path,int(self.cfg["year_start"][:4]))
        except Exception as ex:
            return {"name":name,"ok":False,"note":f"не вдалося прочитати: {ex}","needs_preview":True}
        if not lessons:
            return {"name":name,"ok":False,"note":"не знайдено жодного уроку: перевірте таблицю","needs_preview":True}
        return self._assign_ktp(lessons,name,path,entry,bulk)

    def _manual_preview(self,path,entry):
        """Запасний шлях: якщо стовпці не розпізналися, вчитель вказує їх у попередньому перегляді."""
        def accept(lessons,filename):
            result=self._assign_ktp(lessons,filename,path,entry,False)
            self._report_import([result],False)
        try:ImportPreview(self,path,accept)
        except Exception as ex:messagebox.showerror("КТП не розпізнано",str(ex),parent=self)

    def _assign_ktp(self,lessons,name,path,entry,bulk):
        detection=ktp_detect.detect(name,ktp_detect.header_text(path),lessons)
        selected=list(entry.get("streams") or []) if entry and entry.get("kind")=="course" else []
        created=None
        if entry and entry.get("kind")=="course" and not selected and not bulk:
            created=self._ensure_stream_for_course(entry["course"],detection)      # курс без предметів
            selected=[created]
        targets,note,create=self._decide_targets(detection,entry,selected,bulk)
        if created and (not targets or created not in targets):
            self._remove_streams([created],ask=False)                       # тимчасовий потік не знадобився
        if not targets:
            return {"name":name,"ok":False,"note":note or "не вдалося визначити, для якого класу цей КТП"}
        for stream,course in create.items():                                 # класи з Classroom, яких ще немає в програмі
            key=stream;number=2
            while key in self.plans:
                key=f"{stream} ({number})";number+=1
            self.plans[key]={"filename":"Очікує файл КТП","lessons":[],"needs_review":True}
            self.cfg["course_map"][stream]={"plan":key,"course_title":course}
        replaced=[s for s in targets
                  if self.plans.get(self.cfg["course_map"][s]["plan"],{}).get("lessons")]
        self._store_ktp(targets,lessons,name)
        if replaced:note=(note+"; " if note else "")+"замінено наявний КТП: "+", ".join(replaced)
        return {"name":name,"ok":True,"targets":targets,"lessons":len(lessons),"note":note}

    def _canonical_stream(self,course,detection):
        """Назва потоку для курсу Classroom: «9-Б Право + ГО» + файл Право → «9-Б Право»."""
        parsed=match_parse(course)
        if not parsed:return course
        wanted=expand_subjects(detection.subjects) if detection.subjects else set()
        subjects=(set(parsed.subjects)&wanted) if wanted else set(parsed.subjects)
        codes={"IU":"ІУ","VI":"ВІ","GO":"ГО","LAW":"Право"}
        real=[s for s in subjects if s in codes]
        if len(real)!=1:return course
        prefix=f"{parsed.grade}-{parsed.letter.upper()}" if parsed.letter else str(parsed.grade)
        level={"profile":" профіль","standard":" стандарт"}.get(parsed.level,"")
        return f"{prefix} {codes[real[0]]}{level}"

    def _decide_targets(self,detection,entry,selected,bulk):
        """(класи, примітка, {новий_потік: курс Classroom}).

        Класи беруться і з розкладу (потоки), і з Classroom: якщо курс підходить, а потоку ще немає —
        його буде створено. Питання лише коли інакше не обійтись (один файл).
        """
        course_map=self.cfg["course_map"]
        courses=self._classroom_names()
        every=sorted(course_map)
        if not every and not courses:
            return None,("у програмі ще немає класів: підключіть Google (класи підтягнуться самі) "
                         "або завантажте розклад"),{}
        found=ktp_detect.targets(detection,every) if detection.grade else []
        create={}
        assigned=assign_streams({s:i.get("course_title","") for s,i in course_map.items()},courses) if courses else {}
        if detection.grade and courses:
            for course in ktp_detect.targets(detection,courses):
                if any(assigned.get(s)==course for s in found):continue         # цей предмет курсу вже є
                stream=self._canonical_stream(course,detection)
                if stream in course_map:
                    if stream not in found:found.append(stream)
                else:create[stream]=course
        pool=sorted(set(found)|set(create))
        if ktp_detect.level_conflict(pool) and not detection.level:             # профіль чи стандарт — не вгадуємо
            pool,create=[],{}
        course_name=(entry or {}).get("course")
        if pool:
            note=""
            if selected and not (set(selected)&set(pool)):
                note=f"призначено за змістом файлу, а не до «{course_name}»"
            return pool,note,{s:c for s,c in create.items() if s in pool}
        if selected:
            if detection.classes:
                mine={self._class_of(s) for s in selected}-{None}
                if mine and not (mine & detection.classes):
                    shown=", ".join(sorted(c.upper() for c in detection.classes))
                    if bulk:return None,f"у файлі інші класи ({shown}), а відповідного класу в програмі немає",{}
                    if not messagebox.askyesno("Перевірте клас",
                            f"У файлі є дати для класів: {shown}.\nА ви додаєте цей КТП до «{course_name}».\n\n"
                            "Можливо, ви перетягнули файл не на той клас. Усе одно додати?",parent=self):
                        return None,"не додано: файл для інших класів",{}
            chosen=self._pick_streams(selected,[],detection,course_name,bulk)
            return ((chosen,"",{}) if chosen else (None,"у курсі кілька предметів: вкажіть, для якого цей КТП",{}))
        if bulk:
            if detection.grade is None:
                return None,"не вдалося визначити клас і предмет: киньте цей файл на потрібний клас",{}
            return None,(f"у Classroom і в програмі немає відповідного класу ({detection.describe()}): "
                         "киньте файл на потрібний клас"),{}
        free=[c for c in courses if c not in assigned.values()]
        chosen=self._ask_choice("Для якого класу цей КТП?","Оберіть клас і предмет, для яких цей файл:",every+free)
        if not chosen:return None,"не вибрано клас",{}
        if chosen in course_map:return [chosen],"",{}
        stream=self._canonical_stream(chosen,detection)
        return [stream],"",({} if stream in course_map else {stream:chosen})

    def _ensure_stream_for_course(self,course,detection):
        """Курс Classroom є, а предметів у програмі ще немає: створює потік за змістом файлу."""
        parsed=match_parse(course)
        name=course
        if parsed and detection.known and parsed.grade==detection.grade:
            code={"IU":"ІУ","VI":"ВІ","GO":"ГО","LAW":"Право","HIST":"історія"}[sorted(detection.subjects)[0]]
            prefix=f"{parsed.grade}-{parsed.letter.upper()}" if parsed.letter else str(parsed.grade)
            name=f"{prefix} {code}"
        base=name;number=2
        while name in self.cfg["course_map"]:
            name=f"{base} ({number})";number+=1
        key=name
        while key in self.plans:
            key+=" (КТП)"
        self.plans[key]={"filename":"Очікує файл КТП","lessons":[],"needs_review":True}
        self.cfg["course_map"][name]={"plan":key,"course_title":course}
        return name

    def _class_of(self,stream):
        parsed=match_parse(stream)
        return f"{parsed.grade}-{parsed.letter}" if parsed and parsed.letter else None



    def _pick_streams(self,selected,common,detection,course,bulk=False):
        plans={self.cfg["course_map"][s]["plan"] for s in selected}
        if len(plans)<=1:return list(selected)
        if len(common)==1:return common
        by_subject=[s for s in selected if ktp_detect.targets(detection,[s])]
        if len(by_subject)==1:return by_subject
        if bulk:return None
        chosen=self._ask_choice("Для якого предмета цей КТП?",
            f"У курсі «{course}» кілька предметів. Оберіть, для якого з них цей файл:",sorted(selected))
        return [chosen] if chosen else None

    def _store_ktp(self,targets,entries,filename):
        """Один КТП на всі вибрані класи; порожні плани-заготовки, що стали зайвими, прибираються."""
        course_map=self.cfg["course_map"]
        key=course_map[targets[0]]["plan"]
        self.plans[key]={"filename":filename,"lessons":entries,"needs_review":False}
        for stream in targets[1:]:
            old=course_map[stream]["plan"]
            if old==key:continue
            course_map[stream]["plan"]=key
            if (old in self.plans and not self.plans[old].get("lessons")
                    and not any(i["plan"]==old for i in course_map.values())):
                self.plans.pop(old)
        self.current_plan=key
        self.ktp_dates_stream.set(targets[0])
        self.refresh_streams()
        self._refresh_planlist(chosen=key)

    def _create_streams(self,names):
        """Нові потоки з розкладу: потік + порожній КТП, який вчитель заповнить файлом."""
        titles=self._classroom_course_titles()
        for raw in names:
            name=tidy(raw)
            if not name or name in self.cfg["course_map"]:continue
            key=name;number=2
            while key in self.plans:
                key=f"{name} ({number})";number+=1
            self.plans[key]={"filename":"Очікує файл КТП","lessons":[],"needs_review":True}
            match=best_match(name,titles) or name           # «9-Б Право» → курс «9-Б Право + ГО»
            self.cfg["course_map"][name]={"plan":key,"course_title":match}
        self.refresh_streams()
        self._refresh_planlist()

    def _offer_new_streams(self,unknown,rows,schedule,found):
        """Повертає (залишились_невідомі, розклад, номери_уроків).

        Назви, що читаються як «клас + предмет» («8-Б ГО», «11 ІУ профіль»), стають потоками САМІ, без запитань
        (вони підв'язуються до курсів Classroom). Незрозумілі назви лишаються для ручного зіставлення.
        """
        from .schedule_io import decode_schedule
        def readable(name):
            parsed=match_parse(name)
            return bool(parsed and parsed.subjects)
        candidates=[x for x in unknown if readable(x)]
        if not candidates:return unknown,schedule,found
        self._create_streams(candidates)
        schedule,rest,found=decode_schedule(rows,self.cfg)
        return rest,schedule,found

    def _schedule_ui(self):
        tab=self.tab_schedule
        ttk.Label(tab,text="Для кожного уроку вкажіть потік ЧИСЕЛЬНИКА і ЗНАМЕННИКА. Якщо щотижня — виберіть той самий потік в обох полях.").pack(anchor="w",pady=7)
        daybar=ttk.Frame(tab);daybar.pack(anchor="w",pady=4)
        ttk.Button(daybar,text="◀",width=4,
                   command=lambda:self.shift_schedule_day(-1)).pack(side="left",padx=3)
        self.dayselect=ttk.Combobox(daybar,state="readonly",
            values=("Понеділок","Вівторок","Середа","Четвер","П'ятниця"),width=20)
        self.dayselect.current(0);self.dayselect.pack(side="left")
        ttk.Button(daybar,text="▶",width=4,
                   command=lambda:self.shift_schedule_day(1)).pack(side="left",padx=3)
        self.dayselect.bind("<<ComboboxSelected>>",lambda _:self.refresh_slots())
        ttk.Button(daybar,text="🗑 Видалити розклад",command=self.delete_schedule).pack(side="left",padx=(18,0))
        table=ttk.Frame(tab);table.pack(fill="both",expand=True,pady=10)
        self.slots=ttk.Treeview(table,columns=("period","time","numerator","denominator"),show="headings",height=9)
        for col,t,w in (("period","№",55),("time","Час",160),("numerator","ЧИСЕЛЬНИК",300),("denominator","ЗНАМЕННИК",300)):
            self.slots.heading(col,text=t);self.slots.column(col,width=w)
        self.slots.pack(fill="both",expand=True)
        self.slots.bind("<Double-1>",self._open_calendar_for_slot)
        self.slots.bind("<Delete>",lambda e:self.clear_slot())
        self.slots.bind("<Button-3>",self._schedule_context_menu)
        controls=ttk.Frame(tab);controls.pack(fill="x",pady=5)
        ttk.Button(controls,text="Змінити вибраний урок",command=self.edit_slot).pack(side="left",padx=3)
        ttk.Button(controls,text="Завантажити навантаження / розклад",command=self.import_schedule).pack(side="left",padx=3)
        ttk.Button(controls,text="Згенерувати Word «Навантаження»",command=self.export_workload_word).pack(side="left",padx=3)
        ttk.Button(controls,text="Згенерувати JPEG «Навантаження»",command=self.export_workload_picture).pack(side="left",padx=3)
        ttk.Label(tab,foreground="#365777",text=("Можна перетягнути файл розкладу (Word, Excel, CSV) прямо "
                  "на таблицю вище — він підсвітиться, і програма сама все прочитає."
                  if DND_FILES else "Файл розкладу (Word, Excel, CSV) завантажується кнопкою вище.")
                  ).pack(anchor="w")
        head=ttk.Frame(tab);head.pack(fill="x",pady=(6,0))
        self.teacher_var=tk.StringVar(value=str(self.cfg.get("workload_teacher","")))
        self.code_var=tk.StringVar(value=str(self.cfg.get("workload_code","")))
        ttk.Label(head,text="У заголовку навантаження — прізвище та ініціали:").pack(side="left")
        ttk.Entry(head,textvariable=self.teacher_var,width=22).pack(side="left",padx=(4,14))
        ttk.Label(head,text="код / примітка:").pack(side="left")
        ttk.Entry(head,textvariable=self.code_var,width=14).pack(side="left",padx=4)
        opts=ttk.Frame(tab);opts.pack(fill="x",pady=5)
        self.show_bells=tk.BooleanVar(value=self.cfg.get("print_bells",True))
        self.show_meal=tk.BooleanVar(value=self.cfg.get("print_meal",True))
        self.show_numbers=tk.BooleanVar(value=self.cfg.get("print_numbers",True))
        for txt,var in [("Показувати дзвоники",self.show_bells),
                        ("Рядок харчування",self.show_meal),
                        ("Номери уроків",self.show_numbers)]:
            ttk.Checkbutton(opts,text=txt,variable=var).pack(side="left",padx=7)
        ttk.Label(tab,text="Ці перемикачі визначають лише друкований вигляд розкладу; під час підготовки уроків розклад зберігається повністю.").pack(anchor="w",pady=4)

        self.refresh_slots()

    def refresh_slots(self):
        day=str(self.dayselect.current())
        for i in self.slots.get_children():self.slots.delete(i)
        for i,pair in enumerate(self.cfg["days"].get(day,[])):
            start,end=self.cfg["period_times"][i]
            self.slots.insert("","end",iid=str(i),values=(i+1,f"{start}–{end}",pair[0] or "",pair[1] or ""))

    def shift_schedule_day(self,amount):
        self.dayselect.current((self.dayselect.current()+amount)%5)
        self.refresh_slots()

    def _open_calendar_for_slot(self,event):
        """Подвійне натискання переходить до КТП предмета цього уроку."""
        item=self.slots.identify_row(event.y)
        if not item:return
        index=int(item)
        pair=self.cfg["days"].get(str(self.dayselect.current()),[])[index]
        col=self.slots.identify_column(event.x)
        stream=pair[1] if col=="#4" else pair[0]
        if not stream:stream=pair[0] or pair[1]
        if not stream:return
        mapping=self.cfg["course_map"].get(stream,{})
        plan=mapping.get("plan")
        if plan not in self.plans:return
        self.notebook.select(self.tab_plans)
        self.planlist.selection_clear(0,"end")
        self.planlist.selection_set(self.plan_keys.index(plan))
        self.planlist.see(self.plan_keys.index(plan))
        self.plan_selected()

    def _schedule_context_menu(self,event):
        item=self.slots.identify_row(event.y)
        if item:self.slots.selection_set(item)
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Змінити потоки",command=self.edit_slot)
        menu.add_command(label="Очистити урок: чисельник",command=lambda:self.clear_slot(0))
        menu.add_command(label="Очистити урок: знаменник",command=lambda:self.clear_slot(1))
        menu.add_command(label="Очистити обидва потоки (Delete)",command=self.clear_slot)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def delete_schedule(self):
        if not messagebox.askyesno("Видалити розклад",
                "Видалити розклад усіх п'яти днів (чисельник і знаменник)?\n\n"
                "Класи та КТП залишаться. Поки редактор відкритий, це можна скасувати кнопкою «Назад».",
                parent=self,default="no"):return
        count=len(self.cfg["period_times"])
        self.cfg["days"]={str(day):[[None,None] for _ in range(count)] for day in range(5)}
        self.refresh_slots()

    def clear_slot(self,phase=None):
        """Видаляє призначення вибраних рядків (можна виділити мишкою кілька), а не номер уроку і дзвінки."""
        choice=self.slots.selection()
        if not choice:return "break"
        day=str(self.dayselect.current())
        indexes=sorted(int(i) for i in choice)
        label=("обидва потоки" if phase is None else
               ("чисельник" if phase==0 else "знаменник"))
        names=", ".join(str(i+1) for i in indexes)
        if messagebox.askyesno("Очистити уроки розкладу",
                  f"Очистити {label}: урок(и) №{names} ({self.dayselect.get()})? "
                  "Кількість дзвоників залишиться незмінною.",parent=self):
            for idx in indexes:
                pair=self.cfg["days"][day][idx]
                if phase is None:self.cfg["days"][day][idx]=[None,None]
                else:pair[phase]=None
            self.refresh_slots()
        return "break"

    def edit_slot(self):
        choice=self.slots.selection()
        if not choice:
            messagebox.showinfo("Розклад","Виберіть рядок уроку.",parent=self);return
        day=str(self.dayselect.current());idx=int(choice[0])
        win=tk.Toplevel(self);win.title(f"Урок №{idx+1} • {self.dayselect.get()}")
        win.transient(self);fit_work_window(win,"small");win.grab_set()
        old=self.cfg["days"][day][idx]
        options=["— немає —"]+sorted(self.cfg["course_map"])
        values=[]
        for k,phase in enumerate(("Чисельник","Знаменник")):
            ttk.Label(win,text=phase).pack(anchor="w",padx=12,pady=(10,0))
            var=tk.StringVar(value=old[k] or options[0])
            ttk.Combobox(win,values=options,textvariable=var,state="readonly",width=56).pack(anchor="w",padx=12)
            values.append(var)
        def save():
            self.cfg["days"][day][idx]=[v.get() if v.get()!="— немає —" else None for v in values]
            win.destroy();self.refresh_slots()
        ttk.Button(win,text="Застосувати",command=save).pack(pady=18)

    def _streams_ui(self):
        tab=self.tab_streams
        ttk.Label(tab,wraplength=900,justify="left",foreground="#245471",text=(
            "ЯК ЦЕ ПОВ'ЯЗАНО: ПОТІК (клас + предмет, як у розкладі) → КУРС у Google Classroom (куди створюються "
            "чернетки) → КТП (теми й домашні завдання). Програма підбирає зв'язки САМА за змістом: «10 ІУ» = "
            "10 клас, Історія України; «ГО» = Громадянська освіта; «Право» = Правознавство; «ВІ» = Всесвітня "
            "історія. КТП призначається автоматично, коли ви перетягуєте файл. Змінюйте вручну лише коли потрібно."
            )).pack(anchor="w",pady=(6,2))
        self.streamtree=ttk.Treeview(tab,columns=("name","plan","course","state"),show="headings")
        for col,title,w in (("name","Потік (клас + предмет)",190),("plan","КТП (ідентифікатор)",130),("course","Курс у Google Classroom",250),("state","Стан зв'язків",300)):
            self.streamtree.heading(col,text=title);self.streamtree.column(col,width=w)
        self.streamtree.pack(fill="both",expand=True,pady=4)
        self.streamtree.bind("<ButtonRelease-1>",self._open_inline_on_click)
        self.streamtree.bind("<Double-1>",self._inline_stream_edit)
        self.streamtree.bind("<Delete>",lambda e:self.remove_stream())
        self.streamtree.bind("<Button-3>",self._stream_context_menu)
        ttk.Label(tab,text="Натисніть один раз на КТП або назву Classroom — з’явиться випадаючий список.",
                  foreground="#245471").pack(anchor="w")
        bar=ttk.Frame(tab);bar.pack(fill="x",pady=8)
        for title,fn in [("Підібрати автоматично",lambda:self.auto_link(True)),
                         ("Додати потік",lambda:self.edit_stream(True)),
                         ("Редагувати потік",lambda:self.edit_stream(False)),("Видалити потік",self.remove_stream)]:
            ttk.Button(bar,text=title,command=fn).pack(side="left",padx=4)
        self.refresh_streams()

    def _stream_context_menu(self,event):
        item=self.streamtree.identify_row(event.y)
        if item:self.streamtree.selection_set(item)
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Редагувати",command=lambda:self.edit_stream(False))
        menu.add_command(label="Додати новий потік",command=lambda:self.edit_stream(True))
        menu.add_separator()
        menu.add_command(label="Видалити потік (Delete)",command=self.remove_stream)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def _classroom_names(self):
        names=[str(c.get("name","")).strip() for c in (getattr(self.parent,"google_courses",None) or []) if c.get("name")]
        return names or [x for x in self.parent.state.get("classroom_order",[]) if isinstance(x,str)]

    def _stream_state(self,stream,info):
        names=self._classroom_names()
        if not names:course="Classroom: ще не синхронізовано"
        elif any(match_norm(n)==match_norm(info.get("course_title","")) for n in names):course="Classroom ✓"
        else:
            hit=best_match(info.get("course_title","") or stream,names)
            course=f"≈ {hit}" if hit else "⚠ курсу немає в Classroom"
        count=len(self.plans.get(info["plan"],{}).get("lessons",[]))
        return course+" • "+(f"КТП: {count} уроків" if count else "⚠ без КТП")

    def refresh_streams(self):
        self.streamtree.delete(*self.streamtree.get_children())
        for ix,(stream,info) in enumerate(sorted(self.cfg["course_map"].items())):
            self.streamtree.insert("","end",iid=str(ix),values=(
                stream,friendly_plan_id(info["plan"]),info["course_title"],self._stream_state(stream,info)))
        self.cfg["classroom_course_titles"]=list(dict.fromkeys(
            info["course_title"] for info in self.cfg["course_map"].values()))

    def auto_link(self,announce=False):
        """Підставляє точні назви курсів Classroom за змістом (клас + предмет)."""
        names=self._classroom_names()
        if not names:
            if announce:messagebox.showinfo("Classroom","Спершу підключіть Google і дочекайтесь синхронізації курсів.",parent=self)
            return {}
        changed=link_streams(self.cfg["course_map"],names)
        if changed:
            self.refresh_streams();self._refresh_planlist()
        if announce:
            messagebox.showinfo("Зв'язки",
                ("Оновлено зв'язки з Classroom:\n"+"\n".join(f"• {s}: {old or '—'} → {new}"
                  for s,(old,new) in list(changed.items())[:15])) if changed else
                "Усі потоки вже пов'язані з курсами Classroom правильно.",parent=self)
        return changed

    def _open_inline_on_click(self,event):
        if self.streamtree.identify_region(event.x,event.y)!="cell":return
        if self.streamtree.identify_column(event.x) not in ("#2","#3"):return
        x,y=event.x,event.y
        self.after(10,lambda:self._inline_stream_edit_xy(x,y,open_list=True))

    def _inline_stream_edit_xy(self,x,y,open_list=False):
        from types import SimpleNamespace
        self._inline_stream_edit(SimpleNamespace(x=x,y=y),open_list=open_list)

    def _inline_stream_edit(self,event,open_list=False):
        item=self.streamtree.identify_row(event.y)
        column=self.streamtree.identify_column(event.x)
        if not item or column not in ("#2","#3"):return
        bbox=self.streamtree.bbox(item,column)
        if not bbox:return
        current=self.streamtree.item(item,"values")[0]
        current_info=self.cfg["course_map"].get(current,{})
        is_plan=column=="#2"
        if is_plan:
            options=[friendly_plan_id(key) for key in self.plans]
            current_value=friendly_plan_id(current_info.get("plan",""))
        else:
            options=sorted(set(
                list(self.cfg.get("classroom_course_titles",[]))+
                [m.get("course_title","") for m in self.cfg["course_map"].values()]+
                [item.get("name","") for item in getattr(self.parent,"google_courses",[])]))
            current_value=current_info.get("course_title","")
        x,y,width,height=bbox
        existing=self._active_inline
        if existing is not None:
            try:
                if existing.winfo_exists():return
            except tk.TclError:pass
        editor=ttk.Combobox(self.streamtree,values=options,
                            state="readonly" if is_plan else "normal")
        self._active_inline=editor
        editor.set(current_value)
        editor.place(x=x,y=y,width=width,height=height)
        editor.focus_set()
        if open_list:
            def post_dropdown():
                if editor.winfo_exists():
                    try:editor.tk.call("ttk::combobox::Post",editor)
                    except tk.TclError:pass
            self.after(40,post_dropdown)
        closed=[False]
        def finish(save=True):
            if closed[0]:return
            closed[0]=True
            new=editor.get().strip()
            self._active_inline=None
            editor.destroy()
            if not save or not new:return
            if is_plan:
                by_display={friendly_plan_id(k):k for k in self.plans}
                value=by_display.get(new)
                if not value:return
                self.cfg["course_map"][current]["plan"]=value
            else:
                self.cfg["course_map"][current]["course_title"]=new
            self.refresh_streams()
            self.streamtree.selection_set(item)
        def focus_inside():
            # Відкритий список (popdown) забирає фокус: це не «втрата фокусу».
            try:
                current=str(editor.tk.call("focus"))
                popdown=str(editor.tk.call("ttk::combobox::PopdownWindow",editor))
            except tk.TclError:return False
            return current==str(editor) or current.startswith(popdown)
        def focus_left(_event):
            def check():
                if closed[0]:return
                try:alive=editor.winfo_exists()
                except tk.TclError:alive=False
                if alive and not focus_inside():finish(True)
            self.after(220,check)
        editor.bind("<Return>",lambda _:finish(True))
        editor.bind("<Escape>",lambda _:(finish(False),"break")[1])
        editor.bind("<FocusOut>",focus_left)
        editor.bind("<<ComboboxSelected>>",lambda _:finish(True))

    def edit_stream(self,new):
        current=None
        if not new:
            ids=self.streamtree.selection()
            if not ids:return
            current=self.streamtree.item(ids[0],"values")[0]
        dlg=tk.Toplevel(self);dlg.title("Клас / предмет / курс Classroom")
        dlg.transient(self);fit_work_window(dlg,"small");dlg.grab_set()
        info=self.cfg["course_map"].get(current,{})
        fields=[]
        for label,start in (("Потік за розкладом",current or ""),
                            ("План КТП",friendly_plan_id(info.get("plan",""))),
                            ("Назва курсу Classroom",info.get("course_title",""))):
            ttk.Label(dlg,text=label).pack(anchor="w",padx=12,pady=(10,0))
            var=tk.StringVar(value=start)
            if label=="План КТП":
                ttk.Combobox(dlg,textvariable=var,values=[friendly_plan_id(k) for k in self.plans],width=65,state="readonly").pack(anchor="w",padx=12)
            else:ttk.Entry(dlg,textvariable=var,width=72).pack(anchor="w",padx=12)
            fields.append(var)
        def apply():
            stream,plan_view,course=[v.get().strip() for v in fields]
            plan=next((k for k in self.plans if friendly_plan_id(k)==plan_view),None)
            if not stream or not plan or not course:
                messagebox.showerror("Потік","Усі три поля обов'язкові.",parent=dlg);return
            if stream in self.cfg["course_map"] and (new or stream!=current):
                messagebox.showerror("Потік","Такий потік уже існує.",parent=dlg);return
            if current and stream!=current:
                for pairs in self.cfg["days"].values():
                    for pair in pairs:
                        for k in (0,1):
                            if pair[k]==current:pair[k]=stream
                del self.cfg["course_map"][current]
            self.cfg["course_map"][stream]={"plan":plan,"course_title":course}
            self.refresh_streams();self.refresh_slots();self._refresh_planlist();dlg.destroy()
        ttk.Button(dlg,text="Застосувати",command=apply).pack(pady=15)

    def remove_stream(self):
        selected=self.streamtree.selection()
        if not selected:return "break"
        self._remove_streams([self.streamtree.item(i,"values")[0] for i in selected])
        return "break"

    def _remove_streams(self,names,what=None,ask=True):
        shown="\n".join("• "+n for n in names[:12])+("\n…" if len(names)>12 else "")
        if ask and not messagebox.askyesno("Видалити",
                f"Видалити {what or str(len(names))+' потік(и)'} із програми?\n{shown}\n\n"
                "Їхні уроки в розкладі стануть порожніми. Скасувати: кнопка «Назад».",parent=self,default="no"):
            return False
        for stream in names:
            for pairs in self.cfg["days"].values():
                for pair in pairs:
                    for i in (0,1):
                        if pair[i]==stream:pair[i]=None
            info=self.cfg["course_map"].pop(stream,None)
            if info:
                key=info["plan"]
                if (key in self.plans and not self.plans[key].get("lessons")
                        and not any(i["plan"]==key for i in self.cfg["course_map"].values())):
                    self.plans.pop(key)
        self.lesson_row=None
        self.refresh_streams();self.refresh_slots();self._refresh_planlist()
        return True

    def _as_date(self,text):
        try:return date.fromisoformat(parse_ui_date(text))
        except (ValueError,TypeError):return None

    def _calendar_default(self,key):
        """Календар відкривається там, де вчитель працює, а не на сьогоднішній даті."""
        start=self._as_date(self.dates["year_start"].get()) if hasattr(self,"dates") else None
        today=date.today()
        if key=="year_start":
            return date(today.year if today.month>=7 else today.year-1,9,1)
        if start is None:return today
        if key=="year_end":return date(start.year+1,5,31)
        if key=="anchor_monday":return start-timedelta(days=start.weekday())
        if key=="semester2":return date(start.year+1,1,10)
        return start

    def _holiday_start_default(self):
        ends=sorted(h["end"] for h in self.cfg.get("holidays",[]))
        if ends:
            last=date.fromisoformat(ends[-1])
            return last+timedelta(days=30)
        try:return date.fromisoformat(self.cfg["year_start"])+timedelta(days=45)
        except (KeyError,ValueError):return date.today()

    def _year_ui(self):
        viewport=self.tab_year
        canvas=tk.Canvas(viewport,highlightthickness=0)
        scroll=ttk.Scrollbar(viewport,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        tab=ttk.Frame(canvas,padding=(8,0,8,8))
        handle=canvas.create_window((0,0),window=tab,anchor="nw")
        tab.bind("<Configure>",lambda e:canvas.configure(
                 scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(
                 handle,width=e.width))
        canvas.bind("<MouseWheel>",lambda e:canvas.yview_scroll(
                   -int(e.delta/120) if e.delta else 0,"units"))
        ttk.Label(tab,text="Парність тижнів не зупиняється навіть під час канікул. Дати КТП не визначають урок за розкладом.",
                  font=("Segoe UI",10,"bold")).pack(anchor="w",pady=9)
        fields=ttk.Frame(tab);fields.pack(anchor="w")
        self.dates={}
        for key,label in (("year_start","Початок року (ДД.ММ.РРРР)"),
                          ("year_end","Завершення року"),
                          ("anchor_monday","Опорний понеділок")):
            ttk.Label(fields,text=label,width=37).grid(row=len(self.dates),column=0,sticky="w",pady=5)
            var=tk.StringVar(value=display_ui_date(self.cfg[key]));self.dates[key]=var
            DateField(fields,var,weekday=0 if key=="anchor_monday" else None,width=18,title=label,
                      default=lambda k=key:self._calendar_default(k)).grid(row=len(self.dates)-1,column=1,sticky="w")
        ttk.Label(fields,text="Опорний тиждень ПЕРШОГО семестру").grid(row=3,column=0,sticky="w")
        self.anchorphase=tk.StringVar(value=self.cfg.get("anchor_phase","чисельник"))
        ttk.Combobox(fields,values=("чисельник","знаменник"),textvariable=self.anchorphase,state="readonly",width=18).grid(row=3,column=1,sticky="w")
        ttk.Button(fields,text="Застосувати ці дати",command=self.apply_dates).grid(row=4,column=0,pady=10,sticky="w")
        ttk.Button(fields,text="РОЗПОЧАТИ НОВИЙ НАВЧАЛЬНИЙ РІК",command=self.new_year).grid(row=4,column=1,padx=8,pady=10,sticky="w")
        semesterbox=ttk.LabelFrame(tab,text="ДРУГИЙ СЕМЕСТР — окреме коригування (тільки за потреби)",padding=6)
        semesterbox.pack(fill="x",pady=(6,3),anchor="w")
        self.semester2_enabled=tk.BooleanVar(value=self.cfg.get("semester2_override",False))
        ttk.Checkbutton(semesterbox,text="Використовувати окрему парність із початку другого семестру",
                        variable=self.semester2_enabled).grid(row=0,column=0,columnspan=3,sticky="w")
        proposed=self.cfg.get("semester2_start")
        if not proposed:
            # Після зимових канікул — лише ПРИКЛАД дати, прапорець вимкнений.
            holidays=self.cfg.get("holidays",[])
            winter=[x for x in holidays if x["start"]>self.cfg["year_start"][:4]+"-11-01"
                    and x["end"]<self.cfg["year_end"][:4]+"-03-01"]
            suggested=date.fromisoformat(winter[0]["end"])+timedelta(days=1) if winter else date.fromisoformat(self.cfg["year_start"]).replace(month=1,year=date.fromisoformat(self.cfg["year_start"]).year+1)
            proposed=(suggested+timedelta(days=(7-suggested.weekday())%7)).isoformat()
        self.semester2_start=tk.StringVar(value=display_ui_date(proposed))
        ttk.Label(semesterbox,text="Перший понеділок другого семестру (ДД.ММ.РРРР):").grid(row=1,column=0,sticky="w",pady=5)
        DateField(semesterbox,self.semester2_start,weekday=0,width=15,
                  title="Перший понеділок другого семестру",
                  default=lambda:self._calendar_default("semester2")).grid(row=1,column=1,sticky="w",padx=8)
        self.semester2_phase=tk.StringVar(value=self.cfg.get("semester2_anchor_phase","знаменник"))
        ttk.Label(semesterbox,text="Парність цього понеділка:").grid(row=2,column=0,sticky="w",pady=5)
        ttk.Combobox(semesterbox,textvariable=self.semester2_phase,
                     values=("чисельник","знаменник"),state="readonly",width=17).grid(row=2,column=1,sticky="w",padx=8)
        ttk.Label(semesterbox,text="Якщо прапорець вимкнений, чергування йде безперервно з першого семестру.",
                  foreground="#416079").grid(row=3,column=0,columnspan=3,sticky="w")
        ttk.Label(tab,text="Канікули: додайте/видаліть будь-який період, без автоматичного планування на ці дні.").pack(anchor="w",pady=(9,3))
        self.holidays=ttk.Treeview(tab,columns=("start","end"),show="headings",height=6)
        for col,label in (("start","Початок"),("end","Кінець")):
            self.holidays.heading(col,text=label);self.holidays.column(col,width=150)
        self.holidays.pack(anchor="w",fill="x")
        self.holidays.bind("<Double-1>",self._inline_holiday_edit)
        self.holidays.bind("<Delete>",lambda e:self.del_holiday())
        self.holidays.bind("<Button-3>",self._holidays_context_menu)
        buttons=ttk.Frame(tab);buttons.pack(anchor="w",pady=5)
        ttk.Button(buttons,text="+ Канікули",command=self.add_holiday).pack(side="left")
        ttk.Button(buttons,text="Видалити вибраний період",command=self.del_holiday).pack(side="left",padx=8)
        ttk.Label(tab,text="Час уроків (дзвоники) можна змінити, додати восьмий/дев'ятий урок або прибрати зайві.").pack(anchor="w",pady=(10,0))
        meal=ttk.Frame(tab);meal.pack(anchor="w",pady=7)
        self.meal_after=tk.IntVar(value=self.cfg.get("meal_break_after",2))
        self.meal_label=tk.StringVar(value=self.cfg.get("meal_label","ХАРЧУВАННЯ У ЇДАЛЬНІ"))
        ttk.Label(meal,text="Харчування після уроку №").pack(side="left")
        ttk.Spinbox(meal,from_=1,to=12,textvariable=self.meal_after,width=5).pack(side="left",padx=5)
        ttk.Label(meal,text="Підпис").pack(side="left",padx=5)
        ttk.Entry(meal,textvariable=self.meal_label,width=33).pack(side="left")

        self.times=ttk.Frame(tab);self.times.pack(anchor="w")
        self.timevars=[]
        self.refresh_time_fields()
        control=ttk.Frame(tab);control.pack(anchor="w",pady=6)
        ttk.Button(control,text="+ Додати урок / дзвоник",command=self.add_period).pack(side="left")
        ttk.Button(control,text="− Прибрати останній урок",command=self.remove_period).pack(side="left",padx=7)
        self.refresh_holidays()

    def refresh_time_fields(self):
        for child in self.times.winfo_children():child.destroy()
        self.timevars=[]
        for ix,pair in enumerate(self.cfg["period_times"]):
            ttk.Label(self.times,text=f"Урок {ix+1}",width=9).grid(row=ix,column=0,sticky="w")
            vars=[]
            for j,item in enumerate(pair):
                v=tk.StringVar(value=item)
                ttk.Entry(self.times,textvariable=v,width=10).grid(row=ix,column=j+1,padx=4,pady=2)
                vars.append(v)
            self.timevars.append(vars)

    def add_period(self):
        if len(self.cfg["period_times"])>=12:
            messagebox.showwarning("Дзвоники","Максимум 12 уроків на день.",parent=self);return
        self.cfg["period_times"]=[[v.get().strip() for v in row] for row in self.timevars]
        start="15:10";end="15:55"
        if self.cfg["period_times"]:
            try:
                previous=self.cfg["period_times"][-1][1]
                minutes=int(previous[:2])*60+int(previous[3:])+5
                start=f"{minutes//60:02d}:{minutes%60:02d}"
                minutes+=45
                end=f"{minutes//60:02d}:{minutes%60:02d}"
            except (ValueError,IndexError):pass
        self.cfg["period_times"].append([start,end])
        for day in range(5):self.cfg["days"].setdefault(str(day),[]).append([None,None])
        self.refresh_time_fields();self.refresh_slots()

    def remove_period(self):
        if len(self.cfg["period_times"])<=1:return
        n=len(self.cfg["period_times"])
        if any(len(self.cfg["days"].get(str(day),[]))>=n and any(self.cfg["days"][str(day)][-1]) for day in range(5)):
            messagebox.showwarning("Урок використовується","Спочатку очистіть останню пару для всіх днів.",parent=self);return
        self.cfg["period_times"].pop()
        for day in range(5):
            if self.cfg["days"].get(str(day)):self.cfg["days"][str(day)].pop()
        self.refresh_time_fields();self.refresh_slots()

    def import_schedule(self,path=None,quiet=False):
        from .schedule_io import table_rows,decode_schedule
        if path is None:
            path=filedialog.askopenfilename(parent=self,title="Імпортувати розклад",
                 filetypes=[("Таблиці","*.docx *.doc *.csv *.xlsx"),
                            ("Word","*.docx *.doc"),("Excel","*.xlsx"),("CSV","*.csv")])
        if not path:return False
        try:
            rows_cache=table_rows(path)
            schedule,unknown,found=decode_schedule(rows_cache,self.cfg)
        except Exception as e:
            messagebox.showerror("Не вдалося імпортувати",str(e),parent=self);return False
        if unknown:
            unknown,schedule,found=self._offer_new_streams(unknown,rows_cache,schedule,found)
            if unknown is None:return False
        if unknown:
            from .schedule_io import _normalize
            dlg=tk.Toplevel(self);dlg.title("Зіставте назви предметів у файлі");fit_work_window(dlg,"normal")
            dlg.transient(self);dlg.grab_set()
            ttk.Label(dlg,text="У розкладі є назви, яких немає в поточних потоках. Оберіть правильні відповідники:",
                      wraplength=800).pack(anchor="w",padx=12,pady=9)
            canvas=tk.Canvas(dlg)
            scroll=ttk.Scrollbar(dlg,orient="vertical",command=canvas.yview)
            frame=ttk.Frame(canvas)
            frame.bind("<Configure>",lambda _:canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0,0),window=frame,anchor="nw")
            canvas.configure(yscrollcommand=scroll.set)
            canvas.pack(side="left",fill="both",expand=True)
            scroll.pack(side="right",fill="y")
            mapped={}
            choices=["— Виберіть —"]+sorted(self.cfg["course_map"])
            for i,raw in enumerate(unknown):
                ttk.Label(frame,text=raw,width=40).grid(row=i,column=0,padx=8,pady=5,sticky="w")
                v=tk.StringVar(value=choices[0])
                box=ttk.Combobox(frame,textvariable=v,values=choices,state="readonly",width=43)
                box.grid(row=i,column=1,padx=8,pady=5)
                mapped[raw]=v
            chosen={"ok":False}
            def apply():
                if any(v.get()==choices[0] for v in mapped.values()):
                    messagebox.showwarning("Зіставлення","Для кожного рядка оберіть правильний потік.",parent=dlg);return
                for raw,v in mapped.items():
                    self.cfg.setdefault("schedule_aliases",{})[_normalize(raw)]=v.get()
                chosen["ok"]=True;dlg.destroy()
            ttk.Button(dlg,text="Зберегти відповідності",command=apply).pack(side="bottom",pady=9)
            self.wait_window(dlg)
            if not chosen["ok"]:return False
            schedule,unknown,found=decode_schedule(rows_cache,self.cfg)
            if unknown:
                messagebox.showerror("Зіставлення","Залишилися невідомі назви:\n"+"\n".join(unknown),parent=self);return False
        has_schedule=any(pair[0] or pair[1] for pairs in self.cfg["days"].values() for pair in pairs)
        if quiet or not has_schedule or messagebox.askyesno("Перегляд імпорту",
            f"Прочитано уроків із номерами: {', '.join(map(str,found))}.\n"
            "ЗАМІНИТИ всі 5 днів розкладу на нову таблицю?\n"
            "Зміни поки будуть лише в редакторі до натискання «ЗБЕРЕГТИ ВСІ ЗМІНИ».",parent=self):
            self.cfg["days"]=schedule
            from .workload_io import parse_workload_title
            info=parse_workload_title(rows_cache,self.cfg.get("year_start"))
            if info.get("workload_teacher"):self.teacher_var.set(info["workload_teacher"])
            if info.get("workload_code"):self.code_var.set(info["workload_code"])
            found=info.get("holidays") or []
            if found and sorted((h["start"],h["end"]) for h in found)!=sorted(
                    (h["start"],h["end"]) for h in self.cfg.get("holidays",[])):
                names=", ".join(f"{display_ui_date(h['start'])[:5]}–{display_ui_date(h['end'])[:5]}" for h in found)
                if (not self.cfg.get("holidays")) or messagebox.askyesno("Канікули з файлу",
                        f"У першому рядку файлу вказано канікули: {names}.\n\n"
                        "Записати їх у програму (замінивши поточні канікули)?",parent=self):
                    self.cfg["holidays"]=found;self.refresh_holidays()
            self.refresh_slots()
            self.auto_link()
            self._refresh_planlist()
            if not quiet:
                messagebox.showinfo("Імпорт","Розклад у редакторі оновлено. Перегляньте всі дні.\n"
                    "Не забудьте натиснути «ЗБЕРЕГТИ ВСІ ЗМІНИ».",parent=self)
            return True
        return False

    def _workload_config(self):
        self.cfg["period_times"]=[[v.get().strip() for v in row] for row in self.timevars]
        self.cfg["meal_break_after"]=int(self.meal_after.get())
        self.cfg["meal_label"]=self.meal_label.get().strip() or "ХАРЧУВАННЯ У ЇДАЛЬНІ"
        config=copy.deepcopy(self.cfg)
        config["workload_teacher"]=self.teacher_var.get().strip()
        config["workload_code"]=self.code_var.get().strip()
        return config

    def export_workload_word(self):
        from .workload_io import export_workload_docx
        year=f"{self.cfg['year_start'][:4]}-{self.cfg['year_end'][:4]}"
        path=filedialog.asksaveasfilename(parent=self,title="Зберегти «Навантаження» у Word",
             defaultextension=".docx",initialfile=f"Навантаження_{year}.docx",
             filetypes=[("Word DOCX","*.docx")])
        if not path:return
        try:
            export_workload_docx(self._workload_config(),path,
                show_numbers=self.show_numbers.get(),show_times=self.show_bells.get(),
                show_meal=self.show_meal.get())
            messagebox.showinfo("Навантаження",f"Готово. Файл Word:\n{path}",parent=self)
        except Exception as ex:
            messagebox.showerror("Word",str(ex),parent=self)

    def export_workload_picture(self):
        from .workload_io import export_workload_jpeg
        year=f"{self.cfg['year_start'][:4]}-{self.cfg['year_end'][:4]}"
        path=filedialog.asksaveasfilename(parent=self,title="Зберегти «Навантаження» як зображення",
             defaultextension=".jpg",initialfile=f"Навантаження_{year}.jpg",
             filetypes=[("Зображення JPEG","*.jpg *.jpeg")])
        if not path:return
        try:
            export_workload_jpeg(self._workload_config(),path,
                show_numbers=self.show_numbers.get(),show_times=self.show_bells.get(),
                show_meal=self.show_meal.get())
            messagebox.showinfo("Навантаження",f"Готово. Зображення:\n{path}",parent=self)
        except Exception as ex:
            messagebox.showerror("JPEG",str(ex),parent=self)

    def export_schedule(self):
        from .schedule_io import export_schedule_docx
        path=filedialog.asksaveasfilename(parent=self,
             title="Зберегти розклад у Word",
             defaultextension=".docx",initialfile="Розклад уроків.docx",
             filetypes=[("Word DOCX","*.docx")])
        if not path:return
        self.cfg["period_times"]=[[v.get().strip() for v in row] for row in self.timevars]
        self.cfg["meal_break_after"]=int(self.meal_after.get())
        self.cfg["meal_label"]=self.meal_label.get().strip() or "ХАРЧУВАННЯ У ЇДАЛЬНІ"
        try:
            export_schedule_docx(self.cfg,path,
               show_bells=self.show_bells.get(),
               show_meal=self.show_meal.get(),
               show_numbers=self.show_numbers.get())
            messagebox.showinfo("Розклад у Word","Готово. Файл:\n"+path+
                "\n\nПараметри розкладу збережуться у програмі після натискання «ЗБЕРЕГТИ ВСІ ЗМІНИ».",parent=self)
        except Exception as ex:
            messagebox.showerror("Word",str(ex),parent=self)

    def _year_values(self):
        parsed={}
        for key,var in self.dates.items():
            parsed[key]=parse_ui_date(var.get())
        if parsed["year_start"]>parsed["year_end"]:
            raise ValueError("Дата початку навчального року більша за дату завершення.")
        if date.fromisoformat(parsed["anchor_monday"]).weekday()!=0:
            raise ValueError("Опорна дата повинна припадати на понеділок.")
        return parsed

    def _inline_holiday_edit(self,event):
        """Подвійне натискання на даті канікул відкриває календар."""
        item=self.holidays.identify_row(event.y)
        column=self.holidays.identify_column(event.x)
        if not item or column not in ("#1","#2"):return
        index=int(item);key="start" if column=="#1" else "end"
        current=self.cfg["holidays"][index][key]
        chosen=pick_date(self.holidays,display_ui_date(current),
                         title="Початок канікул" if key=="start" else "Кінець канікул",
                         min_date=(self._as_date(display_ui_date(self.cfg["holidays"][index]["start"]))
                                   if key=="end" else None))
        if not chosen:return
        updated=dict(self.cfg["holidays"][index]);updated[key]=parse_ui_date(chosen)
        if updated["end"]<updated["start"]:
            messagebox.showerror("Канікули","Кінець не може бути раніше початку.",parent=self);return
        self.cfg["holidays"][index]=updated
        self.refresh_holidays()

    def export_schedule_jpeg(self):
        path=filedialog.asksaveasfilename(parent=self,
            title="Зберегти розклад як зображення JPEG",
            defaultextension=".jpg",initialfile="Розклад уроків.jpg",
            filetypes=[("Зображення JPEG","*.jpg *.jpeg")])
        if not path:return
        self.cfg["period_times"]=[[v.get().strip() for v in row] for row in self.timevars]
        self.cfg["meal_break_after"]=int(self.meal_after.get())
        self.cfg["meal_label"]=self.meal_label.get().strip() or "ХАРЧУВАННЯ У ЇДАЛЬНІ"
        try:
            from .schedule_io import export_schedule_jpeg
            export_schedule_jpeg(self.cfg,path,
                show_bells=self.show_bells.get(),
                show_meal=self.show_meal.get(),
                show_numbers=self.show_numbers.get())
            messagebox.showinfo("JPEG-розклад",
                "Зображення розкладу готове:\\n"+path+
                "\\n\\nЗа потреби збережіть зміни у програмі загальною кнопкою.",
                parent=self)
        except Exception as ex:
            messagebox.showerror("JPEG",str(ex),parent=self)

    def _save_semester_values(self):
        self.cfg["semester2_override"]=bool(self.semester2_enabled.get())
        if self.semester2_enabled.get():
            start=parse_ui_date(self.semester2_start.get())
            self.cfg["semester2_start"]=start
            self.cfg["semester2_anchor_monday"]=start
            self.cfg["semester2_anchor_phase"]=self.semester2_phase.get()
        else:
            # Disabled override doesn't alter previously saved phase data.
            self.cfg["semester2_anchor_phase"]=self.semester2_phase.get()

    def apply_dates(self):
        try:self.cfg.update(self._year_values())
        except ValueError as ex:
            messagebox.showerror("Дати",str(ex),parent=self);return
        self.cfg["anchor_phase"]=self.anchorphase.get()
        try:self._save_semester_values()
        except ValueError as ex:
            messagebox.showerror("Другий семестр",str(ex),parent=self);return
        self.cfg["period_times"]=[[v.get().strip() for v in row] for row in self.timevars]
        self.cfg["meal_break_after"]=int(self.meal_after.get())
        self.cfg["meal_label"]=self.meal_label.get().strip() or "ХАРЧУВАННЯ У ЇДАЛЬНІ"
        self.cfg["print_bells"]=self.show_bells.get()
        self.cfg["print_meal"]=self.show_meal.get()
        self.cfg["print_numbers"]=self.show_numbers.get()
        messagebox.showinfo("Дати","Зміни враховані у вікні редактора. Для запису на диск натисніть «ЗБЕРЕГТИ ВСІ ЗМІНИ».",parent=self)

    def new_year(self):
        if not messagebox.askyesno("Новий навчальний рік",
          "Спочатку буде збережена резервна копія попереднього року.\n"
          "Усі старі КТП буде позначено як «потрібна перевірка»: публікація уроків блокується до підтвердження нових КТП.\n"
          "Чернетки й вибрані Word нового року починаються з нуля.\n\n"
          "Продовжити?",parent=self):return
        first=simpledialog.askstring("Початок року","Вкажіть початок у форматі ДД.ММ.РРРР:",parent=self)
        if not first:return
        last=simpledialog.askstring("Кінець року","Вкажіть завершення у форматі ДД.ММ.РРРР:",parent=self)
        if not last:return
        try:
            start=date.fromisoformat(parse_ui_date(first));end=date.fromisoformat(parse_ui_date(last))
            if end<start:raise ValueError("Кінець року раніше початку")
        except ValueError as ex:messagebox.showerror("Рік",str(ex),parent=self);return
        monday=start-timedelta(days=start.weekday())
        self.dates["year_start"].set(display_ui_date(start.isoformat()))
        self.dates["year_end"].set(display_ui_date(end.isoformat()))
        self.dates["anchor_monday"].set(display_ui_date(monday.isoformat()))
        self.anchorphase.set("чисельник")
        self.semester2_enabled.set(False)
        self.cfg["holidays"]=[]
        for plan in self.plans.values(): plan["needs_review"]=True
        self._is_new_year=True
        self.apply_dates()
        self.refresh_holidays();self.refresh_lessons()
        messagebox.showinfo("Новий рік",
           "Тепер додайте канікули, розклад і нові КТП або підтвердьте актуальні плани.\n"
           "Старі КТП блокуються для публікації, доки їх не перевірено.",parent=self)

    def refresh_holidays(self):
        self.holidays.delete(*self.holidays.get_children())
        for i,h in enumerate(self.cfg["holidays"]):
            self.holidays.insert("","end",iid=str(i),
                 values=(display_ui_date(h["start"]),display_ui_date(h["end"])))

    def _ask_holiday(self,start="",end=""):
        """Одне вікно з двома календарями замість двох запитань про текст дати."""
        dialog=tk.Toplevel(self);dialog.title("Канікули");dialog.transient(self)
        dialog.escape_closes=True
        fit_work_window(dialog,"small")
        first=tk.StringVar(value=start);second=tk.StringVar(value=end)
        ttk.Label(dialog,text="Оберіть перший і останній день канікул (кнопка 📅 відкриває календар):",
                  wraplength=460).pack(anchor="w",padx=14,pady=(14,6))
        grid=ttk.Frame(dialog);grid.pack(anchor="w",padx=14)
        ttk.Label(grid,text="Початок:").grid(row=0,column=0,sticky="w",pady=5)
        DateField(grid,first,title="Початок канікул",
                  default=self._holiday_start_default).grid(row=0,column=1,padx=8)
        ttk.Label(grid,text="Кінець:").grid(row=1,column=0,sticky="w",pady=5)
        DateField(grid,second,title="Кінець канікул",default=lambda:self._as_date(first.get()),
                  min_date=lambda:self._as_date(first.get())).grid(row=1,column=1,padx=8)
        result={"value":None}
        def ok():
            try:
                a,b=parse_ui_date(first.get()),parse_ui_date(second.get())
                if b<a:raise ValueError("Кінець раніше початку")
            except ValueError as exc:
                messagebox.showerror("Канікули",str(exc) or "Дата має вигляд ДД.ММ.РРРР",parent=dialog);return
            result["value"]=(a,b);dialog.destroy()
        row=ttk.Frame(dialog);row.pack(pady=14)
        ttk.Button(row,text="Додати",command=ok).pack(side="left",padx=6)
        ttk.Button(row,text="Скасувати",command=dialog.destroy).pack(side="left")
        dialog.grab_set();self.wait_window(dialog)
        return result["value"]

    def add_holiday(self):
        picked=self._ask_holiday()
        if not picked:return
        a,b=picked
        self.cfg["holidays"].append({"start":a,"end":b});self.refresh_holidays()

    def _holidays_context_menu(self,event):
        item=self.holidays.identify_row(event.y)
        if item:self.holidays.selection_set(item)
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Видалити період канікул (Delete)",command=self.del_holiday)
        menu.add_command(label="Додати канікули",command=self.add_holiday)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def del_holiday(self):
        selected=self.holidays.selection()
        if not selected:return "break"
        ix=int(selected[0])
        details=self.cfg["holidays"][ix]
        if messagebox.askyesno("Видалити канікули",
            f"Видалити період {details['start']} — {details['end']}?\n"
            "Після збереження у ці дні знову можуть з'явитися уроки.",
            parent=self):
            self.cfg["holidays"].pop(ix)
            self.refresh_holidays()
        return "break"

    def save(self,confirm=True):
        # Зберігайте ISO всередині програми, а ДД.ММ.РРРР — тільки в інтерфейсі.
        try:self.cfg.update(self._year_values())
        except ValueError as ex:
            messagebox.showerror("Дати",str(ex),parent=self);return
        self.cfg["anchor_phase"]=self.anchorphase.get()
        try:self._save_semester_values()
        except ValueError as ex:
            messagebox.showerror("Другий семестр",str(ex),parent=self);return
        self.cfg["period_times"]=[[v.get().strip() for v in row] for row in self.timevars]
        self.cfg["meal_break_after"]=int(self.meal_after.get())
        self.cfg["meal_label"]=self.meal_label.get().strip() or "ХАРЧУВАННЯ У ЇДАЛЬНІ"
        self.cfg["print_bells"]=self.show_bells.get()
        self.cfg["print_meal"]=self.show_meal.get()
        self.cfg["print_numbers"]=self.show_numbers.get()
        self.cfg["workload_teacher"]=self.teacher_var.get().strip()
        self.cfg["workload_code"]=self.code_var.get().strip()
        renames=dict(self.cfg.pop("pending_stream_renames",None) or {})        # переносимо після запису
        errors=validate_working(self.cfg,self.plans)
        # Клас без КТП — не помилка: вчитель може завантажити КТП пізніше.
        errors=[e for e in errors if not e.startswith("Порожній КТП")]
        if errors:
            if renames:self.cfg["pending_stream_renames"]=renames
            messagebox.showerror("Помилки у даних","Виправте перед збереженням:\n"+"\n".join(errors[:20]),parent=self);return
        if self.cfg==self.original_cfg and self.plans==self.original_plans and not renames:
            if confirm:messagebox.showinfo("Дані","Змін немає.",parent=self)
            return True
        reset=bool(getattr(self,"_is_new_year",False))
        educational_changes=(
            self.cfg.get("days")!=self.original_cfg.get("days")
            or self.cfg.get("course_map")!=self.original_cfg.get("course_map")
            or self.cfg.get("holidays")!=self.original_cfg.get("holidays")
            or any(self.cfg.get(k)!=self.original_cfg.get(k)
                   for k in ("year_start","year_end","anchor_monday","anchor_phase",
                              "semester2_override","semester2_start",
                              "semester2_anchor_phase","semester2_anchor_monday"))
            or self.plans!=self.original_plans
        )
        message=("Зберегти перевірені зміни розкладу/КТП/року та резервну копію?\n"
                 "Існуючі чернетки Google НІКОЛИ не видаляються.")
        if educational_changes:
            message+="\nРаніше перевірені Word будуть позначені як такі, що потребують повторної перевірки."
        if reset:
            message+="\nНовий навчальний рік: зіставлення Google-курсів буде очищено."
        empty=[s for s,i in self.cfg["course_map"].items() if not self.plans.get(i["plan"],{}).get("lessons")]
        if empty:
            message+=f"\n\nБез КТП лишилось класів: {len(empty)}. Це не помилка: КТП можна завантажити пізніше."
        if confirm and not messagebox.askyesno("Збереження",message,parent=self):
            if renames:self.cfg["pending_stream_renames"]=renames
            return
        state=self.parent.state
        try:
            backup=persist(self.cfg,self.plans,state,"Редагування КТП і розкладу у програмі")
            if renames:migrate_stream_keys(state,renames)
            if educational_changes:
                for entry in state.get("files",{}).values():
                    entry["validated"]=False
                    entry["needs_review"]=True
                state["description_overrides"]={}
            # Keep Google DRAFT IDs even across year changes: otherwise a later
            # return to an old date could create duplicate drafts.
            if reset:state["course_ids"]={}
            save_state(state)
            self.parent.cfg=copy.deepcopy(self.cfg)
            self.parent.state=state
            self.parent.update_day()
        except Exception as ex:
            if renames:self.cfg["pending_stream_renames"]=renames
            messagebox.showerror("Помилка збереження",str(ex),parent=self);return
        self.original_cfg=copy.deepcopy(self.cfg);self.original_plans=copy.deepcopy(self.plans)
        self._is_new_year=False
        messagebox.showinfo("Збережено",
            "Усі зміни збережено локально.\nРезервна копія:\n"+str(backup)+
            "\n\nВсі матеріали Google Classroom залишилися без змін.",parent=self)
        try:self.destroy()
        except tk.TclError:pass
        return True
