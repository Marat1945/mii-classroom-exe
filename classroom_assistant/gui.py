"""Вікно локального клієнта. Нічого самовільно не публікує."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import shutil
from dataclasses import replace as dataclass_replace
from datetime import date,timedelta,datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from tkinter import font as tkfont
from .engine import read_json, write_json, read_state, save_state, day_lessons, build_calendar, week_phase, is_holiday, safe_name, word_path, html_classroom_text, is_task_lesson, DATA, ROOT
from .documents import create_word
from .material_library import (parallel_matches,add_document,attach_document,find_for_lesson,signature_key,signature,stream_subject,check_real_docx,copy_for_lesson)
from .attachments import add_attachments, files_for_lesson, copy_attachments, remove_attachment
from .window_ui import maximize_work_window, fit_work_window
from .ui_kit import AccentButton, FlowRow
from .hotkeys import install_hotkeys
from .theme import apply_theme, make_banner, add_rivets
from . import connectivity
from .history import History, describe_change
from .datepicker import pick_date
from . import air_alerts, browser_downloads, data_tools, day_facts, file_match, lecture_inbox, wheel
from . import app_icon
from .alert_ui import AlertPanel, show_alert_setup
from .calendar_leaf import CalendarLeaf
from .toast import show_toast
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    WindowBase = TkinterDnD.Tk
except ImportError:
    DND_FILES=None
    WindowBase=tk.Tk


def display_date(value):
    return date.fromisoformat(value).strftime("%d.%m.%Y")

def parse_date(value):
    value=value.strip()
    if "." in value:return datetime.strptime(value,"%d.%m.%Y").date()
    return date.fromisoformat(value)

def topic_template(text,lesson):
    """Перетворюємо особисті дати/тему/ДЗ в параметризований шаблон."""
    ddmm=lesson.day[8:10]+"."+lesson.day[5:7]
    text=text.replace(lesson.topic,"{topic}").replace(lesson.homework,"{homework}") if lesson.homework else text.replace(lesson.topic,"{topic}")
    text=text.replace(ddmm,"{date}")
    return text

def render_template(text,lesson):
    ddmm=lesson.day[8:10]+"."+lesson.day[5:7]
    out=str(text)
    for key,value in [("{date}",ddmm),("{topic}",lesson.topic),("{homework}",lesson.homework or "не зазначено у КТП"),("{stream}",lesson.stream)]:
        out=out.replace(key,value)
    return out


# Ці ключі стану не відкочуються кнопкою «Назад»: чернетки Google вже створено, курси — з Google.
NON_UNDOABLE=("drafts","drafts_removed","course_ids","classroom_order","chatgpt_url","autopaste","autosend",
              "autopaste_delay","column_order","column_widths","blank_offer_37","watch_downloads","watch_inbox","inbox_done")

WEEKDAYS_UA=("ПОНЕДІЛОК","ВІВТОРОК","СЕРЕДА","ЧЕТВЕР","П’ЯТНИЦЯ","СУБОТА","НЕДІЛЯ")

def weekday_ua(value):
    return WEEKDAYS_UA[parse_date(value).weekday()]

class MainApp(WindowBase):
    def __init__(self):
        super().__init__()
        self.title("Помічник учителя Classroom")
        self.geometry("1250x770")
        self.minsize(1060,630)
        maximize_work_window(self)
        self.cfg=read_json("Налаштування.json")
        self.state=read_state()
        self.escape_closes=False
        apply_theme(self)
        app_icon.set_app_id()
        app_icon.apply(self)                      # логотип замість стандартної пір'їнки Tk
        install_hotkeys(self)
        self.header=make_banner(self,"Помічник учителя Classroom",
                    "розклад  •  календарні плани  •  лекції через ChatGPT  •  чернетки Google Classroom",
                    author="Розробник програми — вчитель історії Пасічник Іван Олегович",
                    animate=not os.environ.get("POMICHNYK_NO_OFFERS"))
        self.header.pack(fill="x",pady=(0,6))
        self._sync_running=False;self._sync_again=False;self._last_sync_ts=0.0
        self._inbox_busy=False;self._last_matched_sources=set()
        self.rows=[]
        self.google_courses=[]
        # Дані лише для перегляду, не змінюють локальні КТП і Google-чернетки.
        self.remote_classroom_entries={}
        self._plans_sig=None;self._plans_digest="";self._plans_store={}
        self._build()
        add_rivets(self)
        self._register_window_drop()
        self._refresh_google_button()
        # прилад на шапці: зв'язок з інтернетом (стрілка й лампочка); у тестах мережу не чіпаємо
        self.alerts=air_alerts.Monitor(lambda:air_alerts.load_settings(DATA),DATA)
        self.facts=day_facts.Loader(DATA,network=not os.environ.get("POMICHNYK_NO_OFFERS"))
        self.net=connectivity.Monitor()
        if not os.environ.get("POMICHNYK_NO_OFFERS"):
            self.net.start()
            self._net_job=self.after(1200,self._net_poll)
            if air_alerts.load_settings(DATA)["key"]:
                self.alerts.start()
        self._alert_job=self.after(500,self._alert_poll)
        self._facts_job=self.after(1500,self._facts_poll)
        self.update_day()
        self.history=History()
        self.history.reset(self._history_snapshot())
        self.history_undo=self.undo;self.history_redo=self.redo       # Ctrl+Z / Ctrl+Y
        self._poll_job=self.after(900,self._history_poll)
        # Одразу після запуску підтягнути актуальний стан Classroom (без вікна входу).
        self.after(1500,lambda:self.sync_classroom(interactive=False))
        self.after(2600,self._clean_start_once)
        self.protocol("WM_DELETE_WINDOW",self.on_close)
        self.bind("<FocusIn>",self._on_focus_in,add="+")
        self._watcher=lecture_inbox.InboxWatcher(self.state.get("inbox_done"))
        self._watch_since_ns=time.time_ns()-6*3600*10**9
        self._inbox_job=self.after(2500,self._inbox_poll)

    def _build(self):
        outer=ttk.Frame(self,padding=12)
        outer.pack(fill="both",expand=True)
        hdr=FlowRow(outer);hdr.pack(fill="x",pady=(0,8))
        left=right=hdr           # один рядок: на вузькому екрані зайве саме переходить на наступний
        hdr.add(ttk.Label(hdr,text="Дата (ДД.ММ.РРРР):"),padx=3)
        self.datevar=tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self._date_refresh_id=None
        self.datevar.trace_add("write",self._on_date_text_change)
        date_entry=ttk.Entry(hdr,width=14,textvariable=self.datevar)
        hdr.add(date_entry,padx=4)
        self.date_entry=date_entry
        hdr.add(ttk.Button(hdr,text="📅",width=3,command=self.pick_day),padx=2)
        date_entry.bind("<Return>",lambda _:self.update_day())
        self.weekday=ttk.Label(hdr,text="",font=("Segoe UI",11,"bold"),foreground="#245A7C",width=13)
        hdr.add(self.weekday,padx=6)
        for widget in (date_entry,self.weekday):        # коліщатко над датою: вниз = пізніше, Shift/Ctrl = тиждень
            wheel.bind_steps(widget,lambda step,big:self.shift(step*(7 if big else 1)))
        hdr.add(ttk.Button(hdr,text="←",width=4,command=lambda:self.shift(-1)),padx=1)
        hdr.add(ttk.Button(hdr,text="→",width=4,command=lambda:self.shift(1)),padx=1)
        hdr.add(ttk.Button(hdr,text="ПОЧАТКОВЕ НАЛАШТУВАННЯ",command=self.setup_dialog),padx=6)
        self.phase=ttk.Label(hdr,text="",font=("Segoe UI",11,"bold"))
        hdr.add(self.phase,padx=8)
        self.google_button=ttk.Button(hdr,text="Підключити Google",command=self.connect_google)
        hdr.add(self.google_button,padx=3)
        self.undo_button=ttk.Button(hdr,text="↶ Назад",command=self.undo,state="disabled")
        hdr.add(self.undo_button,padx=2,right=True)
        self.redo_button=ttk.Button(hdr,text="↷ Вперед",command=self.redo,state="disabled")
        hdr.add(self.redo_button,padx=2,right=True)
        hdr.add(ttk.Button(hdr,text="📄 Зразки документів",command=self.samples_dialog),padx=3,right=True)
        hdr.add(ttk.Button(hdr,text="🗂 Мої дані",command=self.data_dialog),padx=3,right=True)

        cols=("№","Час","Потік","Курс Classroom","Тема","КТП","Стан")
        self.grid_columns=cols
        table_frame=ttk.Frame(outer);table_frame.pack(fill="both",expand=True)
        self.grid=ttk.Treeview(table_frame,columns=cols,show="headings",
                                selectmode="extended",height=5)
        widths=(43,100,140,160,510,60,150)
        for col,width in zip(cols,widths):
            self.grid.heading(col,text=col)
            self.grid.column(col,width=width,minwidth=42,anchor="w",stretch=(col=="Тема"))
        self.grid.tag_configure("ready",background="#DCE8B8")            # Word є, чернетки ще немає: готово до створення
        self._fit_job=None;self._resize_start=False
        self.grid.bind("<Configure>",lambda _e:self._schedule_fit(),add="+")
        sy=ttk.Scrollbar(table_frame,orient="vertical",command=self.grid.yview)
        sx=ttk.Scrollbar(table_frame,orient="horizontal",command=self.grid.xview)
        self.grid.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.grid.grid(row=0,column=0,sticky="nsew")
        sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        self.grid.bind("<<TreeviewSelect>>",lambda _:self.select())
        self.grid.bind("<Button-3>",self._open_lesson_menu)
        # Enter на виділеному рядку = «Створити ЧЕРНЕТКУ в Classroom» (з підтвердженням).
        self.grid.bind("<Return>",self._enter_creates_draft)
        self.grid.bind("<KP_Enter>",self._enter_creates_draft)
        self.background_menu=self._open_day_menu
        self.grid.bind("<Control-c>",lambda e:self.copy_selected_lessons_as_text())
        self.grid.bind("<Control-a>",lambda e:(self._select_all_rows(announce=False),"break")[1])
        self.grid.bind("<Delete>",lambda e:self.remove_selected_local_materials())
        self.grid.bind("<ButtonPress-1>",self._column_drag_start,add="+")
        self.grid.bind("<ButtonRelease-1>",self._column_drag_end,add="+")
        preferred=self.state.get("column_order")
        if (isinstance(preferred,list) and len(preferred)==len(cols)
                and set(preferred)==set(cols)):
            self.grid.configure(displaycolumns=preferred)
        else:self.grid.configure(displaycolumns=cols)
        self._column_start=None
        if DND_FILES:
            self.grid.drop_target_register(DND_FILES)
            self.grid.tag_configure("file-drop-hover",
                                    background="#FFE49A",foreground="#26364D")
            self._hover_lesson_item=None
            self.grid.dnd_bind("<<DropEnter>>",self._highlight_drop_lesson)
            self.grid.dnd_bind("<<DropPosition>>",self._highlight_drop_lesson)
            self.grid.dnd_bind("<<DropLeave>>",self._clear_drop_lesson)
            self.grid.dnd_bind("<<Drop>>",self._drop_on_lesson)

        actions=FlowRow(outer);actions.pack(fill="x",pady=9)
        actions.add(AccentButton(actions,"✨ Word-лекція через мій ChatGPT",self.chatgpt_word),padx=4)
        actions.add(AccentButton(actions,"✨ Лекції GPT на весь день",self.chatgpt_batch,
                                 color="#2E8B57",hover="#3AA36B"),padx=4)
        for title,callback in [
            ("Word: заготовка",lambda:self.make_word(False)),
            ("Вибрати готовий Word",self.choose_docx),
            ("Word і картинки пачкою…",self.choose_lecture_files),
            ("Бібліотека Word",self.library_dialog),
            ("Папка Word",self.open_folder),
            ("Автоприйом файлів GPT…",self.open_inbox),
        ]:
            actions.add(ttk.Button(actions,text=title,command=callback))
        actions2=FlowRow(outer);actions2.pack(fill="x",pady=2)
        actions2.add(ttk.Button(actions2,text="Зіставити курси",command=self.map_courses))
        actions2.add(ttk.Button(actions2,text="Зберегти шаблон паралелі",command=self.save_parallel_description))
        self.assignment=tk.BooleanVar(value=False)
        actions2.add(ttk.Checkbutton(actions2,text="Усе як завдання (інакше — за темою)",variable=self.assignment),padx=8)
        self.watch_var=tk.BooleanVar(value=bool(self.state.get("watch_downloads",True)))
        actions2.add(ttk.Checkbutton(actions2,text="Стежити за «Завантаженнями»",
                                     variable=self.watch_var,command=self._set_watch),padx=8)
        actions2.add(ttk.Button(actions2,text="Створити ЧЕРНЕТКУ в Classroom",command=self.draft),right=True)
        actions3=ttk.Frame(outer);actions3.pack(fill="x",pady=3)
        self.batch_drafts_button=ttk.Button(
            actions3,text="СТВОРИТИ ЧЕРНЕТКИ ДЛЯ ВСІХ УРОКІВ ЦЬОГО ДНЯ",
            command=self.batch_drafts)
        self.batch_drafts_button.pack(side="right",padx=6)
        self._batch_drafts_running=False
        ttk.Button(actions3,text="РЕДАКТОР КТП, РОЗКЛАДУ І НАВЧАЛЬНОГО РОКУ",command=self.edit_academic_year).pack(side="left",padx=3)
        ttk.Button(actions3,text="❓ ДОВІДКА",command=self.show_help).pack(side="right",padx=4)
        ttk.Button(actions3,text="МІЙ CLASSROOM — ПЕРЕГЛЯД",
                   command=self.view_classroom).pack(side="right",padx=4)
        ttk.Label(actions3,text="Плани • розклад • бібліотека • дзвоники • допомога").pack(side="left",padx=10)
        middle=ttk.Frame(outer);middle.pack(fill="both",expand=True)
        side=ttk.Frame(middle);side.pack(side="right",fill="y",padx=(12,0))      # праворуч: тривога й листочок календаря
        left=ttk.Frame(middle);left.pack(side="left",fill="both",expand=True)     # ліворуч: повідомлення (вужче, ніж було)
        self.alert_panel=AlertPanel(side,self.open_alert_setup)
        self.alert_panel.pack(side="left",padx=(0,10),pady=(10,0))
        self.leaf=CalendarLeaf(side)
        self.leaf.pack(side="left",pady=(10,0))
        ttk.Label(left,text="Повідомлення для Classroom (можна редагувати тут перед створенням чернетки):").pack(anchor="w",pady=(10,1))
        self.desc=tk.Text(left,height=4,wrap="word",font=("Segoe UI",10))
        self.desc.pack(fill="both",expand=True)
        self.desc.bind("<Button-3>",self._description_context_menu)
        self.attachment_toolbar=ttk.Frame(left)
        self.attachment_toolbar.pack(fill="x",pady=(5,2))
        ttk.Button(self.attachment_toolbar,text="📎 Додати файли до Classroom",
                   command=self.choose_attachments).pack(side="left",padx=(0,10))
        self.drop_hint=ttk.Label(self.attachment_toolbar,
              text=("Перетягніть файли сюди або в поле опису" if DND_FILES else
                    "Для прикріплення натисніть «Додати файли»"),
              foreground="#245A7C")
        self.drop_hint.pack(side="left")
        self.attachment_bar=ttk.Frame(left)
        self.attachment_bar.pack(fill="x",pady=(2,4))
        self._preview_images=[]
        if DND_FILES:
            self._desc_original_bg=self.desc.cget("background")
            normal_style=ttk.Style(self)
            normal_style.configure("TeacherHoverDrop.TLabel",
                                    background="#FFE49A",foreground="#173657")
            for widget in (self.desc,self.drop_hint,self.attachment_bar,self.attachment_toolbar):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>",self._highlight_description_drop)
                widget.dnd_bind("<<DropPosition>>",self._highlight_description_drop)
                widget.dnd_bind("<<DropLeave>>",self._clear_description_drop)
                widget.dnd_bind("<<Drop>>",self._receive_files)
        bottom=ttk.Frame(outer);bottom.pack(fill="x",pady=(7,0))
        AccentButton(bottom,"⟲ СКИНУТИ ВСЕ",self.reset_everything,color="#C62828",
                     hover="#E53935").pack(side="right")
        ttk.Button(bottom,text="↩ Відновити останню копію",
                   command=self.restore_last_backup).pack(side="right",padx=8)
        bottom.pack_forget()                       # нижній ряд кнопок пакуємо першим (унизу): він не зникне на низьких екранах
        bottom.pack(side="bottom",fill="x",pady=(7,0),before=middle)
        self.foot=ttk.Label(bottom,text="Без авторизації Google програма працює локально. Публікацію заборонено.",foreground="#46576b")
        self.foot.pack(side="left",fill="x",expand=True)

    def _on_date_text_change(self,*_unused):
        """Відобразити уроки після введення ПОВНОЇ правильної дати."""
        pending=getattr(self,"_date_refresh_id",None)
        if pending is not None:
            self.after_cancel(pending)
        def refresh():
            self._date_refresh_id=None
            try:day=parse_date(self.datevar.get())
            except (ValueError,TypeError):return
            if day.year<2020 or day.year>2100:return
            if hasattr(self,"grid"):
                self.update_day()
        self._date_refresh_id=self.after(350,refresh)

    def shift(self,amount):
        try:d=parse_date(self.datevar.get())+timedelta(days=amount)
        except ValueError:d=date.today()
        self.datevar.set(d.strftime("%d.%m.%Y"))
        self.update_day()

    def update_day(self):
        prior=self.selected().unique_key if getattr(self,"rows",None) and self.grid.selection() else None
        try:
            day=parse_date(self.datevar.get())
            self.rows=day_lessons(day.isoformat(),self.cfg)
        except Exception as ex:
            messagebox.showerror("Дата або КТП",str(ex));return
        if DND_FILES:self._clear_drop_lesson()
        for item in self.grid.get_children():self.grid.delete(item)
        off=is_holiday(day,self.cfg)
        self.weekday.configure(text=WEEKDAYS_UA[day.weekday()])
        self.phase.configure(text=f"{week_phase(day,self.cfg).upper()}"+(" • КАНІКУЛИ: УРОКІВ НЕМАЄ" if off else ""))
        for k,row in enumerate(self.rows):
            item=self.state.get("drafts",{}).get(row.unique_key)
            doc=self.state.get("files",{}).get(row.unique_key,{})
            status=("Створено в Google" if item else
                    ("Готовий Word" if doc.get("validated") else
                     ("Word потребує перевірки" if doc.get("complete") else
                      ("Word заготовка" if doc else
                       ("Без Word" if row.status=="готово" else row.status)))))
            if doc.get("from") and not item and status in ("Готовий Word","Word потребує перевірки"):
                status+=f" · {'наперед ' if doc.get('ahead') else ''}з {doc['from']}"      # Word від паралелі
            adjusted=self.effective_lesson(row)
            if row.unique_key in self.state.get("lesson_models",{}):
                status="Зразок із паралелі · "+status
            remote=self._remote_classroom_status(adjusted)
            if item and not remote:
                cid=str(self.state.get("course_ids",{}).get(adjusted.course_title,""))
                created=float(item.get("created_at",0) or 0) if isinstance(item,dict) else 0.0
                if created and time.time()-created<150:
                    status="Створено в Google · перевіряю Classroom…"            # щойно створено
                elif cid in self.remote_classroom_entries and self._last_sync_ts>created:
                    status="Створено в Google · у Classroom не знайдено"          # перевірено, але не бачу
            if remote:
                # Не показувати «чернетка», якщо Google повідомляє PUBLISHED!
                document_status=(" • Word перевірено" if doc.get("validated") else "")
                status=remote+document_status
            ready=bool(doc.get("complete") and not item and not remote and row.status=="готово")
            self.grid.insert("", "end",iid=str(k),values=(row.period,f"{row.begin}–{row.end}",
                     row.stream,row.course_title,adjusted.topic,row.lesson_number,status),
                     tags=(("ready",) if ready else ()))
        self._schedule_fit(0)
        self._refresh_leaf()
        self.desc.delete("1.0","end")
        if self.rows:
            chosen=next((str(i) for i,x in enumerate(self.rows) if x.unique_key==prior),"0")
            self.grid.selection_set(chosen)
            self.grid.focus(chosen)
            self.select()
        else:self.foot.config(text="На обрану дату уроків немає (вихідний або канікули).")

    def _remote_classroom_status(self,lesson):
        """Ознака тільки після синхронізації та точного збігу теми + дати."""
        cid=str(self.state.get("course_ids",{}).get(lesson.course_title,""))
        if not cid or cid not in self.remote_classroom_entries:return ""
        from .classroom_archive import compatible_classroom_title
        own=self.state.get("drafts",{}).get(lesson.unique_key,{})
        own_id=str(own.get("id") or "")
        matched=[row for row in self.remote_classroom_entries[cid]
                 if (own_id and row["id"]==own_id)
                 or compatible_classroom_title(lesson,row)]
        if not matched:return ""
        selected=next((x for x in matched if x["state"]=="PUBLISHED"),
                      next((x for x in matched if x["state"]=="SCHEDULED"),matched[0]))
        what={"Завдання":"Завдання","Матеріал":"Матеріал",
              "Оголошення":"Оголошення"}.get(selected["type"],"Запис")
        if selected["state"]=="PUBLISHED":
            return f"{what} ОПУБЛІКОВАНО в Classroom"
        if selected["state"]=="SCHEDULED":
            return f"{what} ЗАПЛАНОВАНО в Classroom"
        return f"{what} — чернетка в Classroom"

    def view_classroom(self):
        from .classroom_browser import show_classroom_viewer
        show_classroom_viewer(self)

    def selected(self):
        selection=self.grid.selection()
        return self.rows[int(selection[0])] if selection else None

    def effective_lesson(self,lesson):
        model=self.state.get("lesson_models",{}).get(lesson.unique_key)
        if not model:
            return lesson
        return dataclass_replace(lesson,topic=model.get("topic",lesson.topic),
                                 homework=model.get("homework",lesson.homework))

    def select(self):
        original=self.selected()
        if not original:return
        lesson=self.effective_lesson(original)
        self.desc.delete("1.0","end")
        description=self.state.get("description_overrides",{}).get(lesson.unique_key)
        if description is None:
            templ=self.state.get("parallel_templates",{}).get(signature_key(lesson,self.cfg))
            description=render_template(templ,lesson) if templ is not None else html_classroom_text(lesson,asynchronous=True,video=True)
        self.desc.insert("1.0",description)
        self.desc.yview_moveto(0)
        self.refresh_attachment_previews()
        f=self.state.get("files",{}).get(lesson.unique_key,{})
        status=f"Обрано: {lesson.stream}, урок КТП №{lesson.lesson_number}. Джерело: {lesson.source_file}"
        if f: status+=f" | Word: {f['path']} | Перевірено: {f.get('validated',False)}"
        self.foot.config(text=status[:240])

    def worker(self,task,on_success):
        self.config(cursor="watch")
        def run():
            try:
                result=task()
                self.after(0,lambda:self.finish_worker(on_success,result,None))
            except Exception as ex:
                text=str(ex)
                self.after(0,lambda:self.finish_worker(on_success,None,text))
        threading.Thread(target=run,daemon=True).start()

    def finish_worker(self,callback,result,error):
        self.config(cursor="")
        if error:messagebox.showerror("Помилка",error)
        else:callback(result)

    def _parallel(self,lesson):
        return parallel_matches(lesson,self.cfg)

    def _attach_from_master(self,master,lesson,origin,replace_existing=False):
        selected=self._parallel(lesson)
        item=add_document(master,lesson,self.cfg,origin=origin)
        attached=attach_document(item,selected,self.state,replace_existing=replace_existing,primary=lesson)
        save_state(self.state)
        self.update_day()
        return attached

    def _parallel_prompt(self,lesson,verb):
        targets=self._parallel(lesson)
        lines=[f"• {x.stream} — {display_date(x.day)} (№{x.lesson_number})" for x in targets]
        shown="\n".join(lines[:18])
        if len(lines)>18:shown+=f"\n... ще {len(lines)-18} уроків"
        return messagebox.askyesno("Єдина лекція для паралелі",
            f"{verb}\n\nАвтоматична прив'язка до сумісної паралелі:\n{shown}\n\n"
            "Перевірте, що лекція повна, тема правильна, а дати/Д/з оновлено.\n"
            "Для відмінної програми або кількості годин перенесення НЕ виконується.\n"
            "Google Classroom НЕ буде опубліковано автоматично.")

    def make_word(self,with_ai):
        lesson=self.selected()
        if not lesson:return
        if lesson.status!="готово":
            messagebox.showerror("КТП",self._not_ready_text(lesson));return
        if with_ai:
            reusable=find_for_lesson(lesson,self.cfg)
            if reusable is not None:
                if messagebox.askyesno("Економія API","У бібліотеці вже є відповідна лекція.\n\nВикористати її без платного AI-запиту?"):
                    attached=attach_document(reusable,self._parallel(lesson),self.state)
                    save_state(self.state);self.update_day()
                    messagebox.showinfo("Безкоштовне повторне використання",f"Прив'язано уроків: {len(attached)}.")
                    return
            if not self._parallel_prompt(lesson,"Створити ОДНУ платну AI-лекцію?"):
                return
        else:
            if not messagebox.askyesno("Word-заготовка","Створити ТІЛЬКИ порожню заготовку? Учням її надсилати НЕ можна."):
                return
        destination=word_path(lesson)
        def task():
            material=None
            if with_ai:
                from .ai_writer import generate_full_lesson
                material=generate_full_lesson(lesson,self.cfg.get("ai_model","gpt-5"))
            return create_word(lesson,destination,material)
        def done(path):
            if with_ai:
                attached=self._attach_from_master(path,lesson,"AI")
                messagebox.showinfo("AI-лекція готова",
                    f"Лекцію збережено в бібліотеці й автоматично прив'язано до {len(attached)} сумісних уроків.\n"
                    "У Classroom поки нічого не створено. Перевірте всі дати, історичні факти й Д/з "
                    "перед створенням чернеток.")
            else:
                self.state.setdefault("files",{})[lesson.unique_key]={
                    "path":str(path),"validated":False,"complete":False}
                save_state(self.state);self.update_day()
                messagebox.showwarning("Word-заготовка","Це НЕ готова лекція. Не надсилайте її учням.")
        self.worker(task,done)

    def batch_ai(self,only=None,force=False):
        """Платна генерація. force=True — уроки, обрані явно у вікні «на весь день», генеруються навіть за наявного Word."""
        lessons=[i for i in (self.rows if only is None else only) if i.status=="готово"]
        if not lessons:
            messagebox.showinfo("Розклад","На цю дату немає уроків із перевіреними КТП.");return
        pending=[]
        seen=set()
        for lesson in lessons:
            key=(signature_key(lesson,self.cfg),lesson.lesson_number,
                 lesson.topic.casefold().strip())
            if (not force and lesson.unique_key in self.state.get("files",{})) or key in seen:
                continue
            seen.add(key);pending.append(lesson)
        if not pending:
            messagebox.showinfo("Економія API","Усі обрані уроки вже мають Word. Повторної оплати не потрібно.")
            return
        if not messagebox.askyesno("Пакетна генерація",
              (f"Буде виконано до {len(pending)} ПЛАТНИХ AI-запитів; наявний Word цих уроків буде замінено новим."
               if force else
               f"Максимум {len(pending)} AI-запитів. Спершу програма повторно використає те, "
               "що є у бібліотеці.")
              +"\n\nПісля генерації одна лекція підійде тільки "
              "сумісним класам із тією ж темою, програмою та годинами.\nПродовжити?"):
            return
        def task():
            made=[]
            from .ai_writer import generate_full_lesson
            for lesson in pending:
                existing=None if force else find_for_lesson(lesson,self.cfg)
                if existing is not None:
                    made.append((lesson,existing))
                    continue
                material=generate_full_lesson(lesson,self.cfg.get("ai_model","gpt-5"))
                destination=word_path(lesson)
                path=create_word(lesson,destination,material)
                item=add_document(path,lesson,self.cfg,origin="AI")
                made.append((lesson,item))
            return made
        def done(items):
            n=0
            for lesson,item in items:
                n+=len(attach_document(item,self._parallel(lesson),self.state,replace_existing=force,primary=lesson))
            save_state(self.state);self.update_day()
            show_toast(self,f"✓ AI-лекції готові: груп — {len(items)}, прив'язано до уроків — {n} · перевірте Word",3400)
            self.request_sync(900)
        self.worker(task,done)

    # ----- Лекції через власний ChatGPT учителя (безкоштовно, без API) -----
    def chatgpt_word(self):
        lesson=self.selected()
        if not lesson:return
        if lesson.status!="готово":
            messagebox.showerror("КТП",self._not_ready_text(lesson));return
        current=self.state.get("files",{}).get(lesson.unique_key,{})
        replace=False
        if current.get("complete") and Path(current.get("path","")).is_file():
            if not messagebox.askyesno("Word уже є",
                    "Для цього уроку вже є готовий Word.\n\n"
                    "Підготувати НОВУ лекцію через ChatGPT і замінити нею поточний Word "
                    "для цього уроку та сумісної паралелі? Уроки з чернеткою Google не змінюються."):
                return
            replace=True
        else:
            reusable=find_for_lesson(lesson,self.cfg)
            if reusable is not None and messagebox.askyesno("Готова лекція є",
                    "У бібліотеці вже є відповідна лекція.\n\nВикористати її замість нової?"):
                attached=attach_document(reusable,self._parallel(lesson),self.state)
                save_state(self.state);self.update_day()
                messagebox.showinfo("Повторне використання",f"Прив'язано уроків: {len(attached)}.")
                return
            if not self._parallel_prompt(lesson,"Підготувати ОДНУ лекцію через ваш ChatGPT (безкоштовно)?"):
                return
        from .chatgpt_ui import open_chatgpt_dialog
        open_chatgpt_dialog(self,[lesson],batch=False,replace_existing=replace)

    def chatgpt_batch(self,only=None):
        """Лекції на ВЕСЬ ДЕНЬ (або лише для виділених уроків): завдання вчителя виконується для всіх вибраних уроків.

        Одна задача на групу паралелей (однакова тема того ж дня — «8-Б-В-Г ВІ»). Уроки, які вже мають Word
        (навіть локальний, якого нема в Classroom), НЕ пропускаються: у вікні вони позначені, а нові файли їх замінять.
        """
        source=self.rows if not only else only
        lessons=[i for i in source if i.status=="готово"]
        if not lessons:
            messagebox.showinfo("Розклад","Серед обраних уроків немає тих, що мають перевірені КТП.");return
        groups=[];seen=set()
        for lesson in lessons:
            key=(signature_key(lesson,self.cfg),lesson.lesson_number,lesson.topic.casefold().strip())
            if key in seen:continue
            seen.add(key);groups.append(lesson)
        from .chatgpt_ui import open_day_dialog
        open_day_dialog(self,groups)

    def save_chatgpt_lecture(self,lesson,material,replace_existing=False):
        """Word із відповіді ChatGPT → бібліотека → сумісна паралель. Google не змінюється."""
        destination=word_path(lesson)
        path=create_word(lesson,destination,material)
        attached=self._attach_from_master(path,lesson,"ChatGPT",
                                          replace_existing=replace_existing)
        return path,attached

    def save_dropped_lecture(self,lesson,docx_path,extra_files=(),replace_existing=False):
        """Готовий Word від ChatGPT + інфографіка → бібліотека → паралелі → вкладення."""
        check_real_docx(docx_path)
        destination=word_path(lesson)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if Path(docx_path).resolve()!=destination.resolve():
            shutil.copy2(docx_path,destination)
        attached=self._attach_from_master(destination,lesson,"ChatGPT (файл)",
                                          replace_existing=replace_existing)
        problems=[]
        for target in attached:
            if not extra_files:break
            try:add_attachments(self.state,target.unique_key,list(extra_files))
            except Exception as ex:problems.append(str(ex))
        if extra_files:
            save_state(self.state);self.refresh_attachment_previews()
        return destination,attached,"; ".join(dict.fromkeys(problems))

    def choose_docx(self):
        lesson=self.selected()
        if not lesson:return
        path=filedialog.askopenfilename(title="Виберіть ГОТОВИЙ ПОВНИЙ Word (.docx)",
                                        filetypes=[("Word","*.docx")])
        if not path:return
        try:check_real_docx(path)
        except Exception as ex:
            messagebox.showerror("Неправильний Word",str(ex));return
        if not self._parallel_prompt(lesson,"Вибрано ваш готовий Word. Вважаєте його перевіреним і бажаєте прив'язати?"):
            return
        try:targets=self._attach_from_master(path,lesson,"власний Word",replace_existing=True)
        except Exception as ex:messagebox.showerror("Word",str(ex));return
        messagebox.showinfo("Word готовий",
            f"Документ прийнято в бібліотеку.\nПрив'язано до {len(targets)} уроків.\n"
            "Повторно натискати «Підтвердити Word» НЕ потрібно. "
            "Classroom не змінено.")

    def copy_selected_lessons_as_text(self):
        """Ctrl+C: дані уроків у буфер як таблиця з табуляціями."""
        items=self.grid.selection()
        if not items:return "break"
        lines=["\t".join(str(v) for v in self.grid.item(item,"values"))
               for item in sorted(items,key=int)]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        return "break"

    def remove_selected_local_materials(self):
        """Del не видаляє сам урок у розкладі або публікацію Classroom."""
        chosen=self._selected_rows()
        if not chosen:return "break"
        if not messagebox.askyesno("Прибрати локальні матеріали",
            f"Очистити ЛОКАЛЬНІ Word, текстові правки й вкладення "
            f"для {len(chosen)} виділених уроків?\n"
            "Публікації Google, розклад та КТП не змінюються. "
            "Фізичні файли Word на диску не видаляються.",
            parent=self):
            return "break"
        for row in chosen:
            key=row.unique_key
            for part in ("files","description_overrides",
                         "lesson_models","attachments"):
                self.state.get(part,{}).pop(key,None)
        save_state(self.state)
        self.update_day()
        messagebox.showinfo("Видалено локально",
             "Посилання на локальні матеріали прибрано. "
             "Записи Google не змінено.",parent=self)
        return "break"

    def _column_drag_start(self,event):
        self._column_start=None
        region=self.grid.identify_region(event.x,event.y)
        self._resize_start=(region=="separator")                    # тягнуть межу стовпця — запам'ятаємо ширину
        if region=="heading":
            self._column_start=(self.grid.identify_column(event.x),event.x)

    def _column_drag_end(self,event):
        if self._resize_start:
            self._resize_start=False
            try:
                self.state["column_widths"]={c:int(self.grid.column(c,"width")) for c in self.grid_columns}
                save_state(self.state)
            except tk.TclError:pass
            return
        start=self._column_start
        self._column_start=None
        if not start or self.grid.identify_region(event.x,event.y)!="heading":return
        source,index_x=start
        if abs(event.x-index_x)<14:                                  # просто клац по заголовку — виділити весь день
            self._select_all_rows()
            return
        destination=self.grid.identify_column(event.x)
        if destination==source:return
        try:
            order=list(self.grid["displaycolumns"])
            a,b=int(source[1:])-1,int(destination[1:])-1
            if not (0<=a<len(order) and 0<=b<len(order)):return
            col=order.pop(a)
            order.insert(b,col)
            self.grid.configure(displaycolumns=order)
            self.state["column_order"]=list(order)
            save_state(self.state)
        except (ValueError,tk.TclError):return

    def _description_context_menu(self,event):
        menu=tk.Menu(self.desc,tearoff=False)
        menu.add_command(label="Вирізати",command=lambda:self.desc.event_generate("<<Cut>>"))
        menu.add_command(label="Копіювати",command=lambda:self.desc.event_generate("<<Copy>>"))
        menu.add_command(label="Вставити",command=lambda:self.desc.event_generate("<<Paste>>"))
        menu.add_command(label="Виділити весь текст",
                         command=lambda:self.desc.tag_add("sel","1.0","end-1c"))
        menu.add_separator()
        menu.add_command(label="Взяти текст і Word з попереднього уроку паралелі…",
                         command=lambda:self.borrow_lesson("past"))
        menu.add_command(label="Взяти текст і Word з наступного уроку паралелі…",
                         command=lambda:self.borrow_lesson("future"))
        menu.add_command(label="Зберегти текст цього уроку",
                         command=self.save_classroom_description)
        menu.add_command(label="Прикріпити файл…",command=self.choose_attachments)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return "break"

    def _selected_rows(self):
        """Тільки реально виділені рядки. Ctrl / Shift доступні в Treeview."""
        return [self.rows[int(i)] for i in self.grid.selection()
                if i.isdecimal() and int(i)<len(self.rows)]

    def copy_row_materials(self):
        focus=self.grid.focus()
        row=(self.rows[int(focus)] if focus.isdecimal() and
             int(focus)<len(self.rows) else self.selected())
        if not row:return
        self._copied_lesson_key=row.unique_key
        self._copied_row_details=self.effective_lesson(row)
        override=self.state.get("description_overrides",{}).get(row.unique_key)
        self._copied_row_text=(self.desc.get("1.0","end-1c") if
              len(self.grid.selection())==1 else override)
        messagebox.showinfo("Урок скопійовано",
              "Можна копіювати навіть БЕЗ Word: тему, текст і вкладення. "
              "Тепер затисніть Ctrl або Shift, виділіть один чи кілька рядків "
              "і натисніть праву кнопку → «Вставити копію». "
              "Готовий Word буде скопійовано, лише якщо він існує й перевірений. "
              "У Google нічого не надсилається.",parent=self)

    def paste_row_materials(self):
        source=getattr(self,"_copied_row_details",None)
        key=getattr(self,"_copied_lesson_key",None)
        if not source or not key:return
        targets=[lesson for lesson in self._selected_rows() if lesson.unique_key!=key]
        if not targets:
            messagebox.showinfo("Вставити урок","Виділіть один або кілька ІНШИХ уроків.")
            return
        src_meta=self.state.get("files",{}).get(key,{})
        source_word=(src_meta.get("path") if
                     src_meta.get("validated") and src_meta.get("complete")
                     and Path(src_meta.get("path","")).is_file() else None)
        source_grade,source_subject=stream_subject(source.stream)
        mismatched=[x for x in targets if stream_subject(x.stream)!=(source_grade,source_subject)]
        if mismatched:
            messagebox.showerror("Не той предмет",
                "Копіювати можна лише в межах одного класу навчання та предмета. "
                "Для інших предметів виберіть відповідний матеріал вручну.")
            return
        drafts=[x for x in targets if x.unique_key in self.state.get("drafts",{})]
        if drafts:
            messagebox.showerror("Уроки з чернетками",
                   "Є уроки, для яких уже створено чернетку Google. "
                   "Зніміть з них виділення, щоб не створити невідповідність.")
            return
        different=any(signature(x,self.cfg)!=signature(source,self.cfg) for x in targets)
        detail=("\n\nУвага: окремі класи мають інші КТП або кількість годин. "
                "Це ЛИШЕ ваш ручний вибір, а не автоматичне поширення."
                if different else "")
        if not messagebox.askyesno("Підтвердження копіювання",
            f"Вставити «{source.topic}» у {len(targets)} вибраних уроків?\n"
            "Копіюються тема, текст, вкладення та готовий Word (якщо він є); "
            "дата стає датою цільового "
            "уроку. КТП і курс Google НЕ змінюються."
            +detail+"\n\nОпублікування не виконується."):return
        text=self._copied_row_text
        if text is None:
            text=self.state.get("description_overrides",{}).get(key)
        if text is None:
            templ=self.state.get("parallel_templates",{}).get(signature_key(source,self.cfg))
            text=render_template(templ,source) if templ is not None else html_classroom_text(source,asynchronous=True,video=True)
        source_date=source.day[8:10]+"."+source.day[5:7]
        for target in targets:
            local=dataclass_replace(target,topic=source.topic,homework=source.homework)
            try:
                doc=copy_for_lesson(source_word,local) if source_word else None
                copy_attachments(self.state,key,target.unique_key)
            except Exception as ex:
                messagebox.showerror("Копіювання перервано",str(ex))
                save_state(self.state);self.update_day()
                return
            self.state.setdefault("lesson_models",{})[target.unique_key]={
                  "topic":source.topic,"homework":source.homework,"from":key}
            new_date=target.day[8:10]+"."+target.day[5:7]
            self.state.setdefault("description_overrides",{})[target.unique_key]=text.replace(source_date,new_date)
            if doc:
                self.state.setdefault("files",{})[target.unique_key]={
                    "path":str(doc),"validated":True,"complete":True,
                    "borrowed_from":key}
        save_state(self.state);self.update_day()
        messagebox.showinfo("Готово",f"Перенесено у {len(targets)} уроків. "
            "Перевірте теми й домашні завдання перед чернетками.")

    def _highlight_drop_lesson(self,event):
        item=self.grid.identify_row(
            self.grid.winfo_pointery()-self.grid.winfo_rooty())
        if item!=getattr(self,"_hover_lesson_item",None):
            self._clear_drop_lesson()
            if item:
                tags=set(self.grid.item(item,"tags"))
                tags.add("file-drop-hover")
                self.grid.item(item,tags=tuple(tags))
                self._hover_lesson_item=item
                self.foot.config(text="Відпустіть файл — він потрапить у підсвічений урок.")
        return "copy"

    def _clear_drop_lesson(self,_event=None):
        item=getattr(self,"_hover_lesson_item",None)
        if item and self.grid.exists(item):
            tags=[x for x in self.grid.item(item,"tags") if x!="file-drop-hover"]
            self.grid.item(item,tags=tuple(tags))
        self._hover_lesson_item=None
        return "copy"

    def _highlight_description_drop(self,event):
        self.desc.configure(background="#FFF1B4")
        self.drop_hint.configure(style="TeacherHoverDrop.TLabel")
        return "copy"

    def _clear_description_drop(self,event=None):
        self.desc.configure(background=getattr(self,"_desc_original_bg","white"))
        self.drop_hint.configure(style="TLabel")
        return "copy"

    def _drop_on_lesson(self,event):
        """Спершу клас + дата в назві файлу (будь-який урок); решта — до рядка, на який кинули."""
        self._clear_drop_lesson()
        try:paths=[Path(path) for path in self.tk.splitlist(event.data)]
        except (tk.TclError,ValueError):return "copy"
        item=self.grid.identify_row(self.grid.winfo_pointery()-self.grid.winfo_rooty())
        leftover=self.import_lecture_files(paths,report_unmatched=not item)
        if not leftover or not item:return "copy"
        self.grid.selection_set(item);self.grid.focus(item)
        lesson=self.rows[int(item)]
        if lesson.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Чернетка вже існує",
                  "Цей урок уже має чернетку. Додайте файли у Google Classroom.")
            return "copy"
        docs=[path for path in leftover if path.suffix.casefold()==".docx"]
        others=[path for path in leftover if path.suffix.casefold()!=".docx"]
        if docs:
            # Для двох Word немає однозначного головного документа — питаємо.
            if len(docs)>1:
                others+=docs[1:]
            self._accept_dropped_word(lesson,docs[0])
        if others:self._attach_paths(others,lesson=lesson)
        return "copy"

    def _accept_dropped_word(self,lesson,path):
        try:check_real_docx(path)
        except Exception as ex:
            messagebox.showerror("Word",str(ex));return
        if not self._parallel_prompt(lesson,
              "Перетягнутий Word прийняти як ПОВНУ перевірену лекцію для цієї теми "
              "й автоматично поширити на сумісну паралель?"):return
        try:
            attached=self._attach_from_master(path,lesson,"Перетягнутий Word",
                                                replace_existing=True)
        except Exception as ex:
            messagebox.showerror("Не вдалося прикріпити Word",str(ex));return
        messagebox.showinfo("Word додано",
             f"Word прив’язано до {len(attached)} уроків. "
             "Кнопку «Підтвердити Word» натискати не треба. "
             "До Google файли ще не надіслано.")

    def _enter_creates_draft(self,_event=None):
        if self.selected():self.draft()
        return "break"

    def _fill_day_menu(self,menu):
        menu.add_command(label="Попередній день",command=lambda:self.shift(-1))
        menu.add_command(label="Наступний день",command=lambda:self.shift(1))
        menu.add_command(label="Сьогодні",
                         command=lambda:(self.datevar.set(date.today().strftime("%d.%m.%Y")),self.update_day()))
        menu.add_separator()
        menu.add_command(label="Лекції GPT на весь день…",command=self.chatgpt_batch)
        menu.add_command(label="Створити чернетки для всього дня…",command=self.batch_drafts)
        menu.add_separator()
        menu.add_command(label="Оновити стан із Classroom",
                         command=lambda:self.sync_classroom(interactive=False,manual=True))
        menu.add_command(label="Мій Classroom — перегляд",command=self.view_classroom)
        menu.add_command(label="Редактор КТП, розкладу і навчального року…",command=self.edit_academic_year)
        menu.add_separator()
        menu.add_command(label="Зразки документів…",command=self.samples_dialog)
        menu.add_command(label="Мої дані…",command=self.data_dialog)
        menu.add_command(label="Початкове налаштування…",command=self.setup_dialog)
        menu.add_command(label="Довідка",command=self.show_help)

    def _popup(self,menu,event):
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return "break"

    def _open_day_menu(self,event):
        """Меню для порожнього місця таблиці й фону вікна: дії над усім днем (+ виділити все)."""
        menu=tk.Menu(self,tearoff=False)
        total=len(self.grid.get_children()) if hasattr(self,"grid") else 0
        if total:
            menu.add_command(label=f"Виділити всі уроки дня ({total}) — Ctrl+A",
                             command=lambda:self._select_all_rows(announce=False))
            menu.add_separator()
        self._fill_day_menu(menu)
        return self._popup(menu,event)

    def selected_rows(self):
        """Виділені уроки в порядку таблиці."""
        return [self.rows[int(i)] for i in sorted(self.grid.selection(),key=int)]

    def _select_all_rows(self,announce=True):
        rows=self.grid.get_children()
        if not rows:return
        self.grid.selection_set(rows);self.grid.focus(rows[0])
        if announce:
            show_toast(self,f"Виділено всі уроки дня: {len(rows)} · права кнопка миші — дії над ними",2200)

    def _open_header_menu(self,event):
        """Права кнопка на заголовках («№», «Час», «Потік»…): виділення, дії над виділеними, стовпці, день."""
        count=len(self.grid.selection());total=len(self.grid.get_children())
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label=f"Виділити всі уроки дня ({total}) — Ctrl+A",
                         command=lambda:self._select_all_rows(announce=False),
                         state="normal" if total else "disabled")
        menu.add_command(label="Зняти виділення",command=lambda:self.grid.selection_set(()),
                         state="normal" if count else "disabled")
        menu.add_separator()
        if count:
            sub=tk.Menu(menu,tearoff=False)
            self._fill_lesson_menu(sub)
            menu.add_cascade(label=f"Дії над виділеними уроками ({count})",menu=sub)
        else:
            menu.add_command(label="Виділених уроків немає (клацніть заголовок — виділиться весь день)",
                             state="disabled")
        menu.add_separator()
        menu.add_command(label="Ширину стовпців — автоматично (Тема найширша)",command=self.reset_column_widths)
        menu.add_command(label="Порядок стовпців — за замовчуванням",command=self.reset_column_order)
        menu.add_separator()
        self._fill_day_menu(menu)
        return self._popup(menu,event)

    def reset_column_widths(self):
        self.state.pop("column_widths",None);save_state(self.state)
        self._fit_columns()
        show_toast(self,"Ширину стовпців підібрано автоматично: тема найширша",2000)

    def reset_column_order(self):
        self.grid.configure(displaycolumns=self.grid_columns)
        self.state.pop("column_order",None);save_state(self.state)

    # ---------- ширини стовпців: «Тема» найширша й видна повністю ----------
    def _schedule_fit(self,delay=120):
        job=getattr(self,"_fit_job",None)
        if job:
            try:self.after_cancel(job)
            except tk.TclError:pass
        try:self._fit_job=self.after(delay,self._fit_columns)
        except tk.TclError:self._fit_job=None

    def _fit_columns(self):
        """Вузькі стовпці — за вмістом, увесь вільний простір — «Темі». Власну ширину (перетягнули межу) шануємо."""
        self._fit_job=None
        cols=self.grid_columns
        available=self.grid.winfo_width()-6
        if available<200:return
        saved=self.state.get("column_widths")
        if isinstance(saved,dict) and set(saved)==set(cols):
            for col in cols:
                self.grid.column(col,width=int(saved[col]),stretch=(col=="Тема"))
            return
        style_font=ttk.Style().lookup("Treeview","font") or "TkDefaultFont"
        try:font=tkfont.nametofont(style_font)
        except tk.TclError:font=tkfont.Font(font=style_font)
        rows=[self.grid.item(i,"values") for i in self.grid.get_children()]
        index={c:k for k,c in enumerate(cols)}
        def need(col,minimum,cap):
            texts=[col]+[str(r[index[col]]) for r in rows]
            return max(minimum,min(cap,max(font.measure(t) for t in texts)+28))
        spec={"№":(44,70),"Час":(104,150),"Потік":(96,230),"Курс Classroom":(120,280),"КТП":(50,80),"Стан":(150,420)}
        widths={c:need(c,*spec[c]) for c in spec}
        # мінімуми: «Стан» (статуси чернеток) лишається читабельним, решта стискається сильніше
        floor={"№":44,"Час":104,"Потік":min(widths["Потік"],160),"Курс Classroom":min(widths["Курс Classroom"],160),
               "КТП":50,"Стан":min(widths["Стан"],260)}
        topic_need=need("Тема",260,4000)
        topic=available-sum(widths.values())
        for col in ("Стан","Курс Classroom","Потік","Час","КТП","№"):  # теми не вміщаються — стискаємо решту до мінімумів
            if topic>=topic_need:break
            give=min(widths[col]-floor[col],topic_need-topic)
            widths[col]-=give;topic+=give
        for col,width in widths.items():
            self.grid.column(col,width=int(width),stretch=False)
        self.grid.column("Тема",width=int(max(topic,260)),stretch=True)

    def _open_lesson_menu(self,event):
        region=self.grid.identify_region(event.x,event.y)
        item=self.grid.identify_row(event.y)
        if region=="heading":
            return self._open_header_menu(event)
        if not item:
            return self._open_day_menu(event)
        if item not in self.grid.selection():
            self.grid.selection_set(item)
        self.grid.focus(item)
        menu=tk.Menu(self,tearoff=False)
        self._fill_lesson_menu(menu)
        return self._popup(menu,event)

    def _fill_lesson_menu(self,menu):
        selected_count=len(self.grid.selection())
        menu.add_command(label="Копіювати таблицю виділених уроків (Ctrl+C)",
                         command=self.copy_selected_lessons_as_text)
        menu.add_command(label="Копіювати урок (текст, Word якщо є, вкладення)",
                         command=self.copy_row_materials)
        menu.add_command(label=f"Вставити копію у виділені уроки ({selected_count})",
                         command=self.paste_row_materials,
                         state="normal" if getattr(self,"_copied_lesson_key",None) else "disabled")
        menu.add_separator()
        menu.add_command(label="Взяти попередній урок із паралелі…",
                         command=lambda:self.borrow_lesson("past"))
        menu.add_command(label="Взяти майбутній урок із паралелі…",
                         command=lambda:self.borrow_lesson("future"))
        menu.add_separator()
        menu.add_command(label="Лекція через мій ChatGPT…",command=self.chatgpt_word)
        menu.add_command(label=f"Лекції GPT для виділених уроків ({selected_count})…",
                         command=lambda:self.chatgpt_batch(only=self.selected_rows()))
        menu.add_command(label="Лекції GPT на весь день…",command=self.chatgpt_batch)
        menu.add_command(label="Word: заготовка",command=lambda:self.make_word(False))
        menu.add_command(label="Вибрати готовий Word…",command=self.choose_docx)
        menu.add_command(label="Word і картинки пачкою (за назвою)…",command=self.choose_lecture_files)
        menu.add_command(label="Бібліотека Word…",command=self.library_dialog)
        menu.add_command(label="Додати файли до Classroom…",command=self.choose_attachments)
        menu.add_command(label="Відкрити папку Word",command=self.open_folder)
        menu.add_separator()
        menu.add_command(label="Редагувати тему / Д/з цього уроку в КТП…",
                         command=self.edit_lesson_in_ktp)
        menu.add_command(label="Копіювати повідомлення Classroom",command=self.copy_classroom)
        menu.add_command(label="Зберегти опис цього уроку",command=self.save_classroom_description)
        menu.add_command(label="Зберегти шаблон для паралелі",command=self.save_parallel_description)
        menu.add_separator()
        menu.add_command(label="Створити ЧЕРНЕТКУ в Classroom…",command=self.draft)
        menu.add_command(label=f"Створити чернетки для виділених уроків ({selected_count})…",
                         command=lambda:self.batch_drafts(only=self.selected_rows()))
        menu.add_command(label="Створити чернетки для всього дня…",command=self.batch_drafts)
        menu.add_command(label="Мій Classroom — перегляд",command=self.view_classroom)
        menu.add_command(label="Оновити стан із Classroom",
                         command=lambda:self.sync_classroom(interactive=False,manual=True))
        menu.add_separator()
        menu.add_command(label="Прибрати ЛОКАЛЬНІ матеріали (Delete)",
                         command=self.remove_selected_local_materials)

    def _reload_from_disk(self):
        """Перечитати розклад, КТП і стан з диска (після очищення чи відновлення)."""
        self.cfg=read_json("Налаштування.json")
        self.state=read_state()
        self.remote_classroom_entries={}
        self._plans_sig=None
        self.update_day()
        self.after(400,lambda:self.sync_classroom(interactive=False))

    def reload_data(self):
        """Просте перечитування з очищенням історії (коли скасувати вже нічого)."""
        self._reload_from_disk()
        self.history.reset(self._history_snapshot())
        self._history_buttons()

    def begin_data_operation(self):
        """Викликати ДО скидання/відновлення: фіксує поточний стан як крок історії."""
        self._history_record()

    def apply_data_operation(self,label,undo_zip,redo_action):
        """Після скидання/відновлення з копії: це звичайний крок історії.

        «↶ Назад» розпакує undo_zip (повну копію, збережену ПЕРЕД операцією), «↷ Вперед» повторить операцію.
        """
        self._reload_from_disk()
        snapshot=self._history_snapshot()
        if not self.history.record(snapshot,label,{"undo_zip":str(undo_zip),"redo":redo_action}):
            self.history.replace_current(snapshot)
        self._history_buttons()

    def _undo_data_operation(self,meta):
        archive=Path(meta["undo_zip"])
        if not archive.is_file():
            raise FileNotFoundError(f"Копію не знайдено: {archive}")
        data_tools.restore_from_zip(archive,data_tools.auto_backup_path("Стан перед скасуванням"))
        self._reload_from_disk()

    def _redo_data_operation(self,meta):
        action=meta.get("redo")
        if action=="reset":
            data_tools.reset_to_blank(meta["undo_zip"])         # знову: копія -> порожня програма
        elif isinstance(action,(list,tuple)) and action and action[0]=="restore":
            data_tools.restore_from_zip(action[1],data_tools.auto_backup_path("Стан перед відновленням"))
        else:
            raise ValueError("Невідома операція")
        self._reload_from_disk()

    def borrow_lesson(self,when):
        """Ручний вибір попереднього/майбутнього ЗРАЗКА лише в сумісному потоці."""
        target=self.selected()
        if not target:return
        if target.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Уже є чернетка",
                    "У Classroom для цього уроку вже створено чернетку. "
                    "Редагуйте її безпосередньо в Classroom.");return
        target_sig=signature(target,self.cfg)
        candidates=[]
        for source in build_calendar(self.cfg):
            if source.unique_key==target.unique_key or source.status!="готово":continue
            if when=="past" and source.day>=target.day:continue
            if when=="future" and source.day<=target.day:continue
            src_grade,src_subject=stream_subject(source.stream)
            target_grade,target_subject=stream_subject(target.stream)
            if (src_grade,src_subject)!=(target_grade,target_subject):continue
            doc=self.state.get("files",{}).get(source.unique_key,{})
            if not doc.get("validated") or not Path(doc.get("path","")).is_file():continue
            candidates.append(source)
        candidates.sort(key=lambda x:x.day,reverse=(when=="past"))
        if not candidates:
            messagebox.showinfo("Уроки паралелі",
                   "Не знайдено готових перевірених Word для цього предмета, "
                   "навчальної програми та кількості годин у відповідному періоді.")
            return
        win=tk.Toplevel(self)
        win.title("Виберіть попередню роботу" if when=="past" else "Виберіть майбутню роботу")
        win.transient(self);fit_work_window(win,"normal")
        ttk.Label(win,text="Будуть перенесені тема, опис Classroom, готовий Word і вкладення. "
                  "Дата уроку стане поточною. Автоприв'язка для різних КТП/годин заборонена; "
                  "тут дозволяється ЛИШЕ ваш ручний вибір. КТП не змінюється.",
                  wraplength=1000).pack(anchor="w",padx=12,pady=9)
        frame=ttk.Frame(win);frame.pack(fill="both",expand=True,padx=10)
        columns=("date","stream","topic")
        table=ttk.Treeview(frame,columns=columns,show="headings")
        for name,label,width in (("date","Дата",110),("stream","Паралель",150),
                                 ("topic","Тема / вид роботи",750)):
            table.heading(name,text=label);table.column(name,width=width)
        sc=ttk.Scrollbar(frame,orient="vertical",command=table.yview)
        table.configure(yscrollcommand=sc.set)
        table.pack(side="left",fill="both",expand=True)
        sc.pack(side="right",fill="y")
        for i,x in enumerate(candidates):
            eff=self.effective_lesson(x)
            table.insert("", "end",iid=str(i),values=(display_date(x.day),x.stream,eff.topic[:130]))
        table.selection_set("0")
        def apply(_event=None):
            choice=table.selection()
            if not choice:return
            original=candidates[int(choice[0])]
            source=self.effective_lesson(original)
            if not messagebox.askyesno("Один зразок без повторної оплати",
                f"Використати готовий урок «{source.topic}» ({display_date(source.day)}, {source.stream}) "
                f"для {target.stream} ({display_date(target.day)})?\n\n"
                "Зміняться лише локальні тема, опис, Word і вкладення цього уроку. "
                "КТП та Google Classroom залишаються без змін до створення окремої чернетки.",
                parent=win):return
            different_plan=signature(source,self.cfg)!=target_sig
            if different_plan and not messagebox.askyesno(
                "Увага: різні КТП або кількість годин",
                "Ви вручну вибрали роботу з тієї самої паралелі, але з іншими "
                "годинами або календарною програмою.\n\n"
                "Перевірте відповідність теми, навчальній програмі й віку дітей. "
                "Тільки цей один урок буде змінений. Продовжити?",
                parent=win):return
            model={"topic":source.topic,"homework":source.homework,
                   "from":source.unique_key}
            destination=dataclass_replace(target,topic=source.topic,homework=source.homework)
            try:
                src=self.state["files"][source.unique_key]
                dest=copy_for_lesson(src["path"],destination)
                raw=self.state.get("description_overrides",{}).get(source.unique_key)
                if raw is None:
                    templ=self.state.get("parallel_templates",{}).get(signature_key(source,self.cfg))
                    raw=render_template(templ,source) if templ is not None else html_classroom_text(source,asynchronous=True,video=True)
                old_date=source.day[8:10]+"."+source.day[5:7]
                new_date=target.day[8:10]+"."+target.day[5:7]
                text=raw.replace(old_date,new_date)
                copy_attachments(self.state,source.unique_key,target.unique_key)
            except Exception as ex:
                messagebox.showerror("Не вдалося перенести",str(ex),parent=win);return
            self.state.setdefault("lesson_models",{})[target.unique_key]=model
            self.state.setdefault("description_overrides",{})[target.unique_key]=text
            self.state.setdefault("files",{})[target.unique_key]={
                "path":str(dest),"complete":True,"validated":True,
                "borrowed_from":source.unique_key}
            save_state(self.state);win.destroy();self.update_day()
            messagebox.showinfo("Урок використано","Готовий Word та опис перенесено без AI-запиту. "
                    "Перевірте дату, тему й Д/з перед створенням чернетки.")
        table.bind("<Double-1>",apply)
        ttk.Button(win,text="Використати вибраний урок",
                   command=apply).pack(pady=8)

    def _receive_files(self,event):
        try:
            names=list(self.tk.splitlist(event.data))
        except Exception:
            names=[]
        self._clear_description_drop()
        leftover=self.import_lecture_files(names,report_unmatched=False)    # розпізнані — за назвою
        if leftover:self._attach_paths([str(p) for p in leftover])           # решта — до вибраного уроку
        return "copy"

    # ---------- Word і зображення пачкою: урок визначається за назвою ----------
    def _register_window_drop(self):
        if not DND_FILES:return
        self.window_hint=tk.Label(self,bg="#FFE49A",fg="#164F82",font=("Segoe UI",10,"bold"),
            text="⬇  Відпустіть Word і зображення: програма знайде урок за назвою «9-Б ВІ, Урок 05.10 — Тема»")
        special={id(w) for w in (self.grid,self.desc,self.drop_hint,self.attachment_bar,
                                 self.attachment_toolbar)}
        everything=[];stack=[self]
        while stack:
            widget=stack.pop();stack.extend(widget.winfo_children())
            if id(widget) not in special and widget is not self.window_hint:everything.append(widget)
        everything.append(self.window_hint)
        for widget in everything:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>",self._show_window_hint)
                widget.dnd_bind("<<DropPosition>>",self._show_window_hint)
                widget.dnd_bind("<<DropLeave>>",self._hide_window_hint)
                widget.dnd_bind("<<Drop>>",self._drop_anywhere)
            except tk.TclError:pass

    def _show_window_hint(self,_event=None):
        try:self.window_hint.place(x=0,y=0,relwidth=1,height=30);self.window_hint.lift()
        except (AttributeError,tk.TclError):pass
        return "copy"

    def _hide_window_hint(self,_event=None):
        try:self.window_hint.place_forget()
        except (AttributeError,tk.TclError):pass
        return "copy"

    def _drop_anywhere(self,event):
        self._hide_window_hint()
        try:paths=[Path(p) for p in self.tk.splitlist(event.data)]
        except (tk.TclError,ValueError):return "copy"
        self.import_lecture_files(paths)
        return "copy"

    def choose_lecture_files(self):
        paths=filedialog.askopenfilenames(title="Word і зображення (урок визначу за назвою)",
            filetypes=[("Word та зображення","*.docx *.png *.jpg *.jpeg *.gif *.webp"),("Усі файли","*.*")])
        if paths:self.import_lecture_files([Path(p) for p in paths])

    def _extras_targets(self,lesson):
        drafts=self.state.get("drafts",{})
        targets=[x for x in self._parallel(lesson) if x.unique_key not in drafts]
        if lesson.unique_key not in drafts and all(x.unique_key!=lesson.unique_key for x in targets):
            targets.insert(0,lesson)
        return targets

    def import_lecture_files(self,paths,report_unmatched=True):
        """Word і зображення (і ZIP-архів дня) за назвою «9-Б ВІ, Урок 05.10 — Тема» → відповідні уроки.

        Жодних запитань. Повертає файли, яких не розпізнано (якщо report_unmatched=False — без повідомлення).
        Успіх показується короткою підказкою на кілька секунд; помилки — вікном, яке треба прочитати.
        """
        paths=[Path(p) for p in paths if Path(p).is_file()]
        self._last_matched_sources=set()
        if not paths:return []
        workdir=tempfile.mkdtemp(prefix="gpt_zip_")
        try:
            return self._import_lecture_files(paths,workdir,report_unmatched)
        finally:
            shutil.rmtree(workdir,ignore_errors=True)

    def _import_lecture_files(self,paths,workdir,report_unmatched):
        expanded,origin=lecture_inbox.expand_archives(paths,workdir)
        lessons=[x for x in build_calendar(self.cfg) if x.status=="готово"]
        groups={};unmatched=[]
        for path in expanded:
            kind=file_match.kind_of(path)
            first=file_match.first_line_of_docx(path) if kind=="word" else ""
            lesson=file_match.find_lesson(lessons,file_match.parse_file(path,first))
            if lesson is None:
                unmatched.append(path);continue
            self._last_matched_sources.add(origin.get(path,path))
            group=groups.setdefault(lesson.unique_key,{"lesson":lesson,"word":[],"extra":[]})
            group["word" if kind=="word" else "extra"].append(path)
        done=[];failed=[];words=images=0
        for group in groups.values():
            lesson=group["lesson"];title=f"{lesson.stream}, {lesson.day[8:10]}.{lesson.day[5:7]}"
            if lesson.unique_key in self.state.get("drafts",{}):
                failed.append(f"✗ {title}: чернетка вже створена — додайте файли у Google Classroom");continue
            try:
                pictures=[p for p in group["extra"] if file_match.kind_of(p)=="image"]
                if group["word"]:
                    main=max(group["word"],key=lambda p:p.stat().st_mtime)        # найновіший Word
                    _dest,attached,skipped=self.save_dropped_lecture(
                        lesson,main,group["extra"],replace_existing=True)
                    note="Word"+(f" + зображень: {len(pictures)}" if pictures else "")
                    also=[x.stream for x in attached if x.unique_key!=lesson.unique_key]
                    if also:note+="; також для: "+", ".join(dict.fromkeys(also))
                    if len(group["word"])>1:note+="; з кількох Word взято найновіший"
                    if skipped:note+="; "+skipped
                    words+=1;images+=len(pictures)
                else:
                    targets=self._extras_targets(lesson)
                    for target in targets:add_attachments(self.state,target.unique_key,group["extra"])
                    note=f"зображень/файлів: {len(group['extra'])} (без Word)"
                    images+=len(pictures)
                done.append(f"✓ {title} — {note}")
            except Exception as ex:
                failed.append(f"✗ {title}: {ex}")
        save_state(self.state);self.update_day();self.refresh_attachment_previews()
        if unmatched and report_unmatched:
            failed+=[f"✗ {p.name} — не вдалося визначити урок: у назві має бути «9-Б ВІ, Урок 05.10 — Тема»"
                     for p in unmatched]
        if done:self.request_sync(1500)                       # Classroom: сама перевіряє й показує стан
        if failed:
            text=(f"Розпізнано уроків: {len(done)} · Word: {words} · зображень: {images}.\n\n"
                  +"\n".join((done+failed)[:30])
                  +"\n\nУ Classroom нічого не створено: файли додаються до чернетки при її створенні.")
            messagebox.showwarning("Word і зображення",text)
        elif done:
            self.foot.config(text=done[0] if len(done)==1 else self.foot.cget("text"))
            show_toast(self,f"✓ Розпізнано уроків: {len(done)} · Word: {words} · зображень: {images}"
                       +(" · зелені рядки готові до чернеток" if words else ""),2800)
        return [] if report_unmatched else unmatched

    # ---------- автопідхоплення файлів від GPT ----------
    def _watch_sources(self):
        sources=[]
        if self.state.get("watch_inbox",True):
            sources.append((lecture_inbox.inbox_dir(ROOT),False))
        if self.state.get("watch_downloads",True):
            sources.append((lecture_inbox.downloads_dir(),True))
            sources.extend((folder,True) for folder in self._browser_folders())      # куди браузер справді зберігає
        return sources

    def _browser_folders(self):
        """Папки завантажень Chrome/Edge/Brave, окрім «Завантажень» і власної папки (оновлюється раз на хвилину)."""
        now=time.monotonic()
        if now-getattr(self,"_bf_ts",-999)>60:
            self._bf_ts=now
            try:
                self._bf=browser_downloads.watch_folders(
                    browser_downloads.detect(),skip=(lecture_inbox.inbox_dir(ROOT),lecture_inbox.downloads_dir()))
            except Exception:
                self._bf=[]
        return getattr(self,"_bf",[])

    def _set_watch(self):
        self.state["watch_downloads"]=bool(self.watch_var.get())
        save_state(self.state)
        show_toast(self,"Стежу за «Завантаженнями»: "+("так" if self.watch_var.get() else "ні"),1800)

    def open_inbox(self):
        """Вікно «Куди зберігати файли від GPT»: прямий запис браузера в папку програми (+ відкрити папку)."""
        from .download_setup_ui import show_download_setup
        return show_download_setup(self)

    def open_inbox_folder(self):
        folder=lecture_inbox.inbox_dir(ROOT)
        import subprocess
        if sys.platform=="win32":os.startfile(str(folder))
        elif sys.platform=="darwin":subprocess.Popen(["open",str(folder)])
        show_toast(self,"Киньте сюди файли від GPT (або ZIP дня): програма сама розкладе їх по уроках",3200)

    def _inbox_poll(self):
        try:
            if not self.winfo_exists():return
            if not self._inbox_busy:
                ready=self._watcher.poll(self._watch_sources(),self._watch_since_ns)
                if ready:self._process_inbox(ready)
        except Exception as ex:                                  # стеження не має ламати програму
            try:self.foot.config(text=f"Автопідхоплення файлів: {ex}")
            except tk.TclError:return
        try:self._inbox_job=self.after(2000,self._inbox_poll)
        except tk.TclError:pass

    def _process_inbox(self,ready):
        self._inbox_busy=True
        try:
            paths=[p for p,_ in ready];strict={p:s for p,s in ready}
            self.import_lecture_files(paths,report_unmatched=False)
            matched=set(self._last_matched_sources);unknown=[]
            for path in paths:
                self._watcher.mark_done(path)
                if path in matched:
                    if not strict[path]:lecture_inbox.move_to_done(path)      # власна папка: у «Оброблено»
                elif not strict[path] and path.suffix.lower()==".docx":
                    unknown.append(path.name)          # сторонні зображення й архіви в папці тихо лишаємо як є
            if unknown:
                show_toast(self,"Не вдалося визначити урок для: "+", ".join(unknown[:3])
                           +" · назва має бути «клас, Урок дд.мм — тема»",4200,"warn")
            self.state["inbox_done"]=self._watcher.export()
            save_state(self.state)
        finally:
            self._inbox_busy=False

    def on_close(self):
        """Закриття програми: нічого не губимо (зміни редактора зберігаються самі)."""
        editors=[w for w in self.winfo_children() if type(w).__name__=="SchoolEditor" and w.winfo_exists()]
        for editor in editors:
            try:
                if editor.has_unsaved() and not editor.save(confirm=False,close=False,silent=True):
                    if not messagebox.askyesno("Редактор",
                            "У редакторі є зміни, які не вдалося зберегти (є помилки в даних).\n"
                            "Закрити програму БЕЗ цих змін?",default="no"):
                        return
            except tk.TclError:pass
        try:save_state(self.state)
        except Exception:pass
        for monitor in (getattr(self,"net",None),getattr(self,"alerts",None)):
            try:monitor.stop()
            except Exception:pass
        for name in ("_inbox_job","_poll_job","_net_job","_alert_job","_facts_job"):
            job=getattr(self,name,None)
            if job:
                try:self.after_cancel(job)
                except tk.TclError:pass
        self.destroy()

    def _clean_start_once(self):
        """Один раз для цього випуску (на прохання вчителя): очистити тестові дані, попередньо зберігши копію.

        Мітка лежить поза «Стан.json» і не потрапляє в копії, тож «чистий старт» ніколи не повторюється
        і не стирає роботу після перезапуску.
        """
        if os.environ.get("POMICHNYK_NO_OFFERS") or not getattr(sys,"frozen",False):return
        if data_tools.read_install().get("clean_start")==data_tools.CLEAN_START_RELEASE:return
        has=(bool(self.cfg.get("course_map")) or self._plans_text_has_plans()
             or bool(self.state.get("files") or self.state.get("drafts")))
        if has:
            try:
                self.begin_data_operation()
                path=data_tools.auto_backup_path(data_tools.RESET_PREFIX)
                data_tools.reset_to_blank(path)
                self.apply_data_operation("Чистий старт нового випуску",path,"reset")
                show_toast(self,"Чистий старт нового випуску (за вашим проханням). Повну копію збережено в папці "
                                f"«Резервні копії»: {path.name}. Повернути все: «↶ Назад» або «↩ Відновити останню копію».",
                           8000)
            except Exception as ex:
                messagebox.showerror("Чистий старт",str(ex));return
        data_tools.write_install({"clean_start":data_tools.CLEAN_START_RELEASE})

    def choose_attachments(self):
        if not self.selected():return
        paths=filedialog.askopenfilenames(
            title="Виберіть файли для додавання в Classroom (максимум 19)",
            filetypes=[("Усі файли","*.*")])
        self._attach_paths(paths)

    def _attach_paths(self,paths,lesson=None):
        lesson=lesson or self.selected()
        if not lesson or not paths:return
        if lesson.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Уже створено чернетку",
              "Вкладення до наявної чернетки слід додати в Google Classroom.");return
        try:
            added=add_attachments(self.state,lesson.unique_key,paths)
        except Exception as ex:
            messagebox.showerror("Файли",str(ex));return
        save_state(self.state);self.refresh_attachment_previews()
        if added:self.foot.config(text=f"Прикріплено додаткових файлів: "
                  f"{len(self.state.get('attachments',{}).get(lesson.unique_key,[]))} "
                  "· вони ще НЕ надіслані в Google.")

    def refresh_attachment_previews(self):
        if not hasattr(self,"attachment_bar"):return
        for child in self.attachment_bar.winfo_children():child.destroy()
        self._preview_images=[]
        lesson=self.selected()
        if not lesson:return
        attachments=self.state.get("attachments",{}).get(lesson.unique_key,[])
        if not attachments:
            ttk.Label(self.attachment_bar,text="Вкладень поки немає.",
                      foreground="#617081").pack(anchor="w")
            return
        # Horizontal scroll for many photo cards.
        canvas=tk.Canvas(self.attachment_bar,height=93,highlightthickness=0)
        scroll=ttk.Scrollbar(self.attachment_bar,orient="horizontal",command=canvas.xview)
        canvas.configure(xscrollcommand=scroll.set)
        canvas.pack(fill="x",expand=True)
        scroll.pack(fill="x")
        inside=ttk.Frame(canvas)
        canvas.create_window((0,0),window=inside,anchor="nw")
        inside.bind("<Configure>",lambda _:canvas.configure(scrollregion=canvas.bbox("all")))
        for ix,entry in enumerate(attachments):
            part=ttk.Frame(inside,relief="groove",borderwidth=1,padding=3)
            part.grid(row=0,column=ix,padx=3,sticky="nw")
            suffix=Path(entry["path"]).suffix.lower()
            if suffix in (".png",".jpg",".jpeg",".gif",".bmp",".webp"):
                try:
                    from PIL import Image,ImageTk
                    with Image.open(entry["path"]) as original:
                        picture=original.copy()
                    picture.thumbnail((87,53))
                    photo=ImageTk.PhotoImage(picture,master=self)
                    self._preview_images.append(photo)
                    ttk.Label(part,image=photo).pack(side="left",padx=3)
                except Exception:pass
            name=entry.get("name",Path(entry["path"]).name)
            ttk.Label(part,text=name[:30],width=27).pack(side="left")
            ttk.Button(part,text="×",width=3,
                       command=lambda j=ix:self.remove_attachment_at(j)).pack(side="right")

    def remove_attachment_at(self,index):
        lesson=self.selected()
        if not lesson:return
        if lesson.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Чернетка існує",
               "Файли вже прив'язані до чернетки Google. Видалення виконуйте в Classroom.")
            return
        if remove_attachment(self.state,lesson.unique_key,index):
            save_state(self.state);self.refresh_attachment_previews()

    def library_dialog(self):
        from .material_library import load_index,signature,norm
        lesson=self.selected()
        if not lesson:return
        sig=signature(lesson,self.cfg)
        matching=[item for item in load_index()['items']
                  if item['signature']==sig and item['topic_norm']==norm(lesson.topic)
                  and Path(item['path']).is_file()]
        if not matching:
            messagebox.showinfo("Бібліотека","Відповідної лекції немає. Натисніть «Вибрати готовий Word», щоб додати її.");return
        win=tk.Toplevel(self);win.title("Бібліотека перевірених лекцій");fit_work_window(win,"normal")
        ttk.Label(win,text="Показано лише лекції з тим самим предметом, програмою, годинами і темою.").pack(anchor="w",padx=12,pady=8)
        box=tk.Listbox(win,height=9)
        box.pack(fill="both",expand=True,padx=12,pady=10)
        for item in matching:box.insert("end",f"{item['topic'][:82]} · {item['added']} · {item['origin']}")
        box.selection_set(0)
        def apply():
            ids=box.curselection()
            if not ids:return
            item=matching[ids[0]]
            if not self._parallel_prompt(lesson,"Використати цей раніше перевірений Word без додаткової оплати?"):
                return
            attached=attach_document(item,self._parallel(lesson),self.state)
            save_state(self.state);self.update_day();win.destroy()
            messagebox.showinfo("Бібліотека",f"Прив'язано уроків: {len(attached)}.")
        ttk.Button(win,text="Використати для паралелі",command=apply).pack(pady=6)

    def validate_docx(self):
        lesson=self.selected()
        if not lesson:return
        doc=self.state.get("files",{}).get(lesson.unique_key)
        if not doc:messagebox.showwarning("Немає файлу","Спочатку створіть або виберіть Word.");return
        if not doc.get("complete"):
            messagebox.showwarning("Неповний документ","Це лише заготовка. Виберіть готову лекцію або згенеруйте повну лекцію через AI.");return
        if not Path(doc["path"]).exists():
            messagebox.showerror("Файл", "Word-файл не знайдено");return
        if messagebox.askyesno("Перевірка","Ви переглянули Word повністю, перевірили точність матеріалу, план-конспект і Д/з?"):
            doc["validated"]=True;save_state(self.state);self.update_day()

    def open_folder(self):
        lesson=self.selected()
        f=self.state.get("files",{}).get(lesson.unique_key) if lesson else None
        path=Path(f["path"]).parent if f else ROOT/"Готові Word"
        path.mkdir(parents=True,exist_ok=True)
        import os,subprocess,sys
        if sys.platform=="win32":os.startfile(str(path))
        elif sys.platform=="darwin":subprocess.Popen(["open",str(path)])
        else:subprocess.Popen(["xdg-open",str(path)])

    def copy_classroom(self):
        content=self.desc.get("1.0","end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update()
            messagebox.showinfo("Classroom", "Повідомлення скопійоване.")

    def save_classroom_description(self):
        lesson=self.selected()
        if lesson is None:return
        description=self.desc.get("1.0","end").strip()
        if not description:
            messagebox.showwarning("Classroom","Опис уроку не може бути порожнім.")
            return
        self.state.setdefault("description_overrides",{})[lesson.unique_key]=description
        save_state(self.state)
        messagebox.showinfo("Опис збережено","Текст опису збережено для цього уроку на цьому комп'ютері. У Classroom його ще НЕ надіслано.")

    def save_parallel_description(self):
        lesson=self.selected()
        if not lesson:return
        text=self.desc.get("1.0","end").strip()
        if not text:
            messagebox.showerror("Опис","Текст не може бути порожнім.");return
        template=topic_template(text,lesson)
        if "{topic}" not in template or "{date}" not in template or "{homework}" not in template:
            if not messagebox.askyesno("Динамічні поля",
                "Не всі змінні {topic}, {date}, {homework} є в тексті. "
                "Це може перенести стару дату або Д/з в інші класи. Зберегти?"):
                return
        if not messagebox.askyesno("Шаблон паралелі",
             "Застосувати відредагований шаблон до тієї ж паралелі з однаковою "
             "програмою та кількістю годин? Змінні тема/дата/Д/з будуть підставлятися окремо."):
            return
        self.state.setdefault("parallel_templates",{})[signature_key(lesson,self.cfg)]=template
        # User asked to save parallel format; drop this lesson's local override so it also uses template.
        self.state.setdefault("description_overrides",{}).pop(lesson.unique_key,None)
        save_state(self.state)
        messagebox.showinfo("Шаблон збережено",
                            "Збережено для сумісної паралелі. Під час вибору іншого "
                            "класу буде підставлено його дату, тему та Д/з.")
        self.select()

    def show_help(self):
        from .help_ui import show_help
        show_help(self)

    def edit_academic_year(self):
        from .editor_ui import SchoolEditor
        SchoolEditor(self,self.update_day)

    def setup_dialog(self):
        """Настроювання без ручного копіювання JSON або змінних середовища."""
        import json
        import shutil
        from tkinter import simpledialog
        dlg=tk.Toplevel(self)
        dlg.title("Перший запуск • Google, ChatGPT та AI")
        fit_work_window(dlg,"normal")
        dlg.transient(self)
        text=(
            "РОЗКЛАД І КТП вже працюють локально, навіть без налаштувань.\n\n"
            "GOOGLE CLASSROOM: потрібен одноразовий дозвіл Google (OAuth). "
            "Спочатку у власному Google Cloud проєкті створіть OAuth Client ID типу "
            "Desktop app і увімкніть Classroom API та Drive API. Завантажений JSON "
            "імпортуйте кнопкою нижче; далі натисніть «Підключити Google». "
            "Сервісний JSON із Google Cloud містить ідентифікатор програми, "
            "а НЕ пароль вашого акаунта. Нікому не пересилайте токен доступу.\n\n"
            "ЛЕКЦІЇ БЕЗКОШТОВНО — ЧЕРЕЗ ВАШ ChatGPT: кнопка «Word: лекція через ChatGPT». "
            "Програма готує запит за КТП, ви вставляєте його у свій ChatGPT і копіюєте "
            "відповідь — Word створюється автоматично. Ключі й паролі не потрібні.\n\n"
            "ПЛАТНИЙ АВТОМАТИЧНИЙ ВАРІАНТ (за бажанням): власний OpenAI API-ключ "
            "(оплата API окрема від підписки ChatGPT). Ключ зберігається "
            "в захищеному сховищі облікових даних Windows.\n\n"
            "БЕЗПЕКА: програма ніколи сама не опублікує матеріал; у Classroom "
            "створює тільки ЧЕРНЕТКИ і тільки після вашого підтвердження."
        )
        label=tk.Text(dlg,wrap="word",height=15,padx=16,pady=14,font=("Segoe UI",10))
        label.insert("1.0",text)
        label.configure(state="disabled",bg="#f3f6fa",relief="flat")
        label.pack(fill="both",expand=True,padx=10,pady=10)
        buttons=ttk.Frame(dlg)
        buttons.pack(fill="x",padx=10,pady=8)

        def import_credentials():
            path=filedialog.askopenfilename(
                parent=dlg,title="Оберіть OAuth JSON із Google Cloud",
                filetypes=[("JSON","*.json"),("Усі файли","*.*")]
            )
            if not path: return
            try:
                content=json.loads(Path(path).read_text(encoding="utf-8-sig"))
                details=content.get("installed")
                if not isinstance(details,dict) or not all(k in details for k in ("client_id","auth_uri","token_uri")):
                    raise ValueError("Це не OAuth Desktop JSON. Потрібен файл клієнта типу «Desktop app».")
                DATA.mkdir(parents=True,exist_ok=True)
                target=DATA/"google_credentials.json"
                shutil.copyfile(path,target)
                messagebox.showinfo("OAuth", "Google OAuth налаштування імпортовано. Тепер натисніть «Підключити Google» у головному вікні.",parent=dlg)
            except Exception as ex:
                messagebox.showerror("Google OAuth",str(ex),parent=dlg)

        def save_key():
            from .editor_ui import api_key_dialog
            api_key_dialog(dlg)

        ttk.Button(buttons,text="Імпортувати Google OAuth JSON",command=import_credentials).pack(side="left",padx=5)
        ttk.Button(buttons,text="Зберегти AI-ключ (платний режим)",command=save_key).pack(side="left",padx=5)
        ttk.Button(buttons,text="Закрити",command=dlg.destroy).pack(side="right",padx=5)

    # ---------- Назад / Вперед ----------
    def _plans_digest_now(self):
        path=DATA/"Календарні плани.json"
        try:stat=path.stat()
        except OSError:return ""
        signature=(stat.st_mtime_ns,stat.st_size)
        if signature!=self._plans_sig:
            text=path.read_text(encoding="utf-8")
            self._plans_digest=hashlib.sha1(text.encode("utf-8")).hexdigest()
            self._plans_store[self._plans_digest]=text
            self._plans_sig=signature
        return self._plans_digest

    def _history_snapshot(self):
        core={k:v for k,v in self.state.items() if k not in NON_UNDOABLE}
        return json.dumps({"cfg":self.cfg,"state":core,"plans":self._plans_digest_now()},
                          ensure_ascii=False,sort_keys=True)

    def _history_buttons(self):
        try:
            self.undo_button.config(state="normal" if self.history.can_undo() else "disabled")
            self.redo_button.config(state="normal" if self.history.can_redo() else "disabled")
        except tk.TclError:pass

    def _history_record(self):
        snapshot=self._history_snapshot()
        if snapshot!=self.history.current:
            self.history.record(snapshot,describe_change(self.history.current,snapshot))
        self._history_buttons()

    def _history_poll(self):
        try:
            if not self.winfo_exists():return
            self._history_record()
        except tk.TclError:return
        self._poll_job=self.after(900,self._history_poll)

    def _editor_is_open(self):
        return any(type(w).__name__=="SchoolEditor" and w.winfo_exists() for w in self.winfo_children())

    def _restore_snapshot(self,snapshot):
        data=json.loads(snapshot)
        keep={k:v for k,v in self.state.items() if k in NON_UNDOABLE}
        state={**data["state"],**keep}
        write_json("Налаштування.json",data["cfg"])
        text=self._plans_store.get(data.get("plans",""))
        if text is not None:
            (DATA/"Календарні плани.json").write_text(text,encoding="utf-8")
            self._plans_sig=None
        save_state(state)
        self.cfg,self.state=data["cfg"],state
        self.update_day()
        self.history.replace_current(self._history_snapshot())
        self._history_buttons()

    def undo(self):
        if self._editor_is_open():
            messagebox.showinfo("Назад","Спершу закрийте редактор: у ньому є власні кнопки «Назад» і «Вперед».")
            return "break"
        self._history_record()
        step=self.history.undo()
        if not step:
            self.foot.config(text="Немає що скасовувати.");return "break"
        meta=self.history.step_meta
        try:
            if meta and meta.get("undo_zip"):
                self._undo_data_operation(meta)          # скидання / відновлення: беремо автоматичну копію
                self.history.replace_current(self._history_snapshot())
                self._history_buttons()
            else:
                self._restore_snapshot(step[0])
        except Exception as ex:
            self.history.redo()                           # вказівник історії — на місце
            messagebox.showerror("Назад",f"Не вдалося скасувати: {ex}")
            return "break"
        self.foot.config(text=f"Скасовано: {step[1]}. «Вперед» поверне назад.")
        return "break"

    def redo(self):
        if self._editor_is_open():
            messagebox.showinfo("Вперед","Спершу закрийте редактор: у ньому є власні кнопки «Назад» і «Вперед».")
            return "break"
        self._history_record()
        step=self.history.redo()
        if not step:
            self.foot.config(text="Немає що повертати.");return "break"
        meta=self.history.step_meta
        try:
            if meta and meta.get("undo_zip"):
                self._redo_data_operation(meta)
                self.history.replace_current(self._history_snapshot())
                self._history_buttons()
            else:
                self._restore_snapshot(step[0])
        except Exception as ex:
            self.history.undo()
            messagebox.showerror("Вперед",f"Не вдалося повторити: {ex}")
            return "break"
        self.foot.config(text=f"Повернуто: {step[1]}.")
        return "break"

    def destroy(self):
        job=getattr(self,"_poll_job",None)
        if job:
            try:self.after_cancel(job)
            except tk.TclError:pass
        super().destroy()

    def pick_day(self):
        chosen=pick_date(self.date_entry,self.datevar.get(),title="Дата уроків")
        if chosen:
            self.datevar.set(chosen);self.update_day()

    # ---------- Скинути все / відновити копію ----------
    def reset_everything(self):
        if not messagebox.askyesno("Скинути ВСЕ?",
                "Буде видалено розклад, класи, календарні плани, готові Word, вкладення та весь стан програми.\n\n"
                "Підключення до Google збережеться.\n\n"
                "ПЕРЕД цим програма сама збереже повну копію всього. Повернути все назад можна кнопкою "
                "«↶ Назад» (або «↩ Відновити останню копію»).\n\nСкинути все?",icon="warning",default="no"):
            return
        self.begin_data_operation()
        path=data_tools.auto_backup_path(data_tools.RESET_PREFIX)
        try:
            data_tools.reset_to_blank(path)
        except Exception as ex:
            messagebox.showerror("Скинути все",f"Не вдалося: {ex}\nЯкщо копію не створено, дані не змінено.")
            return
        self.apply_data_operation("Скинуто все",path,"reset")
        messagebox.showinfo("Готово",f"Усе скинуто. Повну копію збережено:\n{path}\n\n"
                            "Повернути все назад: кнопка «↶ Назад» (або «↩ Відновити останню копію»).")

    def restore_last_backup(self):
        latest=data_tools.latest_backup()
        if latest is None:
            messagebox.showinfo("Копії",
                "Автоматичних копій ще немає: її створює кнопка «Скинути все».\n"
                "Свої копії можна відновити через «Мої дані» → «Відновити з копії».")
            return
        when=datetime.fromtimestamp(latest.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
        if not messagebox.askyesno("Відновити останню копію",
                f"Відновити дані з копії від {when}?\n{latest.name}\n\n"
                "Поточний стан перед цим буде збережено в окрему копію (кнопка «↶ Назад» поверне його).",default="no"):
            return
        self.begin_data_operation()
        safety=data_tools.auto_backup_path("Стан перед відновленням")
        try:
            count=data_tools.restore_from_zip(latest,safety)
        except Exception as ex:
            messagebox.showerror("Відновлення",str(ex));return
        self.apply_data_operation("Відновлено з копії",safety,("restore",str(latest)))
        messagebox.showinfo("Відновлено",f"Відновлено файлів: {count}.")



    def _plans_text_has_plans(self):
        self._plans_digest_now()
        return self._plans_store.get(self._plans_digest,"").strip() not in ("","{}")

    @staticmethod
    def _not_ready_text(lesson):
        if lesson.status=="КТП не завантажено":
            return ("Для цього класу ще не завантажено КТП. Відкрийте «Редактор КТП…» і перетягніть "
                    "файл КТП на клас: програма сама визначить, кому він підходить.")
        return "Теми в КТП завершилися або план не перевірено."

    def _refresh_google_button(self):
        """Підпис кнопки показує стан: «✓ Google підключено» або «Підключити Google»."""
        from . import google_client
        try:ready=bool(google_client.token_ready())
        except Exception:ready=False
        try:
            self.google_button.config(text="✓ Google підключено" if ready else "Підключити Google")
            row=self.google_button.master                      # підпис змінив ширину: перерахувати рядок шапки
            row.after_idle(row._layout)
        except (AttributeError,tk.TclError):pass

    def connect_google(self):
        """Перший раз — покрокова інструкція; далі — оновлення з Classroom з короткою відповіддю на екрані."""
        from . import google_client
        if google_client.token_ready():
            if self._sync_running:
                show_toast(self,"Оновлення Classroom уже триває…",1800)
                return
            show_toast(self,"✓ Google уже підключено · оновлюю дані Classroom…",2200)
            self.sync_classroom(interactive=True,announce=True)
            return
        from .google_setup_ui import show_google_wizard
        show_google_wizard(self)

    def sync_classroom(self,interactive=False,manual=False,announce=False):
        """Курси (у порядку Classroom) + стан усіх наявних матеріалів. Лише читання."""
        if self._sync_running:return
        from . import google_client
        if not interactive and not google_client.token_ready():
            self.foot.config(text="Google ще не підключено: натисніть «Підключити Google».")
            if manual:
                messagebox.showinfo("Google","Спочатку натисніть «Підключити Google».")
            return
        self._sync_running=True
        self._sync_started=time.time()
        titles=list(self.cfg.get("classroom_course_titles",[]))
        known=dict(self.state.get("course_ids",{}))
        def progress(text):
            self.after(0,lambda:self.foot.config(text=text))
        def run():
            try:
                result=google_client.sync_everything(titles,known,progress)
                self.after(0,lambda:self._sync_done(result,interactive,announce))
            except Exception as ex:
                text=str(ex)
                self.after(0,lambda:self._sync_failed(text,interactive))
        threading.Thread(target=run,daemon=True).start()

    def _link_courses_automatically(self,courses):
        """Курс у програмі = точна назва курсу в Classroom (підбір за змістом: клас + предмет)."""
        from .course_match import link_streams
        ids={c["name"]:str(c["id"]) for c in courses}
        changed=link_streams(self.cfg.get("course_map",{}),list(ids))
        if not changed:return
        self.cfg["classroom_course_titles"]=list(dict.fromkeys(
            info["course_title"] for info in self.cfg["course_map"].values()))
        for _old,new in changed.values():
            self.state["course_ids"][new]=ids[new]
        try:write_json("Налаштування.json",self.cfg)
        except OSError:pass

    def _reconcile_drafts(self,result):
        """Чернетка, яку створила програма, але яку потім видалили в Classroom, більше не вважається «створеною».

        Прибираємо запис лише коли: курс щойно ПОВНІСТЮ прочитано, id цієї чернетки там відсутній, а сама вона
        не свіжа (старша за 2 хв — Classroom оновлюється з затримкою). Без id чи за неповного списку не чіпаємо.
        """
        fresh=result.get("entries",{});cut=result.get("truncated",{})
        started=float(getattr(self,"_sync_started",0) or 0) or time.time()
        drafts=self.state.get("drafts",{})
        gone=[]
        for key,record in list(drafts.items()):
            if not isinstance(record,dict):continue
            try:
                stream=key.split("|",2)[2]
                title=self.cfg["course_map"][stream]["course_title"]
            except (IndexError,KeyError,TypeError):
                continue
            cid=str(self.state.get("course_ids",{}).get(title,""))
            own_id=str(record.get("id") or "")
            if not cid or cid not in fresh or cut.get(cid) or not own_id:continue
            if any(str(row.get("id"))==own_id for row in fresh[cid]):continue
            created=float(record.get("created_at",0) or 0)
            if created and created>started-120:continue
            gone.append((key,own_id))
        log=self.state.setdefault("drafts_removed",[]) if gone else None
        for key,own_id in gone:
            drafts.pop(key,None)
            log.append({"key":key,"id":own_id,"removed_at":time.time(),"reason":"немає в Classroom"})
        if log is not None:del log[:-200]
        return [key for key,_ in gone]

    def _on_focus_in(self,event=None):
        """Повернулися у програму (з браузера, де щось змінили в Classroom): оновити стан, не частіше ніж раз на хвилину."""
        try:
            if event is not None and event.widget is not self:return
            if self._sync_running or time.time()-self._last_sync_ts<60:return
            from . import google_client
            if google_client.token_ready():self.request_sync(400)
        except Exception:pass

    def _draft_is_assignment(self,lesson):
        """Лекція → «Матеріал». Практична, лабораторна, контрольна, проєктна робота, оцінювання → «Завдання»
        (інакше діти не зможуть прикріпити відповідь). Галочка «Усе як завдання» вмикає це для всіх."""
        return bool(self.assignment.get()) or is_task_lesson(lesson.topic)

    def open_alert_setup(self):
        return show_alert_setup(self)

    def alert_settings_changed(self):
        """Місце або ключ змінено: перечитати налаштування, запустити/пришвидшити перевірку, оновити листочок."""
        if air_alerts.load_settings(DATA)["key"] and not os.environ.get("POMICHNYK_NO_OFFERS"):
            self.alerts.start()
            self.alerts.refresh_soon()
        self._apply_alert_status()
        self._refresh_leaf()

    def _apply_alert_status(self):
        settings=air_alerts.load_settings(DATA)
        status=self.alerts.status if settings["key"] else air_alerts.fetch_status(settings,DATA)
        self.alert_panel.show(air_alerts.effective_status(status),air_alerts.place_text(settings["place"]))

    def _alert_poll(self):
        try:
            if not self.winfo_exists():return
            self._apply_alert_status()
        except tk.TclError:return
        self._alert_job=self.after(2000,self._alert_poll)

    def _refresh_leaf(self):
        """Листочок календаря для обраної дати: сонце, Місяць, свята й події (кеш + вбудований список)."""
        try:
            day=parse_date(self.datevar.get())
        except Exception:
            return
        lat,lon=air_alerts.place_coordinates(air_alerts.load_settings(DATA)["place"])
        wiki=day_facts.cached(DATA,day.month,day.day)
        self.leaf.show(day,lat,lon,self.facts.lookup(day.month,day.day),
                       "за матеріалами Вікіпедії (CC BY-SA)" if wiki else "вбудований список пам'ятних дат")
        self.facts.refresh_async(day.month,day.day)

    def _facts_poll(self):
        try:
            if not self.winfo_exists():return
            if self.facts.updated:
                self.facts.updated.clear()
                self._refresh_leaf()
        except tk.TclError:return
        self._facts_job=self.after(1500,self._facts_poll)

    def _net_poll(self):
        try:
            if not self.winfo_exists():return
            self.header.set_online(self.net.online)
        except tk.TclError:return
        self._net_job=self.after(1000,self._net_poll)

    def request_sync(self,delay=900):
        """Перевірити Classroom після змін (чернетки, розклад): якщо синхронізація йде — повторити по завершенню."""
        def go():
            if self._sync_running:self._sync_again=True
            else:self.sync_classroom(interactive=False)
        self.after(delay,go)

    def _after_sync(self):
        if self._sync_again:
            self._sync_again=False
            self.after(300,lambda:self.sync_classroom(interactive=False))

    def _sync_done(self,result,interactive,announce=False):
        self._sync_running=False
        self._last_sync_ts=time.time()
        self.google_courses=result["courses"]
        self.state["course_ids"]=result["mapped"]
        self.state["classroom_order"]=[c["name"] for c in result["courses"]]
        self._link_courses_automatically(result["courses"])
        self.remote_classroom_entries.update(result["entries"])
        removed=self._reconcile_drafts(result)
        try:save_state(self.state)
        except Exception:pass
        self.update_day()
        if removed:
            show_toast(self,f"Чернеток, яких уже немає в Classroom, прибрано зі стану: {len(removed)} · "
                            "їх можна створити знову",3600)
        records=sum(len(v) for v in result["entries"].values())
        text=(f"Classroom синхронізовано: курсів — {len(result['courses'])}, "
              f"записів — {records}.")
        if result["unmapped"]:
            text+=f" Не зіставлено з Classroom: {len(result['unmapped'])} (кнопка «Зіставити курси»)."
        if result["errors"]:
            text+=f" Не вдалося прочитати курсів: {len(result['errors'])}."
        self.foot.config(text=text)
        self._refresh_google_button()
        if interactive and result["errors"]:
            messagebox.showinfo("Google Classroom",text+"\n\n"+"\n".join(result["errors"][:5]))     # треба прочитати
        elif announce and result["unmapped"]:
            show_toast(self,f"Classroom оновлено · не зіставлено курсів: {len(result['unmapped'])} "
                            "(кнопка «Зіставити курси»)",4000,"warn")
        elif announce:
            show_toast(self,f"✓ Classroom оновлено: курсів — {len(result['courses'])}, записів — {records}",2600)
        self._after_sync()

    def _sync_failed(self,error,interactive):
        self._sync_running=False
        self.foot.config(text="Синхронізація з Classroom не вдалася (дані на екрані — з останнього разу).")
        self._after_sync()
        if interactive:
            messagebox.showerror("Google Classroom",error+"\n\nПеревірте інтернет і налаштування Google (ПОЧАТКОВЕ НАЛАШТУВАННЯ).")

    def edit_lesson_in_ktp(self):
        lesson=self.selected()
        if not lesson:return
        from .editor_ui import SchoolEditor
        editor=SchoolEditor(self,self.update_day)
        editor.focus_lesson(lesson.stream,lesson.lesson_number)

    def samples_dialog(self):
        from .samples_ui import show_samples
        show_samples(self)

    def data_dialog(self):
        from .samples_ui import show_data_folder
        show_data_folder(self)

    def get_courses(self):
        def task():
            from .google_client import list_teacher_courses
            return list_teacher_courses()
        def done(courses):
            self.google_courses=courses
            messagebox.showinfo("Google Classroom",f"Отримано курсів: {len(courses)}. Тепер натисніть «Зіставити курси».")
            self.map_courses()
        self.worker(task,done)

    def map_courses(self):
        if not self.google_courses:
            messagebox.showinfo("Курси","Спочатку натисніть «Підключити Google».");return
        dialog=tk.Toplevel(self);dialog.title("Зіставлення місцевих потоків і Google Classroom")
        fit_work_window(dialog,"normal")
        ttk.Label(dialog,text="Кожен потік або об'єднаний курс зіставте з курсом Google. Порожній рядок не публікується.").pack(anchor="w",padx=12,pady=10)
        wrap=ttk.Frame(dialog);wrap.pack(fill="both",expand=True)
        canvas=tk.Canvas(wrap)
        bar=ttk.Scrollbar(wrap,orient="vertical",command=canvas.yview)
        frame=ttk.Frame(canvas)
        frame.bind("<Configure>",lambda _ :canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=frame,anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left",fill="both",expand=True);bar.pack(side="right",fill="y")
        choices=["— не вибрано —"]+[f"{c['name']} [{c['id']}]" for c in self.google_courses]
        vars={}
        known_ids=self.state.get("course_ids",{})
        for i,title in enumerate(self.cfg["classroom_course_titles"]):
            ttk.Label(frame,text=title,width=23).grid(row=i,column=0,padx=10,pady=4,sticky="w")
            var=tk.StringVar()
            box=ttk.Combobox(frame,textvariable=var,values=choices,width=69,state="readonly")
            target=known_ids.get(title)
            matched=next((choice for choice,c in zip(choices[1:],self.google_courses) if str(c["id"])==str(target)),None)
            if not matched:
                from .course_match import best_match
                hit=best_match(title,[c["name"] for c in self.google_courses])
                matched=(next((choice for choice,c in zip(choices[1:],self.google_courses)
                               if c["name"]==hit),choices[0]) if hit else choices[0])
            box.set(matched);box.grid(row=i,column=1,padx=7,pady=4,sticky="ew")
            vars[title]=var
        def save():
            mapped={}
            for title,var in vars.items():
                for c in self.google_courses:
                    if var.get()==f"{c['name']} [{c['id']}]":
                        mapped[title]=str(c["id"]);break
            self.state["course_ids"]=mapped;save_state(self.state)
            dialog.destroy()
            messagebox.showinfo("Збережено",f"Зіставлено курсів: {len(mapped)}/{len(vars)}")
        ttk.Button(dialog,text="Зберегти зіставлення",command=save).pack(pady=9)

    def _description_for_batch(self,lesson):
        """Враховує змінену вручну тему й актуальний текст вибраного уроку."""
        adjusted=self.effective_lesson(lesson)
        current=self.selected()
        if current and current.unique_key==lesson.unique_key:
            return self.desc.get("1.0","end-1c").strip()
        saved=self.state.get("description_overrides",{}).get(lesson.unique_key)
        if saved is not None:return saved
        template=self.state.get("parallel_templates",{}).get(
            signature_key(lesson,self.cfg))
        if template is not None:return render_template(template,adjusted)
        return html_classroom_text(adjusted,asynchronous=True,video=True)

    def batch_drafts(self,only=None):
        """Створення лише ПЕРЕВІРЕНИХ чернеток за обрану дату (або лише для виділених уроків), по одній."""
        if self._batch_drafts_running:return
        source=self.rows if not only else list(only)
        if not source:
            messagebox.showinfo("Чернетки за день",
                  "Цього дня немає уроків (можливо, вихідний або канікули).")
            return
        from .draft_batch import plan_day_drafts
        effective_rows=[self.effective_lesson(row) for row in source]
        ready,skipped=plan_day_drafts(
            effective_rows,self.state,self._description_for_batch)
        # Захист від повторів серед вже видимих записів після синхронізації.
        # Без синхронізації це не є перевіркою всього сервера.
        not_repeated=[]
        for candidate in ready:
            if self._remote_classroom_status(candidate["lesson"]):
                skipped.append((candidate["lesson"],
                   "такий урок уже видно у Classroom після синхронізації"))
            else:not_repeated.append(candidate)
        ready=not_repeated
        summary=[f"Дата: {self.datevar.get()}"+(f" · виділені уроки: {len(source)}" if only else ""),
                 f"Готові для чернеток: {len(ready)}",
                 f"Пропущено: {len(skipped)}"]
        for candidate in ready:
            candidate["assignment"]=self._draft_is_assignment(candidate["lesson"])   # до потоку: Tk-змінні лише тут
        summary.extend(f"✓ {x['lesson'].period}. {x['lesson'].stream}: "
                       f"{x['lesson'].topic[:70]}"+("  [ЗАВДАННЯ]" if x["assignment"] else "") for x in ready)
        summary.extend(f"— {x.period}. {x.stream}: {reason}"
                       for x,reason in skipped)
        if not ready:
            messagebox.showinfo("Чернетки за день","\n".join(summary))
            return
        confirmation=(
            "\n".join(summary)+
            "\n\nСтворити тільки ЧЕРНЕТКИ в указаних Google-курсах? Лекції — як «Матеріал», а практичні, "
            "контрольні, лабораторні та проєктні роботи — як «Завдання» (учні зможуть здати відповідь). "
            "У кожній будуть лише наявні матеріали: текст, перевірений Word "
            "(за наявності) та додаткові вкладення. "
            "Учні НЕ отримають публікацій. Відео додаються вручну.\n\n"
            "Перевірте теми, дати й домашні завдання до підтвердження."
        )
        if not messagebox.askyesno("Пакетна підготовка чернеток",confirmation):
            return
        self._batch_drafts_running=True
        self.batch_drafts_button.config(state="disabled")
        self.foot.config(text=f"Створюю {len(ready)} чернеток послідовно…")
        # Зафіксувати план до початку відправлень: зміни вибраного рядка
        # або дати після старту не вплинуть на вже підтверджений перелік.
        def task():
            from .google_client import create_draft
            done=[]
            errors=[]
            for item in ready:
                # Повторно перевірити дублікат безпосередньо перед API-запитом.
                if item["key"] in self.state.get("drafts",{}):
                    continue
                try:
                    record=create_draft(
                        item["course_id"],item["title"],item["description"],
                        item["docx_path"],item["assignment"],item["attachments"])
                    if isinstance(record,dict):record.setdefault("created_at",time.time())
                except Exception as ex:
                    errors.append(f"{item['lesson'].stream}: {ex}")
                    # Stop: the reason might be a network or authorization error.
                    break
                self.state.setdefault("drafts",{})[item["key"]]=record
                try:
                    # IMPORTANT: Записати кожний результат ОДРАЗУ, щоб
                    # наступна помилка не спричинила повторних публікацій.
                    save_state(self.state)
                except Exception as ex:
                    errors.append("Чернетка створена, але не вдалося зберегти "
                       "локальну позначку! Перевірте Classroom перед повтором. "
                       f"{item['lesson'].stream}: {ex}")
                    break
                done.append(item)
            return done,errors

        def finished(result):
            successful,errors=result
            self._batch_drafts_running=False
            self.batch_drafts_button.config(state="normal")
            self.update_day()
            msg=(f"Створено чернеток: {len(successful)} з {len(ready)} готових.\n"
                 f"Пропущено до початку: {len(skipped)}.\n"
                 "Жоден матеріал не опубліковано.")
            if errors:
                msg+="\n\nПісля помилки зупинено відправлення:\n"+"\n".join(errors)
                msg+="\nПеревірте вже створені чернетки в Classroom, перш ніж повторювати."
                messagebox.showwarning("Пакетна підготовка",msg)
            else:
                show_toast(self,f"✓ Створено чернеток: {len(successful)} з {len(ready)} · учні їх не бачать · "
                                "перевіряю Classroom…",3200)
            self.request_sync(1200)
        def safe_worker():
            try:
                result=task()
                self.after(0,lambda:finished(result))
            except Exception as ex:
                msg=str(ex)
                def failed():
                    self._batch_drafts_running=False
                    self.batch_drafts_button.config(state="normal")
                    self.update_day()
                    messagebox.showerror("Пакетні чернетки",
                        "Сталася непередбачена помилка. Перевірте Classroom "
                        "перед повторним запуском:\n"+msg)
                self.after(0,failed)
        threading.Thread(target=safe_worker,daemon=True).start()

    def draft(self):
        original=self.selected()
        if not original:return
        lesson=self.effective_lesson(original)
        if lesson.status!="готово":
            messagebox.showerror("КТП","Цей урок не готовий: спочатку імпортуйте та перевірте календарний план поточного року.")
            return
        key=lesson.unique_key
        if key in self.state.get("drafts",{}):
            messagebox.showerror("Дублікат","Для цього уроку вже створено чернетку Classroom. Повторне створення заблоковано.");return
        f=self.state.get("files",{}).get(key,{})
        word_path=(str(f["path"]) if
                   f.get("validated") and f.get("complete")
                   and Path(f.get("path","")).is_file() else None)
        course_id=self.state.get("course_ids",{}).get(lesson.course_title)
        if not course_id:
            messagebox.showerror("Classroom","Цей курс ще не зіставлено з Google Classroom.");return
        duplicate=self._remote_classroom_status(lesson)
        if duplicate and not messagebox.askyesno(
                "Перевірте можливий повтор",
                f"Після синхронізації в Classroom уже знайдено: «{duplicate}».\n"
                "Ви дійсно хочете створити ще одну окрему чернетку?",
                parent=self):
            return
        text=self.desc.get("1.0","end").strip()
        assignment=self._draft_is_assignment(lesson)
        attachment_paths=files_for_lesson(self.state,key)
        if len(attachment_paths)!=len(self.state.get("attachments",{}).get(key,[])):
            messagebox.showerror("Вкладення",
              "Деякі прикріплені файли відсутні. Приберіть їх зі списку або додайте знову.")
            return
        if not text and not word_path and not attachment_paths:
            messagebox.showwarning("Порожній матеріал",
                "Напишіть повідомлення або додайте зображення, інший файл чи Word.")
            return
        confirm=("Створити ТІЛЬКИ ЧЕРНЕТКУ?\n\n"
                 f"Курс: {lesson.course_title}\nДата уроку: {lesson.day}\n"
                 f"Тема: {lesson.topic[:110]}\n"
                 f"Тип: {'ЗАВДАННЯ (учні зможуть здати відповідь)' if assignment else 'Матеріал'}\n"
                 f"Word: {'додається' if word_path else 'не потрібний / не додається'}\n"
                 f"Текст: {'є' if text else 'без опису'}\n"
                 f"Додаткові вкладення: {len(attachment_paths)}\n\n"
                 "Відео потрібно додати вручну перед публікацією.")
        if not messagebox.askyesno("Підтвердження",confirm):return
        def task():
            from .google_client import create_draft
            return create_draft(course_id,
                f"Урок {lesson.day[8:10]}.{lesson.day[5:7]} — {lesson.topic}. "
                "(Асинхронно — без виходу у Zoom у зв’язку з довготривалою повітряною тривогою і загрозою для життя і здоров’я)",
                 text,word_path,assignment,attachment_paths)
        def done(result):
            if isinstance(result,dict):result["created_at"]=time.time()
            self.state.setdefault("drafts",{})[key]=result
            save_state(self.state);self.update_day()
            show_toast(self,f"✓ Чернетку створено ({'Завдання' if assignment else 'Матеріал'}, DRAFT) · "
                            "учні її не бачать · перевіряю Classroom…",3200)
            self.request_sync(1200)
        self.worker(task,done)

def launch():
    app_icon.set_app_id()
    MainApp().mainloop()
