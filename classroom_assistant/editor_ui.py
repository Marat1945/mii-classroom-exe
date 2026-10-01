"""Tkinter-редактор КТП/розкладу/класів/року, повністю локальний."""
from __future__ import annotations
import copy
import re
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from .editor_core import deep_copy_data, guess_columns, extract_lessons, docx_table_rows, csv_rows, persist, validate_working, tidy
from .engine import ROOT, save_state, build_calendar


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
    window.geometry("620x245")
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
        self.geometry("1130x700")
        self.transient(parent);self.grab_set()
        self.path=Path(path);self.on_accept=on_accept
        self.rows=docx_table_rows(path) if self.path.suffix.lower() in (".docx",".doc") else csv_rows(path)
        longest=max((len(row) for row in self.rows),default=0)
        if longest<2: raise ValueError("Не знайдено таблицю зі стовпцями тем і домашніх завдань")
        samples=next((r for r in self.rows[:8] if any("тема" in c.casefold() or "зміст" in c.casefold() for c in r)),self.rows[0])
        topic,home,number=guess_columns(samples)
        self.topicvar=tk.IntVar(value=topic+1)
        self.hwvar=tk.IntVar(value=home+1)
        self.numvar=tk.IntVar(value=number+1)
        outer=ttk.Frame(self,padding=10);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Перевірте стовпці: дати й зайві класи ігноруються. Нічого не збережено.",
                  font=("Segoe UI",10,"bold")).pack(anchor="w",pady=6)
        fields=ttk.Frame(outer);fields.pack(fill="x",pady=8)
        for label,var in [("№ уроку (стовпець)",self.numvar),("Тема (стовпець)",self.topicvar),("Д/з (стовпець)",self.hwvar)]:
            block=ttk.Frame(fields);block.pack(side="left",padx=9)
            ttk.Label(block,text=label).pack(anchor="w")
            ttk.Spinbox(block,from_=1,to=longest,textvariable=var,width=6).pack()
        ttk.Button(fields,text="Переглянути розпізнане",command=self.refresh).pack(side="left",padx=12)
        ttk.Label(outer,text="Зверніть увагу: розділи без номера уроку не імпортуються. Після імпорту можна змінити будь-який пункт.").pack(anchor="w")
        table=ttk.Frame(outer);table.pack(fill="both",expand=True,pady=6)
        self.tree=ttk.Treeview(table,columns=("num","topic","hw"),show="headings")
        for col,text,width in (("num","№",55),("topic","Тема",610),("hw","Д/з",380)):
            self.tree.heading(col,text=text);self.tree.column(col,width=width,anchor="w")
        sb=ttk.Scrollbar(table,command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")
        bottom=ttk.Frame(outer);bottom.pack(fill="x")
        self.status=ttk.Label(bottom,text="");self.status.pack(side="left")
        ttk.Button(bottom,text="Скасувати",command=self.destroy).pack(side="right")
        ttk.Button(bottom,text="Замінити план після перевірки",command=self.commit).pack(side="right",padx=8)
        self.refresh()

    def refresh(self):
        try:
            self.parsed=extract_lessons(self.rows,self.topicvar.get()-1,self.hwvar.get()-1,self.numvar.get()-1,True)
        except (ValueError,tk.TclError) as e:
            messagebox.showerror("Стовпці",str(e),parent=self);return
        for item in self.tree.get_children():self.tree.delete(item)
        for row in self.parsed:
            self.tree.insert("","end",values=(row["index"],row["topic"],row["homework"]))
        empties=sum(not r["homework"] for r in self.parsed)
        self.status.config(text=f"Знайдено уроків: {len(self.parsed)}. Без Д/з: {empties}. Перевірте перші й останні рядки.")

    def commit(self):
        self.refresh()
        if not self.parsed:
            messagebox.showerror("Імпорт","Не знайдено жодного уроку. Перевірте номери стовпців.",parent=self);return
        if not messagebox.askyesno("Імпорт КТП",
                f"Замінити поточний план на {len(self.parsed)} тем із файлу?\n"
                "Перевірте теми й Д/з. Заміни зберігаються у програмі після кнопки «Зберегти ВСЕ».",
                parent=self):return
        self.on_accept(copy.deepcopy(self.parsed),self.path.name)
        self.destroy()


class SchoolEditor(tk.Toplevel):
    def __init__(self,parent,on_saved):
        super().__init__(parent)
        self.title("КЕРУВАННЯ НАВЧАЛЬНИМ РОКОМ • редагування КТП і розкладу")
        self.geometry("1250x800")
        self.minsize(960,680)
        self.transient(parent)
        self.cfg,self.plans=deep_copy_data()
        self.original_cfg,self.original_plans=copy.deepcopy(self.cfg),copy.deepcopy(self.plans)
        self.on_saved=on_saved
        self.parent=parent
        self.current_plan=None;self.lesson_row=None
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
        ttk.Button(buttons,text="Відкрити папку резервних копій",
                   command=self.open_backup).pack(side="left",padx=12)
        ttk.Button(buttons,text="Скасувати / закрити",command=self.close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW",self.close)

    def open_backup(self):
        import os
        folder=ROOT/"Архів навчальних даних"
        folder.mkdir(parents=True,exist_ok=True)
        if os.name=="nt":
            os.startfile(folder)
        else:
            messagebox.showinfo("Резервні копії",str(folder),parent=self)

    def close(self):
        if (self.cfg!=self.original_cfg or self.plans!=self.original_plans) and not messagebox.askyesno(
                "Незбережені зміни","Закрити й відкинути всі незбережені правки?",parent=self):return
        self.destroy()

    def _plans_ui(self):
        tab=self.tab_plans
        left=ttk.Frame(tab,padding=6);left.pack(side="left",fill="y")
        ttk.Label(left,text="Оберіть КТП (15 початкових планів)").pack(anchor="w")
        self.planlist=tk.Listbox(left,width=29,exportselection=False,height=22)
        self.planlist.pack(fill="y",expand=True)
        self.planlist.bind("<<ListboxSelect>>",self.plan_selected)
        self.planlist.bind("<Button-3>",self._plan_context_menu)
        ttk.Button(left,text="+ Створити новий план",command=self.add_plan).pack(fill="x",pady=4)
        ttk.Button(left,text="Імпортувати DOCX / DOC / CSV",command=self.import_plan).pack(fill="x",pady=4)
        ttk.Button(left,text="Позначити план перевіреним",command=self.approve_plan).pack(fill="x",pady=4)
        right=ttk.Frame(tab,padding=6);right.pack(side="left",fill="both",expand=True)
        self.plan_name=ttk.Label(right,text="Виберіть план",font=("Segoe UI",11,"bold"))
        self.plan_name.pack(anchor="w")
        self.plan_count=ttk.Label(right,text="")
        self.plan_count.pack(anchor="w")
        datebar=ttk.Frame(right);datebar.pack(fill="x",pady=(2,3))
        ttk.Label(datebar,text="Дати уроків для класу:").pack(side="left",padx=(0,6))
        self.ktp_dates_stream=tk.StringVar()
        self.ktp_dates_combo=ttk.Combobox(datebar,textvariable=self.ktp_dates_stream,
                                              state="readonly",width=25)
        self.ktp_dates_combo.pack(side="left")
        self.ktp_dates_combo.bind("<<ComboboxSelected>>",
                                  lambda _:self.refresh_lessons(self.lesson_row))
        ttk.Label(datebar,text="Дати розраховано за розкладом і канікулами; "
                       "для іншого класу виберіть його вище.",
                  foreground="#365777").pack(side="left",padx=9)
        frame=ttk.Frame(right);frame.pack(fill="both",expand=True,pady=6)
        self.lessons=ttk.Treeview(frame,columns=("num","date","topic","hw"),show="headings",height=14)
        for col,title,width in (("num","№",40),("date","Дата",96),
                                 ("topic","Тема",455),("hw","Домашнє завдання",285)):
            self.lessons.heading(col,text=title);self.lessons.column(col,width=width)
        vert=ttk.Scrollbar(frame,command=self.lessons.yview)
        self.lessons.configure(yscrollcommand=vert.set)
        self.lessons.pack(side="left",fill="both",expand=True);vert.pack(side="right",fill="y")
        self.lessons.bind("<<TreeviewSelect>>",self.lesson_selected)
        self.lessons.bind("<Button-3>",self._lesson_context_menu)
        self.lessons.bind("<Double-1>",lambda _:self.topictext.focus_set())
        form=ttk.Frame(right);form.pack(fill="x")
        ttk.Label(form,text="Тема вибраного уроку (можна редагувати)").pack(anchor="w")
        self.topictext=tk.Text(form,height=3,wrap="word")
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
        index=self.planlist.nearest(event.y)
        if index<0:return
        self.planlist.selection_clear(0,"end");self.planlist.selection_set(index)
        self.plan_selected()
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Імпортувати план…",command=self.import_plan)
        menu.add_command(label="Новий план…",command=self.add_plan)
        menu.add_command(label="Позначити план перевіреним",command=self.approve_plan)
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def _lesson_context_menu(self,event):
        item=self.lessons.identify_row(event.y)
        if item:
            self.lessons.selection_set(item);self.lesson_selected()
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Редагувати тему й Д/з",command=lambda:self.topictext.focus_set())
        menu.add_command(label="Застосувати зміни",command=self.apply_lesson)
        menu.add_separator()
        menu.add_command(label="Додати наступний урок",command=self.add_lesson)
        menu.add_command(label="Видалити урок",command=self.delete_lesson)
        menu.add_separator()
        menu.add_command(label="Пересунути вгору",command=lambda:self.move_lesson(-1))
        menu.add_command(label="Пересунути вниз",command=lambda:self.move_lesson(1))
        menu.tk_popup(event.x_root,event.y_root);menu.grab_release()

    def _refresh_planlist(self,chosen=None):
        keys=list(self.plans)
        self.planlist.delete(0,"end")
        self.plan_keys=keys
        for key in keys:self.planlist.insert("end",friendly_plan_id(key))
        if keys:
            k=chosen if chosen in keys else (self.current_plan if self.current_plan in keys else keys[0])
            self.planlist.selection_set(keys.index(k));self.plan_selected()
        else:self.current_plan=None

    def plan_selected(self,_event=None):
        indexes=self.planlist.curselection()
        if not indexes:return
        self.current_plan=self.plan_keys[indexes[0]]
        self.refresh_lessons()

    def refresh_lessons(self,selected=None):
        if not self.current_plan:return
        doc=self.plans[self.current_plan]
        entries=doc["lessons"]
        streams=[name for name,info in self.cfg["course_map"].items()
                 if info.get("plan")==self.current_plan]
        streams.sort()
        current=self.ktp_dates_stream.get()
        self.ktp_dates_combo.configure(values=streams)
        if current not in streams:
            self.ktp_dates_stream.set(streams[0] if streams else "")
        active=self.ktp_dates_stream.get()
        dates={x.lesson_number:display_ui_date(x.day)
               for x in build_calendar(self.cfg,self.plans)
               if x.stream==active and x.plan_id==self.current_plan}
        for item in self.lessons.get_children():self.lessons.delete(item)
        for i,row in enumerate(entries):
            self.lessons.insert("","end",iid=str(i),
                     values=(i+1,dates.get(i+1,""),row["topic"],row.get("homework","")))
        extra=" ⚠ ПЕРЕВІРТЕ КТП НОВОГО РОКУ" if doc.get("needs_review") else ""
        self.plan_name.config(text=f"{friendly_plan_id(self.current_plan)} • {doc.get('filename','План без джерела')[:90]}{extra}")
        self.plan_count.config(text=f"{len(entries)} уроків. Зміни будуть збережені лише після загальної кнопки «ЗБЕРЕГТИ»")
        self.lesson_row=None
        if entries:
            i=selected if selected is not None and 0<=selected<len(entries) else 0
            self.lessons.selection_set(str(i));self.lesson_selected()

    def lesson_selected(self,_event=None):
        choice=self.lessons.selection()
        if not choice or not self.current_plan:return
        i=int(choice[0]);rows=self.plans[self.current_plan]["lessons"]
        if i>=len(rows):return
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
        if self.lesson_row is None:return
        if not messagebox.askyesno("Видалити",f"Видалити урок №{self.lesson_row+1}? Наступні теми зсунуться.",parent=self):return
        self.plans[self.current_plan]["lessons"].pop(self.lesson_row)
        self._renumber();self.refresh_lessons()

    def move_lesson(self,delta):
        if self.lesson_row is None:return
        entries=self.plans[self.current_plan]["lessons"]
        i=self.lesson_row;j=i+delta
        if j<0 or j>=len(entries):return
        entries[i],entries[j]=entries[j],entries[i]
        self._renumber();self.refresh_lessons(j)

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

    def import_plan(self):
        if not self.current_plan:
            messagebox.showwarning("КТП","Спочатку створіть або виберіть план.",parent=self);return
        path=filedialog.askopenfilename(parent=self,title="Новий календарний план",
                    filetypes=[("Календарні плани Word/CSV","*.docx *.doc *.csv"),("Word DOCX","*.docx"),("Word DOC (через Word)","*.doc"),("CSV","*.csv")])
        if not path:return
        if Path(path).suffix.lower() not in (".docx",".doc",".csv"):
            messagebox.showerror("Формат","Підтримуються DOCX, DOC (через Word) та CSV.",parent=self);return
        target=self.current_plan
        def accept(entries,filename):
            self.plans[target]={"filename":filename,"lessons":entries,"needs_review":False}
            self.current_plan=target
            self.refresh_lessons()
        try:ImportPreview(self,path,accept)
        except Exception as ex:messagebox.showerror("КТП не розпізнано",str(ex),parent=self)

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
        table=ttk.Frame(tab);table.pack(fill="both",expand=True,pady=10)
        self.slots=ttk.Treeview(table,columns=("period","time","numerator","denominator"),show="headings",height=9)
        for col,t,w in (("period","№",55),("time","Час",160),("numerator","ЧИСЕЛЬНИК",300),("denominator","ЗНАМЕННИК",300)):
            self.slots.heading(col,text=t);self.slots.column(col,width=w)
        self.slots.pack(fill="both",expand=True)
        self.slots.bind("<Double-1>",self._open_calendar_for_slot)
        controls=ttk.Frame(tab);controls.pack(fill="x",pady=5)
        ttk.Button(controls,text="Змінити вибраний урок",command=self.edit_slot).pack(side="left",padx=3)
        ttk.Button(controls,text="Імпортувати розклад DOCX/CSV/XLSX",command=self.import_schedule).pack(side="left",padx=3)
        ttk.Button(controls,text="Згенерувати Word-розклад",command=self.export_schedule).pack(side="left",padx=3)
        ttk.Button(controls,text="Згенерувати JPEG-розклад",command=self.export_schedule_jpeg).pack(side="left",padx=3)
        opts=ttk.Frame(tab);opts.pack(fill="x",pady=5)
        self.show_bells=tk.BooleanVar(value=self.cfg.get("print_bells",False))
        self.show_meal=tk.BooleanVar(value=self.cfg.get("print_meal",False))
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

    def edit_slot(self):
        choice=self.slots.selection()
        if not choice:
            messagebox.showinfo("Розклад","Виберіть рядок уроку.",parent=self);return
        day=str(self.dayselect.current());idx=int(choice[0])
        win=tk.Toplevel(self);win.title(f"Урок №{idx+1} • {self.dayselect.get()}")
        win.geometry("500x245");win.transient(self);win.grab_set()
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
        ttk.Label(tab,text="Тільки ці потоки використовує розклад. Для нового класу створіть потік, виберіть КТП та назву курсу Classroom.").pack(anchor="w",pady=8)
        self.streamtree=ttk.Treeview(tab,columns=("name","plan","course"),show="headings")
        for col,title,w in (("name","Клас + предмет / потік",230),("plan","Ідентифікатор КТП",160),("course","Назва у Google Classroom",310)):
            self.streamtree.heading(col,text=title);self.streamtree.column(col,width=w)
        self.streamtree.pack(fill="both",expand=True,pady=4)
        self.streamtree.bind("<ButtonRelease-1>",self._open_inline_on_click)
        self.streamtree.bind("<Double-1>",self._inline_stream_edit)
        ttk.Label(tab,text="Натисніть один раз на КТП або назву Classroom — з’явиться випадаючий список.",
                  foreground="#245471").pack(anchor="w")
        bar=ttk.Frame(tab);bar.pack(fill="x",pady=8)
        for title,fn in [("Додати потік",lambda:self.edit_stream(True)),
                         ("Редагувати потік",lambda:self.edit_stream(False)),("Видалити потік",self.remove_stream)]:
            ttk.Button(bar,text=title,command=fn).pack(side="left",padx=4)
        self.refresh_streams()

    def refresh_streams(self):
        self.streamtree.delete(*self.streamtree.get_children())
        for ix,(stream,info) in enumerate(sorted(self.cfg["course_map"].items())):
            self.streamtree.insert("","end",iid=str(ix),values=(
                stream,friendly_plan_id(info["plan"]),info["course_title"]))
        self.cfg["classroom_course_titles"]=list(dict.fromkeys(
            info["course_title"] for info in self.cfg["course_map"].values()))

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
        editor=ttk.Combobox(self.streamtree,values=options,
                            state="readonly" if is_plan else "normal")
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
        editor.bind("<Return>",lambda _:finish(True))
        editor.bind("<Escape>",lambda _:finish(False))
        editor.bind("<FocusOut>",lambda _:finish(True))
        editor.bind("<<ComboboxSelected>>",lambda _:finish(True))

    def edit_stream(self,new):
        current=None
        if not new:
            ids=self.streamtree.selection()
            if not ids:return
            current=self.streamtree.item(ids[0],"values")[0]
        dlg=tk.Toplevel(self);dlg.title("Клас / предмет / курс Classroom")
        dlg.geometry("670x315");dlg.transient(self);dlg.grab_set()
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
            self.refresh_streams();self.refresh_slots();dlg.destroy()
        ttk.Button(dlg,text="Застосувати",command=apply).pack(pady=15)

    def remove_stream(self):
        selected=self.streamtree.selection()
        if not selected:return
        stream=self.streamtree.item(selected[0],"values")[0]
        if not messagebox.askyesno("Видалити потік",
                f"Видалити {stream}? Всі його уроки в розкладі стануть порожніми.",parent=self):return
        for pairs in self.cfg["days"].values():
            for pair in pairs:
                for i in (0,1):
                    if pair[i]==stream:pair[i]=None
        del self.cfg["course_map"][stream]
        self.refresh_streams();self.refresh_slots()

    def _year_ui(self):
        tab=self.tab_year
        ttk.Label(tab,text="Парність тижнів не зупиняється навіть під час канікул. Дати КТП не визначають урок за розкладом.",
                  font=("Segoe UI",10,"bold")).pack(anchor="w",pady=9)
        fields=ttk.Frame(tab);fields.pack(anchor="w")
        self.dates={}
        for key,label in (("year_start","Початок року (ДД.ММ.РРРР)"),
                          ("year_end","Завершення року"),
                          ("anchor_monday","Опорний понеділок")):
            ttk.Label(fields,text=label,width=37).grid(row=len(self.dates),column=0,sticky="w",pady=5)
            var=tk.StringVar(value=display_ui_date(self.cfg[key]));self.dates[key]=var
            ttk.Entry(fields,textvariable=var,width=21).grid(row=len(self.dates)-1,column=1,sticky="w")
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
        ttk.Entry(semesterbox,textvariable=self.semester2_start,width=17).grid(row=1,column=1,sticky="w",padx=8)
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

    def import_schedule(self):
        from .schedule_io import table_rows,decode_schedule
        path=filedialog.askopenfilename(parent=self,title="Імпортувати розклад",
             filetypes=[("Таблиці","*.docx *.doc *.csv *.xlsx"),
                        ("Word","*.docx *.doc"),("Excel","*.xlsx"),("CSV","*.csv")])
        if not path:return
        try:
            schedule,unknown,found=decode_schedule(table_rows(path),self.cfg)
        except Exception as e:
            messagebox.showerror("Не вдалося імпортувати",str(e),parent=self);return
        if unknown:
            from .schedule_io import _normalize
            dlg=tk.Toplevel(self);dlg.title("Зіставте назви предметів у файлі");dlg.geometry("850x480")
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
            if not chosen["ok"]:return
            schedule,unknown,found=decode_schedule(table_rows(path),self.cfg)
            if unknown:
                messagebox.showerror("Зіставлення","Залишилися невідомі назви:\n"+"\n".join(unknown),parent=self);return
        if messagebox.askyesno("Перегляд імпорту",
            f"Прочитано уроків із номерами: {', '.join(map(str,found))}.\n"
            "ЗАМІНИТИ всі 5 днів розкладу на нову таблицю?\n"
            "Зміни поки будуть лише в редакторі до натискання «ЗБЕРЕГТИ ВСІ ЗМІНИ».",parent=self):
            self.cfg["days"]=schedule
            self.refresh_slots()
            messagebox.showinfo("Імпорт","Розклад у редакторі оновлено. Перегляньте всі дні.",parent=self)

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
        item=self.holidays.identify_row(event.y)
        column=self.holidays.identify_column(event.x)
        if not item or column not in ("#1","#2"):return
        bbox=self.holidays.bbox(item,column)
        if not bbox:return
        x,y,w,h=bbox
        original=self.holidays.set(item,"start" if column=="#1" else "end")
        field=ttk.Entry(self.holidays)
        field.insert(0,original)
        field.place(x=x,y=y,width=w,height=h)
        field.select_range(0,"end");field.focus_set()
        closed=[False]
        def finish(save=False):
            if closed[0]:return
            if not save:closed[0]=True;field.destroy();return
            try:
                iso=parse_ui_date(field.get())
                key="start" if column=="#1" else "end"
                changed=copy.deepcopy(self.cfg["holidays"][int(item)])
                changed[key]=iso
                if changed["end"]<changed["start"]:
                    raise ValueError("Кінець канікул раніше початку.")
            except ValueError as err:
                messagebox.showwarning("Дата канікул",str(err),parent=self)
                field.focus_set();return
            closed[0]=True
            self.cfg["holidays"][int(item)]=changed
            field.destroy()
            self.refresh_holidays()
            self.holidays.selection_set(item)
        field.bind("<Return>",lambda _:finish(True))
        field.bind("<Escape>",lambda _:finish(False))
        field.bind("<FocusOut>",lambda _:finish(True))

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

    def add_holiday(self):
        a=simpledialog.askstring("Канікули","Початок у форматі ДД.ММ.РРРР:",parent=self)
        if not a:return
        b=simpledialog.askstring("Канікули","Кінець у форматі ДД.ММ.РРРР:",parent=self)
        if not b:return
        try:
            a,b=parse_ui_date(a),parse_ui_date(b)
            if b<a:
                raise ValueError("Кінець раніше початку")
        except ValueError as exc:messagebox.showerror("Канікули",str(exc),parent=self);return
        self.cfg["holidays"].append({"start":a,"end":b});self.refresh_holidays()

    def del_holiday(self):
        selected=self.holidays.selection()
        if not selected:return
        self.cfg["holidays"].pop(int(selected[0]))
        self.refresh_holidays()

    def save(self):
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
        errors=validate_working(self.cfg,self.plans)
        # Unconfirmed new year can be saved so that teacher has an editable draft; blank plans are still marked.
        errors=[e for e in errors if not (e.startswith("Порожній КТП") and
                              any(p.get("needs_review") for p in self.plans.values()))]
        if errors:
            messagebox.showerror("Помилки у даних","Виправте перед збереженням:\n"+"\n".join(errors[:20]),parent=self);return
        if self.cfg==self.original_cfg and self.plans==self.original_plans:
            messagebox.showinfo("Дані","Змін немає.",parent=self);return
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
        message=("Зберегти перевірені зміни розкладу/КТП/року та резервну копію?\\n"
                 "Існуючі чернетки Google НІКОЛИ не видаляються.")
        if educational_changes:
            message+="\\nРаніше перевірені Word будуть позначені як такі, що потребують повторної перевірки."
        if reset:
            message+="\\nНовий навчальний рік: зіставлення Google-курсів буде очищено."
        if not messagebox.askyesno("Збереження",message,parent=self):return
        state=self.parent.state
        try:
            backup=persist(self.cfg,self.plans,state,"Редагування КТП і розкладу у програмі")
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
            messagebox.showerror("Помилка збереження",str(ex),parent=self);return
        self.original_cfg=copy.deepcopy(self.cfg);self.original_plans=copy.deepcopy(self.plans)
        self._is_new_year=False
        messagebox.showinfo("Збережено",
            "Усі зміни збережено локально.\nРезервна копія:\n"+str(backup)+
            "\n\nВсі матеріали Google Classroom залишилися без змін.",parent=self)
        self.destroy()
